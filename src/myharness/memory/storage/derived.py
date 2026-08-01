"""SQLite-based derived storage — fast queries, fully rebuildable from SourceOfTruth.

Per P9: This storage layer is DERIVED. All data can be reconstructed
from the SourceOfTruth JSON files. It must never be the sole source of any data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from myharness.core.logging import get_logger

logger = get_logger(__name__)

# SQL schema — created on first connection
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    summary TEXT NOT NULL,
    detail TEXT DEFAULT '',
    participants TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    importance REAL DEFAULT 0.5,
    timestamp TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS semantics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT UNIQUE NOT NULL,
    entity TEXT NOT NULL,
    attribute TEXT NOT NULL,
    value TEXT,
    confidence REAL DEFAULT 1.0,
    source TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT UNIQUE NOT NULL,
    entity_a TEXT NOT NULL,
    entity_b TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    strength REAL DEFAULT 0.5,
    context TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp);
CREATE INDEX IF NOT EXISTS idx_episodes_category ON episodes(category);
CREATE INDEX IF NOT EXISTS idx_episodes_importance ON episodes(importance);
CREATE INDEX IF NOT EXISTS idx_semantics_entity ON semantics(entity);
CREATE INDEX IF NOT EXISTS idx_semantics_attribute ON semantics(attribute);
CREATE INDEX IF NOT EXISTS idx_relationships_entity_a ON relationships(entity_a);
CREATE INDEX IF NOT EXISTS idx_relationships_entity_b ON relationships(entity_b);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relation_type);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    summary, detail, tags, content=episodes, content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS semantics_fts USING fts5(
    entity, attribute, value, content=semantics, content_rowid=id
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, summary, detail, tags)
    VALUES (new.id, new.summary, new.detail, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, detail, tags)
    VALUES ('delete', old.id, old.summary, old.detail, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, detail, tags)
    VALUES ('delete', old.id, old.summary, old.detail, old.tags);
    INSERT INTO episodes_fts(rowid, summary, detail, tags)
    VALUES (new.id, new.summary, new.detail, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS semantics_ai AFTER INSERT ON semantics BEGIN
    INSERT INTO semantics_fts(rowid, entity, attribute, value)
    VALUES (new.id, new.entity, new.attribute, new.value);
END;

CREATE TRIGGER IF NOT EXISTS semantics_ad AFTER DELETE ON semantics BEGIN
    INSERT INTO semantics_fts(semantics_fts, rowid, entity, attribute, value)
    VALUES ('delete', old.id, old.entity, old.attribute, old.value);
END;

CREATE TRIGGER IF NOT EXISTS semantics_au AFTER UPDATE ON semantics BEGIN
    INSERT INTO semantics_fts(semantics_fts, rowid, entity, attribute, value)
    VALUES ('delete', old.id, old.entity, old.attribute, old.value);
    INSERT INTO semantics_fts(rowid, entity, attribute, value)
    VALUES (new.id, new.entity, new.attribute, new.value);
END;
"""


class DerivedStorage:
    """SQLite-based derived metadata storage.

    All data is rebuildable from SourceOfTruth JSON files.
    Provides fast structured queries, FTS5 full-text search, and
    metadata filtering that would be slow on raw JSON files.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        """Lazy-initialize the SQLite connection and schema."""
        if self._conn is None:
            self._conn = await aiosqlite.connect(str(self._db_path))
            self._conn.row_factory = aiosqlite.Row
            await self._conn.executescript(SCHEMA_SQL)
            await self._conn.commit()
            logger.info("DerivedStorage: initialized", path=str(self._db_path))
        return self._conn

    # ── Episode Operations ──────────────────────────────────────────────

    async def insert_episode(self, entry: dict[str, Any]) -> None:
        """Insert or replace an episode entry."""
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO episodes
               (entry_id, category, summary, detail, participants, tags,
                importance, timestamp, source_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("entry_id", ""),
                entry.get("category", "general"),
                entry.get("summary", ""),
                entry.get("detail", ""),
                json.dumps(entry.get("participants", [])),
                json.dumps(entry.get("tags", [])),
                entry.get("importance", 0.5),
                self._normalize_timestamp(entry.get("timestamp")),
                self._source_ref("episodic", entry.get("entry_id", "")),
            ),
        )
        await conn.commit()

    async def query_episodes(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        min_importance: float = 0.0,
        time_start: str | None = None,
        time_end: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query episodes with filters."""
        conn = await self._get_conn()
        query = "SELECT * FROM episodes WHERE 1=1"
        params: list[Any] = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if min_importance > 0:
            query += " AND importance >= ?"
            params.append(min_importance)

        if time_start:
            query += " AND timestamp >= ?"
            params.append(time_start)

        if time_end:
            query += " AND timestamp <= ?"
            params.append(time_end)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            # Deserialize JSON fields
            for field in ("participants", "tags"):
                try:
                    d[field] = json.loads(d.get(field, "[]"))
                except (json.JSONDecodeError, TypeError):
                    d[field] = []
            results.append(d)

        # Filter by tags if needed (post-query, since tags are JSON array)
        if tags:
            results = [
                r for r in results
                if any(t in r.get("tags", []) for t in tags)
            ]

        return results

    async def get_episode(self, entry_id: str) -> dict[str, Any] | None:
        """Get a single episode by entry_id."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM episodes WHERE entry_id = ?", (entry_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        for field in ("participants", "tags"):
            try:
                d[field] = json.loads(d.get(field, "[]"))
            except (json.JSONDecodeError, TypeError):
                d[field] = []
        return d

    async def get_recent_episodes(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get most recent episodes."""
        return await self.query_episodes(limit=limit)

    async def count_episodes(self) -> int:
        """Count total episodes."""
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT COUNT(*) as cnt FROM episodes")
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ── Semantic Operations ─────────────────────────────────────────────

    async def insert_semantic(self, entry: dict[str, Any]) -> None:
        """Insert or replace a semantic entry."""
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO semantics
               (entry_id, entity, attribute, value, confidence, source, created_at, source_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("entry_id", ""),
                entry.get("entity", ""),
                entry.get("attribute", ""),
                json.dumps(entry.get("value")) if entry.get("value") is not None else None,
                entry.get("confidence", 1.0),
                entry.get("source", ""),
                self._normalize_timestamp(entry.get("created_at")),
                self._source_ref("semantic", entry.get("entry_id", "")),
            ),
        )
        await conn.commit()

    async def query_semantics(
        self,
        entity: str | None = None,
        attribute: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query semantic entries."""
        conn = await self._get_conn()
        query = "SELECT * FROM semantics WHERE 1=1"
        params: list[Any] = []

        if entity:
            query += " AND entity = ?"
            params.append(entity)

        if attribute:
            query += " AND attribute = ?"
            params.append(attribute)

        if min_confidence > 0:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("value"):
                try:
                    d["value"] = json.loads(d["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    async def get_related_semantics(
        self, entity: str, attribute: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all semantic entries for an entity, optionally filtered by attribute."""
        conn = await self._get_conn()
        if attribute:
            cursor = await conn.execute(
                "SELECT * FROM semantics WHERE entity = ? AND attribute = ?",
                (entity, attribute),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM semantics WHERE entity = ?", (entity,)
            )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("value"):
                try:
                    d["value"] = json.loads(d["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    # ── Relationship Operations ─────────────────────────────────────────

    async def insert_relationship(self, entry: dict[str, Any]) -> None:
        """Insert or replace a relationship entry."""
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO relationships
               (entry_id, entity_a, entity_b, relation_type, strength, context,
                metadata_json, created_at, updated_at, source_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("entry_id", ""),
                entry.get("entity_a", ""),
                entry.get("entity_b", ""),
                entry.get("relation_type", ""),
                entry.get("strength", 0.5),
                entry.get("context", ""),
                json.dumps(entry.get("metadata", {})),
                self._normalize_timestamp(entry.get("created_at")),
                self._normalize_timestamp(entry.get("updated_at")),
                self._source_ref("relationship", entry.get("entry_id", "")),
            ),
        )
        await conn.commit()

    async def get_relationship(
        self, entity_a: str, entity_b: str
    ) -> dict[str, Any] | None:
        """Get a relationship between two entities."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            """SELECT * FROM relationships
               WHERE (entity_a = ? AND entity_b = ?)
                  OR (entity_a = ? AND entity_b = ?)""",
            (entity_a, entity_b, entity_b, entity_a),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("metadata_json"):
            try:
                d["metadata"] = json.loads(d["metadata_json"])
            except json.JSONDecodeError:
                d["metadata"] = {}
        return d

    async def get_all_relationships_for(self, entity_id: str) -> list[dict[str, Any]]:
        """Get all relationships involving an entity."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            """SELECT * FROM relationships
               WHERE entity_a = ? OR entity_b = ?
               ORDER BY strength DESC""",
            (entity_id, entity_id),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("metadata_json"):
                try:
                    d["metadata"] = json.loads(d["metadata_json"])
                except json.JSONDecodeError:
                    d["metadata"] = {}
            results.append(d)
        return results

    # ── FTS5 Full-Text Search ───────────────────────────────────────────

    async def fts_search_episodes(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search on episode summaries and details."""
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                """SELECT e.*, rank FROM episodes_fts f
                   JOIN episodes e ON f.rowid = e.id
                   WHERE episodes_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            )
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                for field in ("participants", "tags"):
                    try:
                        d[field] = json.loads(d.get(field, "[]"))
                    except (json.JSONDecodeError, TypeError):
                        d[field] = []
                results.append(d)
            return results
        except aiosqlite.OperationalError:
            # FTS query syntax error — return empty
            return []

    async def fts_search_semantics(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search on semantic entries."""
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                """SELECT s.*, rank FROM semantics_fts f
                   JOIN semantics s ON f.rowid = s.id
                   WHERE semantics_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            )
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if d.get("value"):
                    try:
                        d["value"] = json.loads(d["value"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results
        except aiosqlite.OperationalError:
            return []

    # ── Rebuild from Source ─────────────────────────────────────────────

    async def clear_all(self) -> None:
        """Delete all derived data (preparation for rebuild)."""
        conn = await self._get_conn()
        await conn.execute("DELETE FROM episodes")
        await conn.execute("DELETE FROM semantics")
        await conn.execute("DELETE FROM relationships")
        # FTS content tables are cleared via triggers, but also clear them directly
        await conn.execute("DELETE FROM episodes_fts")
        await conn.execute("DELETE FROM semantics_fts")
        await conn.commit()
        logger.info("DerivedStorage: cleared all derived data")

    async def rebuild_from_source(self, source: "SourceOfTruth") -> int:
        """Fully rebuild all derived data from SourceOfTruth.

        This is the key P9 operation: delete all derived data and
        reconstruct it from the canonical JSON files.

        Args:
            source: The SourceOfTruth instance to read from.

        Returns:
            Total number of entries rebuilt.
        """
        await self.clear_all()
        total = 0

        # Rebuild episodes
        async for entry in source.iterate_all("episodic"):
            await self.insert_episode(entry)
            total += 1
        logger.info("DerivedStorage: rebuilt episodes", count=total)

        # Rebuild semantics
        sem_count = 0
        async for entry in source.iterate_all("semantic"):
            await self.insert_semantic(entry)
            sem_count += 1
        total += sem_count
        logger.info("DerivedStorage: rebuilt semantics", count=sem_count)

        # Rebuild relationships
        rel_count = 0
        async for entry in source.iterate_all("relationship"):
            await self.insert_relationship(entry)
            rel_count += 1
        total += rel_count
        logger.info("DerivedStorage: rebuilt relationships", count=rel_count)

        logger.info("DerivedStorage: rebuild complete", total_entries=total)
        return total

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_timestamp(ts: Any) -> str:
        """Normalize a timestamp to ISO format string."""
        if ts is None:
            return datetime.now(timezone.utc).isoformat()
        if isinstance(ts, datetime):
            return ts.isoformat()
        return str(ts)

    @staticmethod
    def _source_ref(store: str, entry_id: str) -> str:
        """Generate a source reference string."""
        return f"{store}:{entry_id}"

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("DerivedStorage: connection closed")
