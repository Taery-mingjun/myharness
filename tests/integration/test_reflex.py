"""Tests for harness/reflex.py — ReflexIndex and promotion logic.

Covers:
1. match() hit and miss
2. promote_to_reflex() preconditions (Stable status, success threshold)
3. rebuild() idempotency and correctness
4. Trigger counting and listing
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from myharness.harness.healing import DriftDetector
from myharness.harness.reflex import ReflexIndex, ReflexTrigger
from myharness.schema.skill import SkillDefinition, SkillStatus
from myharness.skill.store import SkillStore
from myharness.skill.storage import SkillStorage


@pytest.fixture
def storage(tmp_path: Path) -> SkillStorage:
    return SkillStorage(skills_dir=tmp_path)


@pytest.fixture
def skill_store(tmp_path: Path) -> SkillStore:
    return SkillStore(skills_dir=tmp_path)


@pytest.fixture
async def detector(tmp_path: Path) -> DriftDetector:
    d = DriftDetector(db_path=tmp_path / "drift.db", failure_threshold=3)
    yield d
    await d.close()


@pytest.fixture
async def reflex(skill_store: SkillStore, detector: DriftDetector) -> ReflexIndex:
    return ReflexIndex(
        skill_store=skill_store,
        drift_detector=detector,
        success_threshold=5,
    )


class TestReflexMatch:
    """Tests for ReflexIndex.match()."""

    async def test_match_returns_none_on_empty_index(self, reflex: ReflexIndex):
        result = reflex.match("hello world")
        assert result is None

    async def test_match_hits_on_keyword(self, reflex: ReflexIndex):
        trigger = ReflexTrigger(
            skill_id="skill-1",
            skill_name="greet",
            keywords=["hello", "你好"],
        )
        reflex._triggers["skill-1"] = trigger
        reflex._keyword_index["hello"] = ["skill-1"]
        reflex._keyword_index["你好"] = ["skill-1"]

        result = reflex.match("hello there")
        assert result is not None
        assert result.skill_id == "skill-1"
        assert result.trigger_count == 1

    async def test_match_case_insensitive(self, reflex: ReflexIndex):
        trigger = ReflexTrigger(
            skill_id="skill-1",
            skill_name="weather",
            keywords=["weather"],
        )
        reflex._triggers["skill-1"] = trigger
        reflex._keyword_index["weather"] = ["skill-1"]

        result = reflex.match("What's the WEATHER like?")
        assert result is not None
        assert result.skill_id == "skill-1"

    async def test_match_miss_on_unrelated_text(self, reflex: ReflexIndex):
        trigger = ReflexTrigger(
            skill_id="skill-1",
            skill_name="weather",
            keywords=["weather"],
        )
        reflex._triggers["skill-1"] = trigger
        reflex._keyword_index["weather"] = ["skill-1"]

        result = reflex.match("what time is it")
        assert result is None

    async def test_match_increments_trigger_count(self, reflex: ReflexIndex):
        trigger = ReflexTrigger(
            skill_id="skill-1",
            skill_name="greet",
            keywords=["hello"],
        )
        reflex._triggers["skill-1"] = trigger
        reflex._keyword_index["hello"] = ["skill-1"]

        reflex.match("hello")
        reflex.match("hello")
        reflex.match("hello")

        assert reflex._triggers["skill-1"].trigger_count == 3
        assert reflex.total_fires == 3


class TestPromoteToReflex:
    """Tests for promote_to_reflex() precondition checks."""

    async def test_reject_nonexistent_skill(self, reflex: ReflexIndex):
        result = await reflex.promote_to_reflex("nonexistent-id")
        assert result["status"] == "rejected"
        assert "not found" in result["reason"]

    async def test_reject_non_stable_skill(
        self, reflex: ReflexIndex, skill_store: SkillStore
    ):
        skill = SkillDefinition(
            name="test-skill",
            description="A test skill",
            status=SkillStatus.DRAFT,
            capability="test", action_template={"action": "test"},
        )
        await skill_store.register(skill)

        result = await reflex.promote_to_reflex(str(skill.skill_id))
        assert result["status"] == "rejected"
        assert "draft" in result["reason"]
        assert "stable" in result["reason"]

    async def test_reject_stable_but_insufficient_successes(
        self, reflex: ReflexIndex, skill_store: SkillStore, detector: DriftDetector
    ):
        skill = SkillDefinition(
            name="test-skill",
            description="A test skill",
            status=SkillStatus.STABLE,
            capability="test", action_template={"action": "test"},
        )
        await skill_store.register(skill)

        # Record only 3 successes (threshold is 5)
        for _ in range(3):
            await detector.record_skill_execution("test-skill", True)

        result = await reflex.promote_to_reflex(str(skill.skill_id))
        assert result["status"] == "rejected"
        assert "3" in result["reason"]
        assert "5" in result["reason"]

    async def test_promote_when_all_conditions_met(
        self, reflex: ReflexIndex, skill_store: SkillStore, detector: DriftDetector
    ):
        skill = SkillDefinition(
            name="greet",
            description="Greet the user",
            status=SkillStatus.STABLE,
            capability="conversation", action_template={"action": "greet"},
        )
        await skill_store.register(skill)

        # Record 5 consecutive successes
        for _ in range(5):
            await detector.record_skill_execution("greet", True)

        result = await reflex.promote_to_reflex(str(skill.skill_id))
        assert result["status"] == "promoted"
        assert result["skill_name"] == "greet"
        assert "greet" in result["keywords"]

    async def test_promoted_skill_is_matchable(
        self, reflex: ReflexIndex, skill_store: SkillStore, detector: DriftDetector
    ):
        skill = SkillDefinition(
            name="weather",
            description="Check weather forecast",
            status=SkillStatus.STABLE,
            capability="weather_query", action_template={"action": "query"},
        )
        await skill_store.register(skill)

        for _ in range(5):
            await detector.record_skill_execution("weather", True)

        await reflex.promote_to_reflex(str(skill.skill_id))

        # Now matching should work
        hit = reflex.match("what's the weather today")
        assert hit is not None
        assert hit.skill_name == "weather"


class TestRebuild:
    """Tests for rebuild() idempotency and correctness."""

    async def test_rebuild_from_stable_skills(
        self, reflex: ReflexIndex, skill_store: SkillStore, detector: DriftDetector
    ):
        # Create two stable skills with enough successes
        skill1 = SkillDefinition(
            name="greet",
            description="Greet user",
            status=SkillStatus.STABLE,
            capability="conversation", action_template={"action": "greet"},
        )
        skill2 = SkillDefinition(
            name="weather",
            description="Weather forecast",
            status=SkillStatus.STABLE,
            capability="weather_query", action_template={"action": "query"},
        )
        await skill_store.register(skill1)
        await skill_store.register(skill2)

        for _ in range(5):
            await detector.record_skill_execution("greet", True)
            await detector.record_skill_execution("weather", True)

        result = await reflex.rebuild()
        assert result["status"] == "rebuilt"
        assert result["promoted"] == 2
        assert reflex.trigger_count == 2

    async def test_rebuild_clears_old_triggers(
        self, reflex: ReflexIndex, skill_store: SkillStore, detector: DriftDetector
    ):
        # Manually add a trigger
        trigger = ReflexTrigger(
            skill_id="old-id",
            skill_name="old-skill",
            keywords=["old"],
        )
        reflex._triggers["old-id"] = trigger
        reflex._keyword_index["old"] = ["old-id"]
        assert reflex.trigger_count == 1

        # Rebuild with no stable skills
        result = await reflex.rebuild()
        assert result["cleared"] == 1
        assert reflex.trigger_count == 0

    async def test_rebuild_idempotent(
        self, reflex: ReflexIndex, skill_store: SkillStore, detector: DriftDetector
    ):
        skill = SkillDefinition(
            name="greet",
            description="Greet user",
            status=SkillStatus.STABLE,
            capability="conversation", action_template={"action": "greet"},
        )
        await skill_store.register(skill)

        for _ in range(5):
            await detector.record_skill_execution("greet", True)

        # First rebuild
        await reflex.rebuild()
        triggers_after_first = reflex.list_triggers()
        assert len(triggers_after_first) == 1

        # Second rebuild — should produce identical results
        await reflex.rebuild()
        triggers_after_second = reflex.list_triggers()
        assert len(triggers_after_second) == 1
        assert triggers_after_second[0]["skill_name"] == "greet"
        assert triggers_after_second[0]["keywords"] == triggers_after_first[0]["keywords"]

    async def test_rebuild_skips_stable_without_threshold(
        self, reflex: ReflexIndex, skill_store: SkillStore
    ):
        # Stable skill but no success records in DriftDetector
        skill = SkillDefinition(
            name="greet",
            description="Greet user",
            status=SkillStatus.STABLE,
            capability="conversation", action_template={"action": "greet"},
        )
        await skill_store.register(skill)

        result = await reflex.rebuild()
        assert result["promoted"] == 0
        assert result["rejected_by_threshold"] == 1
        assert reflex.trigger_count == 0


class TestListTriggers:
    """Tests for inspection methods."""

    async def test_list_empty(self, reflex: ReflexIndex):
        triggers = reflex.list_triggers()
        assert triggers == []

    async def test_list_after_promotion(
        self, reflex: ReflexIndex, skill_store: SkillStore, detector: DriftDetector
    ):
        skill = SkillDefinition(
            name="greet",
            description="Greet user",
            status=SkillStatus.STABLE,
            capability="conversation", action_template={"action": "greet"},
        )
        await skill_store.register(skill)

        for _ in range(5):
            await detector.record_skill_execution("greet", True)

        await reflex.promote_to_reflex(str(skill.skill_id))

        triggers = reflex.list_triggers()
        assert len(triggers) == 1
        assert triggers[0]["skill_name"] == "greet"
        assert "greet" in triggers[0]["keywords"]
        assert triggers[0]["trigger_count"] == 0
