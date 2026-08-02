"""The Source of Truth must survive concurrency, crashes and bad input.

P9 calls the source canonical and the derived data rebuildable. That is a
durability claim about this layer, and a claim it did not previously
meet: a torn file was reported as a missing file, and the identity store
responded to a missing file by writing a fresh default over it. The
agent's self-model could be erased by one interrupted write.

Every test here corresponds to a defect that was reproduced against the
previous implementation.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from myharness.core.exceptions import (
    MemoryCorruptionError,
    MemoryPathError,
    MemoryWriteError,
)
from myharness.memory.storage.source import SourceOfTruth
from myharness.memory.stores.identity import IDENTITY_KEY, IdentityStore
from myharness.schema.memory import IdentityEntry


@pytest.fixture
def source(tmp_path: Path) -> SourceOfTruth:
    return SourceOfTruth(tmp_path / "source")


@pytest.fixture
def identity_path(tmp_path: Path) -> Path:
    return tmp_path / "source" / "identity" / f"{IDENTITY_KEY}.json"


async def _seeded_identity(source: SourceOfTruth) -> tuple[IdentityStore, str]:
    """An identity store holding a mission worth not losing."""
    store = IdentityStore(source)
    entry = await store.get_identity()
    entry.mission = "Serve the operator faithfully for ten years"
    entry.core_values = ["honesty", "care", "precision"]
    await store.update_identity(entry)
    return store, entry.mission


# ── Corruption must not read as absence ────────────────────────────────


class TestCorruptionIsNotAbsence:
    async def test_read_raises_on_a_torn_file(self, source, identity_path):
        await source.write("identity", IDENTITY_KEY, {"mission": "x"})
        good = identity_path.read_text()
        identity_path.write_text(good[: len(good) // 2])

        with pytest.raises(MemoryCorruptionError) as exc:
            await source.read("identity", IDENTITY_KEY)

        assert "not valid JSON" in str(exc.value)

    async def test_missing_key_still_returns_none(self, source):
        assert await source.read("identity", "never_written") is None

    async def test_a_json_scalar_is_corruption_not_data(self, source, identity_path):
        identity_path.parent.mkdir(parents=True, exist_ok=True)
        identity_path.write_text('"just a string"')

        with pytest.raises(MemoryCorruptionError):
            await source.read("identity", IDENTITY_KEY)


class TestIdentitySurvivesCorruption:
    async def test_a_torn_file_no_longer_erases_the_self_model(
        self, source, identity_path
    ):
        store, mission = await _seeded_identity(source)
        good = identity_path.read_text()
        identity_path.write_text(good[: len(good) // 2])

        recovered = await store.get_identity()

        assert recovered.mission == mission
        assert recovered.core_values == ["honesty", "care", "precision"]

    async def test_the_damaged_file_is_preserved_not_overwritten(
        self, source, identity_path
    ):
        store, _ = await _seeded_identity(source)
        good = identity_path.read_text()
        truncated = good[: len(good) // 2]
        identity_path.write_text(truncated)

        await store.get_identity()

        quarantined = list(identity_path.parent.glob("*.corrupt.*"))
        assert len(quarantined) == 1
        assert quarantined[0].read_text() == truncated

    async def test_schema_violations_are_treated_as_corruption(
        self, source, identity_path
    ):
        store, mission = await _seeded_identity(source)
        # Valid JSON, wrong shape — a hand-edit or a bad migration.
        identity_path.write_text('{"version": "not-a-number", "mission": 12}')

        recovered = await store.get_identity()

        assert recovered.mission == mission

    async def test_it_refuses_to_start_blank_when_nothing_can_be_restored(
        self, source, identity_path
    ):
        store = IdentityStore(source)
        await store.get_identity()
        for path in identity_path.parent.glob("identity_v*.json"):
            path.unlink()
        identity_path.write_text("{{{ not json")

        with pytest.raises(MemoryCorruptionError) as exc:
            await store.get_identity()

        assert "Refusing to start with a blank self-model" in str(exc.value)
        assert list(identity_path.parent.glob("*.corrupt.*"))

    async def test_recovery_picks_the_newest_readable_version(self, source):
        store = IdentityStore(source)
        entry = await store.get_identity()
        for n in range(3):
            entry.mission = f"mission-{n}"
            await store.update_identity(entry)

        latest = await store.get_identity()
        assert latest.mission == "mission-2"


class TestEveryVersionIsRecoverable:
    async def test_the_newest_state_exists_in_two_places(self, source, identity_path):
        store, _ = await _seeded_identity(source)
        current = await store.get_identity()

        versioned = identity_path.parent / f"identity_v{current.version}.json"
        assert versioned.exists(), (
            "the newest identity must also be written as a version file, "
            "otherwise corrupting current loses it outright"
        )
        assert json.loads(versioned.read_text())["mission"] == current.mission

    async def test_history_does_not_double_count_the_current_pointer(self, source):
        store, _ = await _seeded_identity(source)

        history = await store.get_history()
        versions = [e.version for e in history]

        assert versions == sorted(set(versions), reverse=True)

    async def test_history_skips_a_damaged_version_instead_of_failing(
        self, source, identity_path
    ):
        store, _ = await _seeded_identity(source)
        (identity_path.parent / "identity_v1.json").write_text("garbage")

        history = await store.get_history()

        assert history, "one bad version file must not hide every other version"


# ── Concurrency ────────────────────────────────────────────────────────


class TestConcurrentWrites:
    async def test_writers_to_one_key_do_not_collide(self, source, identity_path):
        payload_a = {"who": "A", "pad": "a" * 200_000}
        payload_b = {"who": "B", "pad": "b" * 200_000}

        await asyncio.gather(
            *[source.write("identity", IDENTITY_KEY, payload_a) for _ in range(6)],
            *[source.write("identity", IDENTITY_KEY, payload_b) for _ in range(6)],
        )

        data = json.loads(identity_path.read_text())
        assert data["who"] in ("A", "B")
        assert set(data["pad"]) == {data["who"].lower()}

    async def test_no_temp_files_are_left_behind(self, source, identity_path):
        await asyncio.gather(
            *[source.write("identity", IDENTITY_KEY, {"n": i}) for i in range(20)]
        )

        assert not list(identity_path.parent.glob("*.tmp"))

    async def test_temp_files_never_show_up_as_keys(self, source):
        await asyncio.gather(
            *[source.write("identity", f"k{i}", {"n": i}) for i in range(10)]
        )

        keys = await source.list_keys("identity")
        assert sorted(keys) == sorted(f"k{i}" for i in range(10))

    async def test_concurrent_appends_all_land_intact(self, source, tmp_path):
        async def writer(tag: str) -> None:
            for i in range(8):
                await source.append(
                    "episodic", {"entry_id": f"{tag}-{i}", "content": tag * 20_000}
                )

        await asyncio.gather(*(writer(t) for t in "xyzw"))

        entries = await source.scan("episodic", limit=1000)
        assert len(entries) == 32
        assert len({e["entry_id"] for e in entries}) == 32

    async def test_a_racing_delete_is_not_an_error(self, source):
        await source.write("identity", "doomed", {})

        results = await asyncio.gather(
            *[source.delete("identity", "doomed") for _ in range(5)]
        )

        assert sum(results) == 1


# ── Pagination consistency ─────────────────────────────────────────────


class TestCountAgreesWithScan:
    async def test_blank_and_torn_lines_are_not_counted(self, source, tmp_path):
        for i in range(5):
            await source.append("semantic", {"entry_id": f"e{i}"})

        path = tmp_path / "source" / "semantic" / "entries.jsonl"
        with open(path, "a") as f:
            f.write("\n")
            f.write('{"entry_id": "torn", "cont')

        assert await source.count("semantic") == 5
        assert len(await source.scan("semantic", limit=1000)) == 5

    async def test_a_damaged_line_does_not_shorten_a_page(self, source, tmp_path):
        for i in range(4):
            await source.append("semantic", {"entry_id": f"e{i}"})
        path = tmp_path / "source" / "semantic" / "entries.jsonl"
        with open(path, "a") as f:
            f.write("not json\n")
        for i in range(4, 8):
            await source.append("semantic", {"entry_id": f"e{i}"})

        page = await source.scan("semantic", start=0, limit=8)

        assert [e["entry_id"] for e in page] == [f"e{i}" for i in range(8)]

    async def test_paging_to_the_end_terminates(self, source):
        for i in range(7):
            await source.append("episodic", {"entry_id": f"e{i}"})

        seen, start = [], 0
        while True:
            page = await source.scan("episodic", start=start, limit=3)
            if not page:
                break
            seen.extend(page)
            start += len(page)
            assert start <= 7, "pagination overran the store"

        assert len(seen) == await source.count("episodic") == 7

    async def test_degenerate_windows_return_nothing(self, source):
        await source.append("episodic", {"entry_id": "e0"})

        assert await source.scan("episodic", start=0, limit=0) == []
        assert await source.scan("episodic", start=-1, limit=5) == []


# ── Path containment ───────────────────────────────────────────────────


class TestPathsStayInsideTheRoot:
    @pytest.mark.parametrize(
        "key",
        ["../../escaped", "..", ".", "a/b", "a\\b", "", "with\x00null"],
    )
    async def test_unsafe_keys_are_refused(self, source, key):
        with pytest.raises(MemoryPathError):
            await source.write("identity", key, {"pwned": True})

    async def test_unsafe_store_names_are_refused(self, source):
        with pytest.raises(MemoryPathError):
            await source.append("../../..", {"entry_id": "x"})

    async def test_nothing_was_written_outside_the_root(self, source, tmp_path):
        for key in ("../../escaped", "a/b"):
            with pytest.raises(MemoryPathError):
                await source.write("identity", key, {})

        stray = [p for p in tmp_path.iterdir() if p.name != "source"]
        assert stray == []

    async def test_reads_are_guarded_too(self, source):
        with pytest.raises(MemoryPathError):
            await source.read("identity", "../../../etc/passwd")


# ── Durability ─────────────────────────────────────────────────────────


class TestWritesAreDurable:
    async def test_json_writes_are_flushed_before_the_rename(self, source, monkeypatch):
        order: list[str] = []
        real_fsync, real_replace = __import__("os").fsync, __import__("os").replace

        import os as os_mod

        monkeypatch.setattr(
            os_mod, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1]
        )
        monkeypatch.setattr(
            os_mod,
            "replace",
            lambda a, b: (order.append("replace"), real_replace(a, b))[1],
        )

        await source.write("identity", "durable", {"a": 1})

        assert "fsync" in order and "replace" in order
        assert order.index("fsync") < order.index("replace"), (
            "os.replace only orders the rename; the data has to be on the "
            "device first or the rename can expose an empty file"
        )

    async def test_appends_are_flushed_when_configured(self, tmp_path, monkeypatch):
        import os as os_mod

        calls: list[int] = []
        real_fsync = os_mod.fsync
        monkeypatch.setattr(
            os_mod, "fsync", lambda fd: (calls.append(fd), real_fsync(fd))[1]
        )

        durable = SourceOfTruth(tmp_path / "on", fsync_appends=True)
        await durable.append("episodic", {"entry_id": "1"})
        assert calls

        calls.clear()
        fast = SourceOfTruth(tmp_path / "off", fsync_appends=False)
        await fast.append("episodic", {"entry_id": "1"})
        assert not calls

    async def test_a_failed_write_leaves_the_previous_value_intact(
        self, source, identity_path
    ):
        await source.write("identity", IDENTITY_KEY, {"mission": "original"})

        class Unserializable:
            pass

        with pytest.raises(MemoryWriteError):
            await source.write(
                "identity", IDENTITY_KEY, {"bad": {Unserializable(): 1}}
            )

        assert json.loads(identity_path.read_text())["mission"] == "original"
        assert not list(identity_path.parent.glob("*.tmp"))

    async def test_the_container_honours_the_durability_setting(self, test_settings):
        from myharness.core.di import build_container

        container = build_container(test_settings)
        assert container[SourceOfTruth]._fsync_appends is True
