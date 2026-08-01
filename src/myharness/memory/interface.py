"""Abstract interface for the complete Memory System.

All concrete implementations (e.g., MemoryManager) must implement this
interface. The interface is the contract between the Memory System and
the rest of the Harness (LLM, API, Runtime).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from myharness.schema.identity import IdentityUpdateProposal
from myharness.schema.memory import (
    EpisodicEntry,
    IdentityEntry,
    MemoryQuery,
    MemorySearchResult,
    RelationshipEntry,
    SemanticEntry,
)


class MemorySystem(ABC):
    """Abstract interface for the complete memory system.

    Provides CRUD operations across all four memory stores and
    cross-store hybrid search. All methods are async.
    """

    # ── Identity ────────────────────────────────────────────────────────

    @abstractmethod
    async def get_identity(self) -> IdentityEntry:
        """Get the current agent identity."""
        ...

    @abstractmethod
    async def update_identity(self, entry: IdentityEntry) -> None:
        """Update the agent identity.

        Raises:
            IdentityConflictError: If version conflict is detected.
        """
        ...

    @abstractmethod
    async def apply_identity_proposal(
        self, proposal: IdentityUpdateProposal
    ) -> IdentityEntry:
        """Apply an identity update proposal from the LLM.

        Args:
            proposal: The LLM's suggested identity change.

        Returns:
            The updated IdentityEntry.
        """
        ...

    # ── Episodic ────────────────────────────────────────────────────────

    @abstractmethod
    async def record_episode(self, entry: EpisodicEntry) -> str:
        """Record a new episodic entry.

        Returns:
            The entry_id of the recorded episode.
        """
        ...

    @abstractmethod
    async def get_episode(self, episode_id: str) -> EpisodicEntry | None:
        """Get a specific episode by ID."""
        ...

    @abstractmethod
    async def search_episodes(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Search episodic memory."""
        ...

    @abstractmethod
    async def get_recent_episodes(
        self, limit: int = 50
    ) -> list[EpisodicEntry]:
        """Get the most recent episodes."""
        ...

    # ── Semantic ────────────────────────────────────────────────────────

    @abstractmethod
    async def store_knowledge(self, entry: SemanticEntry) -> str:
        """Store a semantic knowledge entry.

        Returns:
            The entry_id of the stored entry.
        """
        ...

    @abstractmethod
    async def search_knowledge(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Search semantic memory."""
        ...

    @abstractmethod
    async def get_related_knowledge(
        self, entity_id: str, relation: str | None = None
    ) -> list[SemanticEntry]:
        """Get semantic entries related to an entity."""
        ...

    # ── Relationship ────────────────────────────────────────────────────

    @abstractmethod
    async def set_relationship(self, entry: RelationshipEntry) -> None:
        """Set (upsert) a relationship between entities."""
        ...

    @abstractmethod
    async def get_relationship(
        self, entity_a: str, entity_b: str
    ) -> RelationshipEntry | None:
        """Get the relationship between two entities."""
        ...

    @abstractmethod
    async def get_all_relationships_for(
        self, entity_id: str
    ) -> list[RelationshipEntry]:
        """Get all relationships involving an entity."""
        ...

    # ── Cross-Store ─────────────────────────────────────────────────────

    @abstractmethod
    async def search(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Cross-store hybrid search across episodic and semantic memory."""
        ...

    @abstractmethod
    async def archive_old_episodes(
        self, before_timestamp: float
    ) -> int:
        """Archive episodes older than the given timestamp.

        Args:
            before_timestamp: Unix timestamp; episodes before this are archived.

        Returns:
            Number of episodes archived.
        """
        ...

    @abstractmethod
    async def rebuild_indexes(self) -> None:
        """Fully rebuild all derived indexes from SourceOfTruth.

        Per P9: All derived data can be reconstructed from source data.
        """
        ...

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics from all memory stores.

        Returns:
            Dict with counts and metadata from each store.
        """
        ...
