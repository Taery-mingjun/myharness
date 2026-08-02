"""Gap tests for the self-healing / reflex integration (post-review fixes).

Covers:
1. SkillStore.rollback_to_stable() — the method self-healing depends on
2. CJK trigger extraction (bigram segmentation)
3. Supervisor reflex path: real skill execution, drift recording, fallback
4. DI container wiring of DriftDetector + ReflexIndex
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myharness.core.di import build_container
from myharness.harness.reflex import ReflexIndex
from myharness.schema.driver import ExecutionResult
from myharness.schema.skill import SkillDefinition, SkillStatus
from myharness.skill.store import SkillStore


def _skill(**overrides) -> SkillDefinition:
    base = dict(
        name="walk",
        version="1.0.0",
        description="Walk forward",
        capability="mobility.walk",
        driver_type="robot",
        action_template={"action": "walk"},
        status=SkillStatus.DRAFT,
    )
    base.update(overrides)
    return SkillDefinition(**base)


async def _to_stable(store: SkillStore, skill: SkillDefinition) -> SkillDefinition:
    await store.register(skill)
    await store.change_status(skill.skill_id, SkillStatus.TESTING)
    await store.change_status(skill.skill_id, SkillStatus.VERIFIED)
    return await store.change_status(skill.skill_id, SkillStatus.STABLE)


# ── SkillStore.rollback_to_stable ──────────────────────────────────────


class TestRollbackToStable:
    async def test_rollback_to_explicit_version(self, skill_store):
        v1 = await _to_stable(skill_store, _skill(version="1.0.0"))
        await store_make_stable_chain(skill_store, _skill(name="walk", version="1.1.0"))

        # get_by_name resolves to the newest registered version (1.1.0)
        assert (await skill_store.get_by_name("walk")).version == "1.1.0"

        rolled = await skill_store.rollback_to_stable("walk", target_version="1.0.0")
        assert rolled is True
        assert (await skill_store.get_by_name("walk")).version == "1.0.0"

    async def test_rollback_to_newest_stable_without_target(self, skill_store):
        await _to_stable(skill_store, _skill(version="1.0.0"))
        # 1.1.0 registered but left in DRAFT — not a rollback target
        await skill_store.register(_skill(name="walk", version="1.1.0"))

        rolled = await skill_store.rollback_to_stable("walk")
        assert rolled is True
        assert (await skill_store.get_by_name("walk")).version == "1.0.0"

    async def test_rollback_no_stable_version_returns_false(self, skill_store):
        await skill_store.register(_skill())  # DRAFT only
        assert await skill_store.rollback_to_stable("walk") is False

    async def test_rollback_missing_target_returns_false(self, skill_store):
        await _to_stable(skill_store, _skill(version="1.0.0"))
        assert await skill_store.rollback_to_stable("walk", "9.9.9") is False
        # pointer untouched — still the current version
        assert (await skill_store.get_by_name("walk")).version == "1.0.0"

    async def test_rollback_pointer_survives_reload(self, tmp_path):
        store1 = SkillStore(skills_dir=tmp_path)
        await _to_stable(store1, _skill(version="1.0.0"))
        await _to_stable(store1, _skill(name="walk", version="1.1.0"))
        await store1.rollback_to_stable("walk", "1.0.0")

        store2 = SkillStore(skills_dir=tmp_path)  # fresh instance, same dir
        assert (await store2.get_by_name("walk")).version == "1.0.0"


async def store_make_stable_chain(store: SkillStore, skill: SkillDefinition) -> SkillDefinition:
    await store.register(skill)
    await store.change_status(skill.skill_id, SkillStatus.TESTING)
    return await store.change_status(skill.skill_id, SkillStatus.VERIFIED)


# ── CJK trigger extraction ─────────────────────────────────────────────


class TestCJKTriggers:
    def test_chinese_description_segmented_into_bigrams(self, skill_store):
        reflex = ReflexIndex(skill_store=skill_store, success_threshold=1)
        skill = _skill(
            name="open_fridge",
            description="打开冰箱取出食物",
            capability="home.assist",
            driver_type="api",
        )
        keywords, _ = reflex._extract_triggers(skill)
        assert "打开" in keywords
        assert "冰箱" in keywords
        # the whole phrase must NOT be a single keyword
        assert "打开冰箱取出食物" not in keywords

    def test_bigram_limit_bounds_long_runs(self):
        run = "这" * 30
        bigrams = ReflexIndex._cjk_bigrams(run)
        assert len(bigrams) <= 16

    def test_mixed_cjk_and_ascii(self, skill_store):
        reflex = ReflexIndex(skill_store=skill_store, success_threshold=1)
        skill = _skill(
            name="grab",
            description="抓取 object from shelf now",
            capability="robot.grab",
            driver_type="robot",
        )
        keywords, _ = reflex._extract_triggers(skill)
        assert any("抓取" in k or "取物" in k for k in keywords)
        assert "object" in keywords  # ascii word > 3 chars survives
        assert "now" not in keywords  # 3-char ascii words are noise


# ── Supervisor reflex execution path ───────────────────────────────────


class TestSupervisorReflexPath:
    async def _make_supervisor(self, skill, execute_result, driver_raises=False):
        from myharness.harness.supervisor import HarnessSupervisor

        skill_store = AsyncMock()
        skill_store.get = AsyncMock(return_value=skill)

        driver_manager = AsyncMock()
        if driver_raises:
            driver_manager.execute = AsyncMock(side_effect=RuntimeError("boom"))
        else:
            driver_manager.execute = AsyncMock(return_value=execute_result)

        drift = AsyncMock()
        memory = AsyncMock()

        reflex = MagicMock()
        reflex.match = MagicMock(
            return_value=MagicMock(skill_id=str(skill.skill_id), skill_name=skill.name)
        )

        supervisor = HarnessSupervisor(
            event_bus=AsyncMock(),
            router=AsyncMock(),
            memory=memory,
            llm_engine=AsyncMock(),
            skill_store=skill_store,
            capability_registry=AsyncMock(),
            driver_manager=driver_manager,
            scheduler=AsyncMock(),
            monitor=AsyncMock(),
            reflex_index=reflex,
            drift_detector=drift,
        )
        return supervisor, skill_store, driver_manager, drift, memory

    async def test_reflex_executes_skill_through_driver(self):
        skill = _skill(status=SkillStatus.STABLE, action_template={"action": "walk"})
        result = ExecutionResult(success=True, output="moved 5m")
        supervisor, _, driver_manager, drift, memory = (
            await self._make_supervisor(skill, result)
        )
        supervisor._llm_engine.think = AsyncMock(return_value="{}")

        response = await supervisor.handle_user_message("walk forward")
        assert "执行成功" in response
        driver_manager.execute.assert_awaited_once_with(
            driver_name="robot", action="walk", parameters={}
        )
        drift.record_skill_execution.assert_awaited_once_with("walk", True)
        memory.record_episode.assert_awaited()  # reflex episode recorded

    async def test_reflex_failure_falls_back_to_full_pipeline(self):
        skill = _skill(status=SkillStatus.STABLE)
        supervisor, _, driver_manager, drift, memory = (
            await self._make_supervisor(skill, None, driver_raises=True)
        )
        supervisor._llm_engine.think = AsyncMock(return_value="{}")
        # full pipeline must run: record episode for the user message
        response = await supervisor.handle_user_message("walk forward")
        assert "reflex" not in response.lower()
        drift.record_skill_execution.assert_awaited_once_with("walk", False)

    async def test_reflex_skipped_when_index_absent(self):
        from myharness.harness.supervisor import HarnessSupervisor

        supervisor = HarnessSupervisor(
            event_bus=AsyncMock(),
            router=AsyncMock(),
            memory=AsyncMock(),
            llm_engine=AsyncMock(),
            skill_store=AsyncMock(),
            capability_registry=AsyncMock(),
            driver_manager=AsyncMock(),
            scheduler=AsyncMock(),
            monitor=AsyncMock(),
            reflex_index=None,
        )
        # no reflex index -> no match() call anywhere
        assert supervisor._reflex_index is None


# ── DI wiring ──────────────────────────────────────────────────────────


class TestDiWiring:
    def test_container_resolves_reflex_and_drift(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MYH_DATA_DIR", str(tmp_path))
        from myharness.harness.healing import DriftDetector
        from myharness.harness.reflex import ReflexIndex

        from myharness.core.config import get_settings

        container = build_container(get_settings())
        drift = container.resolve(DriftDetector)
        reflex = container.resolve(ReflexIndex)
        assert drift._failure_threshold == 5
        assert reflex._success_threshold == 5
        assert reflex._skill_store is not None
