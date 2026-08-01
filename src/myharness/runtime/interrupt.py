"""Interrupt handler for execution flow interruptions.

Implements the Walk → Obstacle → Interrupt → Replan → Resume pattern.
When an unexpected event occurs during plan execution, the interrupt
handler pauses execution, engages the LLM to replan, reparameterizes
skills, and resumes the execution flow.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class Plan:
    """A simple plan representation for the interrupt handler.

    Represents a plan with steps that can be executed, interrupted,
    and resumed.
    """

    def __init__(
        self,
        plan_id: str = "",
        steps: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a plan.

        Args:
            plan_id: Unique plan identifier.
            steps: List of plan steps.
            context: Execution context.
        """
        self.plan_id = plan_id
        self.steps = steps or []
        self.context = context or {}
        self.current_step: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert plan to dictionary."""
        return {
            "plan_id": self.plan_id,
            "steps": self.steps,
            "context": self.context,
            "current_step": self.current_step,
        }


class InterruptHandler:
    """Handles interruptions to execution flow.

    When a Walk → Obstacle pattern is detected, the interrupt handler:
    1. Pauses the current execution.
    2. Engages the LLM to think about the interruption.
    3. Replans the remaining steps.
    4. Reparameterizes skills if needed.
    5. Resumes execution from the appropriate step.
    """

    def __init__(self, llm_engine: Any, skill_registry: Any) -> None:
        """Initialize the interrupt handler.

        Args:
            llm_engine: The LLM engine for replanning.
            skill_registry: The skill registry for reparameterization.
        """
        self._llm_engine = llm_engine
        self._skill_registry = skill_registry
        logger.info("interrupt_handler_initialized")

    async def handle_interrupt(
        self,
        current_plan: Plan | None,
        interrupt_event: dict[str, Any],
        context: dict[str, Any],
    ) -> Plan:
        """Handle an execution interruption.

        Pause, think, replan, reparameterize, return new plan.

        Args:
            current_plan: The plan being executed when interrupted.
            interrupt_event: The event that caused the interruption.
            context: The current execution context.

        Returns:
            A new or modified plan to resume execution.
        """
        logger.info(
            "handling_interrupt",
            interrupt_type=interrupt_event.get("type", "unknown"),
            plan_id=current_plan.plan_id if current_plan else "none",
        )

        # Step 1: Pause — capture current state
        paused_step = current_plan.current_step if current_plan else 0
        remaining_steps = (
            current_plan.steps[paused_step:] if current_plan else []
        )

        # Step 2: Think — ask LLM to analyze the interruption
        thought = ""
        if hasattr(self._llm_engine, "think"):
            thought = await self._llm_engine.think(
                message=f"Interruption occurred: {interrupt_event}",
                context={
                    **context,
                    "interrupt_event": interrupt_event,
                    "remaining_steps": remaining_steps,
                },
            )

        # Step 3: Replan — ask LLM to create a new plan
        new_plan = await self.replan(
            original_plan=current_plan,
            new_constraint={
                "interrupt_event": interrupt_event,
                "thought": thought,
                "remaining_steps": remaining_steps,
            },
        )

        logger.info(
            "interrupt_handled",
            plan_id=new_plan.plan_id,
            new_step_count=len(new_plan.steps),
        )

        return new_plan

    async def replan(
        self,
        original_plan: Plan | None,
        new_constraint: dict[str, Any],
    ) -> Plan:
        """Create a new plan incorporating the interruption constraint.

        Args:
            original_plan: The original plan that was interrupted.
            new_constraint: The constraint that caused the replanning.

        Returns:
            A new plan that addresses the constraint.
        """
        logger.info("replanning", constraint_type=type(new_constraint).__name__)

        # If we have an LLM engine, use it to replan
        if hasattr(self._llm_engine, "plan"):
            new_plan_dict = await self._llm_engine.plan(
                thought=new_constraint.get("thought", ""),
                context={
                    "original_plan": (
                        original_plan.to_dict() if original_plan else None
                    ),
                    "constraint": new_constraint,
                },
                available_skills=[],
            )
            if new_plan_dict:
                return Plan(
                    plan_id=new_plan_dict.get("plan_id", ""),
                    steps=new_plan_dict.get("steps", []),
                    context=new_plan_dict.get("context", {}),
                )

        # Fallback: keep remaining steps
        remaining = new_constraint.get("remaining_steps", [])
        return Plan(
            plan_id=original_plan.plan_id if original_plan else "replanned",
            steps=remaining,
            context=new_constraint,
        )

    async def resume_plan(self, plan: Plan, from_step: int = 0) -> None:
        """Resume execution of a plan from a specific step.

        Args:
            plan: The plan to resume.
            from_step: The step index to resume from (0-based).
        """
        plan.current_step = from_step
        logger.info(
            "resuming_plan",
            plan_id=plan.plan_id,
            from_step=from_step,
            total_steps=len(plan.steps),
        )
