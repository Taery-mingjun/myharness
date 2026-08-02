"""SemanticStore — factual knowledge as entity-attribute-value triples.

Per P9 (Source of Truth): Write to SourceOfTruth FIRST, then best-effort
updates to derived indexes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from myharness.schema.memory import (
    MemoryCategory,
    MemoryQuery,
    MemorySearchResult,
    SemanticEntry,
)

if TYPE_CHECKING:
    from myharness.memory.indexing.text import TextIndex
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.storage.source import SourceOfTruth

logger = structlog.get_logger(__name__)


class SemanticStore:
    """Manages semantic memory — structured factual knowledge.

    Each entry is an entity-attribute-value triple with confidence scores.
    Supports relationship-based retrieval (get all facts about an entity).
    """

    def __init__(
        self,
        source: SourceOfTruth,
        vector_idx: VectorIndex,
        text_idx: TextIndex,
    ) -> None:
        self._source = source
        self._vector_idx = vector_idx
        self._text_idx = text_idx

    async def store(self, entry: SemanticEntry) -> str:
        """Store a semantic knowledge entry.

        Writes to SourceOfTruth first, then updates indexes on best-effort.

        Args:
            entry: The semantic entry to store.

        Returns:
            The entry_id of the stored entry.
        """
        data = entry.model_dump(mode="json")
        entry_id = str(entry.entry_id)

        # Step 1: Write to SourceOfTruth (MUST succeed)
        await self._source.append("semantic", data)
        logger.debug("SemanticStore: source written", entry_id=entry_id)

        # Step 2-3: Update indexes (best-effort)
        try:
            content = f"{entry.entity} {entry.attribute} {entry.value}"
            await self._text_idx.add(entry_id, {
                "store": "semantic",
                "content": content,
                "metadata": {
                    "entity": entry.entity,
                    "attribute": entry.attribute,
                    "confidence": entry.confidence,
                },
            })
        except Exception as exc:
            logger.warning(
                "SemanticStore: text index update failed",
                entry_id=entry_id,
                error=str(exc),
            )

        if entry.embedding is not None:
            try:
                import numpy as np
                emb = np.array(entry.embedding, dtype=np.float32)
                await self._vector_idx.add(entry_id, emb, {
                    "store": "semantic",
                    "entity": entry.entity,
                    "attribute": entry.attribute,
                    "confidence": entry.confidence,
                })
            except Exception as exc:
                logger.warning(
                    "SemanticStore: vector index update failed",
                    entry_id=entry_id,
                    error=str(exc),
                )

        return entry_id

    async def get(self, entry_id: str) -> SemanticEntry | None:
        """Retrieve a specific semantic entry by ID from SourceOfTruth.

        Args:
            entry_id: The unique entry identifier.

        Returns:
            The SemanticEntry or None if not found.
        """
        async for entry in self._source.iterate_all("semantic"):
            if entry.get("entry_id") == entry_id:
                return SemanticEntry(**entry)
        return None

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        """Search semantic memory using vector and/or text search.

        Args:
            query: The memory query specification.

        Returns:
            List of MemorySearchResult objects ranked by relevance.
        """
        results: list[MemorySearchResult] = []

        # Vector search path
        if query.query_embedding is not None:
            import numpy as np
            emb = np.array(query.query_embedding, dtype=np.float32)
            hits = await self._vector_idx.search(emb, k=query.top_k)
            for entry_id, score, meta in hits:
                if meta.get("store") != "semantic":
                    continue
                entry = await self.get(entry_id)
                if entry is None:
                    continue
                results.append(MemorySearchResult(
                    entry_id=entry.entry_id,
                    category=MemoryCategory.SEMANTIC,
                    score=score,
                    content=f"{entry.entity}.{entry.attribute} = {entry.value}",
                    entry=entry.model_dump(mode="json"),
                ))

        # Text search path
        if query.query_text and (not query.query_embedding or query.hybrid_weight < 1.0):
            text_hits = await self._text_idx.search(query.query_text, k=query.top_k)
            for entry_id, score, meta in text_hits:
                if meta.get("store") != "semantic":
                    continue
                entry = await self.get(entry_id)
                if entry is None:
                    continue

                if query.query_embedding:
                    score = score * (1.0 - query.hybrid_weight)

                existing_ids = {str(r.entry_id) for r in results}
                if entry_id in existing_ids:
                    continue

                results.append(MemorySearchResult(
                    entry_id=entry.entry_id,
                    category=MemoryCategory.SEMANTIC,
                    score=score,
                    content=f"{entry.entity}.{entry.attribute} = {entry.value}",
                    entry=entry.model_dump(mode="json"),
                ))

        # Tag filter
        if query.tags:
            results = [
                r for r in results
                if any(t.lower() in r.content.lower() for t in query.tags)
            ]

        results.sort(key=lambda r: r.score, reverse=True)
        return results[: query.top_k]

    async def get_related(
        self, entity_id: str, relation: str | None = None
    ) -> list[SemanticEntry]:
        """Get all semantic entries related to a specific entity.

        Args:
            entity_id: The entity to query for.
            relation: Optional attribute name to filter by.

        Returns:
            List of matching SemanticEntry objects.
        """
        entries: list[SemanticEntry] = []
        async for data in self._source.iterate_all("semantic"):
            try:
                entry = SemanticEntry(**data)
                if entry.entity == entity_id:
                    if relation is None or entry.attribute == relation:
                        entries.append(entry)
            except Exception:
                logger.warning("SemanticStore: failed to parse entry in get_related")
        return entries

    async def count(self) -> int:
        """Return the total number of semantic entries."""
        return await self._source.count("semantic")
