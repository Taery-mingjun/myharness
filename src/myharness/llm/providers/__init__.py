"""LLM provider registry and factory.

Provides provider discovery and a factory function for creating
LLMProvider instances from configuration.

Per P8 (replaceable compute): the cognitive provider and the embedding
provider are independently selectable. The cognitive provider powers
reasoning (think/plan/reflect); the embedding provider powers vector
memory. They may be the same backend, or different ones — e.g. Anthropic
for reasoning with OpenAI/Local for embeddings, since Anthropic and
DeepSeek do not expose embeddings APIs.
"""

from __future__ import annotations

from myharness.core.config import Settings
from myharness.core.exceptions import ProviderNotAvailableError
from myharness.llm.interfaces import LLMProvider
from myharness.llm.providers.anthropic import AnthropicProvider
from myharness.llm.providers.gemini import GeminiProvider
from myharness.llm.providers.openai import OpenAIProvider
from myharness.llm.providers.openai_compatible import (
    DeepSeekProvider,
    LocalProvider,
    QwenProvider,
)

__all__ = [
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "DeepSeekProvider",
    "QwenProvider",
    "LocalProvider",
    "create_provider",
    "get_available_providers",
]

# Registry of provider factory classes keyed by provider name.
_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GeminiProvider,
    "qwen": QwenProvider,
    "deepseek": DeepSeekProvider,
    "local": LocalProvider,
}


def get_available_providers() -> list[str]:
    """Return names of all registered provider implementations."""
    return list(_PROVIDER_REGISTRY.keys())


def create_provider(
    name: str,
    settings: Settings,
    embedding_model: str | None = None,
) -> LLMProvider:
    """Create an LLM provider instance from configuration.

    Args:
        name: Provider name (e.g. 'openai', 'anthropic', 'google',
            'qwen', 'deepseek', 'local').
        settings: Application settings with API keys and defaults.
        embedding_model: Optional override for the embedding model. Used
            when this provider serves as the embedding backend.

    Returns:
        An initialized LLMProvider instance.

    Raises:
        ProviderNotAvailableError: If the provider is not registered or
            its required configuration (API key) is missing.
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
            embedding_model=embedding_model or None,
        )

    if name == "anthropic":
        if not settings.anthropic_api_key:
            raise ProviderNotAvailableError(
                "Anthropic API key is not configured. Set MYH_ANTHROPIC_API_KEY.",
                code="ANTHROPIC_NOT_CONFIGURED",
                details={"env_var": "MYH_ANTHROPIC_API_KEY"},
            )
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            default_model=settings.anthropic_default_model,
        )

    if name == "google":
        if not settings.google_api_key:
            raise ProviderNotAvailableError(
                "Google Gemini API key is not configured. Set MYH_GOOGLE_API_KEY.",
                code="GOOGLE_NOT_CONFIGURED",
                details={"env_var": "MYH_GOOGLE_API_KEY"},
            )
        return GeminiProvider(
            api_key=settings.google_api_key,
            default_model=settings.google_default_model,
            embedding_model=embedding_model or "text-embedding-004",
        )

    if name == "qwen":
        if not settings.qwen_api_key:
            raise ProviderNotAvailableError(
                "Qwen API key is not configured. Set MYH_QWEN_API_KEY.",
                code="QWEN_NOT_CONFIGURED",
                details={"env_var": "MYH_QWEN_API_KEY"},
            )
        return QwenProvider(
            api_key=settings.qwen_api_key,
            default_model=settings.qwen_default_model,
        )

    if name == "deepseek":
        if not settings.deepseek_api_key:
            raise ProviderNotAvailableError(
                "DeepSeek API key is not configured. Set MYH_DEEPSEEK_API_KEY.",
                code="DEEPSEEK_NOT_CONFIGURED",
                details={"env_var": "MYH_DEEPSEEK_API_KEY"},
            )
        return DeepSeekProvider(
            api_key=settings.deepseek_api_key,
            default_model=settings.deepseek_default_model,
        )

    if name == "local":
        return LocalProvider(
            default_model=settings.ollama_default_model,
            base_url=f"{settings.ollama_base_url}/v1",
        )

    raise ProviderNotAvailableError(
        f"Provider '{name}' creation logic not implemented",
        code="PROVIDER_NOT_IMPLEMENTED",
        details={"requested": name},
    )
