"""RelationshipStore — entity relationship graph.

Per P9 (Source of Truth): Write to SourceOfTruth FIRST, then best-effort
updates to derived indexes. Relationships use upsert semantics (same entity
pair + relation_type overwrites).
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import structlog

from myharness.core.exceptions import MemoryNotFoundError
from myharness.schema.memory import RelationshipEntry

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth

logger = structlog.get_logger(__name__)


class RelationshipStore:
    """Manages relationship memory — connections between entities.

    Relationships are directed (entity_a → entity_b) with typed relations
    and strength scores. Uses upsert semantics: setting the same entity
    pair + relation_type overwrites the previous entry.
    """

    def __init__(self, source: SourceOfTruth) -> None:
        self._source = source

    async def set(self, entry: RelationshipEntry) -> None:
        """Set (upsert) a relationship entry.

        If a relationship with the same entity_a, entity_b, and
        relation_type already exists, it is overwritten.

        Args:
            entry: The relationship entry to set.
        """
        data = entry.model_dump(mode="json")

        # Check for existing relationship with same pair+type
        existing = await self._find_existing(
            entry.entity_a, entry.entity_b, entry.relation_type
        )

        if existing is not None:
            # Preserve the original entry_id but update other fields
            data["entry_id"] = existing.entry_id
            data["created_at"] = existing.created_at.isoformat() if hasattr(existing.created_at, 'isoformat') else str(existing.created_at)
            logger.debug(
                "RelationshipStore: updating existing relationship",
                entry_id=str(existing.entry_id),
            )
        else:
            logger.debug(
                "RelationshipStore: creating new relationship",
                entry_id=str(entry.entry_id),
            )

        # Write to SourceOfTruth (JSONL append — immutable log)
        await self._source.append("relationship", data)
        logger.info(
            "RelationshipStore: relationship set",
            entity_a=entry.entity_a,
            entity_b=entry.entity_b,
            relation_type=entry.relation_type,
        )

    async def _find_existing(
        self, entity_a: str, entity_b: str, relation_type: str
    ) -> RelationshipEntry | None:
        """Find an existing relationship with the same pair and type.

        Scans the relationship JSONL from newest to oldest to find
        the most recent matching entry.
        """
        # Collect all matching entries (iterate in reverse order by scanning
        # all and picking the last one for each unique pair+type combination)
        best: RelationshipEntry | None = None
        async for data in self._source.iterate_all("relationship"):
            try:
                entry = RelationshipEntry(**data)
                if (
                    entry.entity_a == entity_a
                    and entry.entity_b == entity_b
                    and entry.relation_type == relation_type
                ):
                    best = entry  # Keep the last (most recent) one
            except Exception:
                logger.warning("RelationshipStore: failed to parse entry in find")
        return best

    async def get(
        self, entity_a: str, entity_b: str
    ) -> RelationshipEntry | None:
        """Get the most recent relationship between two entities.

        Returns the latest entry for any relation_type between the pair.

        Args:
            entity_a: Source entity.
            entity_b: Target entity.

        Returns:
            The RelationshipEntry or None if not found.
        """
        best: RelationshipEntry | None = None
        async for data in self._source.iterate_all("relationship"):
            try:
                entry = RelationshipEntry(**data)
                if (
                    (entry.entity_a == entity_a and entry.entity_b == entity_b)
                    or (entry.entity_a == entity_b and entry.entity_b == entity_a)
                ):
                    best = entry  # Keep the last (most recent) one
            except Exception:
                logger.warning("RelationshipStore: failed to parse entry in get")
        return best

    async def get_all_for(self, entity_id: str) -> list[RelationshipEntry]:
        """Get all relationships involving a specific entity.

        Includes relationships where the entity is either entity_a or entity_b.
        Returns the latest version for each unique (entity_a, entity_b, relation_type)
        combination.

        Args:
            entity_id: The entity to query relationships for.

        Returns:
            List of RelationshipEntry objects.
        """
        # Build a dict keyed by (entity_a, entity_b, relation_type) → entry
        # to keep only the latest version of each relationship
        seen: dict[tuple[str, str, str], RelationshipEntry] = {}
        async for data in self._source.iterate_all("relationship"):
            try:
                entry = RelationshipEntry(**data)
                if entry.entity_a == entity_id or entry.entity_b == entity_id:
                    key = (entry.entity_a, entry.entity_b, entry.relation_type)
                    seen[key] = entry  # Overwrite with latest
            except Exception:
                logger.warning(
                    "RelationshipStore: failed to parse entry in get_all_for"
                )

        return sorted(
            seen.values(),
            key=lambda e: e.strength,
            reverse=True,
        )

    async def count(self) -> int:
        """Return the total number of relationship entries (including history)."""
        return await self._source.count("relationship")
