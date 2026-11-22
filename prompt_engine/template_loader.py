"""Loads versioned prompt templates from prompt_engine/templates/*.md.

Template file format::

    ---
    id: P05
    name: lecture_notes
    version: 1.0.0
    schema: LectureNotes
    techniques: role, contextual, structured-output, prompt-chaining
    temperature: 0.4
    max_output_tokens: 3072
    description: ...
    ---
    ## SYSTEM
    ...system prompt (may include {{> partial_name}})...
    ## USER
    ...user prompt with {{variables}}...

Partials live in templates/partials/<name>.md; few-shot snippets in templates/fewshot/.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
PARTIAL_RE = re.compile(r"\{\{>\s*([a-zA-Z0-9_\-/]+)\s*\}\}")


class TemplateError(Exception):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    name: str
    version: str
    schema: str | None
    system: str
    user: str
    techniques: tuple[str, ...] = ()
    temperature: float = 0.3
    max_output_tokens: int | None = None
    description: str = ""
    path: str = ""
    variables: frozenset[str] = field(default_factory=frozenset)
    fingerprint: str = ""  # hash of the fully expanded template text (changes when partials change)

    @property
    def label(self) -> str:
        return f"{self.id}:{self.name}@{self.full_version}"

    @property
    def full_version(self) -> str:
        return f"{self.version}+{self.fingerprint}" if self.fingerprint else self.version


def _parse_front_matter(text: str, path: Path) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        raise TemplateError(f"{path.name}: missing front matter")
    _, fm, body = text.split("---", 2)
    meta = {}
    for line in fm.strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    for required in ("id", "name", "version"):
        if required not in meta:
            raise TemplateError(f"{path.name}: front matter lacks '{required}'")
    return meta, body


def load_partial(name: str) -> str:
    path = TEMPLATES_DIR / "partials" / f"{name}.md"
    if not path.exists():
        path = TEMPLATES_DIR / f"{name}.md"
    if not path.exists():
        raise TemplateError(f"Unknown partial '{name}'")
    return path.read_text(encoding="utf-8").strip()


def expand_partials(text: str, depth: int = 0) -> str:
    if depth > 3:
        raise TemplateError("Partials nested too deeply")
    return PARTIAL_RE.sub(lambda m: expand_partials(load_partial(m.group(1)), depth + 1), text)


def parse_template(path: Path) -> PromptTemplate:
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"), path)
    parts = re.split(r"^##\s+(SYSTEM|USER)\s*$", body, flags=re.M)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if "SYSTEM" not in sections or "USER" not in sections:
        raise TemplateError(f"{path.name}: needs '## SYSTEM' and '## USER' sections")
    system = expand_partials(sections["SYSTEM"])
    user = expand_partials(sections["USER"])
    variables = frozenset(VAR_RE.findall(system) + VAR_RE.findall(user))
    return PromptTemplate(
        id=meta["id"], name=meta["name"], version=meta["version"], schema=meta.get("schema") or None,
        system=system, user=user,
        techniques=tuple(t.strip() for t in meta.get("techniques", "").split(",") if t.strip()),
        temperature=float(meta.get("temperature", 0.3)),
        max_output_tokens=int(meta["max_output_tokens"]) if meta.get("max_output_tokens") else None,
        description=meta.get("description", ""), path=str(path), variables=variables,
        fingerprint=hashlib.sha1((system + "|" + user).encode("utf-8")).hexdigest()[:7],
    )


@lru_cache(maxsize=1)
def load_all_templates() -> dict[str, PromptTemplate]:
    templates = {}
    for path in sorted(TEMPLATES_DIR.glob("*.md")):
        tpl = parse_template(path)
        if tpl.name in templates:
            raise TemplateError(f"Duplicate template name {tpl.name}")
        templates[tpl.name] = tpl
    return templates


def get_template(name: str) -> PromptTemplate:
    templates = load_all_templates()
    if name not in templates:
        raise TemplateError(f"Unknown template '{name}'. Available: {sorted(templates)}")
    return templates[name]


def load_fewshot(name: str) -> str:
    path = TEMPLATES_DIR / "fewshot" / f"{name}.md"
    if not path.exists():
        raise TemplateError(f"Unknown few-shot block '{name}'")
    return path.read_text(encoding="utf-8").strip()


def reload_templates() -> None:
    load_all_templates.cache_clear()
