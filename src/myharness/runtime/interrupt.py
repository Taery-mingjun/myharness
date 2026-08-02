"""Interrupt handler for execution flow interruptions.

Implements the Walk → Obstacle → Interrupt → Replan → Resume pattern.
When an unexpected event occurs during plan execution, the handler pauses
execution, engages the LLM to replan around the obstacle, and hands back a
plan the harness can actually execute.

Design notes
------------
An earlier revision of this module could not complete a single cycle
against the real ``LLMEngine``:

  * it called ``think(message=...)`` — the engine parameter is ``query``;
  * it called ``plan(thought=...)`` — the engine parameter is ``goal``;
  * it then called ``.get()`` on the returned value, but ``plan()`` returns
    a ``Plan`` dataclass, not a dict;
  * it passed ``available_skills=[]``, so the LLM had nothing to route
    around the obstacle with, even though a skill registry was injected;
  * it defined its own ``Plan`` class whose steps were dicts, while the
    harness executor reads ``step.skill_name`` — so every replanned step
    was silently skipped downstream.

This module now uses the engine's ``Plan``/``PlanStep`` as the single plan
model and calls the engine with its real signatures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from myharness.llm.engine import Plan, PlanStep

logger = structlog.get_logger(__name__)

__all__ = ["InterruptHandler", "Plan", "PlanStep"]


def _now() -> datetime:
    return datetime.now(UTC)


def _coerce_step(raw: Any) -> PlanStep:
    """Normalize a step into a ``PlanStep``.

    Accepts an existing ``PlanStep`` or a loose dict from an external
    planner/demo. Dict steps are the historic failure mode: the harness
    executor reads attributes, so an un-normalized dict step is dropped
    without a word.
    """
    if isinstance(raw, PlanStep):
        return raw
    if isinstance(raw, dict):
        return PlanStep(
            step_id=str(raw.get("step_id") or uuid.uuid4()),
            action=str(raw.get("action", "")),
            skill_name=raw.get("skill_name") or raw.get("skill"),
            parameters=dict(raw.get("parameters") or {}),
            expected_outcome=str(raw.get("expected_outcome", "")),
        )
    # Duck-typed step from a third-party planner.
    return PlanStep(
        step_id=str(getattr(raw, "step_id", "") or uuid.uuid4()),
        action=str(getattr(raw, "action", "")),
        skill_name=getattr(raw, "skill_name", None) or getattr(raw, "skill", None),
        parameters=dict(getattr(raw, "parameters", {}) or {}),
        expected_outcome=str(getattr(raw, "expected_outcome", "")),
    )


def _coerce_plan(raw: Any) -> Plan | None:
    """Normalize an incoming plan into the canonical ``Plan`` model."""
    if raw is None:
        return None
    if isinstance(raw, Plan):
        raw.steps = [_coerce_step(s) for s in raw.steps]
        return raw

    getter = raw.get if isinstance(raw, dict) else (lambda k, d=None: getattr(raw, k, d))
    return Plan(
        plan_id=str(getter("plan_id", "") or ""),
        goal=str(getter("goal", "") or ""),
        steps=[_coerce_step(s) for s in (getter("steps", []) or [])],
        reasoning=str(getter("reasoning", "") or ""),
        created_at=getter("created_at", None) or _now(),
        current_step=int(getter("current_step", 0) or 0),
    )


class InterruptHandler:
    """Handles interruptions to execution flow.

    When a Walk → Obstacle pattern is detected, the interrupt handler:
    1. Pauses the current execution and captures the remaining steps.
    2. Engages the LLM to think about the interruption.
    3. Replans the remaining work, with the real skill catalogue in hand.
    4. Returns an executable plan positioned at its first step.
    """

    def __init__(self, llm_engine: Any, skill_registry: Any = None) -> None:
        """Initialize the interrupt handler.

        Args:
            llm_engine: The LLM engine used for thinking and replanning.
            skill_registry: Registry used to enumerate the skills the LLM
                may reach for when routing around the obstacle.
        """
        self._llm_engine = llm_engine
        self._skill_registry = skill_registry
        logger.info("interrupt_handler_initialized")

    async def handle_interrupt(
        self,
        current_plan: Any,
        interrupt_event: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Plan:
        """Handle an execution interruption: pause, think, replan.

        Args:
            current_plan: The plan being executed when interrupted.
            interrupt_event: The event that caused the interruption.
            context: The current execution context.

        Returns:
            An executable ``Plan`` positioned at its first step.
        """
        context = context or {}
        plan = _coerce_plan(current_plan)

        logger.info(
            "handling_interrupt",
            interrupt_type=interrupt_event.get("type", "unknown"),
            plan_id=plan.plan_id if plan else "none",
        )

        # Step 1: Pause — capture what is left to do.
        paused_step = plan.current_step if plan else 0
        remaining_steps = plan.steps[paused_step:] if plan else []

        # Step 2: Think about the interruption.
        thought = await self._think(interrupt_event, remaining_steps, context)

        # Step 3: Replan with the obstacle as a constraint.
        new_plan = await self.replan(
            original_plan=plan,
            new_constraint={
                "interrupt_event": interrupt_event,
                "thought": thought,
                "remaining_steps": remaining_steps,
            },
            context=context,
        )

        # The returned plan is fresh — execution restarts at its first step.
        new_plan.current_step = 0

        logger.info(
            "interrupt_handled",
            plan_id=new_plan.plan_id,
            new_step_count=len(new_plan.steps),
            paused_at=paused_step,
        )
        return new_plan

    async def replan(
        self,
        original_plan: Plan | None,
        new_constraint: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Plan:
        """Create a new plan that incorporates the interruption constraint.

        Args:
            original_plan: The plan that was interrupted.
            new_constraint: What forced the replan (event, thought, remainder).
            context: Optional execution context passed to the LLM.

        Returns:
            A new ``Plan``. If the LLM is unavailable or fails, degrades to a
            plan containing the remaining steps so an in-flight agent is never
            left without instructions — logged loudly, never silently.
        """
        logger.info("replanning", has_original=original_plan is not None)

        planner = getattr(self._llm_engine, "plan", None)
        if planner is not None:
            try:
                goal = self._build_goal(original_plan, new_constraint)
                produced = await planner(
                    goal=goal,
                    available_skills=await self._available_skills(),
                    context={
                        **(context or {}),
                        "original_plan": _plan_summary(original_plan),
                        "constraint": _constraint_summary(new_constraint),
                    },
                )
                plan = _coerce_plan(produced)
                if plan is not None and plan.steps:
                    return plan
                logger.warning("replan_produced_empty_plan", plan_id=getattr(plan, "plan_id", None))
            except Exception:
                logger.error("replan_llm_failed", exc_info=True)

        return self._fallback_plan(original_plan, new_constraint)

    async def resume_plan(self, plan: Plan, from_step: int = 0) -> list[PlanStep]:
        """Position a plan at ``from_step`` and return the steps still to run.

        Args:
            plan: The plan to resume.
            from_step: The step index to resume from (0-based, clamped).

        Returns:
            The remaining steps, so the caller can execute them directly.
        """
        from_step = max(0, min(from_step, len(plan.steps)))
        plan.current_step = from_step
        remaining = plan.steps[from_step:]

        logger.info(
            "resuming_plan",
            plan_id=plan.plan_id,
            from_step=from_step,
            remaining_steps=len(remaining),
            total_steps=len(plan.steps),
        )
        return remaining

    # ── Internals ──────────────────────────────────────────────────

    async def _think(
        self,
        interrupt_event: dict[str, Any],
        remaining_steps: list[PlanStep],
        context: dict[str, Any],
    ) -> str:
        """Ask the LLM to analyze the interruption. Never fatal."""
        thinker = getattr(self._llm_engine, "think", None)
        if thinker is None:
            return ""
        try:
            return await thinker(
                query=(
                    f"Execution was interrupted by: {interrupt_event}. "
                    f"{len(remaining_steps)} step(s) remain. "
                    "Explain what changed and how to proceed."
                ),
                context={
                    **context,
                    "interrupt_event": interrupt_event,
                    "remaining_steps": [_step_summary(s) for s in remaining_steps],
                },
            )
        except Exception:
            logger.error("interrupt_think_failed", exc_info=True)
            return ""

    async def _available_skills(self) -> list[dict[str, Any]]:
        """Enumerate skills the LLM may use to route around the obstacle.

        Replanning with an empty catalogue can only ever reshuffle existing
        steps, which defeats the purpose of the interrupt.
        """
        discover = getattr(self._skill_registry, "discover", None)
        if discover is None:
            return []
        try:
            skills = await discover()
        except Exception:
            logger.warning("interrupt_skill_discovery_failed", exc_info=True)
            return []

        return [
            {
                "name": getattr(s, "name", ""),
                "capability": getattr(s, "capability", ""),
                "driver_type": getattr(s, "driver_type", ""),
            }
            for s in (skills or [])
        ]

    @staticmethod
    def _build_goal(original_plan: Plan | None, constraint: dict[str, Any]) -> str:
        """Compose the replanning goal handed to the LLM."""
        original_goal = original_plan.goal if original_plan else ""
        event = constraint.get("interrupt_event", {})
        thought = constraint.get("thought", "")
        parts = [
            f"Original goal: {original_goal}" if original_goal else "",
            f"Interruption: {event}",
            f"Analysis: {thought}" if thought else "",
            "Produce a revised plan that achieves the goal despite the interruption.",
        ]
        return "\n".join(p for p in parts if p)

    @staticmethod
    def _fallback_plan(
        original_plan: Plan | None, constraint: dict[str, Any]
    ) -> Plan:
        """Degrade to the remaining steps when the LLM cannot replan."""
        remaining = [_coerce_step(s) for s in constraint.get("remaining_steps", [])]
        logger.warning(
            "replan_fallback_used",
            reason="llm_unavailable_or_failed",
            retained_steps=len(remaining),
        )
        return Plan(
            plan_id=f"fallback-{uuid.uuid4().hex[:8]}",
            goal=original_plan.goal if original_plan else "",
            steps=remaining,
            reasoning=(
                "Fallback plan: the LLM could not replan around the "
                "interruption, so the remaining steps were retained unchanged."
            ),
            created_at=_now(),
        )


def _step_summary(step: PlanStep) -> dict[str, Any]:
    return {
        "action": step.action,
        "skill_name": step.skill_name,
        "parameters": step.parameters,
    }


def _plan_summary(plan: Plan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "plan_id": plan.plan_id,
        "goal": plan.goal,
        "current_step": plan.current_step,
        "steps": [_step_summary(s) for s in plan.steps],
    }


def _constraint_summary(constraint: dict[str, Any]) -> dict[str, Any]:
    return {
        "interrupt_event": constraint.get("interrupt_event"),
        "thought": constraint.get("thought", ""),
        "remaining_steps": [
            _step_summary(_coerce_step(s))
            for s in constraint.get("remaining_steps", [])
        ],
    }
