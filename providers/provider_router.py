"""Primary/fallback provider routing.

Fallback only happens for `fallback_eligible` errors (availability, network,
quota, auth, missing model). Validation problems with the *content* of a
response are never hidden by switching providers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config.logging_config import get_logger
from config.settings import Settings, get_settings
from providers.base import BaseLLMProvider, GenerationRequest, GenerationResult, ProviderStatus
from providers.exceptions import ProviderError, ProviderUnavailableError

log = get_logger("providers.router")


def build_provider(name: str, settings: Settings) -> BaseLLMProvider:
    if name == "ollama":
        from providers.ollama_provider import OllamaProvider
        return OllamaProvider(settings)
    if name == "gemini":
        from providers.gemini_provider import GeminiProvider
        return GeminiProvider(settings)
    raise ValueError(f"Unknown provider {name!r}")


@dataclass
class RouteEvent:
    provider: str
    ok: bool
    message: str


@dataclass
class ProviderRouter:
    primary: BaseLLMProvider
    fallback: BaseLLMProvider | None = None
    last_provider: str | None = None
    events: list[RouteEvent] = field(default_factory=list)

    @classmethod
    def from_settings(cls, settings: Settings | None = None, primary_override: str | None = None) -> "ProviderRouter":
        settings = settings or get_settings()
        primary_name = primary_override or settings.default_provider
        primary = build_provider(primary_name, settings)
        fallback = None
        if settings.fallback_provider and settings.fallback_provider != primary_name:
            fallback = build_provider(settings.fallback_provider, settings)
        return cls(primary=primary, fallback=fallback)

    @property
    def chain(self) -> list[BaseLLMProvider]:
        return [p for p in (self.primary, self.fallback) if p is not None]

    def statuses(self) -> list[ProviderStatus]:
        return [p.is_available() for p in self.chain]

    def active_provider_name(self) -> str:
        """Name of the first provider in the chain that is currently available."""
        for status in self.statuses():
            if status.available:
                return status.provider
        return "none"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        errors: list[str] = []
        for provider in self.chain:
            try:
                result = provider.generate(request)
            except ProviderError as exc:
                self.events.append(RouteEvent(provider.name, False, str(exc)))
                if exc.fallback_eligible and provider is not self.chain[-1]:
                    log.warning("Provider %s failed (%s); falling back", provider.name, exc)
                    errors.append(f"{provider.name}: {exc}")
                    continue
                raise
            self.last_provider = provider.name
            self.events.append(RouteEvent(provider.name, True, "ok"))
            if errors:
                log.info("Generation served by fallback provider %s", provider.name)
            return result
        raise ProviderUnavailableError("No provider could serve the request: " + " | ".join(errors))
