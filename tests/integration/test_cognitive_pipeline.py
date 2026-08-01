"""Integration tests for the full cognitive pipeline."""

from __future__ import annotations

import pytest


class TestCognitivePipeline:
    """Test the full cognitive pipeline: think → plan → execute → reflect."""

    async def test_event_flow(self, event_bus, router, memory_manager):
        """Test basic event routing through the system."""
        from myharness.schema.event import EventType, BaseEvent

        processed = []

        async def cognitive_handler(event):
            processed.append(event.event_type)

        event_bus.subscribe(EventType.USER_MESSAGE, cognitive_handler)

        event = BaseEvent(event_type=EventType.USER_MESSAGE, source="api",
                          payload={"message": "Hello", "user_id": "test"})
        await event_bus.publish(event)

        assert EventType.USER_MESSAGE in processed

    async def test_memory_roundtrip(self, memory_manager):
        """Test writing and reading memory through the manager."""
        from myharness.schema.memory import EpisodicEntry, MemoryQuery, MemoryCategory

        # Write
        entry = EpisodicEntry(
            summary="User asked about weather",
            category="conversation",
            detail="User: What's the weather? Agent: Let me check.",
            tags=["weather", "conversation"],
            importance=0.6,
        )
        entry_id = await memory_manager.record_episode(entry)
        assert entry_id is not None

        # Read back
        retrieved = await memory_manager.get_episode(entry_id)
        assert retrieved is not None
        assert retrieved.summary == "User asked about weather"

    async def test_identity_through_manager(self, memory_manager):
        """Test identity operations through the manager."""
        identity = await memory_manager.get_identity()
        assert identity is not None
        assert identity.version >= 1

        identity.mission = "Help users accomplish their goals"
        await memory_manager.update_identity(identity)

        updated = await memory_manager.get_identity()
        assert updated.mission == "Help users accomplish their goals"

    async def test_skill_store_integration(self, skill_store, memory_manager):
        """Test skill store with identity context."""
        from myharness.schema.skill import SkillDefinition, SkillStatus

        # Create skill based on agent identity
        identity = await memory_manager.get_identity()

        skill = SkillDefinition(
            name="answer_question",
            version="1.0.0",
            description="Answer user questions based on knowledge",
            capability="llm",
            driver_type="api",
            action_template={"action": "answer", "params": {"style": "helpful"}},
            author="Jarvis",
        )
        registered = await skill_store.register(skill)
        assert registered.name == "answer_question"

        # Transition to verified
        await skill_store.change_status(registered.skill_id, SkillStatus.TESTING)
        await skill_store.change_status(registered.skill_id, SkillStatus.VERIFIED)

        verified = await skill_store.get(registered.skill_id)
        assert verified.status == SkillStatus.VERIFIED

    async def test_driver_manager(self, driver_manager):
        """Test driver registration and execution."""
        from myharness.driver.adapters.api import APIDriver

        driver = APIDriver(base_url="http://localhost:9999")
        await driver_manager.register(driver)

        drivers = await driver_manager.list_drivers()
        assert "api" in drivers

    async def test_di_container(self, test_settings):
        """Test the DI container builds correctly."""
        from myharness.core.di import build_container

        container = build_container(test_settings)
        assert container is not None

        # Should be able to resolve key services
        from myharness.memory.interface import MemorySystem
        memory = container.resolve(MemorySystem)
        assert memory is not None

    async def test_supervisor_boot(self, test_settings):
        """Test that HarnessSupervisor can boot with all subsystems."""
        from myharness.core.di import build_container
        from myharness.harness.supervisor import HarnessSupervisor

        container = build_container(test_settings)
        supervisor = container.resolve(HarnessSupervisor)

        await supervisor.boot()
        status = supervisor.status
        assert isinstance(status, dict)

        await supervisor.shutdown()
