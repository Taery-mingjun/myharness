"""SQLite FTS5-based full-text search index.

Provides fast keyword search over episodic and semantic memory entries.
Fully rebuildable from SourceOfTruth — per P9, this is derived data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite

from myharness.core.config import get_settings
from myharness.core.logging import get_logger
from myharness.memory.indexing.base import BaseIndexer

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth

logger = get_logger(__name__)

# Separate FTS5 schema (independent from DerivedStorage's FTS)
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS text_idx USING fts5(
    entry_id UNINDEXED,
    store UNINDEXED,
    content,
    metadata UNINDEXED,
    tokenize='porter unicode61'
);
"""


class TextIndex(BaseIndexer):
    """SQLite FTS5 full-text search index for memory entries.

    Indexes text content (summary, detail, tags for episodic;
    entity, attribute, value for semantic) for fast keyword search.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        settings = get_settings()
        self._db_path = db_path or (settings.memory_index_dir / "text_fts.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        """Lazy-initialize the SQLite connection."""
        if self._conn is None:
            self._conn = await aiosqlite.connect(str(self._db_path))
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.executescript(FTS_SCHEMA)
            await self._conn.commit()
            logger.info("TextIndex: initialized", path=str(self._db_path))
        return self._conn

    async def add(
        self, entry_id: str, data: str | dict[str, Any]
    ) -> None:
        """Add a text entry to the FTS index.

        Args:
            entry_id: The memory entry's unique ID.
            data: Either a text string or dict with 'store', 'content', 'metadata'.
        """
        conn = await self._get_conn()

        if isinstance(data, str):
            store = "unknown"
            content = data
            metadata = {}
        else:
            store = data.get("store", "unknown")
            content = data.get("content", "")
            metadata = data.get("metadata", {})

        # Delete existing entry first (FTS has no upsert)
        await conn.execute(
            "DELETE FROM text_idx WHERE entry_id = ?", (entry_id,)
        )

        await conn.execute(
            "INSERT INTO text_idx (entry_id, store, content, metadata) VALUES (?, ?, ?, ?)",
            (entry_id, store, content, json.dumps(metadata, default=str)),
        )
        await conn.commit()

    async def search(
        self, query: str, k: int = 10
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Full-text search on indexed content.

        Args:
            query: Search query string (supports FTS5 syntax).
            k: Maximum results.

        Returns:
            List of (entry_id, bm25_score, metadata) tuples sorted by score.
        """
        conn = await self._get_conn()

        if not query.strip():
            return []

        try:
            cursor = await conn.execute(
                """SELECT entry_id, rank, store, metadata
                   FROM text_idx WHERE text_idx MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, k),
            )
            rows = await cursor.fetchall()

            results: list[tuple[str, float, dict[str, Any]]] = []
            for row in rows:
                entry_id = row[0]
                bm25_rank = row[1]
                meta = {}
                if row[3]:
                    try:
                        meta = json.loads(row[3])
                    except json.JSONDecodeError:
                        pass
                # BM25 rank is negative; normalize to [0,1]
                score = 1.0 / (1.0 + abs(float(bm25_rank or 0)))
                results.append((entry_id, score, meta))

            return results

        except aiosqlite.OperationalError:
            # FTS5 query syntax error
            logger.warning("TextIndex: FTS5 query error", query=query)
            return []

    async def delete(self, entry_id: str) -> None:
        """Remove an entry from the FTS index."""
        conn = await self._get_conn()
        await conn.execute(
            "DELETE FROM text_idx WHERE entry_id = ?", (entry_id,)
        )
        await conn.commit()

    async def clear(self) -> None:
        """Remove all entries from the index."""
        conn = await self._get_conn()
        await conn.execute("DELETE FROM text_idx")
        await conn.commit()
        logger.info("TextIndex: cleared")

    async def rebuild_from_source(self, source: SourceOfTruth) -> int:
        """Rebuild the text index from SourceOfTruth data.

        Args:
            source: The SourceOfTruth instance.

        Returns:
            Number of entries indexed.
        """
        await self.clear()
        count = 0

        # Index episodic entries
        async for entry in source.iterate_all("episodic"):
            content_parts = [
                entry.get("summary", ""),
                entry.get("detail", ""),
                " ".join(entry.get("tags", [])),
            ]
            content = " ".join(p for p in content_parts if p)
            if content.strip():
                await self.add(entry.get("entry_id", ""), {
                    "store": "episodic",
                    "content": content,
                    "metadata": {
                        "category": entry.get("category", ""),
                        "importance": entry.get("importance", 0.5),
                        "summary": entry.get("summary", ""),
                    },
                })
                count += 1

        # Index semantic entries
        async for entry in source.iterate_all("semantic"):
            content_parts = [
                entry.get("entity", ""),
                entry.get("attribute", ""),
                str(entry.get("value", "")),
            ]
            content = " ".join(p for p in content_parts if p)
            if content.strip():
                await self.add(entry.get("entry_id", ""), {
                    "store": "semantic",
                    "content": content,
                    "metadata": {
                        "entity": entry.get("entity", ""),
                        "attribute": entry.get("attribute", ""),
                        "confidence": entry.get("confidence", 1.0),
                    },
                })
                count += 1

        logger.info("TextIndex: rebuilt from source", entries=count)
        return count

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
