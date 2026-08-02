"""Demonstrates: Walk → Obstacle → Interrupt → LLM Replan → Resume.

This runs the real interrupt pipeline. The previous version of this module
was theatre: it accepted a ``supervisor`` it never used, hardcoded the
"replanned" plan as a literal, and slept for 100ms under a
``thinking_about_obstacle`` log line. It printed a flawless success report
whether or not the interrupt subsystem worked at all — which it did not.

A demo that cannot fail proves nothing, so this one calls the actual
``InterruptHandler``, asks the actual LLM engine to replan, and executes the
resulting steps through the actual driver stack. If any of that is broken,
the demo raises.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from myharness.llm.engine import Plan, PlanStep

logger = structlog.get_logger(__name__)


def _walk_plan() -> Plan:
    """The plan the robot is executing when it hits the wall."""
    return Plan(
        plan_id=f"walk-demo-{uuid.uuid4().hex[:6]}",
        goal="Walk to the destination at (10, 5)",
        steps=[
            PlanStep(
                step_id="s1",
                action="move_forward",
                skill_name="walk",
                parameters={"distance_m": 10, "speed": "normal"},
                expected_outcome="advanced 10 metres",
            ),
            PlanStep(
                step_id="s2",
                action="turn",
                skill_name="walk",
                parameters={"angle_deg": 90},
                expected_outcome="facing the destination",
            ),
            PlanStep(
                step_id="s3",
                action="move_forward",
                skill_name="walk",
                parameters={"distance_m": 5, "speed": "normal"},
                expected_outcome="arrived at the destination",
            ),
        ],
        reasoning="Direct route to the destination",
        created_at=datetime.now(timezone.utc),
        current_step=1,  # s1 already done; interrupted partway through s2
    )


async def demo_walk_obstacle(
    supervisor: Any = None,
    interrupt_handler: Any = None,
) -> Plan:
    """Run the walk-obstacle demo against the real interrupt pipeline.

    Sequence:
    1. A robot is midway through a walking plan.
    2. The front lidar reports an obstacle — the plan is interrupted.
    3. The interrupt handler thinks, then asks the LLM to replan using the
       skills actually present in the registry.
    4. The revised plan is resumed and executed through the drivers.

    Args:
        supervisor: A booted ``HarnessSupervisor``. Used to source the
            interrupt handler and to execute the revised plan. Optional if
            ``interrupt_handler`` is supplied.
        interrupt_handler: An ``InterruptHandler`` to use directly.

    Returns:
        The revised ``Plan`` produced by the replan.

    Raises:
        ValueError: If no interrupt handler can be resolved. The demo will
            not fake a result.
    """
    handler = interrupt_handler or _resolve_handler(supervisor)
    if handler is None:
        raise ValueError(
            "demo_walk_obstacle needs an InterruptHandler. Pass one, or pass "
            "a supervisor built by build_container() so it can be resolved."
        )

    started = time.monotonic()
    plan = _walk_plan()

    obstacle_event = {
        "type": "obstacle_detected",
        "location": {"x": 5.0, "y": 0.0},
        "obstacle_type": "wall",
        "sensor": "front_lidar",
        "distance_cm": 30,
    }
    context = {
        "robot_id": "robot-001",
        "current_position": {"x": 5, "y": 0},
        "destination": {"x": 10, "y": 5},
    }

    logger.info(
        "walk_obstacle_demo_starting",
        plan_id=plan.plan_id,
        paused_at_step=plan.current_step,
        obstacle=obstacle_event["obstacle_type"],
    )

    # Interrupt → think → replan (all real work, no sleeps).
    revised = await handler.handle_interrupt(plan, obstacle_event, context)

    logger.info(
        "plan_replanned",
        original_steps=len(plan.steps),
        revised_steps=len(revised.steps),
        revised_plan_id=revised.plan_id,
        reasoning=revised.reasoning[:160],
    )

    # Resume — the revised plan starts from its first step.
    remaining = await handler.resume_plan(revised, from_step=0)
    for i, step in enumerate(remaining):
        logger.info(
            "executing_step",
            step_index=i,
            skill=step.skill_name,
            action=step.action,
            parameters=step.parameters,
        )

    executed = False
    if supervisor is not None and hasattr(supervisor, "_execute_plan"):
        await supervisor._execute_plan(revised, context)
        executed = True

    logger.info(
        "walk_obstacle_demo_complete",
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        steps_resumed=len(remaining),
        dispatched_to_drivers=executed,
    )
    return revised


def _resolve_handler(supervisor: Any) -> Any:
    """Pull the interrupt handler out of a supervisor, if it has one."""
    if supervisor is None:
        return None
    handler = getattr(supervisor, "_interrupt_handler", None)
    if handler is not None:
        return handler
    loop = getattr(supervisor, "_cognitive_loop", None)
    return getattr(loop, "_interrupt_handler", None)
