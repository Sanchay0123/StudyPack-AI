"""Gemini (cloud) provider using the official `google-genai` SDK.

Gemini is optional: without GEMINI_API_KEY the provider reports itself as
unavailable and the router uses the local fallback.
"""
from __future__ import annotations

import time
from typing import Any

from config.logging_config import get_logger
from config.settings import Settings
from providers.base import BaseLLMProvider, GenerationRequest, GenerationResult, ProviderStatus
from providers.exceptions import (
    ModelNotFoundError,
    ProviderAuthError,
    ProviderError,
    ProviderQuotaError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

log = get_logger("providers.gemini")


class GeminiProvider(BaseLLMProvider):
    name = "gemini"

    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self.model = settings.gemini_model
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.settings.gemini_configured:
            raise ProviderUnavailableError("Gemini is not configured (GEMINI_API_KEY is empty).", self.name)
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - dependency is in requirements
            raise ProviderUnavailableError("google-genai package is not installed", self.name) from exc
        self._client = genai.Client(
            api_key=self.settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=self.settings.gemini_timeout_s * 1000),
        )
        return self._client

    def _map_error(self, exc: Exception) -> ProviderError:
        try:
            from google.genai import errors as genai_errors
        except ImportError:  # pragma: no cover
            genai_errors = None
        code = getattr(exc, "code", None)
        message = str(exc)[:300]
        if genai_errors is not None and isinstance(exc, genai_errors.APIError):
            if code in (401, 403) or "API key not valid" in message or "API_KEY_INVALID" in message:
                return ProviderAuthError(f"Gemini rejected the API key: {message}", self.name)
            if code == 400 and "API key" in message:
                return ProviderAuthError(f"Gemini rejected the API key: {message}", self.name)
            if code == 429:
                return ProviderQuotaError(f"Gemini quota/rate limit exceeded: {message}", self.name)
            if code == 404:
                return ModelNotFoundError(f"Gemini model '{self.model}' not found: {message}", self.name)
            if code and code >= 500:
                return ProviderUnavailableError(f"Gemini server error {code}: {message}", self.name)
            return ProviderResponseError(f"Gemini request error {code}: {message}", self.name)
        name = exc.__class__.__name__.lower()
        if "timeout" in name:
            return ProviderTimeoutError(f"Gemini timed out: {message}", self.name)
        if "connect" in name or "network" in name:
            return ProviderUnavailableError(f"Gemini network failure: {message}", self.name)
        return ProviderUnavailableError(f"Gemini call failed: {exc.__class__.__name__}: {message}", self.name)

    def is_available(self) -> ProviderStatus:
        if not self.settings.gemini_configured and self._client is None:
            return ProviderStatus(self.name, False, self.model,
                                  "Gemini unavailable: GEMINI_API_KEY is not set. The local provider will be used.")
        try:
            client = self._get_client()
            client.models.get(model=self.model)
        except ProviderError as exc:
            return ProviderStatus(self.name, False, self.model, str(exc))
        except Exception as exc:  # noqa: BLE001 - mapped to a status message
            return ProviderStatus(self.name, False, self.model, str(self._map_error(exc)))
        return ProviderStatus(self.name, True, self.model, "Gemini API reachable, model available")

    def get_model_info(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "configured": self.settings.gemini_configured}

    def generate(self, request: GenerationRequest) -> GenerationResult:
        client = self._get_client()
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "system_instruction": request.system,
            "temperature": request.temperature,
            "max_output_tokens": request.max_tokens,
        }
        if request.json_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_json_schema"] = request.json_schema
        start = time.perf_counter()
        try:
            contents: Any = request.prompt
            if request.images:
                contents = [types.Part.from_bytes(data=img, mime_type="image/png") for img in request.images] + [request.prompt]
            response = client.models.generate_content(
                model=self.model, contents=contents, config=types.GenerateContentConfig(**config_kwargs),
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalised into our hierarchy
            raise self._map_error(exc) from exc
        duration = time.perf_counter() - start
        text = getattr(response, "text", None)
        if not text:
            raise ProviderResponseError("Gemini returned an empty response (possibly blocked by safety filters)", self.name)
        usage = getattr(response, "usage_metadata", None)
        finish = ""
        try:
            finish = str(response.candidates[0].finish_reason or "")
        except (AttributeError, IndexError, TypeError):
            pass
        log.info("gemini %s: %.1fs finish=%s", self.model, duration, finish)
        return GenerationResult(
            text=text, provider=self.name, model=self.model, duration_s=duration,
            prompt_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            truncated="MAX_TOKENS" in finish,
        )
