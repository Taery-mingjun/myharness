"""Append-only JSON/JSONL storage — the single Source of Truth.

All memory data is first written here before derived indexes are updated.
This enforces P9: Source data is canonical; derived data is rebuildable.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os as aio_os

from myharness.core.exceptions import MemoryNotFoundError, MemoryWriteError
from myharness.core.logging import get_logger

logger = get_logger(__name__)


class SourceOfTruth:
    """Append-only JSON/JSONL file storage — canonical, immutable, human-readable.

    Directory structure:
        {base_path}/
            identity/       # JSON files (identity.json, identity_v1.json, ...)
            episodic/       # JSONL file (entries.jsonl)
            semantic/       # JSONL file (entries.jsonl)
            relationship/   # JSONL file (entries.jsonl)

    JSONL stores use append-only semantics for immutability.
    JSON stores (identity) use atomic write-then-rename for safety.
    """

    def __init__(self, base_path: Path) -> None:
        self._base_path = Path(base_path)
        self._ensure_store_dirs()

    def _ensure_store_dirs(self) -> None:
        """Create per-store directories if they don't exist."""
        for store in ("identity", "episodic", "semantic", "relationship"):
            (self._base_path / store).mkdir(parents=True, exist_ok=True)

    def _store_path(self, store: str) -> Path:
        """Get the directory path for a given store name."""
        return self._base_path / store

    def _key_path(self, store: str, key: str) -> Path:
        """Get the file path for a JSON key within a store."""
        return self._store_path(store) / f"{key}.json"

    def _jsonl_path(self, store: str) -> Path:
        """Get the JSONL file path for a store."""
        return self._store_path(store) / "entries.jsonl"

    # ── JSON (key-value) Operations ─────────────────────────────────────

    async def write(self, store: str, key: str, data: dict[str, Any]) -> str:
        """Write a JSON file atomically (write to temp, then rename).

        Args:
            store: Store name (e.g., "identity").
            key: Unique key within the store.
            data: Serializable dictionary to persist.

        Returns:
            The full path to the written file.

        Raises:
            MemoryWriteError: If the write operation fails.
        """
        file_path = self._key_path(store, key)
        tmp_path = file_path.with_suffix(".tmp")

        try:
            async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2, default=str))

            os.replace(tmp_path, file_path)
            logger.debug("SourceOfTruth: wrote JSON", store=store, key=key, path=str(file_path))
            return str(file_path)

        except Exception as exc:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise MemoryWriteError(
                f"Failed to write {store}/{key}",
                details={"store": store, "key": key, "path": str(file_path)},
                cause=exc,
            ) from exc

    async def read(self, store: str, key: str) -> dict[str, Any] | None:
        """Read a JSON file from a store.

        Args:
            store: Store name.
            key: Key within the store.

        Returns:
            The parsed dictionary, or None if not found.
        """
        file_path = self._key_path(store, key)
        if not file_path.exists():
            return None

        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("SourceOfTruth: JSON decode error", path=str(file_path), error=str(exc))
            return None

    async def delete(self, store: str, key: str) -> bool:
        """Delete a JSON file from a store. Returns True if deleted."""
        file_path = self._key_path(store, key)
        if not file_path.exists():
            return False
        file_path.unlink()
        logger.debug("SourceOfTruth: deleted JSON", store=store, key=key)
        return True

    async def list_keys(self, store: str) -> list[str]:
        """List all JSON keys (without .json extension) in a store."""
        store_path = self._store_path(store)
        if not store_path.exists():
            return []
        return sorted(
            p.stem for p in store_path.glob("*.json") if p.is_file() and not p.name.endswith(".tmp")
        )

    # ── JSONL (append-only log) Operations ──────────────────────────────

    async def append(self, store: str, entry: dict[str, Any]) -> str:
        """Append a JSON line to the store's JSONL file.

        This is the canonical write path for episodic, semantic, and
        relationship entries. Append-only ensures immutability.

        Args:
            store: Store name (episodic, semantic, relationship).
            entry: Serializable dictionary to append.

        Returns:
            The entry_id from the entry dict.

        Raises:
            MemoryWriteError: If the append fails.
        """
        file_path = self._jsonl_path(store)

        try:
            line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
            async with aiofiles.open(file_path, "a", encoding="utf-8") as f:
                await f.write(line)

            entry_id = entry.get("entry_id", "unknown")
            logger.debug("SourceOfTruth: appended JSONL", store=store, entry_id=entry_id)
            return str(entry_id)

        except Exception as exc:
            raise MemoryWriteError(
                f"Failed to append to {store}",
                details={"store": store, "path": str(file_path)},
                cause=exc,
            ) from exc

    async def scan(
        self, store: str, start: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Scan a slice of the JSONL file.

        Args:
            store: Store name.
            start: Zero-based line offset.
            limit: Maximum number of entries to return.

        Returns:
            List of parsed dictionaries.
        """
        file_path = self._jsonl_path(store)
        if not file_path.exists():
            return []

        results: list[dict[str, Any]] = []
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                line_num = 0
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if line_num >= start + limit:
                        break
                    if line_num >= start:
                        try:
                            results.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning(
                                "SourceOfTruth: bad JSONL line",
                                store=store, line=line_num,
                            )
                    line_num += 1
        except FileNotFoundError:
            return []

        return results

    async def count(self, store: str) -> int:
        """Count the number of entries in a JSONL store."""
        file_path = self._jsonl_path(store)
        if not file_path.exists():
            return 0

        count = 0
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                async for _ in f:
                    count += 1
        except FileNotFoundError:
            return 0

        return count

    async def iterate_all(self, store: str) -> AsyncIterator[dict[str, Any]]:
        """Iterate over all entries in a JSONL file.

        Args:
            store: Store name.

        Yields:
            Parsed dictionaries, one per line.
        """
        file_path = self._jsonl_path(store)
        if not file_path.exists():
            return

        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("SourceOfTruth: skipping bad JSONL line", store=store)
                    continue

    # ── Bulk / Utility ──────────────────────────────────────────────────

    async def get_all_identity_versions(self) -> list[dict[str, Any]]:
        """Get all identity versions, sorted by version descending."""
        keys = await self.list_keys("identity")
        entries = []
        for key in keys:
            data = await self.read("identity", key)
            if data:
                entries.append(data)
        entries.sort(key=lambda e: e.get("version", 0), reverse=True)
        return entries

    async def get_latest_identity(self) -> dict[str, Any] | None:
        """Get the latest identity version."""
        versions = await self.get_all_identity_versions()
        return versions[0] if versions else None
