"""Central orchestrator — the "brain stem" of MyHarness.

Connects EventBus, Memory, LLM, Skills, and Drivers into a unified
cognitive pipeline. Coordinates all subsystems during boot, runtime,
and shutdown.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from myharness.harness.guard import ExecutionGuard
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
        cognitive_loop: Any = None,
        execution_guard: Any = None,
        reflex_index: Any = None,
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
            cognitive_loop: The runtime ``EventLoop`` that drains the event
                queue and routes events through the cognitive pipeline. When
                provided it becomes the queue's sole consumer and the bus's
                built-in queue processor is left dormant.
            execution_guard: Authorises every plan step before it reaches a
                driver. Defaults to an enforcing :class:`ExecutionGuard`
                with no RBAC — the skill boundary is never optional.
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
        self._cognitive_loop = cognitive_loop

        # The skill boundary is what makes the Skill power constrain the
        # Execution power. A control that only applies when a dependency
        # happens to be injected is not a control, so a default enforcing
        # guard is built when none is supplied. Pass an explicit guard to
        # attach RBAC or to run in audit-only mode.
        self._execution_guard = execution_guard or ExecutionGuard()

        # Reflex Layer (§6.5): low-latency skill triggering for Stable skills.
        # When non-None, incoming messages are checked against the reflex index
        # before entering the full think→plan→reflect pipeline.
        self._reflex_index = reflex_index

        self._boot_time: float = 0.0
        self._is_running = False
        self._has_shut_down = False
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

        # Start event bus. The queue admits exactly one consumer: when a
        # cognitive loop is attached it drains the queue *through the Router*,
        # so the bus's built-in processor (which publishes raw and bypasses
        # routing rules entirely) must stay dormant.
        if hasattr(self._event_bus, "start"):
            if self._cognitive_loop is None:
                await self._event_bus.start()
            else:
                await self._event_bus.start(with_queue_processor=False)

        # Initialize memory
        if hasattr(self._memory, "initialize"):
            await self._memory.initialize()

        # Start the monitor heartbeat
        if hasattr(self._monitor, "start_heartbeat"):
            await self._monitor.start_heartbeat()

        # Start the cognitive loop (P4: one loop, no mode switching)
        if self._cognitive_loop is not None:
            await self._cognitive_loop.start()

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
        # Terminal, in-process: memory backends get closed below and are not
        # reopened. Health probes read this so an orchestrator stops routing
        # traffic here instead of holding a zombie in the pool.
        self._has_shut_down = True

        # Stop the cognitive loop first so it stops pulling events, then
        # release its claim on the queue before the bus is torn down.
        if self._cognitive_loop is not None:
            try:
                await self._cognitive_loop.stop()
            except Exception:
                logger.warning("cognitive_loop_stop_failed", exc_info=True)

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
            # Stage 0: Reflex Layer check (§6.5) — before full cognition.
            # If a Stable skill's trigger matches, execute directly with
            # LLM only for parameter filling. This bypasses think→plan.
            if self._reflex_index is not None:
                match = self._reflex_index.match(message)
                if match is not None:
                    reflex_start = time.monotonic()
                    logger.info(
                        "reflex_hit",
                        skill_id=match.skill_id,
                        skill_name=match.skill_name,
                        user_id=user_id,
                    )
                    # Fetch the full skill definition
                    skill = await self._skill_store.get(match.skill_id)
                    if skill is not None:
                        # LLM parameter extraction (lightweight, not full think)
                        param_prompt = (
                            f"Extract parameters for skill '{skill.name}' "
                            f"from this user message: '{message}'. "
                            f"Skill description: {skill.description}. "
                            f"Return ONLY a JSON object with parameter names "
                            f"and values. If no parameters needed, return {{}}."
                        )
                        try:
                            raw_params = await self._llm_engine.think(
                                query=param_prompt,
                                context={"query": param_prompt, "identity": {}, "memories": []},
                            )
                            import json as _json
                            try:
                                params = _json.loads(raw_params.strip())
                            except _json.JSONDecodeError:
                                # Fallback: try extracting JSON from text
                                start = raw_params.find("{")
                                end = raw_params.rfind("}") + 1
                                params = _json.loads(raw_params[start:end]) if start >= 0 else {}
                        except Exception:
                            params = {}

                        reflex_ms = (time.monotonic() - reflex_start) * 1000
                        logger.info(
                            "reflex_executed",
                            skill_name=skill.name,
                            duration_ms=round(reflex_ms, 2),
                            params=params,
                        )

                        # Record the reflex execution as an episode
                        await self._memory.record_episode(
                            EpisodicEntry(
                                summary=f"Reflex: {skill.name} triggered",
                                category="interaction",
                                detail=f"User: {message}\nReflex skill: {skill.name}\nParams: {params}",
                                participants=[user_id],
                                tags=["reflex", skill.name],
                                importance=0.5,
                            )
                        )

                        return f"[reflex:{skill.name}] Executed with params: {params}"

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
            from myharness.schema.memory import MemoryCategory, MemoryQuery

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
            # Do NOT pass context= here — let LLMEngine.plan() call
            # build_plan_context(goal, available_skills) internally so the
            # plan prompt template gets the correct identity + skill list.
            plan = await self._llm_engine.plan(thought or message, skill_summaries)

            # Stage 5: Execute (if plan has steps)
            if plan and getattr(plan, "steps", None):
                await self._execute_plan(plan, context)

            # Stage 6: Reflect on the interaction
            # Keys must align with llm/prompts/reflect.py template:
            # experience.summary, experience.detail, experience.tags
            reflection = await self._llm_engine.reflect(
                experience={
                    "summary": f"User said: {message[:200]}",
                    "detail": f"User: {message}\nThought: {thought}\nPlan: {getattr(plan, 'reasoning', '')}",
                    "tags": ["interaction_complete", "reflection"],
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
        """Run the cognitive loop in the foreground until shutdown.

        Delegates to the injected ``EventLoop`` — the single cognitive
        consumer of the event queue (P0: one cognitive center). This method
        must not grow a second, divergent loop implementation: the previous
        inline version polled an event-bus API that did not exist, never
        awaited anything that yields, and therefore starved the entire
        asyncio event loop at 100% CPU the moment it was called.

        Raises:
            RuntimeError: If no cognitive loop was injected.
        """
        if self._cognitive_loop is None:
            raise RuntimeError(
                "HarnessSupervisor has no cognitive loop attached. Build the "
                "supervisor through build_container() or pass cognitive_loop= "
                "explicitly; the supervisor does not implement its own loop."
            )

        logger.info("cognitive_loop_starting")
        if not self._cognitive_loop.is_running:
            await self._cognitive_loop.start()

        task = self._cognitive_loop._loop_task
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("cognitive_loop_stopped")

    async def _execute_plan(
        self, plan: Any, context: dict[str, Any]
    ) -> None:
        """Execute a plan's steps using the appropriate drivers.

        Every step is authorised before it reaches a driver. Plan steps
        come from the LLM, whose context includes retrieved memories and
        tool output, so a step is untrusted input: the skill it names only
        grants the actions that skill declares.

        A denial aborts the whole plan rather than skipping the step. The
        remaining steps were composed on the assumption that the denied
        one ran, and a plan containing an unauthorised step is not a plan
        worth finishing.

        ``plan.current_step`` tracks the cursor so an interrupt mid-plan
        resumes at the step that did not complete.

        Args:
            plan: A Plan object with ordered steps.
            context: The execution context. An ``actor`` key overrides the
                actor attributed to these steps.

        Raises:
            PermissionDeniedError: If a step fails authorisation.
        """
        steps = getattr(plan, "steps", [])
        actor = (context or {}).get("actor")

        for index, step in enumerate(steps):
            skill_name = getattr(step, "skill_name", "") or ""
            action = getattr(step, "action", "") or ""
            parameters = getattr(step, "parameters", {}) or {}

            if hasattr(plan, "current_step"):
                plan.current_step = index

            # Find matching skill
            skill = await self._skill_store.get_by_name(skill_name)

            # Authorise before dispatch. This must sit outside the try
            # below: that block swallows driver failures, and a swallowed
            # authorisation failure is an authorisation failure that let
            # the next step run.
            await self._execution_guard.authorize(
                skill=skill,
                action=action,
                skill_name=skill_name,
                actor=actor,
            )

            if skill is None:
                # Only reachable with a non-enforcing (audit-only) guard.
                logger.warning("skill_not_found_for_step", skill_name=skill_name)
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

            if hasattr(plan, "current_step"):
                plan.current_step = index + 1

    @property
    def is_shut_down(self) -> bool:
        """Whether shutdown() has run — the instance cannot serve again."""
        return self._has_shut_down

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
