"""EpisodicStore — immutable experience records.

Per P9 (Source of Truth): Write to SourceOfTruth FIRST, then best-effort
updates to derived indexes. Episodic entries are append-only and immutable.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from myharness.schema.memory import (
    EpisodicEntry,
    MemoryCategory,
    MemoryQuery,
    MemorySearchResult,
)

if TYPE_CHECKING:
    from myharness.memory.indexing.text import TextIndex
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.storage.derived import DerivedStorage
    from myharness.memory.storage.source import SourceOfTruth

logger = structlog.get_logger(__name__)


class EpisodicStore:
    """Manages episodic memory — the agent's chronological experience log.

    Write path (P9-compliant):
      1. SourceOfTruth.append() — MUST succeed
      2. DerivedStorage.insert_episode() — best-effort
      3. TextIndex.add() — best-effort
      4. VectorIndex.add() — best-effort (if embedding present)
    """

    def __init__(
        self,
        source: SourceOfTruth,
        derived: DerivedStorage,
        vector_idx: VectorIndex,
        text_idx: TextIndex,
    ) -> None:
        self._source = source
        self._derived = derived
        self._vector_idx = vector_idx
        self._text_idx = text_idx

    async def record(self, entry: EpisodicEntry) -> str:
        """Record an episodic entry.

        Writes to SourceOfTruth first (must succeed), then updates
        derived storage and indexes on a best-effort basis.

        Args:
            entry: The episodic entry to record.

        Returns:
            The entry_id of the recorded episode.

        Raises:
            MemoryWriteError: If the source-of-truth write fails.
        """
        data = entry.model_dump(mode="json")
        entry_id = str(entry.entry_id)

        # Step 1: Write to SourceOfTruth (MUST succeed)
        await self._source.append("episodic", data)
        logger.debug("EpisodicStore: source written", entry_id=entry_id)

        # Step 2-4: Update derived indexes (best-effort)
        try:
            await self._derived.insert_episode(data)
        except Exception as exc:
            logger.warning(
                "EpisodicStore: derived update failed",
                entry_id=entry_id,
                error=str(exc),
            )

        try:
            content = f"{entry.summary} {entry.detail} {' '.join(entry.tags)}"
            await self._text_idx.add(entry_id, {
                "store": "episodic",
                "content": content,
                "metadata": {
                    "category": entry.category,
                    "importance": entry.importance,
                    "summary": entry.summary,
                },
            })
        except Exception as exc:
            logger.warning(
                "EpisodicStore: text index update failed",
                entry_id=entry_id,
                error=str(exc),
            )

        if entry.embedding is not None:
            try:
                import numpy as np
                emb = np.array(entry.embedding, dtype=np.float32)
                await self._vector_idx.add(entry_id, emb, {
                    "store": "episodic",
                    "summary": entry.summary,
                    "category": entry.category,
                    "importance": entry.importance,
                })
            except Exception as exc:
                logger.warning(
                    "EpisodicStore: vector index update failed",
                    entry_id=entry_id,
                    error=str(exc),
                )

        return entry_id

    async def get(self, episode_id: str) -> EpisodicEntry | None:
        """Retrieve a specific episode by ID from SourceOfTruth.

        Args:
            episode_id: The unique episode identifier.

        Returns:
            The EpisodicEntry or None if not found.
        """
        # Scan source — JSONL doesn't support direct lookup, so iterate
        async for entry in self._source.iterate_all("episodic"):
            if entry.get("entry_id") == episode_id:
                return EpisodicEntry(**entry)
        return None

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        """Search episodic memory using vector and/or text search.

        If query_embedding is provided, uses vector search. Otherwise
        falls back to full-text search via the derived store.

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
                if meta.get("store") != "episodic":
                    continue
                entry = await self.get(entry_id)
                if entry is None:
                    continue
                if entry.importance < query.min_importance:
                    continue
                results.append(MemorySearchResult(
                    entry_id=entry.entry_id,
                    category=MemoryCategory.EPISODIC,
                    score=score,
                    content=entry.summary,
                    entry=entry.model_dump(mode="json"),
                ))

        # Text search path (if no vector or hybrid)
        if query.query_text and (not query.query_embedding or query.hybrid_weight < 1.0):
            text_hits = await self._text_idx.search(query.query_text, k=query.top_k)
            for entry_id, score, meta in text_hits:
                if meta.get("store") != "episodic":
                    continue
                entry = await self.get(entry_id)
                if entry is None:
                    continue
                if entry.importance < query.min_importance:
                    continue

                # If hybrid, merge scores
                if query.query_embedding:
                    score = score * (1.0 - query.hybrid_weight)

                # Avoid duplicates
                existing_ids = {str(r.entry_id) for r in results}
                if entry_id in existing_ids:
                    continue

                results.append(MemorySearchResult(
                    entry_id=entry.entry_id,
                    category=MemoryCategory.EPISODIC,
                    score=score,
                    content=entry.summary,
                    entry=entry.model_dump(mode="json"),
                ))

        # Time range filter (post-search)
        if query.time_range:
            start, end = query.time_range
            results = [
                r for r in results
                if start <= datetime.fromisoformat(
                    r.entry.get("timestamp", start.isoformat())
                ) <= end
            ]

        # Tag filter (post-search)
        if query.tags:
            results = [
                r for r in results
                if any(t in r.entry.get("tags", []) for t in query.tags)
            ]

        results.sort(key=lambda r: r.score, reverse=True)
        return results[: query.top_k]

    async def get_recent(self, limit: int = 50) -> list[EpisodicEntry]:
        """Get the most recent episodic entries from SourceOfTruth.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of EpisodicEntry objects, newest first.
        """
        count = await self._source.count("episodic")
        start = max(0, count - limit)
        raw = await self._source.scan("episodic", start=start, limit=limit)
        entries: list[EpisodicEntry] = []
        for data in raw:
            try:
                entries.append(EpisodicEntry(**data))
            except Exception:
                logger.warning("EpisodicStore: failed to parse entry")
        entries.reverse()  # Newest first
        return entries

    async def get_by_timerange(
        self, start: datetime, end: datetime
    ) -> list[EpisodicEntry]:
        """Get episodic entries within a time range.

        Args:
            start: Start of the time range (inclusive).
            end: End of the time range (inclusive).

        Returns:
            List of EpisodicEntry objects within the range.
        """
        entries: list[EpisodicEntry] = []
        async for data in self._source.iterate_all("episodic"):
            try:
                entry = EpisodicEntry(**data)
                if start <= entry.timestamp <= end:
                    entries.append(entry)
            except Exception:
                logger.warning("EpisodicStore: failed to parse entry in timerange")
        return entries

    async def count(self) -> int:
        """Return the total number of episodic entries."""
        return await self._source.count("episodic")
