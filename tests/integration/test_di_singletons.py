"""Regression tests for DI singleton semantics.

These exist because of a severe, silent defect: ``build_container`` registered
every service as a bare lambda, and lagom re-runs a bare lambda on *every*
resolution. Each caller therefore received its own MemoryManager, its own FAISS
index and its own SQLite connections.

In production that meant every API request got a private, empty memory system —
writes vanished between requests — while leaking a database connection each
time. Nothing logged an error; the system merely behaved as if it had amnesia.

Identity assertions (``is``) are the whole point here. A test that only checks
"memory works" passes happily against the broken wiring.
"""

from __future__ import annotations

import pytest

from myharness.bus.dispatcher import EventBus
from myharness.bus.router import Router
from myharness.core.di import build_container
from myharness.driver.protocol import DriverManager
from myharness.harness.registry import CapabilityRegistry
from myharness.harness.supervisor import HarnessSupervisor
from myharness.llm.context import ContextBuilder
from myharness.memory.embedder import Embedder
from myharness.memory.indexing.text import TextIndex
from myharness.memory.indexing.vector import VectorIndex
from myharness.memory.interface import MemorySystem
from myharness.memory.manager import MemoryManager
from myharness.memory.storage.derived import DerivedStorage
from myharness.memory.storage.source import SourceOfTruth
from myharness.schema.memory import EpisodicEntry
from myharness.skill.store import SkillStore

pytestmark = pytest.mark.asyncio

#: Every stateful service that must be shared across the whole process.
STATEFUL_SERVICES = [
    SourceOfTruth,
    DerivedStorage,
    VectorIndex,
    TextIndex,
    Embedder,
    MemoryManager,
    MemorySystem,
    ContextBuilder,
    SkillStore,
    EventBus,
    Router,
    DriverManager,
    CapabilityRegistry,
    HarnessSupervisor,
]


@pytest.fixture
async def container(test_settings):
    """A container whose memory backends are released after the test.

    Without the close(), each test would strand aiosqlite worker threads and
    the pytest process would hang at interpreter shutdown.
    """
    built = build_container(test_settings)
    yield built
    await built.resolve(MemorySystem).close()


class TestSingletonIdentity:
    @pytest.mark.parametrize("service", STATEFUL_SERVICES, ids=lambda s: s.__name__)
    async def test_repeated_resolution_returns_same_instance(
        self, container, service
    ):
        first = container.resolve(service)
        second = container.resolve(service)
        assert first is second, (
            f"{service.__name__} is rebuilt on every resolve — its state is "
            "discarded and any resources it holds are leaked"
        )

    async def test_supervisor_shares_the_container_memory(self, container):
        """The supervisor must not get a private memory system."""
        memory = container.resolve(MemorySystem)
        supervisor = container.resolve(HarnessSupervisor)
        assert supervisor._memory is memory

    async def test_memory_system_and_manager_are_the_same_object(self, container):
        """MemorySystem is an alias registration, not a second instance."""
        assert container.resolve(MemorySystem) is container.resolve(MemoryManager)

    async def test_stores_share_one_source_of_truth(self, container):
        """All four stores must append to the same P9 source of truth."""
        source = container.resolve(SourceOfTruth)
        memory = container.resolve(MemoryManager)
        assert memory._identity._source is source
        assert memory._episodic._source is source
        assert memory._semantic._source is source
        assert memory._relationship._source is source

    async def test_episodic_and_semantic_share_one_vector_index(self, container):
        """Cross-store semantic search depends on a single shared index."""
        index = container.resolve(VectorIndex)
        memory = container.resolve(MemoryManager)
        assert memory._episodic._vector_idx is index
        assert memory._semantic._vector_idx is index


class TestSharedStateIsObservable:
    """Behavioural proof, not just object identity."""

    async def test_write_through_one_handle_is_visible_from_another(
        self, container
    ):
        """A write via the supervisor's memory must be readable via the container's.

        This is exactly what broke in production: the API wrote into one
        MemoryManager and read back from a different, empty one.
        """
        memory = container.resolve(MemorySystem)
        supervisor = container.resolve(HarnessSupervisor)

        await supervisor._memory.record_episode(
            EpisodicEntry(category="conversation", summary="written via supervisor")
        )

        recent = await memory.get_recent_episodes(limit=10)
        assert any(e.summary == "written via supervisor" for e in recent), (
            "memory written through the supervisor was invisible to the "
            "container's MemorySystem — they are not the same instance"
        )

    async def test_event_bus_subscription_is_visible_to_the_supervisor(
        self, container
    ):
        """A handler registered on the resolved bus must reach supervisor events."""
        bus = container.resolve(EventBus)
        supervisor = container.resolve(HarnessSupervisor)
        assert supervisor._event_bus is bus

    async def test_separate_containers_stay_isolated(self, test_settings):
        """Singletons are per-container, not global — no cross-test bleed."""
        a = build_container(test_settings)
        b = build_container(test_settings)
        try:
            assert a.resolve(MemorySystem) is not b.resolve(MemorySystem)
        finally:
            await a.resolve(MemorySystem).close()
            await b.resolve(MemorySystem).close()
