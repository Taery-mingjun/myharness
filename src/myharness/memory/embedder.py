"""Embedder — the bridge that lets Memory vectorize without depending on the LLM.

Per P8 (Replaceable Compute) and the four-power separation, the Memory System
must NOT depend on the LLM System. But vector memory needs embeddings, which
only a compute provider can produce.

This module resolves that tension with a deliberately narrow port: Memory
depends on :class:`EmbeddingPort` — a single-method interface — rather than on
``LLMEngine`` or any concrete provider. Any object exposing
``async embed(text) -> list[list[float]]`` satisfies it, including every
:class:`~myharness.llm.interfaces.LLMProvider`.

Two additional realities are handled here:

1. **Not every cognitive provider can embed.** Anthropic and DeepSeek ship no
   embeddings API, so the embedding provider is configured independently
   (``settings.embedding_provider``) from the cognitive one.
2. **Embeddings must never break writes.** A memory write that fails because
   an embedding API was rate-limited would lose the source of truth. The
   embedder therefore degrades to ``None`` on failure, and callers fall back
   to text-only indexing.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


@runtime_checkable
class EmbeddingPort(Protocol):
    """Minimal capability Memory needs from the compute layer."""

    async def embed(self, text: str | list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...


class Embedder:
    """Generates embeddings for memory indexing, degrading safely on failure.

    Args:
        port: Any object implementing ``async embed(text)``. Typically an
            ``LLMProvider``. If ``None``, the embedder is inert and every call
            returns ``None`` — vector indexing is skipped, text search still
            works.
        dimension: Expected vector dimension. Vectors whose length differs are
            rejected, because FAISS raises on a dimension mismatch and would
            otherwise turn a recoverable config error into a write failure.
    """

    #: Seconds to wait for the embedding backend before giving up on a batch.
    #: Memory writes sit on the request-critical path, so an unreachable or
    #: slow embedding endpoint must not stall them for a provider-default
    #: timeout (often 60s+).
    DEFAULT_TIMEOUT_SECONDS: float = 10.0

    def __init__(
        self,
        port: EmbeddingPort | None,
        dimension: int,
        timeout: float | None = None,
    ) -> None:
        self._port = port
        self._dimension = dimension
        self._timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT_SECONDS
        self._degraded = False

    @property
    def enabled(self) -> bool:
        """Whether embedding generation is currently possible."""
        return self._port is not None and not self._degraded

    @property
    def dimension(self) -> int:
        """Expected embedding dimension."""
        return self._dimension

    async def embed_one(self, text: str) -> list[float] | None:
        """Embed a single text, returning ``None`` if unavailable.

        Never raises. A failure here must degrade vector search, not abort the
        memory write that triggered it.
        """
        if not text or not text.strip():
            return None
        vectors = await self.embed_many([text])
        return vectors[0] if vectors else None

    async def embed_many(self, texts: list[str]) -> list[list[float]] | None:
        """Embed a batch of texts, returning ``None`` if unavailable.

        Never raises. On the first hard failure the embedder marks itself
        degraded so a broken or unconfigured provider does not incur an API
        round-trip on every subsequent memory write.
        """
        if not self.enabled or not texts:
            return None

        assert self._port is not None  # narrowed by self.enabled

        try:
            vectors = await asyncio.wait_for(
                self._port.embed(texts), timeout=self._timeout
            )
        except TimeoutError:
            self._degraded = True
            logger.warning(
                "embedding_timed_out_degrading_to_text_only",
                timeout_seconds=self._timeout,
            )
            return None
        except Exception as exc:
            self._degraded = True
            logger.warning(
                "embedding_unavailable_degrading_to_text_only",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None

        if not vectors or len(vectors) != len(texts):
            logger.warning(
                "embedding_count_mismatch",
                expected=len(texts),
                received=len(vectors) if vectors else 0,
            )
            return None

        for vector in vectors:
            if len(vector) != self._dimension:
                # Do not degrade permanently: this is a configuration error
                # (wrong embedding_dimension for the chosen model), and the
                # loud, repeated warning is the point.
                logger.error(
                    "embedding_dimension_mismatch",
                    expected=self._dimension,
                    received=len(vector),
                    hint=(
                        "Set settings.embedding_dimension to match the "
                        "embedding_model's output dimension."
                    ),
                )
                return None

        return vectors

    def reset(self) -> None:
        """Clear the degraded flag so embedding is retried.

        Useful after rotating credentials or switching providers at runtime.
        """
        self._degraded = False


class NullEmbedder(Embedder):
    """An embedder that never produces vectors.

    Used when embeddings are disabled outright, keeping call sites free of
    ``if embedder is not None`` checks.
    """

    def __init__(self, dimension: int = 1536) -> None:
        super().__init__(port=None, dimension=dimension)
