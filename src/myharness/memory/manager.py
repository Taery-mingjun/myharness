"""MemoryManager — concrete implementation of MemorySystem.

Orchestrates all four memory stores (identity, episodic, semantic,
relationship) and provides cross-store hybrid search. Implements P9
(Source of Truth) and P3 (Identity Externalization).
"""

from __future__ import annotations

import inspect
from typing import Any

import structlog

from myharness.memory.embedder import Embedder, NullEmbedder
from myharness.memory.interface import MemorySystem
from myharness.memory.stores.identity import IdentityStore
from myharness.memory.stores.episodic import EpisodicStore
from myharness.memory.stores.semantic import SemanticStore
from myharness.memory.stores.relationship import RelationshipStore
from myharness.schema.identity import IdentityUpdateProposal
from myharness.schema.memory import (
    EpisodicEntry,
    IdentityEntry,
    MemoryCategory,
    MemoryQuery,
    MemorySearchResult,
    RelationshipEntry,
    SemanticEntry,
)

logger = structlog.get_logger(__name__)


class MemoryManager(MemorySystem):
    """Concrete implementation of the MemorySystem interface.

    Orchestrates:
      - IdentityStore: Agent self-model
      - EpisodicStore: Chronological experience log
      - SemanticStore: Factual knowledge base
      - RelationshipStore: Entity relationship graph

    Cross-store search merges results from episodic and semantic stores
    with configurable hybrid (vector + text) weighting.
    """

    def __init__(
        self,
        identity: IdentityStore,
        episodic: EpisodicStore,
        semantic: SemanticStore,
        relationship: RelationshipStore,
        embedder: Embedder | None = None,
    ) -> None:
        self._identity = identity
        self._episodic = episodic
        self._semantic = semantic
        self._relationship = relationship
        # Memory owns indexing, so it owns embedding generation. It depends on
        # the narrow EmbeddingPort, never on the LLM System — preserving the
        # four-power separation. Absent an embedder, memory degrades to
        # text-only search rather than silently storing un-indexed vectors.
        self._embedder = embedder or NullEmbedder()

        # Set once close() runs. Readiness probes consult this: once the
        # backends are closed the instance can no longer serve traffic and
        # must stop being advertised as ready.
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """Whether close() has released the backing stores."""
        return self._closed

    # ── Identity ────────────────────────────────────────────────────────

    async def get_identity(self) -> IdentityEntry:
        """Get the current agent identity."""
        return await self._identity.get_identity()

    async def update_identity(self, entry: IdentityEntry) -> None:
        """Update the agent identity."""
        await self._identity.update_identity(entry)

    async def apply_identity_proposal(
        self, proposal: IdentityUpdateProposal
    ) -> IdentityEntry:
        """Apply an identity update proposal from the LLM."""
        return await self._identity.apply_proposal(proposal)

    # ── Episodic ────────────────────────────────────────────────────────

    async def record_episode(self, entry: EpisodicEntry) -> str:
        """Record a new episodic entry, vectorizing it for semantic recall.

        The embedding is generated here rather than pushed onto callers: every
        write path (supervisor, API, reflection loop) would otherwise have to
        remember to do it, and forgetting is silent — the entry persists but is
        invisible to vector search.

        If embedding is unavailable, the entry is still recorded and remains
        findable via full-text search.
        """
        if entry.embedding is None:
            entry = await self._with_embedding(entry)
        return await self._episodic.record(entry)

    async def get_episode(self, episode_id: str) -> EpisodicEntry | None:
        """Get a specific episode by ID."""
        return await self._episodic.get(episode_id)

    async def search_episodes(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Search episodic memory."""
        q = query.model_copy()
        q.categories = [MemoryCategory.EPISODIC]
        return await self._episodic.search(q)

    async def get_recent_episodes(
        self, limit: int = 50
    ) -> list[EpisodicEntry]:
        """Get the most recent episodes."""
        return await self._episodic.get_recent(limit)

    # ── Semantic ────────────────────────────────────────────────────────

    async def store_knowledge(self, entry: SemanticEntry) -> str:
        """Store a semantic knowledge entry."""
        return await self._semantic.store(entry)

    async def search_knowledge(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Search semantic memory."""
        q = query.model_copy()
        q.categories = [MemoryCategory.SEMANTIC]
        return await self._semantic.search(q)

    async def get_related_knowledge(
        self, entity_id: str, relation: str | None = None
    ) -> list[SemanticEntry]:
        """Get semantic entries related to an entity."""
        return await self._semantic.get_related(entity_id, relation)

    # ── Relationship ────────────────────────────────────────────────────

    async def set_relationship(self, entry: RelationshipEntry) -> None:
        """Set (upsert) a relationship between entities."""
        await self._relationship.set(entry)

    async def get_relationship(
        self, entity_a: str, entity_b: str
    ) -> RelationshipEntry | None:
        """Get the relationship between two entities."""
        return await self._relationship.get(entity_a, entity_b)

    async def get_all_relationships_for(
        self, entity_id: str
    ) -> list[RelationshipEntry]:
        """Get all relationships involving an entity."""
        return await self._relationship.get_all_for(entity_id)

    # ── Cross-Store ─────────────────────────────────────────────────────

    async def search(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Cross-store hybrid search across episodic and semantic memory.

        Searches both episodic and semantic stores, merges results,
        and ranks by relevance score.

        Args:
            query: The memory query specification.

        Returns:
            Merged and ranked list of MemorySearchResult objects.
        """
        categories = query.categories or list(MemoryCategory)
        all_results: list[MemorySearchResult] = []

        # Vectorize the query once and reuse it across stores: without an
        # embedding the stores silently fall back to keyword-only matching,
        # which defeats the purpose of semantic recall.
        query = await self._with_query_embedding(query)

        if MemoryCategory.EPISODIC in categories:
            try:
                episodic_results = await self._episodic.search(query)
                all_results.extend(episodic_results)
            except Exception as exc:
                logger.warning(
                    "MemoryManager: episodic search failed",
                    error=str(exc),
                )

        if MemoryCategory.SEMANTIC in categories:
            try:
                semantic_results = await self._semantic.search(query)
                all_results.extend(semantic_results)
            except Exception as exc:
                logger.warning(
                    "MemoryManager: semantic search failed",
                    error=str(exc),
                )

        # Sort by score descending and limit to top_k
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[: query.top_k]

    async def archive_old_episodes(
        self, before_timestamp: float
    ) -> int:
        """Archive episodes older than the given timestamp.

        Since SourceOfTruth is append-only, "archiving" is handled at
        the query level (filter by timestamp). This method returns the
        count of episodes that would be eligible for archiving.

        Args:
            before_timestamp: Unix timestamp threshold.

        Returns:
            Number of episodes older than the threshold.
        """
        from datetime import datetime, timezone

        cutoff = datetime.fromtimestamp(before_timestamp, tz=timezone.utc)
        count = 0
        async for entry in self._episodic._source.iterate_all("episodic"):
            try:
                ts = entry.get("timestamp", "")
                if isinstance(ts, str):
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    ts_dt = ts
                if ts_dt < cutoff:
                    count += 1
            except Exception:
                pass
        return count

    async def rebuild_indexes(self) -> None:
        """Fully rebuild all derived indexes from SourceOfTruth.

        Per P9: All derived data (SQLite, FAISS, FTS5) can be
        reconstructed from the canonical JSON/JSONL source files.

        Rebuild order:
          1. DerivedStorage (SQLite)
          2. TextIndex (FTS5)
          3. VectorIndex (FAISS)
        """
        logger.info("MemoryManager: starting full index rebuild")

        source = self._episodic._source  # All stores share the same SourceOfTruth

        # Rebuild derived storage
        try:
            derived_count = await self._episodic._derived.rebuild_from_source(source)
            logger.info("MemoryManager: derived storage rebuilt", entries=derived_count)
        except Exception as exc:
            logger.error(
                "MemoryManager: derived storage rebuild failed",
                error=str(exc),
            )

        # Rebuild text index
        try:
            text_count = await self._episodic._text_idx.rebuild_from_source(source)
            logger.info("MemoryManager: text index rebuilt", entries=text_count)
        except Exception as exc:
            logger.error(
                "MemoryManager: text index rebuild failed",
                error=str(exc),
            )

        # Rebuild vector index
        try:
            vector_count = await self._episodic._vector_idx.rebuild_from_source(source)
            logger.info("MemoryManager: vector index rebuilt", entries=vector_count)
        except Exception as exc:
            logger.error(
                "MemoryManager: vector index rebuild failed",
                error=str(exc),
            )

        logger.info("MemoryManager: index rebuild complete")

    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics from all memory stores.

        Returns:
            Dict with counts and metadata from each store.
        """
        stats: dict[str, Any] = {
            "episodic": {},
            "semantic": {},
            "relationship": {},
            "identity": {},
            "indexes": {},
        }

        # Store counts
        try:
            stats["episodic"]["total_entries"] = await self._episodic.count()
        except Exception as exc:
            stats["episodic"]["error"] = str(exc)

        try:
            stats["semantic"]["total_entries"] = await self._semantic.count()
        except Exception as exc:
            stats["semantic"]["error"] = str(exc)

        try:
            stats["relationship"]["total_entries"] = await self._relationship.count()
        except Exception as exc:
            stats["relationship"]["error"] = str(exc)

        # Identity info
        try:
            identity = await self._identity.get_identity()
            stats["identity"] = {
                "version": identity.version,
                "has_mission": bool(identity.mission),
                "num_values": len(identity.core_values),
                "num_guidelines": len(identity.behavioral_guidelines),
                "num_preferences": len(identity.preferences),
            }
        except Exception as exc:
            stats["identity"]["error"] = str(exc)

        # Index stats
        try:
            stats["indexes"]["vector_count"] = self._episodic._vector_idx.size
        except Exception:
            stats["indexes"]["vector_count"] = 0

        return stats

    # ── Embedding helpers ───────────────────────────────────────────────

    @staticmethod
    def _episode_text(entry: EpisodicEntry) -> str:
        """Build the text representation of an episode used for embedding.

        Summary and detail are joined so that recall works both from a
        high-level gist and from specifics buried in the detail.
        """
        parts = [entry.summary]
        if entry.detail:
            parts.append(entry.detail)
        return "\n".join(p for p in parts if p)

    async def _with_embedding(self, entry: EpisodicEntry) -> EpisodicEntry:
        """Return a copy of the entry with its embedding populated.

        Returns the entry unchanged when embedding is unavailable, so the
        write always proceeds.
        """
        if not self._embedder.enabled:
            return entry

        vector = await self._embedder.embed_one(self._episode_text(entry))
        if vector is None:
            return entry

        return entry.model_copy(update={"embedding": vector})

    async def _with_query_embedding(self, query: MemoryQuery) -> MemoryQuery:
        """Return a copy of the query with ``query_embedding`` populated.

        Respects a caller-supplied embedding and skips work when the query has
        no text or embedding is unavailable.
        """
        if query.query_embedding is not None:
            return query
        if not query.query_text.strip() or not self._embedder.enabled:
            return query

        vector = await self._embedder.embed_one(query.query_text)
        if vector is None:
            return query

        return query.model_copy(update={"query_embedding": vector})

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release all backing resources held by the memory subsystem.

        Closes every distinct storage/index backend reachable from the four
        stores. This is mandatory for graceful shutdown: ``aiosqlite`` spawns
        a NON-daemon worker thread per connection, so an unclosed connection
        prevents the interpreter from ever exiting (the process hangs in
        ``threading._shutdown`` and must be SIGKILLed by the supervisor).

        Backends are deduplicated by identity because the stores share the
        same SourceOfTruth/DerivedStorage/VectorIndex/TextIndex instances,
        and closed best-effort so one failure cannot strand the others.
        """
        seen: set[int] = set()
        backends: list[Any] = []

        for store in (
            self._identity,
            self._episodic,
            self._semantic,
            self._relationship,
        ):
            for attr in ("_source", "_derived", "_vector_idx", "_text_idx"):
                backend = getattr(store, attr, None)
                if backend is None or id(backend) in seen:
                    continue
                seen.add(id(backend))
                backends.append(backend)

        for backend in backends:
            closer = getattr(backend, "close", None)
            if closer is None:
                continue
            try:
                result = closer()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.warning(
                    "memory_backend_close_failed",
                    backend=type(backend).__name__,
                    exc_info=True,
                )

        self._closed = True
        logger.info("memory_manager_closed", backends_closed=len(backends))
