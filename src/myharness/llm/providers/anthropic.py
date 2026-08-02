"""Anthropic provider adapter using the official anthropic SDK.

Implements the LLMProvider interface for Anthropic's Claude models.

NOTE on embeddings: Anthropic does not expose an embeddings API. When
Anthropic is used as the *cognitive* provider, embeddings must be served
by a separate embedding backend (configured via MYH_EMBEDDING_PROVIDER,
default "openai"). Calling ``embed`` on this provider raises a clear
ProviderError so the failure mode is explicit rather than silent.

Per P8 (replaceable compute): this provider can be swapped at runtime
without affecting identity, memory, or skill state.
"""

from __future__ import annotations

import structlog
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from myharness.core.exceptions import ProviderError, TokenLimitError
from myharness.llm.interfaces import LLMProvider

logger = structlog.get_logger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic (Claude) provider adapter."""

    _SUPPORTED_MODELS = [
        "claude-opus-4-20250514",
        "claude-sonnet-4-20250514",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-20240229",
        "claude-3-haiku-20240307",
    ]

    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-sonnet-4-20250514",
        base_url: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        """Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key.
            default_model: Default Claude model.
            base_url: Optional custom base URL (for proxies/gateways).
            max_tokens: Default max output tokens (required by Anthropic).
        """
        if not api_key:
            raise ProviderError(
                "Anthropic API key is required",
                code="ANTHROPIC_MISSING_API_KEY",
            )

        self._api_key = api_key
        self._default_model = default_model
        self._max_tokens = max_tokens
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        logger.info(
            "anthropic_provider_initialized",
            default_model=default_model,
            base_url=base_url or "default",
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def supported_models(self) -> list[str]:
        return list(self._SUPPORTED_MODELS)

    @property
    def default_model(self) -> str:
        return self._default_model

    @staticmethod
    def _split_messages(
        messages: list[dict[str, str]],
    ) -> tuple[str, list[dict[str, str]]]:
        """Split OpenAI-style messages into (system_text, conversation).

        Anthropic's API takes ``system`` as a top-level string and only
        allows ``user``/``assistant`` roles in the messages list. We
        concatenate any ``system`` role messages and drop unsupported
        roles (e.g. ``tool``) with a warning.
        """
        system_parts: list[str] = []
        conversation: list[dict[str, str]] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system_parts.append(content)
            elif role in ("user", "assistant"):
                conversation.append({"role": role, "content": content})
            else:
                logger.warning(
                    "anthropic_unsupported_role_dropped",
                    role=role,
                )
        return "\n".join(system_parts), conversation

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
        system_text, conversation = self._split_messages(messages)

        params: dict[str, Any] = {
            "model": used_model,
            "messages": conversation,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text:
            params["system"] = system_text
        # Tool calling requires the Anthropic tools beta; only forward if
        # present and explicitly enabled via kwargs to avoid API errors.
        if tools and kwargs.get("enable_tools"):
            params["tools"] = tools
        params.update({k: v for k, v in kwargs.items() if k != "enable_tools"})

        try:
            logger.debug(
                "anthropic_complete_request",
                model=used_model,
                message_count=len(conversation),
            )
            response = await self._client.messages.create(**params)
            text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            logger.debug(
                "anthropic_complete_response",
                model=used_model,
                response_length=len(text),
            )
            return text
        except Exception as exc:
            error_message = str(exc).lower()
            if "token" in error_message and (
                "limit" in error_message or "exceed" in error_message
                or "too long" in error_message
            ):
                raise TokenLimitError(
                    f"Token limit exceeded with model {used_model}",
                    code="ANTHROPIC_TOKEN_LIMIT",
                    details={"model": used_model},
                    cause=exc,
                ) from exc
            raise ProviderError(
                f"Anthropic completion failed: {exc}",
                code="ANTHROPIC_COMPLETION_ERROR",
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
        """Stream response tokens from the Anthropic API."""
        used_model = model or self._default_model
        system_text, conversation = self._split_messages(messages)

        params: dict[str, Any] = {
            "model": used_model,
            "messages": conversation,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_text:
            params["system"] = system_text
        params.update(kwargs)

        try:
            logger.debug(
                "anthropic_stream_request",
                model=used_model,
                message_count=len(conversation),
            )
            async with self._client.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as exc:
            error_message = str(exc).lower()
            if "token" in error_message and (
                "limit" in error_message or "exceed" in error_message
            ):
                raise TokenLimitError(
                    f"Token limit exceeded with model {used_model}",
                    code="ANTHROPIC_TOKEN_LIMIT",
                    details={"model": used_model},
                    cause=exc,
                ) from exc
            raise ProviderError(
                f"Anthropic streaming failed: {exc}",
                code="ANTHROPIC_STREAM_ERROR",
                details={"model": used_model},
                cause=exc,
            ) from exc

    async def embed(self, text: str | list[str]) -> list[list[float]]:
        """Anthropic does not provide an embeddings API.

        Raises:
            ProviderError: Always — embeddings must be served by a
            dedicated embedding backend (see MYH_EMBEDDING_PROVIDER).
        """
        raise ProviderError(
            "Anthropic does not provide an embeddings API. Configure a "
            "separate embedding provider (MYH_EMBEDDING_PROVIDER, e.g. "
            "'openai' or 'local') for vector memory.",
            code="ANTHROPIC_NO_EMBEDDINGS",
        )

    async def health_check(self) -> bool:
        """Check connectivity via a minimal model list call."""
        try:
            await self._client.models.list()
            logger.debug("anthropic_health_check_success")
            return True
        except Exception as exc:
            logger.warning("anthropic_health_check_failed", error=str(exc))
            return False
