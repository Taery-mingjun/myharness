"""Tests for schema models."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from myharness.schema.event import EventType, BaseEvent, UserMessageEvent, ThinkResultEvent
from myharness.schema.memory import (
    MemoryCategory, IdentityEntry, EpisodicEntry, SemanticEntry,
    RelationshipEntry, MemoryQuery, MemorySearchResult
)
from myharness.schema.skill import SkillStatus, SkillDefinition, SkillParameter, SkillProposal
from myharness.schema.identity import Identity, IdentityField, IdentityUpdateProposal
from myharness.schema.capability import CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress, DriverStatus


class TestEventSchema:
    def test_base_event_creation(self):
        event = BaseEvent(
            event_type=EventType.SYSTEM_STARTUP,
            source="test",
        )
        assert event.event_type == EventType.SYSTEM_STARTUP
        assert event.source == "test"
        assert event.event_id is not None

    def test_user_message_event(self):
        event = UserMessageEvent(
            source="api",
            payload={"message": "Hello", "user_id": "test_user"},
        )
        assert event.event_type == EventType.USER_MESSAGE
        assert event.payload["message"] == "Hello"

    def test_event_correlation(self):
        event1 = BaseEvent(event_type=EventType.USER_MESSAGE, source="api")
        event2 = BaseEvent(
            event_type=EventType.THINK_RESULT,
            source="llm",
            correlation_id=event1.event_id,
            causation_id=event1.event_id,
        )
        assert event2.correlation_id == event1.event_id


class TestMemorySchema:
    def test_identity_entry_defaults(self):
        entry = IdentityEntry()
        assert entry.version == 1
        assert entry.core_values == []
        assert entry.mission == ""

    def test_episodic_entry_creation(self):
        entry = EpisodicEntry(
            summary="Test episode",
            category="test",
            importance=0.8,
            tags=["test", "unit"],
        )
        assert entry.summary == "Test episode"
        assert entry.importance == 0.8
        assert "test" in entry.tags

    def test_semantic_entry(self):
        entry = SemanticEntry(
            entity="Python",
            attribute="version",
            value="3.11",
            confidence=0.95,
            source="test",
        )
        assert entry.entity == "Python"
        assert entry.confidence == 0.95

    def test_relationship_entry(self):
        entry = RelationshipEntry(
            entity_a="agent",
            entity_b="user",
            relation_type="serves",
            strength=0.9,
        )
        assert entry.relation_type == "serves"

    def test_memory_query_defaults(self):
        query = MemoryQuery(query_text="test")
        assert query.query_text == "test"
        assert query.top_k == 10
        assert len(query.categories) == 4  # All categories

    def test_memory_search_result(self):
        result = MemorySearchResult(
            entry_id="test-id",
            category=MemoryCategory.EPISODIC,
            score=0.85,
            content="test content",
        )
        assert result.score == 0.85


class TestSkillSchema:
    def test_skill_status_enum(self):
        assert SkillStatus.DRAFT == "draft"
        assert SkillStatus.STABLE == "stable"

    def test_skill_definition_creation(self):
        skill = SkillDefinition(
            name="walk",
            version="1.0.0",
            description="Walk to a location",
            capability="robot",
            driver_type="robot",
            action_template={"action": "move", "params": {"x": 0, "y": 0}},
        )
        assert skill.name == "walk"
        assert skill.status == SkillStatus.DRAFT

    def test_skill_parameter(self):
        param = SkillParameter(
            name="speed",
            type="float",
            description="Walking speed",
            required=True,
            default=1.0,
        )
        assert param.name == "speed"
        assert param.required is True


class TestIdentitySchema:
    def test_identity_defaults(self):
        identity = Identity()
        assert identity.name == "Jarvis"
        assert identity.version == 1

    def test_identity_bump_version(self):
        identity = Identity()
        old_version = identity.version
        identity.bump_version()
        assert identity.version == old_version + 1

    def test_identity_update_proposal(self):
        proposal = IdentityUpdateProposal(
            field=IdentityField.MISSION,
            proposed_value="New mission",
            reasoning="Test reasoning",
            confidence=0.8,
        )
        assert proposal.field == IdentityField.MISSION


class TestCapabilitySchema:
    def test_capability_descriptor(self):
        from myharness.schema.capability import CapabilityAction
        cap = CapabilityDescriptor(
            capability_id="test.cap",
            name="Test Capability",
            description="A test capability",
            driver_name="test_driver",
            actions=[CapabilityAction(name="test_action")],
            parameters={"test_action": {"param1": "str"}},
            constraints={},
            version="1.0.0",
        )
        assert cap.capability_id == "test.cap"
        assert len(cap.actions) == 1


class TestDriverSchema:
    def test_execution_result_success(self):
        result = ExecutionResult(
            success=True,
            output={"status": "done"},
            duration_ms=100.0,
        )
        assert result.success is True

    def test_execution_result_failure(self):
        result = ExecutionResult(
            success=False,
            error="Something went wrong",
            duration_ms=50.0,
        )
        assert result.success is False
        assert "wrong" in result.error
