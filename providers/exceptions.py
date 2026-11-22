"""Provider error hierarchy.

`fallback_eligible` marks errors that justify switching to the fallback
provider (availability, network, quota, auth/configuration). Errors caused by
our own prompts or by malformed model output are NOT fallback-eligible: they
are handled by validation + targeted refinement in the prompt engine, so that
a provider switch never hides a real bug.
"""
from __future__ import annotations


class ProviderError(Exception):
    fallback_eligible = False

    def __init__(self, message: str, provider: str = ""):
        super().__init__(message)
        self.provider = provider


class ProviderUnavailableError(ProviderError):
    """Server unreachable / network failure / provider not configured."""
    fallback_eligible = True


class ModelNotFoundError(ProviderError):
    """The configured model does not exist on the provider."""
    fallback_eligible = True


class ProviderTimeoutError(ProviderError):
    fallback_eligible = True


class ProviderQuotaError(ProviderError):
    fallback_eligible = True


class ProviderAuthError(ProviderError):
    """Invalid or missing credentials (a configured-provider failure)."""
    fallback_eligible = True


class ProviderResponseError(ProviderError):
    """The provider answered, but the response envelope was malformed or empty."""
    fallback_eligible = False


class ContextOverflowError(ProviderError):
    """The request does not fit the model's context window."""
    fallback_eligible = False
