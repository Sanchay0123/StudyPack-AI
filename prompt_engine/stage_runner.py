"""Executes one prompt stage: build -> budget check -> generate -> parse ->
validate -> (targeted repair) -> record.

Validation failures are repaired by sending the model its previous output
plus the precise validation errors (iterative refinement), instead of
restarting from scratch. Provider failures are NOT retried here; the provider
router handles fallback for genuine availability problems.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from config.logging_config import get_logger
from config.settings import Settings, get_settings
from prompt_engine.context_manager import calibrate, chars_per_token, estimate_tokens
from prompt_engine.prompt_builder import PromptPackage, build_prompt
from prompt_engine.template_loader import get_template
from providers.base import GenerationRequest
from providers.exceptions import ContextOverflowError, ProviderError
from providers.provider_router import ProviderRouter
from storage.models import StageRun

log = get_logger("prompt_engine.stage")

SemanticCheck = Callable[[BaseModel], list[str]]


class StageError(Exception):
    """A stage could not produce valid output after all repair attempts."""

    def __init__(self, message: str, stage: str, attempts: int, errors: list[str], last_output: str = ""):
        super().__init__(message)
        self.stage, self.attempts, self.errors, self.last_output = stage, attempts, errors, last_output


@dataclass
class StageResult:
    output: BaseModel
    template_id: str
    template_name: str
    version: str
    provider: str
    model: str
    attempts: int
    duration_s: float
    repairs: list[list[str]] = field(default_factory=list)
    raw_text: str = ""


def extract_json(text: str) -> str:
    """Pull a JSON object out of model text (strips fences / chatter / think tags)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return text


def _format_validation_errors(exc: ValidationError, limit: int = 12) -> list[str]:
    errors = []
    for err in exc.errors()[:limit]:
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        errors.append(f"{loc}: {err['msg']}")
    return errors


def parse_and_validate(text: str, model: type[BaseModel], semantic_check: SemanticCheck | None = None) -> tuple[BaseModel | None, list[str]]:
    candidate = extract_json(text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, [f"Output is not valid JSON ({exc.msg} at position {exc.pos}). Return one complete JSON object."]
    try:
        obj = model.model_validate(data)
    except ValidationError as exc:
        return None, _format_validation_errors(exc)
    if semantic_check:
        problems = semantic_check(obj)
        if problems:
            return None, problems
    return obj, []


SOURCE_BLOCK_RE = re.compile(r"\n(?=\[S\d+\] \()")
SHRINKABLE = ("source", "outline", "section_index", "notes_text", "notes_digest")


def shrink_variables(variables: dict[str, Any], excess_tokens: int) -> tuple[dict[str, Any] | None, str]:
    """Free roughly `excess_tokens` from the bulkiest shrinkable variable.

    Labelled source material loses whole trailing [S#] blocks (the remaining labels stay valid); other text
    is cut at a line boundary. Returns (new variables, note) or (None, reason) if nothing can be shrunk.
    """
    need_chars = int(excess_tokens * chars_per_token()) + 200
    candidates = [k for k in SHRINKABLE if isinstance(variables.get(k), str) and len(variables[k]) > 800]
    if not candidates:
        return None, "nothing left to shrink"
    key = max(candidates, key=lambda k: len(variables[k]))
    text = variables[key]
    if key == "source" and "[S" in text:
        head, _, tail = text.partition("\n")  # "<source_material>" line
        blocks = SOURCE_BLOCK_RE.split("\n" + tail)
        blocks = [b for b in blocks if b.strip()]
        closing = "</source_material>"
        removed = 0
        while len(blocks) > 1 and removed < need_chars:
            removed += len(blocks.pop())
        if removed == 0:
            return None, "source cannot be shrunk further"
        new = head + "\n" + "\n".join(b.replace(closing, "").rstrip() for b in blocks) + "\n" + closing
        note = f"(dropped trailing source blocks, ~{removed} chars)"
    else:
        keep = max(400, len(text) - need_chars)
        if keep >= len(text):
            return None, f"{key} cannot be shrunk further"
        new = text[:keep].rsplit("\n", 1)[0] + "\n[... shortened to fit the context window ...]"
        note = f"(shortened {key} by ~{len(text) - keep} chars)"
    return {**variables, key: new}, note


REPAIR_INSTRUCTIONS = """Your previous response could not be accepted because it failed validation.

Validation errors:
{errors}

Previous response (possibly truncated):
<previous_response>
{previous}
</previous_response>

Return a corrected, complete JSON object that fixes every error above while keeping all valid content.
{length_hint}Do not add commentary."""


class StageRunner:
    def __init__(self, router: ProviderRouter, settings: Settings | None = None, recorder: Callable[[StageRun], None] | None = None,
                 project_id: str | None = None):
        self.router = router
        self.settings = settings or get_settings()
        self.recorder = recorder
        self.project_id = project_id

    def build(self, template_name: str, variables: dict[str, Any]) -> PromptPackage:
        return build_prompt(get_template(template_name), variables)

    def max_output_for(self, package: PromptPackage) -> int:
        return min(package.template.max_output_tokens or self.settings.max_output_tokens, self.settings.max_output_tokens)

    def check_budget(self, package: PromptPackage, max_output: int) -> int:
        prompt_tokens = estimate_tokens(package.system) + estimate_tokens(package.user) + 50
        if prompt_tokens + max_output > self.settings.context_length:
            raise ContextOverflowError(
                f"Prompt for {package.template.label} needs ~{prompt_tokens} tokens + {max_output} output tokens, "
                f"exceeding the {self.settings.context_length}-token context window.")
        return prompt_tokens

    def _fit(self, template_name: str, package: PromptPackage, variables: dict[str, Any],
             max_output: int) -> tuple[PromptPackage, dict[str, Any]]:
        """Pre-flight: if the prompt is estimated not to fit, shrink the bulkiest shrinkable variable (trailing source
        blocks, notes text, outline...) and re-check, instead of failing outright. Raises if nothing can be shrunk."""
        for _ in range(8):
            try:
                self.check_budget(package, max_output)
                return package, variables
            except ContextOverflowError as exc:
                prompt_tokens = estimate_tokens(package.system) + estimate_tokens(package.user) + 50
                shrunk, note = shrink_variables(variables, prompt_tokens + max_output - self.settings.context_length + 100)
                if shrunk is None:
                    raise exc
                log.warning("%s: prompt over budget before sending (%s); %s", package.template.label, exc, note)
                variables = shrunk
                package = self.build(template_name, variables)
        self.check_budget(package, max_output)
        return package, variables

    def run(self, template_name: str, variables: dict[str, Any], semantic_check: SemanticCheck | None = None,
            temperature: float | None = None, images: list[bytes] | None = None) -> StageResult:
        package = self.build(template_name, variables)
        if package.schema_model is None:
            raise ValueError(f"Template {template_name} has no schema; use run_text()")
        tpl = package.template
        max_output = self.max_output_for(package)
        package, variables = self._fit(template_name, package, variables, max_output)
        attempts, repairs, total_duration = 0, [], 0.0
        prompt = package.user
        last_text, errors = "", []
        provider = model = ""
        prompt_tokens = output_tokens = None
        max_attempts = 1 + max(0, self.settings.max_validation_retries)
        started = time.perf_counter()
        try:
            while attempts < max_attempts:
                attempts += 1
                request = GenerationRequest(system=package.system, prompt=prompt, temperature=temperature if temperature is not None else tpl.temperature,
                                            max_tokens=max_output, json_schema=package.json_schema, context_length=self.settings.context_length,
                                            images=list(images or []),
                                            metadata={"template": tpl.label, "attempt": attempts})
                result = self.router.generate(request)
                provider, model = result.provider, result.model
                prompt_tokens, output_tokens = result.prompt_tokens, result.output_tokens
                total_duration += result.duration_s
                last_text = result.text
                calibrate(len(package.system) + len(prompt), prompt_tokens)  # learn the real chars/token ratio
                obj, errors = parse_and_validate(result.text, package.schema_model, semantic_check)
                context_full = bool(result.truncated and prompt_tokens and
                                    prompt_tokens + (output_tokens or 0) >= self.settings.context_length - 64)
                if obj is None and context_full:
                    # Not a verbosity problem: the prompt left too little room for the answer. Shrink the source
                    # material and retry the original task (without resending the cut-off output).
                    errors = [f"Context window full: the prompt used {prompt_tokens} of {self.settings.context_length} "
                              f"tokens, leaving only {output_tokens} for the answer."] + errors
                    excess = prompt_tokens + max_output - self.settings.context_length + 300
                    shrunk, note = shrink_variables(variables, excess)
                    repairs.append(errors)
                    log.warning("%s attempt %d: %s %s", tpl.label, attempts, errors[0], note)
                    if shrunk is None:
                        break
                    variables = shrunk
                    package = self.build(template_name, variables)
                    prompt = package.user
                    continue
                if result.truncated and obj is None:
                    errors = ["The response was cut off because it exceeded the output length limit."] + errors
                if obj is not None:
                    self._record(tpl, provider, model, attempts, True, total_duration, prompt_tokens, output_tokens, None)
                    return StageResult(obj, tpl.id, tpl.name, tpl.full_version, provider, model, attempts, total_duration, repairs, result.text)
                repairs.append(errors)
                log.warning("%s attempt %d failed validation: %s", tpl.label, attempts, "; ".join(errors)[:400])
                length_hint = ("Be more concise: shorten long text fields so the whole JSON fits.\n"
                               if result.truncated else "")
                repair = REPAIR_INSTRUCTIONS.format(errors="\n".join(f"- {e}" for e in errors),
                                                    previous=last_text[-6000:], length_hint=length_hint)
                prompt = package.user + "\n\n" + repair
                # Keep repair prompts inside the context window.
                if estimate_tokens(package.system + prompt) + max_output > self.settings.context_length:
                    prompt = package.user + "\n\n" + REPAIR_INSTRUCTIONS.format(
                        errors="\n".join(f"- {e}" for e in errors), previous="(omitted for length)", length_hint=length_hint)
        except ProviderError as exc:
            self._record(tpl, provider or None, model or None, attempts, False, time.perf_counter() - started, prompt_tokens, output_tokens, str(exc))
            raise
        self._record(tpl, provider, model, attempts, False, total_duration, prompt_tokens, output_tokens, "; ".join(errors)[:1000])
        raise StageError(f"{tpl.label} failed validation after {attempts} attempt(s): {'; '.join(errors)[:500]}",
                         tpl.name, attempts, errors, last_text)

    def run_text(self, template_name: str, variables: dict[str, Any], temperature: float | None = None) -> tuple[str, StageResult | None]:
        """Free-text stage (used by the baseline experiment)."""
        package = self.build(template_name, variables)
        tpl = package.template
        max_output = self.max_output_for(package)
        self.check_budget(package, max_output)
        result = self.router.generate(GenerationRequest(system=package.system, prompt=package.user,
                                                        temperature=temperature if temperature is not None else tpl.temperature,
                                                        max_tokens=max_output, context_length=self.settings.context_length))
        self._record(tpl, result.provider, result.model, 1, True, result.duration_s, result.prompt_tokens, result.output_tokens, None)
        return result.text, None

    def _record(self, tpl, provider, model, attempts, success, duration, prompt_tokens, output_tokens, error) -> None:
        if self.recorder is None:
            return
        try:
            self.recorder(StageRun(project_id=self.project_id, stage_id=tpl.label, prompt_version=tpl.full_version,
                                   provider=provider, model=model, attempts=attempts, success=success,
                                   duration_s=round(duration, 2), prompt_tokens=prompt_tokens,
                                   output_tokens=output_tokens, error=error))
        except Exception:  # noqa: BLE001 - recording must never break generation
            log.exception("Failed to record stage run")
