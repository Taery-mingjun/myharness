"""Shared test fixtures and utilities for MyHarness tests."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from myharness.core.config import Settings


def _close_backend(backend) -> None:
    """Synchronously close an async storage backend during fixture teardown.

    ``aiosqlite`` runs each connection on a NON-daemon worker thread, so a
    connection that is never closed keeps the interpreter alive forever at
    ``threading._shutdown``. Test fixtures must therefore close their
    backends, not just drop the reference.

    A fresh event loop is safe here: aiosqlite's worker thread resolves
    futures via ``future.get_loop().call_soon_threadsafe(...)``, so it binds
    to whichever loop issued the call rather than the one that opened the
    connection.
    """
    closer = getattr(backend, "close", None)
    if closer is None:
        return
    try:
        asyncio.run(closer())
    except Exception:  # pragma: no cover - teardown must never fail a test
        pass


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_settings(temp_dir):
    """Create test settings with temp data directory.

    ``embedding_provider="none"`` keeps the suite hermetic: with a real
    provider name the Embedder would dial the live OpenAI endpoint using the
    dummy key and block on network timeouts. Tests that exercise vector memory
    should inject their own fake embedding port.
    """
    return Settings(
        data_dir=temp_dir,
        openai_api_key="test-key",
        default_llm_provider="openai",
        embedding_provider="none",
        log_level="ERROR",
    )


@pytest.fixture
def event_bus():
    """Create a fresh EventBus for testing."""
    from myharness.bus.dispatcher import EventBus
    return EventBus()


@pytest.fixture
def source_of_truth(temp_dir):
    """Create a SourceOfTruth with temp directory."""
    from myharness.memory.storage.source import SourceOfTruth
    return SourceOfTruth(temp_dir / "source")


@pytest.fixture
def identity_store(source_of_truth):
    """Create an IdentityStore backed by SourceOfTruth."""
    from myharness.memory.stores.identity import IdentityStore
    return IdentityStore(source_of_truth)


@pytest.fixture
def derived_storage(temp_dir):
    """Create a DerivedStorage, closing its SQLite connection on teardown."""
    from myharness.memory.storage.derived import DerivedStorage

    storage = DerivedStorage(temp_dir / "derived.db")
    yield storage
    _close_backend(storage)


@pytest.fixture
def text_index(temp_dir):
    """Create a TextIndex, closing its SQLite connection on teardown."""
    from myharness.memory.indexing.text import TextIndex

    index = TextIndex(temp_dir / "fts.db")
    yield index
    _close_backend(index)


@pytest.fixture
def semantic_text_index(temp_dir):
    """Create a separate TextIndex for semantic memory, closed on teardown."""
    from myharness.memory.indexing.text import TextIndex

    index = TextIndex(temp_dir / "fts_semantic.db")
    yield index
    _close_backend(index)


@pytest.fixture
def episodic_store(source_of_truth, derived_storage, text_index):
    """Create an EpisodicStore with temp storage."""
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.stores.episodic import EpisodicStore

    vector_idx = VectorIndex(dimension=64)  # Small dimension for tests
    return EpisodicStore(source_of_truth, derived_storage, vector_idx, text_index)


@pytest.fixture
def semantic_store(source_of_truth, semantic_text_index):
    """Create a SemanticStore with temp storage."""
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.stores.semantic import SemanticStore

    vector_idx = VectorIndex(dimension=64)
    return SemanticStore(source_of_truth, vector_idx, semantic_text_index)


@pytest.fixture
def relationship_store(source_of_truth):
    """Create a RelationshipStore backed by SourceOfTruth."""
    from myharness.memory.stores.relationship import RelationshipStore
    return RelationshipStore(source_of_truth)


@pytest.fixture
def memory_manager(identity_store, episodic_store, semantic_store, relationship_store):
    """Create a MemoryManager with all stores."""
    from myharness.memory.manager import MemoryManager
    return MemoryManager(
        identity=identity_store,
        episodic=episodic_store,
        semantic=semantic_store,
        relationship=relationship_store,
    )


@pytest.fixture
def skill_store(temp_dir):
    """Create a SkillStore with temp directory."""
    from myharness.skill.store import SkillStore
    skills_dir = temp_dir / "skills"
    skills_dir.mkdir(exist_ok=True)
    return SkillStore(skills_dir)


@pytest.fixture
def router(event_bus):
    """Create a Router connected to EventBus."""
    from myharness.bus.router import Router
    return Router(event_bus)


@pytest.fixture
def driver_manager():
    """Create a DriverManager."""
    from myharness.driver.protocol import DriverManager
    return DriverManager()
