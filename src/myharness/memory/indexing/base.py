"""Abstract base class for all memory indexes.

All indexes are DERIVED DATA per P9 — fully rebuildable from SourceOfTruth.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth


class BaseIndexer(ABC):
    """Abstract interface for searchable memory indexes.

    Implementations: VectorIndex (FAISS), TextIndex (SQLite FTS5).
    """

    @abstractmethod
    async def add(self, entry_id: str, data: Any) -> None:
        """Add an entry to the index.

        Args:
            entry_id: Unique identifier for the memory entry.
            data: The data to index (embedding for vector, text for text).
        """
        ...

    @abstractmethod
    async def search(
        self, query: Any, k: int = 10
    ) -> list[tuple[str, float, Any]]:
        """Search the index.

        Args:
            query: Search query (embedding array for vector, string for text).
            k: Maximum number of results to return.

        Returns:
            List of (entry_id, score, metadata) tuples, sorted by score descending.
        """
        ...

    @abstractmethod
    async def delete(self, entry_id: str) -> None:
        """Remove an entry from the index."""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Remove all entries from the index."""
        ...

    @abstractmethod
    async def rebuild_from_source(self, source: SourceOfTruth) -> int:
        """Rebuild the entire index from SourceOfTruth data.

        Args:
            source: The SourceOfTruth instance to read canonical data from.

        Returns:
            Number of entries indexed.
        """
        ...
