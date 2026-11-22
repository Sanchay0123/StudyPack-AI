"""Renders templates into provider-independent prompt packages."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from prompt_engine.schemas import SCHEMAS
from prompt_engine.template_loader import VAR_RE, PromptTemplate, TemplateError

SOURCE_OPEN, SOURCE_CLOSE = "<source_material>", "</source_material>"


@dataclass
class PromptPackage:
    template: PromptTemplate
    system: str
    user: str
    schema_model: type[BaseModel] | None
    json_schema: dict[str, Any] | None

    @property
    def text_length(self) -> int:
        return len(self.system) + len(self.user)


def neutralize_source_text(text: str) -> str:
    """Prevent uploaded text from closing the data delimiter or faking prompt structure."""
    replacements = {
        SOURCE_CLOSE: "</source-material>", SOURCE_OPEN: "<source-material>",
        "## SYSTEM": "## system", "## USER": "## user",
        "<|im_start|>": "<im_start>", "<|im_end|>": "<im_end>", "<|endoftext|>": "<endoftext>",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _type_hint(annotation: Any) -> str:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list:
        return f"list of {_type_hint(args[0])}" if args else "list"
    if origin is not None and str(origin).endswith("Literal"):
        return " | ".join(repr(a) for a in args)
    if args and type(None) in args:
        inner = [a for a in args if a is not type(None)]
        return _type_hint(inner[0]) + " or null"
    if str(annotation).startswith("typing.Literal"):
        return " | ".join(repr(a) for a in args)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.__name__
    return getattr(annotation, "__name__", str(annotation))


def schema_outline(model: type[BaseModel], indent: int = 0, seen: set | None = None) -> str:
    """Compact, human-readable description of a schema for the prompt text.

    Constrained decoding (Ollama `format`, Gemini `response_json_schema`) enforces
    syntax; this outline tells the model what each field *means*.
    """
    seen = seen or set()
    pad = "  " * indent
    lines = []
    nested = []
    for name, field in model.model_fields.items():
        desc = f" - {field.description}" if field.description else ""
        lines.append(f"{pad}- {name}: {_type_hint(field.annotation)}{desc}")
        for candidate in [field.annotation, *get_args(field.annotation)]:
            for inner in [candidate, *get_args(candidate)]:
                if isinstance(inner, type) and issubclass(inner, BaseModel) and inner not in seen:
                    seen.add(inner)
                    nested.append(inner)
    out = "\n".join(lines)
    for sub in nested:
        out += f"\n{pad}{sub.__name__} fields:\n" + schema_outline(sub, indent + 1, seen)
    return out


def render(text: str, variables: dict[str, Any]) -> str:
    def sub(match):
        key = match.group(1)
        value = variables[key]
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=1)
        return str(value)
    return VAR_RE.sub(sub, text)


def build_prompt(template: PromptTemplate, variables: dict[str, Any]) -> PromptPackage:
    schema_model = SCHEMAS.get(template.schema) if template.schema else None
    if template.schema and schema_model is None:
        raise TemplateError(f"Template {template.label} references unknown schema {template.schema}")
    variables = dict(variables)
    if "output_outline" in template.variables:
        variables.setdefault("output_outline", schema_outline(schema_model) if schema_model else "")
    missing = template.variables - variables.keys()
    if missing:
        raise TemplateError(f"Template {template.label} is missing variables: {sorted(missing)}")
    return PromptPackage(
        template=template,
        system=render(template.system, variables),
        user=render(template.user, variables),
        schema_model=schema_model,
        json_schema=schema_model.model_json_schema() if schema_model else None,
    )
