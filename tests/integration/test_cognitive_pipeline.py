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

        # Release backends so no aiosqlite worker thread outlives the test
        await memory.close()

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

    async def test_full_cognitive_pipeline(self, test_settings):
        """End-to-end: user message flows through think → plan → execute → reflect.

        Uses a FakeProvider so no real LLM API call is made.
        """
        from myharness.core.di import build_container
        from myharness.harness.supervisor import HarnessSupervisor
        from myharness.llm.engine import LLMEngine
        from myharness.llm.interfaces import LLMProvider
        from myharness.llm.context import ContextBuilder
        from myharness.memory.interface import MemorySystem
        from myharness.schema.memory import EpisodicEntry

        class FakeProvider(LLMProvider):
            @property
            def provider_name(self) -> str:
                return "fake"

            async def complete(self, messages, model=None, temperature=0.7,
                               max_tokens=4096, tools=None, **kwargs) -> str:
                user_msg = messages[-1]["content"] if messages else ""
                system_msg = messages[0]["content"] if messages else ""
                if "plan" in system_msg.lower():
                    return '{"goal": "respond", "steps": [], "reasoning": "no action needed"}'
                if "reflect" in system_msg.lower():
                    return '{"summary": "handled a message", "lessons_learned": [], "skill_improvement_suggestions": [], "identity_implications": [], "emotional_tone": "neutral"}'
                return f"[thought] Processed: {user_msg[:80]}"

            async def complete_stream(self, messages, model=None, temperature=0.7,
                                      max_tokens=4096, **kwargs):
                yield "ok"

            async def embed(self, text) -> list[list[float]]:
                import numpy as np
                if isinstance(text, str):
                    text = [text]
                return [np.random.rand(64).tolist() for _ in text]

            @property
            def supported_models(self) -> list[str]:
                return ["fake-1"]

            @property
            def default_model(self) -> str:
                return "fake-1"

            async def health_check(self) -> bool:
                return True

        container = build_container(test_settings)
        memory = container.resolve(MemorySystem)
        context_builder = ContextBuilder(memory)
        engine = LLMEngine(FakeProvider(), context_builder)

        # Replace engine in supervisor with one using FakeProvider
        supervisor = container.resolve(HarnessSupervisor)
        supervisor._llm_engine = engine

        await supervisor.boot()
        try:
            response = await supervisor.handle_user_message(
                "What is the weather today?", user_id="tester"
            )
            assert isinstance(response, str)
            assert len(response) > 0
            assert "Processed" in response

            # Verify the interaction was persisted to memory
            recent = await memory.get_recent_episodes(limit=10)
            assert len(recent) >= 1
            assert any(e.category == "conversation" for e in recent)
            assert any(e.category == "interaction" for e in recent)
        finally:
            await supervisor.shutdown()
