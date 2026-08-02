"""Core cognitive event loop.

Implements P4 (Event-Driven Architecture): a single event loop that
processes events sequentially without mode switching. Each event is
pulled off the bus queue and routed through the cognitive pipeline.

Design notes
------------
This loop is deliberately *strict* about its collaborators. An earlier
revision probed every call site with ``hasattr`` and silently skipped
anything that did not match. When the bus API drifted, the result was a
loop that spun at 100% CPU forever while processing exactly zero events
and logging nothing wrong. A cognitive loop that silently does nothing is
worse than one that refuses to start, so the collaborator contract is now
validated in ``__init__`` and violations raise immediately.

Per-event failures are a different matter: one poisoned event must never
take down the loop. Those are caught, counted, and surfaced through
``error_count`` and the runtime state metrics.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

#: Seconds to block on an empty queue. This wait *is* the idle throttle —
#: without it the loop would busy-spin between events.
DEFAULT_POLL_TIMEOUT = 0.1

#: Owner identifier used to claim exclusive consumption of the bus queue.
QUEUE_CONSUMER_ID = "runtime.event_loop"


class EventLoop:
    """Core cognitive event loop.

    Event-driven, no mode switching (P4). Pulls events off the event bus
    queue one at a time and routes each through the cognitive pipeline,
    maintaining observable runtime state.

    The loop is the single consumer of the bus queue; it claims exclusive
    ownership on ``start()`` so it can never race the bus's own queue
    processor.
    """

    def __init__(
        self,
        event_bus: Any,
        router: Any,
        state: Any,
        interrupt_handler: Any = None,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
    ) -> None:
        """Initialize the event loop.

        Args:
            event_bus: The system event bus. Must expose an awaitable
                ``get_event(timeout)`` and a ``publish(event)`` coroutine.
            router: The cognitive pipeline router. Must expose an
                awaitable ``route(event)``.
            state: The runtime state tracker (see ``RuntimeState``).
            interrupt_handler: Optional handler for execution interruptions.
            poll_timeout: Seconds to block waiting for an event. Must be > 0;
                a zero timeout would turn the loop into a CPU spinner.

        Raises:
            TypeError: If ``event_bus`` or ``router`` does not satisfy the
                required contract.
            ValueError: If ``poll_timeout`` is not positive.
        """
        _require_async_method(event_bus, "get_event", "event_bus")
        _require_async_method(event_bus, "publish", "event_bus")
        _require_async_method(router, "route", "router")

        if poll_timeout <= 0:
            raise ValueError(
                f"poll_timeout must be > 0, got {poll_timeout!r}. The poll "
                "wait is the loop's only idle throttle; without it the loop "
                "burns a full CPU core doing nothing."
            )

        self._event_bus = event_bus
        self._router = router
        self._state = state
        self._interrupt_handler = interrupt_handler
        self._poll_timeout = poll_timeout

        self._is_running = False
        self._loop_task: asyncio.Task | None = None
        self._event_count: int = 0
        self._error_count: int = 0
        self._start_time: float = 0.0

        logger.info("event_loop_initialized", poll_timeout=poll_timeout)

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the event loop as a background task.

        Claims exclusive ownership of the bus queue, then begins pulling
        and routing events until ``stop()`` is called.

        Raises:
            EventBusError: If another component already drains the queue.
        """
        if self._is_running:
            logger.warning("event_loop_already_running")
            return

        claim = getattr(self._event_bus, "claim_queue_consumer", None)
        if claim is not None:
            claim(QUEUE_CONSUMER_ID)

        self._is_running = True
        self._start_time = time.monotonic()
        self._loop_task = asyncio.create_task(self._run_loop())

        self._set_state("is_running", True)
        self._set_state("uptime_seconds", 0.0)

        logger.info("event_loop_started")

    async def stop(self) -> None:
        """Stop the event loop and release the queue.

        Cancels the background task and awaits it so shutdown is clean and
        no orphaned task keeps the interpreter alive. Safe to call twice.
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

        release = getattr(self._event_bus, "release_queue_consumer", None)
        if release is not None:
            release(QUEUE_CONSUMER_ID)

        self._set_state("is_running", False)

        logger.info(
            "event_loop_stopped",
            total_events=self._event_count,
            total_errors=self._error_count,
            uptime_seconds=time.monotonic() - self._start_time,
        )

    # ── Stepping ───────────────────────────────────────────────────

    async def step(self) -> bool:
        """Process at most one event from the queue.

        A single iteration of the cognitive loop:
        1. Pull the next event from the bus queue (blocks up to
           ``poll_timeout`` when idle).
        2. Route it through the cognitive pipeline.
        3. Update runtime state and metrics.

        This works whether or not the background loop is running, so it can
        be driven manually for debugging and deterministic tests.

        Returns:
            True if an event was consumed, False if the queue was idle or
            the event failed to process.
        """
        try:
            event = await self._event_bus.get_event(timeout=self._poll_timeout)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._error_count += 1
            logger.error("event_loop_fetch_error", exc_info=True)
            # Back off so a persistently failing bus cannot spin the loop.
            await asyncio.sleep(self._poll_timeout)
            return False

        if event is None:
            return False

        try:
            await self._dispatch(event)
            self._event_count += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            self._error_count += 1
            logger.error(
                "event_loop_dispatch_error",
                event_type=getattr(
                    getattr(event, "event_type", None), "value", "unknown"
                ),
                event_id=getattr(event, "event_id", None),
                exc_info=True,
            )
            self._refresh_state()
            return False

        self._refresh_state()
        return True

    async def _dispatch(self, event: Any) -> None:
        """Route one event through the cognitive pipeline.

        Routing rules are an *overlay*, not a gate: an event with no
        matching rule is still published, so plain ``subscribe()`` handlers
        keep working. Without that fallback, switching the cognitive loop on
        would silently black-hole every event on a bus with no rules yet.

        The fallback keys off ``router.match()`` rather than an empty
        ``route()`` result. Those are not the same thing — a rule can match,
        publish, and still return an empty list because every handler
        returned None. Treating that as "unrouted" delivers the event twice.
        """
        matcher = getattr(self._router, "match", None)
        if matcher is None:
            # Custom router without rule introspection — it owns delivery.
            await self._router.route(event)
            return

        if matcher(event):
            await self._router.route(event)
        else:
            await self._event_bus.publish(event)

    async def _run_loop(self) -> None:
        """Internal loop that continuously processes events."""
        logger.info("event_loop_running")
        try:
            while self._is_running:
                await self.step()
        except asyncio.CancelledError:
            logger.debug("event_loop_cancelled")
            raise
        finally:
            logger.info("event_loop_exited", total_events=self._event_count)

    # ── State ──────────────────────────────────────────────────────

    def _set_state(self, field: str, value: Any) -> None:
        """Assign a runtime-state field if the state object exposes it."""
        if self._state is not None and hasattr(self._state, field):
            setattr(self._state, field, value)

    def _refresh_state(self) -> None:
        """Push counters, uptime, and queue depth into the runtime state."""
        if self._state is None:
            return

        uptime = time.monotonic() - self._start_time if self._start_time else 0.0
        self._set_state("uptime_seconds", uptime)
        self._set_state("pending_events", self._queue_depth())
        self._set_state("error_count", self._error_count)

        metrics = getattr(self._state, "metrics", None)
        if isinstance(metrics, dict):
            metrics["total_events"] = self._event_count
            metrics["total_errors"] = self._error_count
            metrics["events_per_second"] = self._event_count / max(uptime, 1e-6)

    def _queue_depth(self) -> int:
        """Read the bus queue depth, tolerating property or method form."""
        depth = getattr(self._event_bus, "queue_size", None)
        if callable(depth):  # some buses expose it as a method
            try:
                depth = depth()
            except Exception:
                return 0
        return depth if isinstance(depth, int) and depth >= 0 else 0

    # ── Introspection ──────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """Whether the background loop task is active."""
        return self._is_running

    @property
    def event_count(self) -> int:
        """Number of events successfully routed since start."""
        return self._event_count

    @property
    def error_count(self) -> int:
        """Number of fetch/dispatch failures since start."""
        return self._error_count


def _require_async_method(obj: Any, name: str, role: str) -> None:
    """Validate that ``obj`` exposes an awaitable method called ``name``.

    Raises:
        TypeError: If the attribute is missing or not a coroutine function.
    """
    if obj is None:
        raise TypeError(f"EventLoop requires a {role}, got None")

    method = getattr(obj, name, None)
    if method is None:
        raise TypeError(
            f"EventLoop {role} {type(obj).__name__!r} is missing required "
            f"method {name!r}. The loop cannot function without it and will "
            "not start in a silently degraded state."
        )
    if not callable(method):
        raise TypeError(
            f"EventLoop {role} attribute {name!r} is not callable "
            f"(got {type(method).__name__})"
        )
    if not inspect.iscoroutinefunction(method):
        # Bound mocks/partials may not introspect as coroutine functions;
        # only reject plainly synchronous definitions.
        unwrapped = inspect.unwrap(method)
        if inspect.isfunction(unwrapped) or inspect.ismethod(unwrapped):
            raise TypeError(
                f"EventLoop {role} method {name!r} must be async "
                f"(def -> async def) on {type(obj).__name__!r}"
            )
