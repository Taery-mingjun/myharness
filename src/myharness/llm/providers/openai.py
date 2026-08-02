"""OpenAI provider adapter using the official openai SDK.

Implements the LLMProvider interface for OpenAI-compatible APIs.
Supports chat completions, streaming, and embeddings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog
from openai import AsyncOpenAI

from myharness.core.exceptions import ProviderError, TokenLimitError
from myharness.llm.interfaces import LLMProvider

logger = structlog.get_logger(__name__)

# Default embedding models in preference order
_EMBEDDING_MODELS = ["text-embedding-3-small", "text-embedding-ada-002"]


class OpenAIProvider(LLMProvider):
    """OpenAI provider adapter using the official openai SDK.

    Handles chat completions (sync and streaming), embeddings, and health checks.
    Per P8: This provider can be swapped at runtime without affecting state.
    """

    _SUPPORTED_MODELS = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
    ]

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-4o",
        base_url: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        """Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key.
            default_model: Default chat model (default: gpt-4o).
            base_url: Optional custom base URL (for proxies or compatible APIs).
            embedding_model: Override embedding model. If None, auto-detects.
        """
        if not api_key:
            raise ProviderError(
                "OpenAI API key is required",
                code="OPENAI_MISSING_API_KEY",
            )

        self._api_key = api_key
        self._default_model = default_model
        self._embedding_model = embedding_model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        logger.info(
            "openai_provider_initialized",
            default_model=default_model,
            base_url=base_url or "default",
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supported_models(self) -> list[str]:
        return list(self._SUPPORTED_MODELS)

    @property
    def default_model(self) -> str:
        return self._default_model

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a chat completion request and return the full response text."""
        used_model = model or self._default_model

        params: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            params["tools"] = tools

        # Merge any provider-specific extra parameters
        params.update(kwargs)

        try:
            logger.debug(
                "openai_complete_request",
                model=used_model,
                message_count=len(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                has_tools=bool(tools),
            )
            response = await self._client.chat.completions.create(**params)
            content = response.choices[0].message.content or ""
            logger.debug(
                "openai_complete_response",
                model=used_model,
                response_length=len(content),
                usage=(
                    response.usage.model_dump() if response.usage else None
                ),
            )
            return content

        except Exception as exc:
            error_message = str(exc).lower()
            if "token" in error_message and ("limit" in error_message or "exceed" in error_message):
                raise TokenLimitError(
                    f"Token limit exceeded with model {used_model}",
                    code="OPENAI_TOKEN_LIMIT",
                    details={"model": used_model, "max_tokens": max_tokens},
                    cause=exc,
                ) from exc
            raise ProviderError(
                f"OpenAI completion failed: {exc}",
                code="OPENAI_COMPLETION_ERROR",
                details={"model": used_model},
                cause=exc,
            ) from exc

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Send a chat completion request and stream response tokens."""
        used_model = model or self._default_model

        params: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        params.update(kwargs)

        try:
            logger.debug(
                "openai_stream_request",
                model=used_model,
                message_count=len(messages),
            )
            stream = await self._client.chat.completions.create(**params)
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content

        except Exception as exc:
            error_message = str(exc).lower()
            if "token" in error_message and ("limit" in error_message or "exceed" in error_message):
                raise TokenLimitError(
                    f"Token limit exceeded with model {used_model}",
                    code="OPENAI_TOKEN_LIMIT",
                    details={"model": used_model, "max_tokens": max_tokens},
                    cause=exc,
                ) from exc
            raise ProviderError(
                f"OpenAI streaming failed: {exc}",
                code="OPENAI_STREAM_ERROR",
                details={"model": used_model},
                cause=exc,
            ) from exc

    async def embed(self, text: str | list[str]) -> list[list[float]]:
        """Generate embedding vectors for input text(s).

        Uses text-embedding-3-small by default, falling back to
        text-embedding-ada-002 if the primary model is not available.
        """
        # Normalize to list
        texts = [text] if isinstance(text, str) else text
        if not texts:
            return []

        model = self._embedding_model or _EMBEDDING_MODELS[0]

        try:
            logger.debug(
                "openai_embed_request",
                model=model,
                text_count=len(texts),
            )
            response = await self._client.embeddings.create(
                model=model,
                input=texts,
            )
            embeddings = [d.embedding for d in response.data]
            logger.debug(
                "openai_embed_response",
                model=model,
                vector_count=len(embeddings),
                dimensions=len(embeddings[0]) if embeddings else 0,
            )
            return embeddings

        except Exception as exc:
            # Try fallback model if primary fails
            if model != _EMBEDDING_MODELS[-1]:
                fallback = _EMBEDDING_MODELS[-1]
                logger.warning(
                    "openai_embed_fallback",
                    failed_model=model,
                    fallback_model=fallback,
                    error=str(exc),
                )
                try:
                    response = await self._client.embeddings.create(
                        model=fallback,
                        input=texts,
                    )
                    return [d.embedding for d in response.data]
                except Exception as fallback_exc:
                    raise ProviderError(
                        f"OpenAI embedding failed with both models: {fallback_exc}",
                        code="OPENAI_EMBED_ERROR",
                        details={"model": model, "fallback": fallback},
                        cause=fallback_exc,
                    ) from fallback_exc

            raise ProviderError(
                f"OpenAI embedding failed: {exc}",
                code="OPENAI_EMBED_ERROR",
                details={"model": model},
                cause=exc,
            ) from exc

    async def health_check(self) -> bool:
        """Check if the OpenAI API is reachable and the key is valid.

        Uses a minimal models list call to verify connectivity.
        """
        try:
            await self._client.models.list()
            logger.debug("openai_health_check_success")
            return True
        except Exception as exc:
            logger.warning(
                "openai_health_check_failed",
                error=str(exc),
            )
            return False
