"""Walk → Obstacle → Interrupt → Replan → Resume.

The interrupt handler previously could not complete a single cycle against
the real ``LLMEngine``. Every call site was wrong:

  * ``think(message=...)``  — the engine parameter is ``query``
  * ``plan(thought=...)``   — the engine parameter is ``goal``
  * ``.get()`` on the result — ``plan()`` returns a ``Plan`` dataclass
  * ``available_skills=[]`` — hardcoded, so the LLM had nothing to route
    around the obstacle with, despite a registry being injected
  * a second ``Plan`` class whose steps were dicts — the harness executor
    reads ``step.skill_name``, so every replanned step was silently dropped

The signature-parity tests are the important ones: they fail the moment the
handler and the engine drift apart again, which is how this broke the
first time.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from myharness.llm.engine import LLMEngine, Plan, PlanStep
from myharness.runtime.interrupt import InterruptHandler
from myharness.runtime.interrupt import Plan as InterruptPlan

pytestmark = pytest.mark.asyncio


OBSTACLE = {"type": "obstacle_detected", "distance_m": 1.2}


class FakeEngine:
    """Mirrors the real LLMEngine signatures exactly (see parity test)."""

    def __init__(self, plan_result: Plan | None = None, fail: bool = False):
        self._plan_result = plan_result
        self._fail = fail
        self.think_calls: list[dict] = []
        self.plan_calls: list[dict] = []

    async def think(self, query: str, context: dict | None = None) -> str:
        self.think_calls.append({"query": query, "context": context})
        if self._fail:
            raise RuntimeError("llm down")
        return "the path ahead is blocked; go around to the left"

    async def plan(
        self, goal: str, available_skills: list[dict], context: dict | None = None
    ) -> Plan | None:
        self.plan_calls.append(
            {"goal": goal, "available_skills": available_skills, "context": context}
        )
        if self._fail:
            raise RuntimeError("llm down")
        return self._plan_result


class FakeSkill:
    def __init__(self, name: str, capability: str, driver_type: str):
        self.name = name
        self.capability = capability
        self.driver_type = driver_type


class FakeRegistry:
    def __init__(self, skills=None):
        self._skills = skills or [
            FakeSkill("walk", "locomotion", "ros2"),
            FakeSkill("navigate", "path_planning", "ros2"),
        ]

    async def discover(self):
        return self._skills


def _replanned() -> Plan:
    return Plan(
        plan_id="replan-001",
        goal="reach the dock despite the obstacle",
        steps=[
            PlanStep(
                step_id="s1",
                action="navigate_around",
                skill_name="navigate",
                parameters={"clearance_m": 1.5},
                expected_outcome="obstacle bypassed",
            )
        ],
        reasoning="route left around the obstacle",
        created_at=datetime.now(timezone.utc),
    )


def _walk_plan() -> dict:
    """A loose dict plan, as produced by external planners and the demo."""
    return {
        "plan_id": "walk-demo-001",
        "goal": "walk to the loading dock",
        "steps": [
            {"skill": "walk", "action": "move_forward", "parameters": {"distance_m": 10}},
            {"skill": "walk", "action": "turn", "parameters": {"angle_deg": 90}},
            {"skill": "walk", "action": "move_forward", "parameters": {"distance_m": 5}},
        ],
        "current_step": 1,
    }


# ── Contract parity with the real engine ───────────────────────────────


class TestEngineSignatureParity:
    async def test_fake_engine_mirrors_real_engine(self):
        """Pins the test double to reality so it cannot drift."""
        for name in ("think", "plan"):
            real = list(inspect.signature(getattr(LLMEngine, name)).parameters)
            fake = list(inspect.signature(getattr(FakeEngine, name)).parameters)
            assert real == fake, f"FakeEngine.{name} drifted from LLMEngine.{name}"

    async def test_handler_kwargs_bind_against_real_engine(self):
        """The exact kwargs the handler emits must be accepted by LLMEngine."""
        captured: dict[str, dict] = {}

        class Recorder:
            async def think(self, **kwargs):
                captured["think"] = kwargs
                return "ok"

            async def plan(self, **kwargs):
                captured["plan"] = kwargs
                return _replanned()

        handler = InterruptHandler(Recorder(), FakeRegistry())
        await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})

        # Raises TypeError if a parameter name is wrong or one is missing.
        inspect.signature(LLMEngine.think).bind(None, **captured["think"])
        inspect.signature(LLMEngine.plan).bind(None, **captured["plan"])

    async def test_single_plan_model(self):
        """A second Plan type is what silently killed step execution."""
        assert InterruptPlan is Plan


# ── The happy path ─────────────────────────────────────────────────────


class TestReplanCycle:
    async def test_full_cycle_returns_executable_plan(self):
        engine = FakeEngine(plan_result=_replanned())
        handler = InterruptHandler(engine, FakeRegistry())

        new_plan = await handler.handle_interrupt(_walk_plan(), OBSTACLE, {"robot": "r1"})

        assert isinstance(new_plan, Plan)
        assert new_plan.plan_id == "replan-001"
        assert len(new_plan.steps) == 1
        # The harness executor reads attributes, not dict keys.
        assert new_plan.steps[0].skill_name == "navigate"
        assert new_plan.steps[0].action == "navigate_around"
        assert new_plan.current_step == 0

    async def test_dict_plan_is_coerced_to_plansteps(self):
        engine = FakeEngine(plan_result=None)  # force fallback, keeps our steps
        handler = InterruptHandler(engine, FakeRegistry())

        new_plan = await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})

        assert all(isinstance(s, PlanStep) for s in new_plan.steps)
        assert new_plan.steps[0].skill_name == "walk"

    async def test_remaining_steps_start_at_the_pause_point(self):
        engine = FakeEngine(plan_result=None)
        handler = InterruptHandler(engine, FakeRegistry())

        # current_step=1 of 3 steps -> 2 remain
        new_plan = await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})
        assert len(new_plan.steps) == 2

    async def test_real_skills_are_offered_to_the_planner(self):
        """Replanning with an empty catalogue cannot route around anything."""
        engine = FakeEngine(plan_result=_replanned())
        handler = InterruptHandler(engine, FakeRegistry())

        await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})

        offered = engine.plan_calls[0]["available_skills"]
        assert [s["name"] for s in offered] == ["walk", "navigate"]
        assert offered[1]["capability"] == "path_planning"

    async def test_goal_carries_the_obstacle_and_the_analysis(self):
        engine = FakeEngine(plan_result=_replanned())
        handler = InterruptHandler(engine, FakeRegistry())

        await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})

        goal = engine.plan_calls[0]["goal"]
        assert "walk to the loading dock" in goal
        assert "obstacle_detected" in goal
        assert "go around to the left" in goal  # the think() output


# ── Degradation: an interrupted agent must never be left stranded ──────


class TestDegradation:
    async def test_llm_failure_falls_back_to_remaining_steps(self):
        handler = InterruptHandler(FakeEngine(fail=True), FakeRegistry())

        new_plan = await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})

        assert new_plan.plan_id.startswith("fallback-")
        assert len(new_plan.steps) == 2
        assert "could not replan" in new_plan.reasoning

    async def test_empty_llm_plan_falls_back(self):
        empty = Plan(
            plan_id="empty", goal="g", steps=[], reasoning="",
            created_at=datetime.now(timezone.utc),
        )
        handler = InterruptHandler(FakeEngine(plan_result=empty), FakeRegistry())

        new_plan = await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})

        assert new_plan.plan_id.startswith("fallback-")
        assert len(new_plan.steps) == 2

    async def test_missing_registry_is_tolerated(self):
        engine = FakeEngine(plan_result=_replanned())
        handler = InterruptHandler(engine, skill_registry=None)

        new_plan = await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})

        assert new_plan.plan_id == "replan-001"
        assert engine.plan_calls[0]["available_skills"] == []

    async def test_registry_failure_does_not_abort_replanning(self):
        class BrokenRegistry:
            async def discover(self):
                raise RuntimeError("store offline")

        engine = FakeEngine(plan_result=_replanned())
        handler = InterruptHandler(engine, BrokenRegistry())

        new_plan = await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})
        assert new_plan.plan_id == "replan-001"

    async def test_no_current_plan_is_handled(self):
        handler = InterruptHandler(FakeEngine(plan_result=_replanned()), FakeRegistry())
        new_plan = await handler.handle_interrupt(None, OBSTACLE, {})
        assert new_plan.plan_id == "replan-001"


# ── Resume ─────────────────────────────────────────────────────────────


class TestResume:
    async def test_resume_returns_remaining_steps(self):
        handler = InterruptHandler(FakeEngine(), FakeRegistry())
        plan = Plan(
            plan_id="p", goal="g",
            steps=[
                PlanStep(f"s{i}", "act", "walk", {}, "done") for i in range(4)
            ],
            reasoning="", created_at=datetime.now(timezone.utc),
        )

        remaining = await handler.resume_plan(plan, from_step=2)

        assert len(remaining) == 2
        assert plan.current_step == 2
        assert remaining[0].step_id == "s2"

    @pytest.mark.parametrize("requested,expected", [(-5, 0), (99, 4)])
    async def test_resume_clamps_out_of_range_cursor(self, requested, expected):
        handler = InterruptHandler(FakeEngine(), FakeRegistry())
        plan = Plan(
            plan_id="p", goal="g",
            steps=[PlanStep(f"s{i}", "a", "walk", {}, "") for i in range(4)],
            reasoning="", created_at=datetime.now(timezone.utc),
        )

        await handler.resume_plan(plan, from_step=requested)
        assert plan.current_step == expected


# ── The replanned plan must actually be executable downstream ──────────


class TestHarnessCanExecuteReplannedPlan:
    async def test_supervisor_executes_every_replanned_step(self):
        """End-to-end proof the dict/dataclass split is gone.

        With dict steps, ``getattr(step, "skill_name", "")`` returned "" and
        the supervisor skipped the step without raising — the failure mode
        that made this invisible.
        """
        from myharness.harness.supervisor import HarnessSupervisor

        executed: list[tuple[str, str]] = []

        class FakeSkillStore:
            async def get_by_name(self, name):
                return FakeSkill(name, "path_planning", "ros2") if name else None

        class FakeDriverManager:
            async def execute(self, driver_name, action, parameters):
                executed.append((driver_name, action))
                return type("R", (), {"success": True})()

        handler = InterruptHandler(FakeEngine(plan_result=_replanned()), FakeRegistry())
        new_plan = await handler.handle_interrupt(_walk_plan(), OBSTACLE, {})

        sup = HarnessSupervisor(
            event_bus=None, router=None, memory=None, llm_engine=None,
            skill_store=FakeSkillStore(), capability_registry=None,
            driver_manager=FakeDriverManager(), scheduler=None, monitor=None,
        )
        await sup._execute_plan(new_plan, context={})

        assert executed == [("ros2", "navigate_around")]


# ── The demo must exercise the real pipeline, not simulate it ──────────


class TestWalkObstacleDemo:
    async def test_demo_drives_the_real_interrupt_pipeline(self):
        from myharness.runtime.examples import demo_walk_obstacle

        engine = FakeEngine(plan_result=_replanned())
        handler = InterruptHandler(engine, FakeRegistry())

        revised = await demo_walk_obstacle(interrupt_handler=handler)

        # It genuinely asked the LLM instead of hardcoding the outcome.
        assert len(engine.think_calls) == 1
        assert len(engine.plan_calls) == 1
        assert revised.plan_id == "replan-001"
        assert revised.steps[0].skill_name == "navigate"

    async def test_demo_refuses_to_fake_a_result(self):
        """A demo that always succeeds proves nothing."""
        from myharness.runtime.examples import demo_walk_obstacle

        with pytest.raises(ValueError, match="InterruptHandler"):
            await demo_walk_obstacle()

    async def test_demo_dispatches_steps_to_drivers(self):
        from myharness.harness.supervisor import HarnessSupervisor
        from myharness.runtime.examples import demo_walk_obstacle

        executed: list[tuple[str, str]] = []

        class FakeSkillStore:
            async def get_by_name(self, name):
                return FakeSkill(name, "path_planning", "ros2") if name else None

        class FakeDriverManager:
            async def execute(self, driver_name, action, parameters):
                executed.append((driver_name, action))
                return type("R", (), {"success": True})()

        handler = InterruptHandler(FakeEngine(plan_result=_replanned()), FakeRegistry())
        sup = HarnessSupervisor(
            event_bus=None, router=None, memory=None, llm_engine=None,
            skill_store=FakeSkillStore(), capability_registry=None,
            driver_manager=FakeDriverManager(), scheduler=None, monitor=None,
        )
        sup._interrupt_handler = handler

        await demo_walk_obstacle(supervisor=sup)

        assert executed == [("ros2", "navigate_around")]
