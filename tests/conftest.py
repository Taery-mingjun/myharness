"""Shared test fixtures and utilities for MyHarness tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from myharness.core.config import Settings


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_settings(temp_dir):
    """Create test settings with temp data directory."""
    return Settings(
        data_dir=temp_dir,
        openai_api_key="test-key",
        default_llm_provider="openai",
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
def episodic_store(source_of_truth, temp_dir):
    """Create an EpisodicStore with temp storage."""
    from myharness.memory.storage.derived import DerivedStorage
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.indexing.text import TextIndex
    from myharness.memory.stores.episodic import EpisodicStore

    derived = DerivedStorage(temp_dir / "derived.db")
    vector_idx = VectorIndex(dimension=64)  # Small dimension for tests
    text_idx = TextIndex(temp_dir / "fts.db")
    return EpisodicStore(source_of_truth, derived, vector_idx, text_idx)


@pytest.fixture
def semantic_store(source_of_truth, temp_dir):
    """Create a SemanticStore with temp storage."""
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.indexing.text import TextIndex
    from myharness.memory.stores.semantic import SemanticStore

    vector_idx = VectorIndex(dimension=64)
    text_idx = TextIndex(temp_dir / "fts_semantic.db")
    return SemanticStore(source_of_truth, vector_idx, text_idx)


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
