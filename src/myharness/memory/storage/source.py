"""Append-only JSON/JSONL storage — the single Source of Truth.

All memory data is first written here before derived indexes are updated.
This enforces P9: Source data is canonical; derived data is rebuildable.

"Canonical" is a durability claim, so this module has to earn it:

- Writes are atomic *and* durable. A temp file is fsynced before the
  rename and the directory is fsynced after it, because ``os.replace``
  orders the rename but says nothing about whether the bytes reached the
  device. Without both, a power loss can leave an empty file where the
  agent's identity used to be.
- Each writer gets its own temp path. A shared ``key.tmp`` meant two
  concurrent writes to one key raced: whoever renamed second hit
  FileNotFoundError, so a legitimate identity update failed with a write
  error, and under other interleavings the surviving file could hold
  bytes from both writers.
- Damaged data is reported as damaged, never as missing. See
  :class:`~myharness.core.exceptions.MemoryCorruptionError`.
- ``store`` and ``key`` are validated as single path segments. They were
  interpolated straight into a path, so ``key="../../escaped"`` wrote
  outside the memory root.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Collection
from pathlib import Path
from typing import Any

import aiofiles

from myharness.core.exceptions import (
    MemoryCorruptionError,
    MemoryPathError,
    MemoryWriteError,
)
from myharness.core.logging import get_logger

logger = get_logger(__name__)

#: Characters that must never appear in a store or key name. Anything
#: that could introduce a new path segment, escape upwards, or truncate
#: the path at the OS layer.
_FORBIDDEN_IN_SEGMENT = ("/", "\\", "\x00")


def _as_int(value: Any) -> int:
    """Coerce a stored version to an int for sorting.

    Sorting raw values raises TypeError the moment one file holds a
    string version and another an int, which would take down the very
    listing a recovery routine depends on.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


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

    def __init__(self, base_path: Path, fsync_appends: bool = True) -> None:
        """Initialize the source of truth.

        Args:
            base_path: Root directory for all stores.
            fsync_appends: Whether each JSONL append is flushed to the
                device before returning. On by default: ``append``
                returning is what the rest of the system treats as "this
                memory is persisted". Turn it off only if you have
                measured the cost and accept losing the most recent
                entries on power loss.
        """
        self._base_path = Path(base_path).resolve()
        self._fsync_appends = fsync_appends
        self._ensure_store_dirs()

    def _ensure_store_dirs(self) -> None:
        """Create per-store directories if they don't exist."""
        for store in ("identity", "episodic", "semantic", "relationship"):
            (self._base_path / store).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _check_segment(value: str, label: str) -> str:
        """Reject anything that is not a single, safe path segment.

        Store and key names reach this class from callers that may be
        constructing them out of entry ids or user input. A name is only
        allowed to be a plain filename.
        """
        if not isinstance(value, str) or not value:
            raise MemoryPathError(
                f"{label} must be a non-empty string",
                details={label: repr(value)},
            )
        if value in (".", "..") or any(c in value for c in _FORBIDDEN_IN_SEGMENT):
            raise MemoryPathError(
                f"{label} '{value}' is not a valid path segment",
                details={label: value},
            )
        return value

    def _store_path(self, store: str) -> Path:
        """Get the directory path for a given store name."""
        return self._base_path / self._check_segment(store, "store")

    def _key_path(self, store: str, key: str) -> Path:
        """Get the file path for a JSON key within a store."""
        self._check_segment(key, "key")
        path = self._store_path(store) / f"{key}.json"
        return self._assert_contained(path)

    def _jsonl_path(self, store: str) -> Path:
        """Get the JSONL file path for a store."""
        return self._assert_contained(self._store_path(store) / "entries.jsonl")

    def _assert_contained(self, path: Path) -> Path:
        """Second line of defence: the final path must stay under the root.

        Segment validation should already make escape impossible; this
        catches anything it missed, including symlinked store
        directories pointing elsewhere.
        """
        resolved = Path(os.path.normpath(path))
        if not resolved.is_relative_to(self._base_path):
            raise MemoryPathError(
                "Resolved path escapes the memory root",
                details={"path": str(resolved), "root": str(self._base_path)},
            )
        return resolved

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        """Flush a directory entry so a rename or unlink survives a crash.

        Best-effort: some filesystems reject O_DIRECTORY fsync, and a
        failure here must not fail a write that already landed.
        """
        try:
            fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            logger.debug("SourceOfTruth: directory fsync unsupported", path=str(directory))
        finally:
            os.close(fd)

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
            MemoryPathError: If store or key is not a safe path segment.
            MemoryWriteError: If the write operation fails.
        """
        file_path = self._key_path(store, key)

        # Per-writer temp name. Sharing "{key}.tmp" made two concurrent
        # writes to one key collide: both opened the same file with "w",
        # and the second rename failed because the first had already
        # moved it away.
        tmp_path = file_path.with_name(
            f".{file_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )

        try:
            payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)

            # Written through the blocking API on purpose: fsync must
            # apply to this exact descriptor, and it has to happen before
            # the rename for the rename to mean anything.
            def _write_durably() -> None:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, file_path)
                self._fsync_dir(file_path.parent)

            await asyncio.to_thread(_write_durably)

            logger.debug("SourceOfTruth: wrote JSON", store=store, key=key, path=str(file_path))
            return str(file_path)

        except Exception as exc:
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
            The parsed dictionary, or None if the key does not exist.

        Raises:
            MemoryPathError: If store or key is not a safe path segment.
            MemoryCorruptionError: If the file exists but cannot be read
                or parsed. This used to return None, which callers read
                as "no such key" — and the caller for identity responds
                to a missing key by writing a fresh default over it. One
                torn write therefore erased the agent's self-model with
                nothing but a log line to show for it.
        """
        file_path = self._key_path(store, key)
        if not file_path.exists():
            return None

        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
        except OSError as exc:
            raise MemoryCorruptionError(
                f"Cannot read {store}/{key}",
                details={"store": store, "key": key, "path": str(file_path)},
                cause=exc,
            ) from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error(
                "SourceOfTruth: source data is corrupt",
                path=str(file_path),
                error=str(exc),
            )
            raise MemoryCorruptionError(
                f"Source data for {store}/{key} is not valid JSON",
                details={
                    "store": store,
                    "key": key,
                    "path": str(file_path),
                    "size_bytes": len(content),
                },
                cause=exc,
            ) from exc

        if not isinstance(parsed, dict):
            raise MemoryCorruptionError(
                f"Source data for {store}/{key} is a {type(parsed).__name__}, "
                "expected an object",
                details={"store": store, "key": key, "path": str(file_path)},
            )
        return parsed

    async def quarantine(self, store: str, key: str) -> str | None:
        """Move a damaged file aside instead of deleting it.

        Recovery paths need somewhere to put data they cannot parse. The
        one thing they must not do is overwrite it: a human may be able
        to salvage a truncated identity by hand, and they cannot salvage
        a file that was replaced with a default.

        Returns:
            The quarantine path, or None if there was nothing to move.
        """
        file_path = self._key_path(store, key)
        if not file_path.exists():
            return None

        stamp = uuid.uuid4().hex[:8]
        target = file_path.with_name(f"{file_path.name}.corrupt.{stamp}")

        def _move() -> None:
            os.replace(file_path, target)
            self._fsync_dir(file_path.parent)

        await asyncio.to_thread(_move)
        logger.warning(
            "SourceOfTruth: quarantined corrupt source file",
            store=store,
            key=key,
            path=str(target),
        )
        return str(target)

    async def delete(self, store: str, key: str) -> bool:
        """Delete a JSON file from a store. Returns True if deleted."""
        file_path = self._key_path(store, key)

        def _unlink() -> bool:
            try:
                file_path.unlink()
            except FileNotFoundError:
                # Another caller won the race; the postcondition holds.
                return False
            self._fsync_dir(file_path.parent)
            return True

        removed = await asyncio.to_thread(_unlink)
        if removed:
            logger.debug("SourceOfTruth: deleted JSON", store=store, key=key)
        return removed

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
            if "\n" in line[:-1]:
                # json.dumps escapes newlines, so this can only happen if
                # the serialiser was subverted. One entry spilling across
                # two lines would corrupt every offset after it.
                raise ValueError("Serialized entry contains an embedded newline")

            payload = line.encode("utf-8")
            fsync = self._fsync_appends

            def _append_durably() -> None:
                # O_APPEND makes the seek-and-write atomic against other
                # appenders, and one write() call keeps the line intact.
                fd = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                try:
                    written = 0
                    while written < len(payload):
                        written += os.write(fd, payload[written:])
                    if fsync:
                        os.fsync(fd)
                finally:
                    os.close(fd)

            await asyncio.to_thread(_append_durably)

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

        The offset indexes *readable* entries, matching :meth:`count` and
        :meth:`iterate_all`. Blank and unparseable lines are skipped
        without consuming a slot — previously a damaged line still
        advanced the cursor, so a full page silently came back short and
        the caller had no way to tell that from reaching the end.

        Args:
            store: Store name.
            start: Zero-based offset into the readable entries.
            limit: Maximum number of entries to return.

        Returns:
            List of parsed dictionaries.
        """
        if limit <= 0 or start < 0:
            return []

        file_path = self._jsonl_path(store)
        if not file_path.exists():
            return []

        results: list[dict[str, Any]] = []
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                index = 0
                lineno = 0
                async for line in f:
                    lineno += 1
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "SourceOfTruth: bad JSONL line",
                            store=store, line=lineno,
                        )
                        continue
                    if index >= start:
                        results.append(parsed)
                        if len(results) >= limit:
                            break
                    index += 1
        except FileNotFoundError:
            return []

        return results

    async def count(self, store: str) -> int:
        """Count the entries a caller can actually read back.

        Counts exactly what :meth:`scan` and :meth:`iterate_all` yield —
        non-blank, parseable lines. It used to count raw lines instead,
        so a blank line or a half-written line left by a crash inflated
        the total. Clients paginate on this number: with count() ahead of
        the readable rows, the last page comes back empty and a loop that
        stops on "fewer rows than requested" never stops.
        """
        file_path = self._jsonl_path(store)
        if not file_path.exists():
            return 0

        count = 0
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        continue
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

    async def get_all_identity_versions(
        self, exclude_keys: Collection[str] = ()
    ) -> list[dict[str, Any]]:
        """Get all identity versions, sorted by version descending.

        Bulk enumeration tolerates damaged files: the caller asked for
        every version it can have, and refusing all of them because one
        is unreadable is the opposite of useful — especially when this is
        the path a recovery routine uses to find a good version.

        Args:
            exclude_keys: Keys to leave out — used to drop the "current"
                pointer file, which duplicates the newest version.
        """
        keys = await self.list_keys("identity")
        entries = []
        for key in keys:
            if key in exclude_keys:
                continue
            try:
                data = await self.read("identity", key)
            except MemoryCorruptionError as exc:
                logger.error(
                    "SourceOfTruth: skipping corrupt identity version",
                    key=key,
                    error=str(exc),
                )
                continue
            if data:
                entries.append(data)
        entries.sort(key=lambda e: _as_int(e.get("version")), reverse=True)
        return entries

    async def get_latest_identity(self) -> dict[str, Any] | None:
        """Get the latest identity version."""
        versions = await self.get_all_identity_versions()
        return versions[0] if versions else None
