"""Tests for the Skill Store module."""

from __future__ import annotations

import pytest

from myharness.schema.skill import (
    SkillStatus, SkillDefinition, SkillParameter, SkillProposal
)


class TestSkillLifecycle:
    def test_valid_transitions(self):
        from myharness.skill.lifecycle import SkillLifecycle
        assert SkillLifecycle.can_transition(SkillStatus.DRAFT, SkillStatus.TESTING) is True
        assert SkillLifecycle.can_transition(SkillStatus.TESTING, SkillStatus.VERIFIED) is True
        assert SkillLifecycle.can_transition(SkillStatus.VERIFIED, SkillStatus.STABLE) is True
        assert SkillLifecycle.can_transition(SkillStatus.STABLE, SkillStatus.DEPRECATED) is True
        assert SkillLifecycle.can_transition(SkillStatus.DEPRECATED, SkillStatus.ARCHIVED) is True

    def test_invalid_transitions(self):
        from myharness.skill.lifecycle import SkillLifecycle
        assert SkillLifecycle.can_transition(SkillStatus.DRAFT, SkillStatus.STABLE) is False
        assert SkillLifecycle.can_transition(SkillStatus.ARCHIVED, SkillStatus.DRAFT) is False
        assert SkillLifecycle.can_transition(SkillStatus.STABLE, SkillStatus.DRAFT) is False

    def test_transition_updates_status(self):
        from myharness.skill.lifecycle import SkillLifecycle

        skill = SkillDefinition(
            name="test_skill",
            version="1.0.0",
            description="Test skill",
            capability="test",
            driver_type="test",
            action_template={},
        )
        assert skill.status == SkillStatus.DRAFT

        updated = SkillLifecycle.transition(skill, SkillStatus.TESTING)
        assert updated.status == SkillStatus.TESTING


class TestSkillStore:
    async def test_register_skill(self, skill_store):
        skill = SkillDefinition(
            name="walk",
            version="1.0.0",
            description="Walk to a location",
            capability="robot",
            driver_type="robot",
            action_template={"action": "move"},
        )
        registered = await skill_store.register(skill)
        assert registered.skill_id is not None
        assert registered.name == "walk"

    async def test_get_skill(self, skill_store):
        skill = SkillDefinition(
            name="grab",
            version="1.0.0",
            description="Grab an object",
            capability="robot",
            driver_type="robot",
            action_template={"action": "grab"},
        )
        registered = await skill_store.register(skill)

        retrieved = await skill_store.get(registered.skill_id)
        assert retrieved is not None
        assert retrieved.name == "grab"

    async def test_get_by_name(self, skill_store):
        skill = SkillDefinition(
            name="open_door",
            version="1.0.0",
            description="Open a door",
            capability="robot",
            driver_type="robot",
            action_template={"action": "open"},
        )
        await skill_store.register(skill)

        retrieved = await skill_store.get_by_name("open_door")
        assert retrieved is not None
        assert retrieved.version == "1.0.0"

    async def test_list_all(self, skill_store):
        for name in ["skill_a", "skill_b", "skill_c"]:
            skill = SkillDefinition(
                name=name, version="1.0.0", description=name,
                capability="test", driver_type="api", action_template={"action": "test"},
            )
            await skill_store.register(skill)

        all_skills = await skill_store.list_all()
        assert len(all_skills) == 3

    async def test_change_status(self, skill_store):
        skill = SkillDefinition(
            name="test", version="1.0.0", description="test",
            capability="test", driver_type="api", action_template={"action": "test"},
        )
        registered = await skill_store.register(skill)

        updated = await skill_store.change_status(registered.skill_id, SkillStatus.TESTING)
        assert updated.status == SkillStatus.TESTING

    async def test_search(self, skill_store):
        skill = SkillDefinition(
            name="navigate", version="1.0.0",
            description="Navigate to a specific location using pathfinding",
            capability="robot", driver_type="robot", action_template={},
        )
        await skill_store.register(skill)

        results = await skill_store.search("pathfinding")
        assert len(results) >= 1
        assert results[0].name == "navigate"

    async def test_version_history(self, skill_store):
        v1 = SkillDefinition(name="tool", version="1.0.0", description="v1",
                             capability="test", driver_type="api", action_template={"action": "test"})
        v2 = SkillDefinition(name="tool", version="2.0.0", description="v2",
                             capability="test", driver_type="api", action_template={"action": "test"})
        await skill_store.register(v1)
        await skill_store.register(v2)

        history = await skill_store.get_version_history("tool")
        assert len(history) == 2


class TestSkillRegistry:
    async def test_find_best_match(self, skill_store):
        from myharness.skill.registry import SkillRegistry

        # Register a verified skill
        skill = SkillDefinition(
            name="navigate", version="1.0.0", description="Navigation",
            capability="robot.navigation", driver_type="robot", action_template={},
        )
        registered = await skill_store.register(skill)
        await skill_store.change_status(registered.skill_id, SkillStatus.TESTING)
        await skill_store.change_status(registered.skill_id, SkillStatus.VERIFIED)

        registry = SkillRegistry(skill_store)
        match = await registry.find_best_match("robot.navigation")
        assert match is not None
        assert match.name == "navigate"

    async def test_no_match(self, skill_store):
        from myharness.skill.registry import SkillRegistry

        registry = SkillRegistry(skill_store)
        match = await registry.find_best_match("nonexistent.capability")
        assert match is None


class TestSkillValidator:
    def test_valid_skill(self):
        from myharness.skill.validator import SkillValidator

        skill = SkillDefinition(
            name="valid_skill", version="1.0.0", description="Valid skill",
            capability="test", driver_type="api", action_template={"action": "test"},
        )
        errors = SkillValidator.validate(skill)
        assert len(errors) == 0

    def test_missing_name(self):
        from myharness.skill.validator import SkillValidator
        import pytest
        from pydantic import ValidationError

        # Pydantic catches empty name at construction time
        with pytest.raises(ValidationError):
            SkillDefinition(
                name="", version="1.0.0", description="No name",
                capability="test", driver_type="api", action_template={},
            )

    def test_missing_capability(self):
        from myharness.skill.validator import SkillValidator

        skill = SkillDefinition(
            name="test", version="1.0.0", description="No capability",
            capability="", driver_type="test", action_template={},
        )
        errors = SkillValidator.validate(skill)
        assert len(errors) > 0
