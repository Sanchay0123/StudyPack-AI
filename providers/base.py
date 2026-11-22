"""Provider-independent LLM interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationRequest:
    system: str
    prompt: str
    temperature: float = 0.3
    max_tokens: int = 2048
    # JSON schema the output must follow (None = free text). Providers that
    # support constrained decoding use it; all providers receive it in the prompt.
    json_schema: dict[str, Any] | None = None
    # Context window to use for this request (None = provider default from settings).
    context_length: int | None = None
    # PNG/JPEG bytes attached to the user message (vision-capable models only).
    images: list[bytes] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    text: str
    provider: str
    model: str
    duration_s: float
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    truncated: bool = False


@dataclass
class ProviderStatus:
    provider: str
    available: bool
    model: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class BaseLLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Run a single generation. Raises providers.exceptions.ProviderError subclasses."""

    @abstractmethod
    def is_available(self) -> ProviderStatus:
        """Cheap health check: server reachable, credentials valid, model present."""

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """Static/dynamic information about the configured model."""
