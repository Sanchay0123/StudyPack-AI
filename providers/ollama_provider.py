"""Ollama (local inference) provider using the HTTP API directly."""
from __future__ import annotations

import time
from typing import Any

import requests

from config.logging_config import get_logger
from config.settings import Settings
from providers.base import BaseLLMProvider, GenerationRequest, GenerationResult, ProviderStatus
from providers.exceptions import (
    ContextOverflowError,
    ModelNotFoundError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

log = get_logger("providers.ollama")


def _model_matches(configured: str, available: str) -> bool:
    if configured == available:
        return True
    if ":" not in configured and available == f"{configured}:latest":
        return True
    return False


class OllamaProvider(BaseLLMProvider):
    name = "ollama"

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self.settings = settings
        self.base_url = settings.ollama_base_url
        self.model = settings.ollama_model
        self.session = session or requests.Session()

    # ------------------------------------------------------------------ health
    def list_models(self) -> list[str]:
        try:
            resp = self.session.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise ProviderUnavailableError(
                f"Ollama server not reachable at {self.base_url}. Start it with scripts\\start_ollama.ps1 ({exc.__class__.__name__}).",
                self.name,
            ) from exc
        try:
            return [m["name"] for m in resp.json().get("models", [])]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderResponseError("Malformed /api/tags response from Ollama", self.name) from exc

    def is_available(self) -> ProviderStatus:
        try:
            models = self.list_models()
        except (ProviderUnavailableError, ProviderResponseError) as exc:
            return ProviderStatus(self.name, False, self.model, str(exc))
        if not any(_model_matches(self.model, m) for m in models):
            return ProviderStatus(
                self.name, False, self.model,
                f"Ollama is running but model '{self.model}' is not pulled. Run: ollama pull {self.model}",
                {"installed_models": models},
            )
        return ProviderStatus(self.name, True, self.model, "Ollama running, model available", {"installed_models": models})

    def get_model_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"provider": self.name, "model": self.model, "base_url": self.base_url,
                                "think": self.settings.ollama_think, "num_ctx": self.settings.context_length}
        try:
            resp = self.session.post(f"{self.base_url}/api/show", json={"model": self.model}, timeout=10)
            if resp.ok:
                data = resp.json()
                details = data.get("details", {})
                info.update({
                    "family": details.get("family"),
                    "parameter_size": details.get("parameter_size"),
                    "quantization": details.get("quantization_level"),
                    "capabilities": data.get("capabilities"),
                })
        except requests.exceptions.RequestException:
            info["error"] = "Ollama not reachable"
        return info

    def running_models(self) -> list[dict[str, Any]]:
        """Models loaded in memory, including VRAM usage (/api/ps)."""
        try:
            resp = self.session.get(f"{self.base_url}/api/ps", timeout=5)
            resp.raise_for_status()
            return resp.json().get("models", [])
        except (requests.exceptions.RequestException, ValueError):
            return []

    # -------------------------------------------------------------- generation
    def generate(self, request: GenerationRequest) -> GenerationResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "stream": False,
            "think": self.settings.ollama_think,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": {
                "temperature": request.temperature,
                "num_ctx": request.context_length or self.settings.context_length,
                "num_predict": request.max_tokens,
            },
        }
        if request.json_schema is not None:
            # Ollama structured outputs: grammar-constrained decoding to the schema.
            payload["format"] = request.json_schema

        start = time.perf_counter()
        try:
            resp = self.session.post(f"{self.base_url}/api/chat", json=payload, timeout=self.settings.ollama_timeout_s)
        except requests.exceptions.Timeout as exc:
            raise ProviderTimeoutError(f"Ollama timed out after {self.settings.ollama_timeout_s}s", self.name) from exc
        except requests.exceptions.ConnectionError as exc:
            raise ProviderUnavailableError(f"Cannot connect to Ollama at {self.base_url}", self.name) from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderUnavailableError(f"Ollama request failed: {exc}", self.name) from exc

        if resp.status_code == 404:
            raise ModelNotFoundError(f"Model '{self.model}' not found in Ollama. Run: ollama pull {self.model}", self.name)
        if resp.status_code >= 400:
            body = resp.text[:500]
            if "context" in body.lower() and ("length" in body.lower() or "exceed" in body.lower()):
                raise ContextOverflowError(f"Ollama rejected the request as too long: {body}", self.name)
            if resp.status_code >= 500:
                raise ProviderUnavailableError(f"Ollama server error {resp.status_code}: {body}", self.name)
            raise ProviderResponseError(f"Ollama returned HTTP {resp.status_code}: {body}", self.name)

        try:
            data = resp.json()
            text = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderResponseError("Malformed response from Ollama /api/chat", self.name) from exc

        duration = time.perf_counter() - start
        if not text or not text.strip():
            raise ProviderResponseError("Ollama returned an empty response", self.name)

        prompt_tokens = data.get("prompt_eval_count")
        truncated = data.get("done_reason") == "length"
        if prompt_tokens and prompt_tokens >= (request.context_length or self.settings.context_length) - 16:
            log.warning("Prompt (%s tokens) filled the context window; input was likely truncated by Ollama", prompt_tokens)
        log.info("ollama %s: %.1fs, prompt=%s out=%s done_reason=%s", self.model, duration,
                 prompt_tokens, data.get("eval_count"), data.get("done_reason"))
        return GenerationResult(
            text=text, provider=self.name, model=self.model, duration_s=duration,
            prompt_tokens=prompt_tokens, output_tokens=data.get("eval_count"), truncated=truncated,
        )
