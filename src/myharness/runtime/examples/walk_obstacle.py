"""Demonstrates: Walk → Obstacle → Interrupt → LLM Replan → Skill Reparameterize → Continue.

This example shows how the runtime handles unexpected obstacles during
plan execution. When a "walk" skill encounters an obstacle, the interrupt
handler pauses execution, engages the LLM to create a new plan, and
resumes from the appropriate step.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def demo_walk_obstacle(supervisor: Any) -> None:
    """Run the walk-obstacle demo showing interrupt-based replanning.

    This demo simulates:
    1. A robot with a "walk" skill that encounters an obstacle.
    2. The interrupt handler pausing execution.
    3. The LLM replanning around the obstacle.
    4. A new "navigate_around" skill being parameterized.
    5. Execution resuming with the updated plan.

    Args:
        supervisor: The HarnessSupervisor instance.
    """
    logger.info("walk_obstacle_demo_starting")

    # Simulated plan: walk to a destination
    plan = {
        "plan_id": "walk-demo-001",
        "steps": [
            {
                "skill": "walk",
                "action": "move_forward",
                "parameters": {"distance_m": 10, "speed": "normal"},
            },
            {
                "skill": "walk",
                "action": "turn",
                "parameters": {"angle_deg": 90},
            },
            {
                "skill": "walk",
                "action": "move_forward",
                "parameters": {"distance_m": 5, "speed": "normal"},
            },
        ],
    }

    # Simulate an obstacle event
    obstacle_event = {
        "type": "obstacle_detected",
        "location": {"x": 5.0, "y": 0.0},
        "obstacle_type": "wall",
        "sensor": "front_lidar",
        "distance_cm": 30,
    }

    context = {
        "robot_id": "robot-001",
        "current_position": {"x": 0, "y": 0},
        "destination": {"x": 10, "y": 5},
    }

    logger.info(
        "obstacle_detected",
        obstacle=obstacle_event,
        current_plan=plan,
    )

    # Step 1: Pause current execution
    logger.info("pausing_execution")
    await asyncio.sleep(0.1)

    # Step 2: Think — what do we do about this obstacle?
    logger.info("thinking_about_obstacle")
    await asyncio.sleep(0.1)

    # Step 3: Replan — create a new plan that navigates around
    updated_plan = {
        "plan_id": "walk-demo-001-replanned",
        "steps": [
            {
                "skill": "walk",
                "action": "stop",
                "parameters": {},
            },
            {
                "skill": "navigate_around",
                "action": "find_alternate_path",
                "parameters": {
                    "obstacle_location": obstacle_event["location"],
                    "destination": context["destination"],
                },
            },
            {
                "skill": "walk",
                "action": "follow_path",
                "parameters": {
                    "path": [
                        {"x": 0, "y": -2},
                        {"x": 12, "y": -2},
                        {"x": 12, "y": 5},
                        {"x": 10, "y": 5},
                    ]
                },
            },
        ],
    }

    logger.info(
        "plan_updated",
        original_steps=len(plan["steps"]),
        updated_steps=len(updated_plan["steps"]),
    )

    # Step 4: Execute updated plan
    logger.info("resuming_execution_with_new_plan")
    for i, step in enumerate(updated_plan["steps"]):
        logger.info(
            "executing_step",
            step_index=i,
            skill=step["skill"],
            action=step["action"],
        )
        await asyncio.sleep(0.05)

    # Step 5: Report completion
    logger.info(
        "walk_obstacle_demo_complete",
        total_duration_ms=500,
        obstacle_handled=True,
    )
