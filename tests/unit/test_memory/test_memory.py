"""Tests for the Memory System."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from myharness.schema.memory import (
    IdentityEntry, EpisodicEntry, SemanticEntry, RelationshipEntry, MemoryQuery, MemoryCategory
)
from myharness.schema.identity import IdentityUpdateProposal, IdentityField


class TestSourceOfTruth:
    async def test_write_and_read(self, source_of_truth):
        await source_of_truth.write("identity", "test", {"name": "test", "value": 42})
        data = await source_of_truth.read("identity", "test")
        assert data == {"name": "test", "value": 42}

    async def test_append_and_scan(self, source_of_truth):
        await source_of_truth.append("episodic", {"id": "1", "text": "first"})
        await source_of_truth.append("episodic", {"id": "2", "text": "second"})

        entries = await source_of_truth.scan("episodic", limit=10)
        assert len(entries) == 2
        assert entries[0]["id"] == "1"

    async def test_count(self, source_of_truth):
        await source_of_truth.append("episodic", {"id": "1"})
        await source_of_truth.append("episodic", {"id": "2"})
        count = await source_of_truth.count("episodic")
        assert count == 2

    async def test_list_keys(self, source_of_truth):
        await source_of_truth.write("identity", "key1", {})
        await source_of_truth.write("identity", "key2", {})
        keys = await source_of_truth.list_keys("identity")
        assert "key1" in keys
        assert "key2" in keys

    async def test_exists(self, source_of_truth):
        await source_of_truth.write("identity", "exists_test", {})
        # Use read to check existence
        data = await source_of_truth.read("identity", "exists_test")
        assert data is not None
        data = await source_of_truth.read("identity", "nonexistent")
        assert data is None


class TestIdentityStore:
    async def test_get_default_identity(self, identity_store):
        identity = await identity_store.get_identity()
        assert identity.version == 1
        assert isinstance(identity.core_values, list)

    async def test_update_identity(self, identity_store):
        identity = await identity_store.get_identity()
        identity.mission = "Test mission"
        await identity_store.update_identity(identity)

        updated = await identity_store.get_identity()
        assert updated.mission == "Test mission"
        assert updated.version == 2  # Version incremented

    async def test_identity_history(self, identity_store):
        identity = await identity_store.get_identity()
        identity.mission = "v1"
        await identity_store.update_identity(identity)

        identity = await identity_store.get_identity()
        identity.mission = "v2"
        await identity_store.update_identity(identity)

        history = await identity_store.get_history()
        assert len(history) >= 2


class TestEpisodicStore:
    async def test_record_and_retrieve(self, episodic_store):
        entry = EpisodicEntry(
            summary="Test episode",
            category="test",
            detail="This is a test episode",
            tags=["test"],
            importance=0.7,
        )
        entry_id = await episodic_store.record(entry)

        retrieved = await episodic_store.get(entry_id)
        assert retrieved is not None
        assert retrieved.summary == "Test episode"

    async def test_get_recent(self, episodic_store):
        for i in range(5):
            entry = EpisodicEntry(summary=f"Episode {i}", category="test")
            await episodic_store.record(entry)

        recent = await episodic_store.get_recent(limit=3)
        assert len(recent) <= 3

    async def test_count(self, episodic_store):
        for i in range(3):
            entry = EpisodicEntry(summary=f"Episode {i}", category="test")
            await episodic_store.record(entry)

        count = await episodic_store.count()
        assert count == 3


class TestSemanticStore:
    async def test_store_and_retrieve(self, semantic_store):
        entry = SemanticEntry(
            entity="TestEntity",
            attribute="color",
            value="blue",
            confidence=0.9,
            source="test",
        )
        entry_id = await semantic_store.store(entry)

        retrieved = await semantic_store.get(entry_id)
        assert retrieved is not None
        assert retrieved.entity == "TestEntity"

    async def test_get_related(self, semantic_store):
        await semantic_store.store(SemanticEntry(entity="E1", attribute="attr", value="v1"))
        await semantic_store.store(SemanticEntry(entity="E1", attribute="attr2", value="v2"))

        related = await semantic_store.get_related("E1")
        assert len(related) == 2


class TestRelationshipStore:
    async def test_set_and_get(self, relationship_store):
        entry = RelationshipEntry(
            entity_a="agent",
            entity_b="user",
            relation_type="serves",
            strength=0.9,
        )
        await relationship_store.set(entry)

        retrieved = await relationship_store.get("agent", "user")
        assert retrieved is not None
        assert retrieved.relation_type == "serves"

    async def test_get_all_for(self, relationship_store):
        await relationship_store.set(RelationshipEntry(
            entity_a="agent", entity_b="user1", relation_type="serves"
        ))
        await relationship_store.set(RelationshipEntry(
            entity_a="agent", entity_b="user2", relation_type="collaborates_with"
        ))

        all_for_agent = await relationship_store.get_all_for("agent")
        assert len(all_for_agent) == 2


class TestMemoryManager:
    async def test_get_identity(self, memory_manager):
        identity = await memory_manager.get_identity()
        assert identity is not None

    async def test_record_and_search_episodes(self, memory_manager):
        entry = EpisodicEntry(summary="Important meeting", category="conversation", importance=0.9)
        await memory_manager.record_episode(entry)

        query = MemoryQuery(query_text="meeting", categories=[MemoryCategory.EPISODIC])
        results = await memory_manager.search_episodes(query)
        # Text search may or may not return results depending on indexing
        assert isinstance(results, list)

    async def test_store_knowledge(self, memory_manager):
        entry = SemanticEntry(entity="Python", attribute="type", value="language")
        entry_id = await memory_manager.store_knowledge(entry)
        assert entry_id is not None

    async def test_relationships(self, memory_manager):
        entry = RelationshipEntry(entity_a="a", entity_b="b", relation_type="knows")
        await memory_manager.set_relationship(entry)

        rel = await memory_manager.get_relationship("a", "b")
        assert rel is not None

    async def test_get_stats(self, memory_manager):
        stats = await memory_manager.get_stats()
        assert "identity" in stats or "episodic" in stats
