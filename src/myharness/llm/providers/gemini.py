"""Google Gemini provider adapter using the Generative Language REST API.

Implements the LLMProvider interface for Google's Gemini models via direct
HTTP calls (httpx), so no heavy SDK dependency is required. Supports chat
completions, streaming, and embeddings.

Per P8 (replaceable compute): this provider can be swapped at runtime
without affecting identity, memory, or skill state.
"""

from __future__ import annotations

import structlog
from typing import Any, AsyncIterator

import httpx

from myharness.core.exceptions import ProviderError, TokenLimitError
from myharness.llm.interfaces import LLMProvider

logger = structlog.get_logger(__name__)

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(LLMProvider):
    """Google Gemini provider adapter (REST API)."""

    _SUPPORTED_MODELS = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
    ]

    def __init__(
        self,
        api_key: str,
        default_model: str = "gemini-2.0-flash",
        embedding_model: str = "text-embedding-004",
        timeout: float = 60.0,
    ) -> None:
        """Initialize the Gemini provider.

        Args:
            api_key: Google AI Studio / Vertex API key.
            default_model: Default Gemini chat model.
            embedding_model: Default embedding model (Gemini embeddings).
            timeout: HTTP request timeout in seconds.
        """
        if not api_key:
            raise ProviderError(
                "Google Gemini API key is required",
                code="GEMINI_MISSING_API_KEY",
            )

        self._api_key = api_key
        self._default_model = default_model
        self._embedding_model = embedding_model
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)
        logger.info(
            "gemini_provider_initialized",
            default_model=default_model,
            embedding_model=embedding_model,
        )

    @property
    def provider_name(self) -> str:
        return "google"

    @property
    def supported_models(self) -> list[str]:
        return list(self._SUPPORTED_MODELS)

    @property
    def default_model(self) -> str:
        return self._default_model

    @staticmethod
    def _to_gemini_contents(
        messages: list[dict[str, str]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert OpenAI-style messages to Gemini system + contents.

        Returns (system_instruction_text, contents) where contents uses
        Gemini's ``user``/``model`` roles.
        """
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role", "user")
            text = m.get("content", "")
            if role == "system":
                system_parts.append(text)
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append(
                {"role": gemini_role, "parts": [{"text": text}]}
            )
        return "\n".join(system_parts), contents

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a generateContent request and return the response text."""
        used_model = model or self._default_model
        system_text, contents = self._to_gemini_contents(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        if tools:
            payload["tools"] = tools

        url = f"{_GEMINI_BASE}/models/{used_model}:generateContent"
        try:
            logger.debug(
                "gemini_complete_request",
                model=used_model,
                content_count=len(contents),
            )
            resp = await self._client.post(
                url, params={"key": self._api_key}, json=payload
            )
            data = self._raise_for_api_error(resp, used_model)
            text = self._extract_text(data)
            logger.debug(
                "gemini_complete_response",
                model=used_model,
                response_length=len(text),
            )
            return text
        except (ProviderError, TokenLimitError):
            raise
        except Exception as exc:
            raise ProviderError(
                f"Gemini completion failed: {exc}",
                code="GEMINI_COMPLETION_ERROR",
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
        """Stream response tokens via the streaming generateContent endpoint."""
        used_model = model or self._default_model
        system_text, contents = self._to_gemini_contents(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        url = f"{_GEMINI_BASE}/models/{used_model}:streamGenerateContent"
        try:
            async with self._client.stream(
                "POST", url, params={"key": self._api_key}, json=payload
            ) as resp:
                await self._raise_for_api_error_stream(resp, used_model)
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        import json

                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    text = self._extract_text(data)
                    if text:
                        yield text
        except (ProviderError, TokenLimitError):
            raise
        except Exception as exc:
            raise ProviderError(
                f"Gemini streaming failed: {exc}",
                code="GEMINI_STREAM_ERROR",
                details={"model": used_model},
                cause=exc,
            ) from exc

    async def embed(self, text: str | list[str]) -> list[list[float]]:
        """Generate embeddings via Gemini's batchEmbedContents API."""
        texts = [text] if isinstance(text, str) else text
        if not texts:
            return []

        requests = [
            {
                "model": f"models/{self._embedding_model}",
                "content": {"parts": [{"text": t}]},
            }
            for t in texts
        ]
        url = f"{_GEMINI_BASE}/models/{self._embedding_model}:batchEmbedContents"
        try:
            logger.debug(
                "gemini_embed_request",
                model=self._embedding_model,
                text_count=len(texts),
            )
            resp = await self._client.post(
                url, params={"key": self._api_key}, json={"requests": requests}
            )
            data = self._raise_for_api_error(resp, self._embedding_model)
            embeddings = [e["values"] for e in data.get("embeddings", [])]
            if len(embeddings) != len(texts):
                raise ProviderError(
                    "Gemini returned an unexpected number of embeddings",
                    code="GEMINI_EMBED_MISMATCH",
                    details={"expected": len(texts), "got": len(embeddings)},
                )
            logger.debug(
                "gemini_embed_response",
                model=self._embedding_model,
                vector_count=len(embeddings),
            )
            return embeddings
        except (ProviderError, TokenLimitError):
            raise
        except Exception as exc:
            raise ProviderError(
                f"Gemini embedding failed: {exc}",
                code="GEMINI_EMBED_ERROR",
                details={"model": self._embedding_model},
                cause=exc,
            ) from exc

    async def health_check(self) -> bool:
        """Check connectivity by listing available models."""
        url = f"{_GEMINI_BASE}/models"
        try:
            resp = await self._client.get(url, params={"key": self._api_key})
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("gemini_health_check_failed", error=str(exc))
            return False

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        """Extract concatenated text from a generateContent response."""
        parts: list[str] = []
        for candidate in data.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if part.get("text"):
                    parts.append(part["text"])
        return "".join(parts)

    def _raise_for_api_error(
        self, resp: httpx.Response, model: str
    ) -> dict[str, Any]:
        """Raise typed errors for non-2xx Gemini responses."""
        if resp.status_code == 200:
            return resp.json()
        body = ""
        try:
            body = resp.text
        except Exception:
            pass
        lowered = body.lower()
        if "token" in lowered and (
            "limit" in lowered or "exceed" in lowered or "maximum" in lowered
        ):
            raise TokenLimitError(
                f"Token limit exceeded with model {model}: {body[:200]}",
                code="GEMINI_TOKEN_LIMIT",
                details={"model": model},
            )
        raise ProviderError(
            f"Gemini API error {resp.status_code}: {body[:300]}",
            code="GEMINI_API_ERROR",
            details={"model": model, "status": resp.status_code},
        )

    async def _raise_for_api_error_stream(
        self, resp: httpx.Response, model: str
    ) -> None:
        if resp.status_code != 200:
            body = ""
            try:
                body = resp.text
            except Exception:
                pass
            raise ProviderError(
                f"Gemini streaming API error {resp.status_code}: {body[:300]}",
                code="GEMINI_STREAM_API_ERROR",
                details={"model": model, "status": resp.status_code},
            )
