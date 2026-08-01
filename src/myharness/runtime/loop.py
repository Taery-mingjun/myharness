"""Core cognitive event loop.

Implements P4 (Event-Driven Architecture): a single event loop that
processes events sequentially without mode switching. Each event is
routed through the cognitive pipeline: Think → Plan → Execute → Reflect.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class EventLoop:
    """Core cognitive event loop.

    Event-driven, no mode switching (P4). Processes events from the
    event bus through the cognitive pipeline. Maintains runtime state
    and handles interruptions.

    The loop runs until explicitly stopped. Each iteration processes
    one event from the queue and updates the runtime state.
    """

    def __init__(
        self,
        event_bus: Any,
        router: Any,
        state: Any,
        interrupt_handler: Any,
    ) -> None:
        """Initialize the event loop.

        Args:
            event_bus: The system event bus for receiving events.
            router: The cognitive pipeline router.
            state: The runtime state tracker.
            interrupt_handler: Handler for execution interruptions.
        """
        self._event_bus = event_bus
        self._router = router
        self._state = state
        self._interrupt_handler = interrupt_handler

        self._is_running = False
        self._loop_task: asyncio.Task | None = None
        self._event_count: int = 0
        self._start_time: float = 0.0

        logger.info("event_loop_initialized")

    async def start(self) -> None:
        """Start the event loop.

        Begins processing events from the event bus. The loop runs
        in a background task and processes events until stopped.
        """
        if self._is_running:
            logger.warning("event_loop_already_running")
            return

        self._is_running = True
        self._start_time = time.monotonic()
        self._loop_task = asyncio.create_task(self._run_loop())

        if hasattr(self._state, "is_running"):
            self._state.is_running = True
        if hasattr(self._state, "uptime_seconds"):
            self._state.uptime_seconds = 0.0

        logger.info("event_loop_started")

    async def stop(self) -> None:
        """Stop the event loop.

        Gracefully stops processing events. The loop task is cancelled
        and awaited to ensure clean shutdown.
        """
        if not self._is_running:
            return

        self._is_running = False

        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        if hasattr(self._state, "is_running"):
            self._state.is_running = False

        logger.info(
            "event_loop_stopped",
            total_events=self._event_count,
            uptime_seconds=time.monotonic() - self._start_time,
        )

    async def step(self) -> None:
        """Process one event from the queue.

        A single iteration of the cognitive loop:
        1. Get next event from the event bus.
        2. Route it through the cognitive pipeline.
        3. Update runtime state.

        This is exposed as a public method to allow manual stepping
        for debugging or testing.
        """
        if not self._is_running:
            return

        try:
            # Get next event
            event = None
            if hasattr(self._event_bus, "get_event"):
                event = await self._event_bus.get_event(timeout=0.01)

            if event is None:
                return

            # Route the event
            if hasattr(self._router, "route"):
                await self._router.route(event)

            self._event_count += 1

            # Update state
            if hasattr(self._state, "pending_events"):
                if hasattr(self._event_bus, "queue_size"):
                    self._state.pending_events = (
                        await self._event_bus.queue_size()
                    )
                else:
                    self._state.pending_events = max(
                        0, self._state.pending_events - 1
                    )

            if hasattr(self._state, "uptime_seconds"):
                self._state.uptime_seconds = (
                    time.monotonic() - self._start_time
                )

            if hasattr(self._state, "metrics"):
                self._state.metrics["total_events"] = self._event_count
                self._state.metrics["events_per_second"] = (
                    self._event_count
                    / max(self._state.uptime_seconds, 0.001)
                )

        except Exception:
            logger.error(
                "event_loop_step_error",
                event_count=self._event_count,
                exc_info=True,
            )

    async def _run_loop(self) -> None:
        """Internal loop that continuously processes events."""
        logger.info("event_loop_running")

        while self._is_running:
            await self.step()
            # Small yield to prevent CPU spinning
            await asyncio.sleep(0)

        logger.info("event_loop_exited")
