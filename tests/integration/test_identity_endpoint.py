"""The agent's identity must be writable over HTTP — and survive conflict.

This file is the regression suite for a defect found during the
Source-of-Truth durability work: ``PUT /api/v1/memory/identity`` rejected
every request it ever received. The route bumped ``version`` to N+1 and
handed the entry to the store, while the store treats the incoming
version as the caller's view of *current* state and owns the increment —
so the conflict check always saw N+1 where it expected N, and answered
"Version conflict: expected 1, got 2". The agent's self-model was
effectively read-only over HTTP.

Also covered: partial updates must not blank out the fields they omit,
optimistic concurrency must reject stale writers, and concurrent writers
must serialise instead of silently discarding one another's update.
"""

from __future__ import annotations

import asyncio

import pytest

from myharness.core.exceptions import IdentityConflictError
from myharness.memory.storage.source import SourceOfTruth
from myharness.memory.stores.identity import IDENTITY_KEY, IdentityStore
from myharness.schema.memory import IdentityEntry

API_KEY = "integration-test-key"

IDENTITY_URL = "/api/v1/memory/identity"


def _json_headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


# ── The endpoint works at all ──────────────────────────────────────────


class TestIdentityEndpointWrites:
    async def test_a_full_update_succeeds(self, api_client):
        response = api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={
                "mission": "Serve the operator faithfully for ten years",
                "core_values": ["honesty", "care"],
            },
        )

        assert response.status_code == 200
        assert response.json()["version"] == 2

        identity = api_client.get(IDENTITY_URL, headers=_auth_headers()).json()
        assert identity["mission"] == "Serve the operator faithfully for ten years"
        assert identity["core_values"] == ["honesty", "care"]
        assert identity["version"] == 2

    async def test_a_partial_update_keeps_the_untouched_fields(self, api_client):
        api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"mission": "The mission that must survive"},
        )
        api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"self_description": "A careful assistant"},
        )

        identity = api_client.get(IDENTITY_URL, headers=_auth_headers()).json()

        assert identity["mission"] == "The mission that must survive"
        assert identity["self_description"] == "A careful assistant"
        assert identity["version"] == 3, "each update must advance the version once"

    async def test_two_updates_do_not_collide_with_the_store(self, api_client):
        """The store increments the version — the route must not pre-increment."""
        api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"mission": "first"},
        )
        api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"mission": "second"},
        )

        identity = api_client.get(IDENTITY_URL, headers=_auth_headers()).json()
        assert identity["mission"] == "second"
        assert identity["version"] == 3


# ── Optimistic concurrency ─────────────────────────────────────────────


class TestOptimisticConcurrency:
    async def test_matching_expected_version_succeeds(self, api_client):
        api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"mission": "v1"},
        )

        response = api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"mission": "v2", "expected_version": 2},
        )

        assert response.status_code == 200
        assert response.json()["version"] == 3

    async def test_stale_expected_version_is_rejected(self, api_client):
        api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"mission": "v1"},
        )

        response = api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"mission": "stale-writer", "expected_version": 1},
        )

        assert response.status_code == 409
        body = response.json()["error"]
        assert body["code"] == "IdentityConflictError"
        assert body["details"]["expected_version"] == 2

    async def test_the_rejected_write_left_no_trace(self, api_client):
        api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"mission": "v1"},
        )
        api_client.put(
            IDENTITY_URL,
            headers=_json_headers(),
            json={"mission": "stale", "expected_version": 1},
        )

        identity = api_client.get(IDENTITY_URL, headers=_auth_headers()).json()
        assert identity["mission"] == "v1"
        assert identity["version"] == 2


# ── The store serialises concurrent writers ────────────────────────────


class TestConcurrentUpdatesSerialise:
    @pytest.fixture
    def store(self, tmp_path):
        source = SourceOfTruth(tmp_path / "source")
        return IdentityStore(source)

    async def test_two_racing_writers_lose_nothing(self, store):
        await store.get_identity()

        async def writer(mission: str) -> int | None:
            current = await store.get_identity()
            entry = IdentityEntry(**current.model_dump())
            entry.mission = mission
            try:
                await store.update_identity(entry)
                return entry.version
            except IdentityConflictError:
                return None

        versions = await asyncio.gather(writer("from A"), writer("from B"))

        applied = [v for v in versions if v is not None]
        assert applied, "at least one writer must succeed"
        assert max(applied) >= 2

        final = await store.get_identity()
        assert final.mission in ("from A", "from B")
        # Every applied write is accounted for in the version history.
        history = [e.version for e in await store.get_history()]
        assert final.version in history

    async def test_a_reader_sees_a_consistent_version(self, store):
        await store.get_identity()

        async def hammer(mission: str) -> None:
            for _ in range(5):
                current = await store.get_identity()
                entry = IdentityEntry(**current.model_dump())
                entry.mission = mission
                try:
                    await store.update_identity(entry)
                except IdentityConflictError:
                    continue

        await asyncio.gather(hammer("A"), hammer("B"))

        final = await store.get_identity()
        assert final.version >= 2, "at least one hammered update must land"
        assert final.mission in ("A", "B")
        # The current pointer and the newest version file must agree.
        data = await store._source.read("identity", IDENTITY_KEY)
        assert data["version"] == final.version
        # Every version up to the current one has a readable history file —
        # nothing was applied but lost.
        history = {e.version for e in await store.get_history()}
        assert set(range(1, final.version + 1)) <= history


# ── Every state is written to a versioned file ─────────────────────────


class TestVersionedFilesAreTheSource:
    async def test_each_update_writes_a_version_file_before_the_pointer(
        self, tmp_path
    ):
        source = SourceOfTruth(tmp_path / "source")
        store = IdentityStore(source)

        entry = await store.get_identity()
        assert entry.version == 1, "the initial identity is written as version 1"
        for n in range(3):
            entry.mission = f"mission-{n}"
            await store.update_identity(entry)

        versions = await source.get_all_identity_versions(exclude_keys=(IDENTITY_KEY,))
        assert sorted(v["version"] for v in versions) == [1, 2, 3, 4]
        by_version = sorted(versions, key=lambda v: v["version"])
        assert [v["mission"] for v in by_version] == [
            "",
            "mission-0",
            "mission-1",
            "mission-2",
        ]
