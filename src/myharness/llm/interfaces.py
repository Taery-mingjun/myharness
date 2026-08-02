"""LLM provider abstract interface — adapter pattern for multi-provider support."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class LLMProvider(ABC):
    """Abstract LLM provider. Adapter pattern for multi-provider support.

    Each provider (OpenAI, Anthropic, Google, local, etc.) implements this
    interface, enabling the LLM Engine to work with any backend without
    provider-specific logic.

    Per P8 (Provider Switching): The engine can swap providers at runtime
    without affecting identity, memory, or skill state.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier (e.g., 'openai', 'anthropic')."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a completion request and return the full response text.

        Args:
            messages: Chat messages in [{"role": ..., "content": ...}] format.
            model: Override the default model for this request.
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum tokens in the response.
            tools: Optional function/tool definitions for tool-calling.
            **kwargs: Provider-specific extra parameters.

        Returns:
            The complete response text from the LLM.
        """
        ...

    @abstractmethod
    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Send a completion request and stream response tokens.

        Args:
            messages: Chat messages in [{"role": ..., "content": ...}] format.
            model: Override the default model for this request.
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum tokens in the response.
            **kwargs: Provider-specific extra parameters.

        Yields:
            Tokens of the response text as they arrive.
        """
        ...

    @abstractmethod
    async def embed(self, text: str | list[str]) -> list[list[float]]:
        """Generate embedding vectors for input text(s).

        Args:
            text: A single string or list of strings to embed.

        Returns:
            A list of embedding vectors, one per input text.
            Each vector is a list of floats (the embedding dimension).
        """
        ...

    @property
    @abstractmethod
    def supported_models(self) -> list[str]:
        """List of model names supported by this provider."""
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """The default model used when none is specified."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable and functional.

        Returns:
            True if the provider responds successfully, False otherwise.
        """
        ...
