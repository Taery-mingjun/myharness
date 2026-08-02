"""OpenAI-compatible provider adapters.

Many LLM backends (DeepSeek, Qwen/DashScope, local Ollama/llama.cpp, and
any OpenAI-compatible gateway) speak the OpenAI chat-completions and
embeddings protocol. Rather than duplicate the networking code, these
adapters subclass :class:`OpenAIProvider` and only override the provider
name and the base URL / model defaults.

Per P8 (replaceable compute): any of these can be swapped at runtime
without affecting identity, memory, or skill state.
"""

from __future__ import annotations

from myharness.core.exceptions import ProviderError
from myharness.llm.providers.openai import OpenAIProvider

# DeepSeek does not offer an embeddings endpoint, so embedding requests
# must be served by a dedicated embedding backend.
_DEEPSEEK_EMBED_MSG = (
    "DeepSeek does not provide an embeddings API. Configure a separate "
    "embedding provider (MYH_EMBEDDING_PROVIDER, e.g. 'openai' or 'local')."
)


class OpenAICompatibleProvider(OpenAIProvider):
    """Base adapter for any OpenAI-compatible backend.

    Args:
        api_key: API key for the backend (some local backends accept any
            non-empty string or may be empty).
        default_model: Default chat model for this backend.
        base_url: Base URL of the OpenAI-compatible API.
        provider_name: Logical provider name (for logging/metrics).
        embedding_model: Override embedding model. If None, the backend's
            default OpenAI embedding model is attempted.
    """

    def __init__(
        self,
        api_key: str,
        default_model: str,
        base_url: str,
        provider_name: str,
        embedding_model: str | None = None,
    ) -> None:
        if not api_key:
            # Some local/compatible servers accept an arbitrary key; supply
            # a placeholder so the upstream SDK can be constructed.
            api_key = "not-needed"
        super().__init__(
            api_key=api_key,
            default_model=default_model,
            base_url=base_url,
            embedding_model=embedding_model,
        )
        self._provider_name = provider_name

    @property
    def provider_name(self) -> str:
        return self._provider_name


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek provider (OpenAI-compatible API at api.deepseek.com)."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        super().__init__(
            api_key=api_key,
            default_model=default_model,
            base_url=base_url,
            provider_name="deepseek",
        )

    async def embed(self, text: str | list[str]) -> list[list[float]]:
        """DeepSeek has no embeddings API — embeddings come from a separate backend."""
        raise ProviderError(_DEEPSEEK_EMBED_MSG, code="DEEPSEEK_NO_EMBEDDINGS")


class QwenProvider(OpenAICompatibleProvider):
    """Alibaba Qwen (通义千问) provider via DashScope OpenAI-compatible mode."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "qwen-max",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ) -> None:
        super().__init__(
            api_key=api_key,
            default_model=default_model,
            base_url=base_url,
            provider_name="qwen",
            embedding_model="text-embedding-v3",
        )


class LocalProvider(OpenAICompatibleProvider):
    """Local model provider (Ollama / llama.cpp) via the OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str = "local",
        default_model: str = "llama3.1",
        base_url: str = "http://localhost:11434/v1",
    ) -> None:
        super().__init__(
            api_key=api_key,
            default_model=default_model,
            base_url=base_url,
            provider_name="local",
            embedding_model=None,
        )
