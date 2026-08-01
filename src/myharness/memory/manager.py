"""MemoryManager — concrete implementation of MemorySystem.

Orchestrates all four memory stores (identity, episodic, semantic,
relationship) and provides cross-store hybrid search. Implements P9
(Source of Truth) and P3 (Identity Externalization).
"""

from __future__ import annotations

from typing import Any

import structlog

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
    ) -> None:
        self._identity = identity
        self._episodic = episodic
        self._semantic = semantic
        self._relationship = relationship

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
        """Record a new episodic entry."""
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
