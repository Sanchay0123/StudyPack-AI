"""Provider layer tests.

Offline tests use a FAKE HTTP session (test fixture) so they run without
Ollama. The `live` test calls the real configured model: `pytest -m live`.
"""
from __future__ import annotations

import pytest
import requests

from config.settings import Settings, get_settings
from providers.base import GenerationRequest, GenerationResult, ProviderStatus, BaseLLMProvider
from providers.exceptions import (
    ModelNotFoundError,
    ProviderAuthError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from providers.gemini_provider import GeminiProvider
from providers.ollama_provider import OllamaProvider
from providers.provider_router import ProviderRouter


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (str(payload) if payload is not None else "")
        self.ok = status_code < 400

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(str(self.status_code))


class FakeSession:
    """TEST FIXTURE: imitates requests.Session for the Ollama HTTP API."""

    def __init__(self, get=None, post=None, exc=None):
        self._get, self._post, self._exc = get, post, exc
        self.last_json = None

    def get(self, url, timeout=None):
        if self._exc:
            raise self._exc
        return self._get

    def post(self, url, json=None, timeout=None):
        self.last_json = json
        if self._exc:
            raise self._exc
        return self._post


SETTINGS = Settings(ollama_model="qwen3.5:4b-q4_K_M")


def test_ollama_unreachable_reports_unavailable():
    provider = OllamaProvider(SETTINGS, FakeSession(exc=requests.exceptions.ConnectionError("refused")))
    status = provider.is_available()
    assert not status.available
    assert "not reachable" in status.message


def test_ollama_missing_model_reported():
    provider = OllamaProvider(SETTINGS, FakeSession(get=FakeResponse(payload={"models": [{"name": "llama3:8b"}]})))
    status = provider.is_available()
    assert not status.available
    assert "ollama pull qwen3.5:4b-q4_K_M" in status.message


def test_ollama_available_when_model_present():
    provider = OllamaProvider(SETTINGS, FakeSession(get=FakeResponse(payload={"models": [{"name": "qwen3.5:4b-q4_K_M"}]})))
    assert provider.is_available().available


def test_ollama_generate_parses_response_and_sends_schema():
    session = FakeSession(post=FakeResponse(payload={
        "message": {"content": '{"ok": true}'}, "prompt_eval_count": 20, "eval_count": 5, "done_reason": "stop"}))
    provider = OllamaProvider(SETTINGS, session)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    result = provider.generate(GenerationRequest(system="s", prompt="p", json_schema=schema))
    assert result.text == '{"ok": true}'
    assert result.output_tokens == 5 and not result.truncated
    assert session.last_json["format"] == schema
    assert session.last_json["think"] is False
    assert session.last_json["options"]["num_ctx"] == SETTINGS.context_length


def test_ollama_404_is_model_not_found():
    provider = OllamaProvider(SETTINGS, FakeSession(post=FakeResponse(404, text="model not found")))
    with pytest.raises(ModelNotFoundError):
        provider.generate(GenerationRequest(system="s", prompt="p"))


def test_ollama_malformed_response():
    provider = OllamaProvider(SETTINGS, FakeSession(post=FakeResponse(200, payload={"unexpected": 1})))
    with pytest.raises(ProviderResponseError):
        provider.generate(GenerationRequest(system="s", prompt="p"))


def test_gemini_without_key_is_unavailable():
    provider = GeminiProvider(Settings(gemini_api_key=""))
    status = provider.is_available()
    assert not status.available and "GEMINI_API_KEY" in status.message
    with pytest.raises(ProviderUnavailableError):
        provider.generate(GenerationRequest(system="s", prompt="p"))


def test_gemini_invalid_key_maps_to_auth_error():
    from google.genai import errors

    class FakeModels:
        def generate_content(self, **kwargs):
            raise errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}})

    class FakeClient:  # TEST FIXTURE
        models = FakeModels()

    provider = GeminiProvider(Settings(gemini_api_key="bad"), client=FakeClient())
    with pytest.raises(ProviderAuthError):
        provider.generate(GenerationRequest(system="s", prompt="p"))


class ScriptedProvider(BaseLLMProvider):
    """TEST FIXTURE: provider that raises or returns preset values."""

    def __init__(self, name, error=None, text="ok"):
        self.name, self.error, self.text, self.calls = name, error, text, 0

    def generate(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return GenerationResult(self.text, self.name, "m", 0.0)

    def is_available(self):
        return ProviderStatus(self.name, self.error is None, "m", "")

    def get_model_info(self):
        return {}


def test_router_falls_back_on_availability_error():
    primary = ScriptedProvider("gemini", error=ProviderAuthError("bad key"))
    fallback = ScriptedProvider("ollama", text="local")
    router = ProviderRouter(primary, fallback)
    result = router.generate(GenerationRequest(system="s", prompt="p"))
    assert result.text == "local" and router.last_provider == "ollama"


def test_router_does_not_fall_back_on_response_errors():
    primary = ScriptedProvider("gemini", error=ProviderResponseError("malformed"))
    fallback = ScriptedProvider("ollama")
    router = ProviderRouter(primary, fallback)
    with pytest.raises(ProviderResponseError):
        router.generate(GenerationRequest(system="s", prompt="p"))
    assert fallback.calls == 0


def test_router_from_settings_without_gemini_key():
    router = ProviderRouter.from_settings(Settings(default_provider="gemini", fallback_provider="ollama", gemini_api_key=""))
    assert router.primary.name == "gemini" and router.fallback.name == "ollama"
    assert not router.primary.is_available().available


@pytest.mark.live
def test_live_ollama_roundtrip():
    """Calls the real configured local model."""
    provider = OllamaProvider(get_settings())
    status = provider.is_available()
    assert status.available, status.message
    result = provider.generate(GenerationRequest(
        system="You are a concise assistant.", prompt="Reply with exactly one word: the capital of France.",
        max_tokens=20, temperature=0.0))
    assert "paris" in result.text.lower()


def test_unresponsive_primary_is_skipped_during_cooldown_then_retried():
    from providers.exceptions import ProviderTimeoutError
    primary = ScriptedProvider("gemini", error=ProviderTimeoutError("no response"))
    fallback = ScriptedProvider("ollama", text="local")
    router = ProviderRouter(primary, fallback, cooldown_s=60)
    req = GenerationRequest(system="s", prompt="p")
    assert router.generate(req).text == "local" and primary.calls == 1
    for _ in range(3):  # within the cooldown: no more waiting on the dead primary
        assert router.generate(req).text == "local"
    assert primary.calls == 1 and fallback.calls == 4
    assert router.cooling_down("gemini") > 0
    router._skip_until["gemini"] = 0  # cooldown elapsed
    primary.error = None  # Gemini is back
    assert router.generate(req).provider == "gemini" and primary.calls == 2
    assert router.cooling_down("gemini") == 0


def test_cooldown_not_triggered_by_content_errors():
    primary = ScriptedProvider("gemini", error=ProviderResponseError("blocked"))
    router = ProviderRouter(primary, ScriptedProvider("ollama"), cooldown_s=60)
    with pytest.raises(ProviderResponseError):
        router.generate(GenerationRequest(system="s", prompt="p"))
    assert router.cooling_down("gemini") == 0


def test_gemini_timeout_maps_to_fallback_eligible_error():
    class ReadTimeout(Exception):  # stands in for the HTTP client's timeout exception
        pass
    from providers.exceptions import ProviderTimeoutError

    class TimeoutModels:  # TEST FIXTURE: SDK call that never answers
        def generate_content(self, **kwargs):
            raise ReadTimeout("timed out")

    class Client:
        models = TimeoutModels()

    provider = GeminiProvider(Settings(gemini_api_key="k"), client=Client())
    with pytest.raises(ProviderTimeoutError) as info:
        provider.generate(GenerationRequest(system="s", prompt="p"))
    assert info.value.fallback_eligible
