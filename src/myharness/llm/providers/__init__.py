"""LLM provider registry and factory.

Provides provider discovery and a factory function for creating
LLMProvider instances from configuration.
"""

from __future__ import annotations

from myharness.core.config import Settings
from myharness.core.exceptions import ProviderNotAvailableError
from myharness.llm.interfaces import LLMProvider
from myharness.llm.providers.openai import OpenAIProvider

__all__ = [
    "OpenAIProvider",
    "create_provider",
    "get_available_providers",
]

# Registry of provider factory functions keyed by provider name
_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
}


def get_available_providers() -> list[str]:
    """Return names of all registered provider implementations."""
    return list(_PROVIDER_REGISTRY.keys())


def create_provider(name: str, settings: Settings) -> LLMProvider:
    """Create an LLM provider instance from configuration.

    Args:
        name: Provider name (e.g., 'openai', 'anthropic').
        settings: Application settings with API keys and defaults.

    Returns:
        An initialized LLMProvider instance.

    Raises:
        ProviderNotAvailableError: If the provider is not registered
            or its required configuration is missing.
    """
    provider_cls = _PROVIDER_REGISTRY.get(name)
    if provider_cls is None:
        raise ProviderNotAvailableError(
            f"Provider '{name}' is not registered. Available: {get_available_providers()}",
            code="PROVIDER_NOT_REGISTERED",
            details={"requested": name, "available": get_available_providers()},
        )

    if name == "openai":
        if not settings.openai_api_key:
            raise ProviderNotAvailableError(
                "OpenAI API key is not configured. Set MYH_OPENAI_API_KEY.",
                code="OPENAI_NOT_CONFIGURED",
                details={"env_var": "MYH_OPENAI_API_KEY"},
            )
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            default_model=settings.openai_default_model,
        )

    raise ProviderNotAvailableError(
        f"Provider '{name}' creation logic not implemented",
        code="PROVIDER_NOT_IMPLEMENTED",
        details={"requested": name},
    )
