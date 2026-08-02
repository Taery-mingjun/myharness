"""Central orchestrator — the "brain stem" of MyHarness.

Connects EventBus, Memory, LLM, Skills, and Drivers into a unified
cognitive pipeline. Coordinates all subsystems during boot, runtime,
and shutdown.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from myharness.schema.event import (
    SystemShutdownEvent,
    SystemStartupEvent,
)

logger = structlog.get_logger(__name__)


class HarnessSupervisor:
    """Central orchestrator connecting all MyHarness subsystems.

    This is the "brain stem" that coordinates:
    - EventBus: System-wide event routing.
    - Router: Cognitive pipeline routing.
    - Memory: Episodic, semantic, and identity storage.
    - LLM Engine: Cognitive computation.
    - Skill Store: Executable capability templates.
    - Capability Registry: Available execution capabilities.
    - Driver Manager: Execution driver lifecycle.
    - Scheduler: Concurrent task management.
    - Monitor: Health and metrics tracking.
    """

    def __init__(
        self,
        event_bus: Any,
        router: Any,
        memory: Any,
        llm_engine: Any,
        skill_store: Any,
        capability_registry: Any,
        driver_manager: Any,
        scheduler: Any,
        monitor: Any,
    ) -> None:
        """Initialize the harness supervisor.

        Args:
            event_bus: The system event bus.
            router: The cognitive pipeline router.
            memory: The memory system instance.
            llm_engine: The LLM engine for cognitive computation.
            skill_store: The skill store for capability templates.
            capability_registry: The capability registry.
            driver_manager: The execution driver manager.
            scheduler: The resource scheduler.
            monitor: The runtime monitor.
        """
        self._event_bus = event_bus
        self._router = router
        self._memory = memory
        self._llm_engine = llm_engine
        self._skill_store = skill_store
        self._capability_registry = capability_registry
        self._driver_manager = driver_manager
        self._scheduler = scheduler
        self._monitor = monitor

        self._boot_time: float = 0.0
        self._is_running = False
        self._active_tasks: dict[str, Any] = {}

        logger.info("harness_supervisor_initialized")

    async def boot(self) -> None:
        """Initialize all subsystems, register routes, start monitoring.

        Boot sequence:
        1. Start the event bus.
        2. Initialize memory system.
        3. Load skills from storage.
        4. Register drivers and discover capabilities.
        5. Start runtime monitor (heartbeat).
        6. Emit SystemStartupEvent.
        """
        self._boot_time = time.monotonic()
        logger.info("harness_boot_starting")

        # Start event bus
        if hasattr(self._event_bus, "start"):
            await self._event_bus.start()

        # Initialize memory
        if hasattr(self._memory, "initialize"):
            await self._memory.initialize()

        # Start the monitor heartbeat
        if hasattr(self._monitor, "start_heartbeat"):
            await self._monitor.start_heartbeat()

        self._is_running = True

        # Emit startup event
        startup_event = SystemStartupEvent(
            source="harness.supervisor",
            payload={
                "version": "0.1.0",
                "components": [
                    "event_bus",
                    "router",
                    "memory",
                    "llm_engine",
                    "skill_store",
                    "capability_registry",
                    "driver_manager",
                    "scheduler",
                    "monitor",
                ],
            },
        )
        if hasattr(self._event_bus, "emit"):
            await self._event_bus.emit(startup_event)

        logger.info(
            "harness_boot_complete",
            boot_duration_ms=(time.monotonic() - self._boot_time) * 1000,
        )

    async def shutdown(self) -> None:
        """Graceful shutdown of all subsystems.

        Shutdown sequence:
        1. Stop accepting new events.
        2. Cancel active tasks.
        3. Shutdown all drivers.
        4. Stop the monitor.
        5. Emit SystemShutdownEvent.
        6. Stop the event bus.
        """
        logger.info("harness_shutdown_starting")
        self._is_running = False

        # Cancel active tasks
        for task_id in list(self._active_tasks.keys()):
            try:
                await self._scheduler.cancel(task_id)
            except Exception:
                logger.warning(
                    "task_cancel_failed",
                    task_id=task_id,
                    exc_info=True,
                )

        # Shutdown drivers
        if hasattr(self._driver_manager, "shutdown_all"):
            await self._driver_manager.shutdown_all()

        # Stop monitor
        if hasattr(self._monitor, "stop_heartbeat"):
            await self._monitor.stop_heartbeat()

        # Emit shutdown event
        shutdown_event = SystemShutdownEvent(
            source="harness.supervisor",
            payload={
                "reason": "graceful_shutdown",
                "pending_tasks": len(self._active_tasks),
            },
        )
        if hasattr(self._event_bus, "emit"):
            await self._event_bus.emit(shutdown_event)

        # Stop event bus
        if hasattr(self._event_bus, "stop"):
            await self._event_bus.stop()

        # Release memory subsystem resources LAST — after the bus has drained,
        # so late-arriving handlers can still read/write memory. Unclosed
        # aiosqlite connections keep non-daemon threads alive and block
        # interpreter exit, so this must never be skipped.
        if hasattr(self._memory, "close"):
            try:
                await self._memory.close()
            except Exception:
                logger.warning("memory_close_failed", exc_info=True)

        logger.info("harness_shutdown_complete")

    async def handle_user_message(
        self, message: str, user_id: str = "default"
    ) -> str:
        """Process a user message through the full cognitive pipeline.

        Pipeline stages:
        1. Record episode (Memory) — store the user message.
        2. Build context (Memory + Identity) — gather relevant history.
        3. Think (LLM) — understand the message.
        4. Plan (LLM + Skills) — determine what to do.
        5. Execute (Driver) — if plan requires execution.
        6. Reflect (LLM) — learn from the interaction.
        7. Update memory — persist insights.
        8. Return response.

        Args:
            message: The user's message text.
            user_id: The user identifier.

        Returns:
            The system's response string.
        """
        from myharness.schema.memory import EpisodicEntry

        start_time = time.monotonic()
        logger.info(
            "handle_user_message",
            user_id=user_id,
            message_length=len(message),
        )

        try:
            # Stage 1: Record the user message as an episodic entry
            await self._memory.record_episode(
                EpisodicEntry(
                    summary=message[:200],
                    category="conversation",
                    detail=message,
                    participants=[user_id],
                    tags=["user_message"],
                    importance=0.6,
                )
            )

            # Stage 2: Build context from memory (hybrid search)
            context: dict[str, Any] = {"user_id": user_id, "message": message}
            from myharness.schema.memory import MemoryQuery, MemoryCategory

            related = await self._memory.search(
                MemoryQuery(
                    query_text=message,
                    categories=[MemoryCategory.EPISODIC, MemoryCategory.SEMANTIC],
                    top_k=5,
                    min_importance=0.0,
                )
            )
            if related:
                context["related_memories"] = [
                    r.content for r in related if r.score >= 0.3
                ]

            # Stage 3: Think
            thought: str = await self._llm_engine.think(message, context=context)

            # Stage 4: Plan (using available skills)
            available_skills = await self._skill_store.list_all()
            skill_summaries = [
                {"name": s.name, "capability": s.capability, "driver_type": s.driver_type}
                for s in available_skills
            ]
            plan = await self._llm_engine.plan(thought or message, skill_summaries, context=context)

            # Stage 5: Execute (if plan has steps)
            if plan and getattr(plan, "steps", None):
                await self._execute_plan(plan, context)

            # Stage 6: Reflect on the interaction
            reflection = await self._llm_engine.reflect(
                experience={
                    "user_message": message,
                    "thought": thought,
                    "plan": getattr(plan, "reasoning", ""),
                }
            )

            # Stage 7: Persist the interaction outcome as a new episode
            await self._memory.record_episode(
                EpisodicEntry(
                    summary=f"Interaction with {user_id}",
                    category="interaction",
                    detail=f"User: {message}\nThought: {thought}\nReflection: {getattr(reflection, 'summary', '')}",
                    participants=[user_id],
                    tags=["interaction_complete", "reflection"],
                    importance=0.7,
                )
            )

            # Record metrics
            duration_ms = (time.monotonic() - start_time) * 1000
            if hasattr(self._monitor, "record_metric"):
                await self._monitor.record_metric(
                    "cognitive_pipeline.duration_ms",
                    duration_ms,
                    tags={"user_id": user_id},
                )

            # Stage 8: Return response
            response = thought or "I processed your message."
            logger.info(
                "handle_user_message_complete",
                user_id=user_id,
                duration_ms=duration_ms,
            )
            return response

        except Exception as exc:
            logger.error(
                "cognitive_pipeline_error",
                user_id=user_id,
                error=str(exc),
                exc_info=True,
            )
            return f"I encountered an error processing your message: {exc}"

    async def run_cognitive_loop(self) -> None:
        """Main event-driven cognitive loop.

        Continuously processes events from the event bus through the
        cognitive pipeline. Runs until shutdown is requested.
        """
        logger.info("cognitive_loop_starting")

        while self._is_running:
            try:
                # Process events from the bus
                if hasattr(self._event_bus, "get_event"):
                    event = await self._event_bus.get_event(timeout=0.1)
                    if event is not None:
                        if hasattr(self._router, "route"):
                            await self._router.route(event)

                # Record heartbeat metric
                if hasattr(self._monitor, "record_metric"):
                    await self._monitor.record_metric(
                        "cognitive_loop.iteration", 1.0
                    )

            except Exception:
                logger.error(
                    "cognitive_loop_iteration_error",
                    exc_info=True,
                )

        logger.info("cognitive_loop_stopped")

    async def _execute_plan(
        self, plan: Any, context: dict[str, Any]
    ) -> None:
        """Execute a plan's steps using the appropriate drivers.

        Args:
            plan: A Plan object with ordered steps.
            context: The execution context.
        """
        steps = getattr(plan, "steps", [])
        for step in steps:
            skill_name = getattr(step, "skill_name", "") or ""
            action = getattr(step, "action", "") or ""
            parameters = getattr(step, "parameters", {}) or {}

            # Find matching skill
            skill = await self._skill_store.get_by_name(skill_name)
            if skill is None:
                logger.warning(
                    "skill_not_found_for_step",
                    skill_name=skill_name,
                )
                continue

            # Execute via driver
            try:
                result = await self._driver_manager.execute(
                    driver_name=skill.driver_type,
                    action=action,
                    parameters=parameters,
                )
                logger.info(
                    "step_executed",
                    skill_name=skill_name,
                    action=action,
                    success=getattr(result, "success", False),
                )
            except Exception as exc:
                logger.error(
                    "step_execution_failed",
                    skill_name=skill_name,
                    action=action,
                    error=str(exc),
                )

    @property
    def status(self) -> dict[str, Any]:
        """Get the current status of the harness supervisor.

        Returns:
            A dictionary with runtime status information.
        """
        return {
            "is_running": self._is_running,
            "active_tasks": len(self._active_tasks),
            "uptime_seconds": (
                time.monotonic() - self._boot_time if self._boot_time > 0 else 0.0
            ),
        }
