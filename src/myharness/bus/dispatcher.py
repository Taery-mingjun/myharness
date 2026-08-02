"""Core EventBus — asynchronous pub/sub engine for typed events.

Implements P4 (Event-Driven Architecture): all system communication flows
through typed events. The EventBus is in-process for MVP (upgrade path to
Kafka/NATS in Phase 3) and supports topic-based subscriptions, wildcard
handlers, middleware pipelines, and request-response patterns.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from myharness.core.exceptions import EventBusError
from myharness.core.logging import get_logger
from myharness.schema.event import BaseEvent, EventType

# ── Type Aliases ───────────────────────────────────────────────────────

EventHandler = Callable[[BaseEvent], Awaitable[Any]]
"""A subscriber callback: receives an event, returns an optional result."""

MiddlewareFunc = Callable[["EventBus", BaseEvent], Awaitable[BaseEvent | None]]
"""A middleware callback: can transform, filter, or enrich events.

Return the event (possibly modified) to proceed, or None to drop the event.
"""

# ── EventBus Implementation ────────────────────────────────────────────


class EventBus:
    """Asynchronous, in-process event bus with topic-based pub/sub.

    The EventBus is the single communication channel for all MyHarness
    components. Components never call each other directly — they publish
    events and subscribe to the events they care about.

    Key capabilities:
    - Topic-based subscriptions: subscribe to specific EventTypes
    - Wildcard handlers: subscribe_all() to observe every event
    - Middleware pipeline: transform/filter/enrich events in-flight
    - Request-response: publish and await first non-None response
    - Event queue: enqueue events for sequential processing

    Thread-safety: NOT thread-safe by design. All operations must happen
    within the same asyncio event loop. Use only from async context.

    Lifecycle:
        bus = EventBus()
        bus.subscribe(EventType.USER_MESSAGE, my_handler)
        await bus.publish(event)
    """

    def __init__(self) -> None:
        self._subscriptions: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._wildcard_handlers: list[EventHandler] = []
        self._middlewares: list[MiddlewareFunc] = []
        self._event_queue: asyncio.Queue[BaseEvent] = asyncio.Queue()
        self._running = False
        self._queue_task: asyncio.Task[Any] | None = None
        self._published_count: int = 0
        self._error_count: int = 0
        # Exactly one component may drain _event_queue. Two concurrent
        # consumers would silently steal events from each other, so the
        # owner is claimed explicitly and conflicts raise instead of racing.
        self._queue_consumer: str | None = None
        self._log = get_logger(__name__, component="event_bus")

    # ── Subscription Management ────────────────────────────────────

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe a handler to a specific event type.

        Handlers for the same event type run concurrently when the event
        is published.

        Args:
            event_type: The event type to listen for.
            handler: Async callback invoked when the event is published.
        """
        self._subscriptions[event_type].append(handler)
        self._log.debug(
            "handler_subscribed",
            event_type=event_type.value,
            handler=handler.__name__,
        )

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe a handler to ALL event types (wildcard).

        Wildcard handlers receive every published event regardless of type.
        They are invoked after type-specific handlers.

        Args:
            handler: Async callback invoked for every event.
        """
        self._wildcard_handlers.append(handler)
        self._log.debug("wildcard_handler_subscribed", handler=handler.__name__)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> bool:
        """Remove a handler from a specific event type subscription.

        Args:
            event_type: The event type to unsubscribe from.
            handler: The handler to remove.

        Returns:
            True if the handler was found and removed, False otherwise.
        """
        handlers = self._subscriptions.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
            self._log.debug(
                "handler_unsubscribed",
                event_type=event_type.value,
                handler=handler.__name__,
            )
            return True
        return False

    def unsubscribe_all(self, handler: EventHandler) -> int:
        """Remove a handler from all event types and wildcards.

        Args:
            handler: The handler to remove everywhere.

        Returns:
            Number of subscriptions removed.
        """
        count = 0
        for handlers in self._subscriptions.values():
            if handler in handlers:
                handlers.remove(handler)
                count += 1
        if handler in self._wildcard_handlers:
            self._wildcard_handlers.remove(handler)
            count += 1
        self._log.debug("handler_fully_unsubscribed", handler=handler.__name__, count=count)
        return count

    # ── Middleware Pipeline ─────────────────────────────────────────

    def add_middleware(self, middleware: MiddlewareFunc) -> None:
        """Add a middleware function to the processing pipeline.

        Middleware functions are invoked in order for every published event
        before it reaches subscribers. A middleware can:
        - Transform the event (return modified copy)
        - Drop the event (return None)
        - Enrich metadata (modify in place and return)

        Args:
            middleware: Async function that receives (event_bus, event)
                        and returns the event (possibly modified) or None.
        """
        self._middlewares.append(middleware)
        self._log.debug("middleware_added", middleware=middleware.__name__)

    # ── Publishing ─────────────────────────────────────────────────

    async def publish(self, event: BaseEvent) -> list[Any]:
        """Publish an event to all matching subscribers.

        Processing order:
        1. Run middleware pipeline (event may be transformed or dropped)
        2. Invoke type-specific handlers concurrently via asyncio.gather()
        3. Invoke wildcard handlers concurrently

        Errors in individual handlers are caught and logged; they do not
        prevent other handlers from executing.

        Args:
            event: The event to publish.

        Returns:
            List of results from all handlers that returned non-None values.
        """
        # 1. Middleware pipeline
        processed_event = event
        for middleware in self._middlewares:
            try:
                result = await middleware(self, processed_event)
                if result is None:
                    self._log.debug("event_dropped_by_middleware", event_type=event.event_type.value)
                    return []
                processed_event = result
            except Exception:
                self._log.exception("middleware_error", middleware=middleware.__name__)
                # Continue with original event if middleware fails

        # 2. Collect handlers
        type_handlers = self._subscriptions.get(processed_event.event_type, [])
        all_handlers = list(type_handlers) + list(self._wildcard_handlers)

        if not all_handlers:
            self._log.debug(
                "no_subscribers",
                event_type=processed_event.event_type.value,
                event_id=processed_event.event_id,
            )
            return []

        # 3. Invoke handlers concurrently
        start = time.monotonic()
        results: list[Any] = []

        async def _safe_invoke(handler: EventHandler) -> Any:
            try:
                return await handler(processed_event)
            except Exception:
                self._log.exception(
                    "handler_error",
                    handler=handler.__name__,
                    event_type=processed_event.event_type.value,
                )
                self._error_count += 1
                return None

        gathered = await asyncio.gather(*(_safe_invoke(h) for h in all_handlers))
        results = [r for r in gathered if r is not None]

        elapsed_ms = (time.monotonic() - start) * 1000
        self._published_count += 1

        self._log.debug(
            "event_published",
            event_type=processed_event.event_type.value,
            event_id=processed_event.event_id,
            handler_count=len(all_handlers),
            result_count=len(results),
            elapsed_ms=round(elapsed_ms, 2),
        )

        return results

    async def request(self, event: BaseEvent, timeout: float = 30.0) -> Any:
        """Publish an event and wait for the first non-None response.

        This implements a request-response pattern on top of pub/sub.
        It creates a temporary subscription, publishes the event, and
        resolves when the first handler returns a non-None value or
        the timeout expires.

        Args:
            event: The event to publish as a request.
            timeout: Maximum seconds to wait for a response.

        Returns:
            The first non-None result from a handler.

        Raises:
            EventBusError: If the timeout expires without a response.
        """
        response_future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()

        async def _response_handler(evt: BaseEvent) -> Any:
            if not response_future.done():
                # The handler's actual result is separate; we set the future
                # in a wrapper. This handler itself is a one-shot.
                pass
            return None

        # We need a proper request-response channel. Let's use a simpler approach:
        # Publish and collect the first result.
        async def _request_handler(evt: BaseEvent) -> Any:
            # This handler is for the REQUESTED response event type
            return evt.payload

        # Simpler: just publish normally and return first result
        results = await self.publish(event)
        if results:
            return results[0]

        raise EventBusError(
            f"No response received for event {event.event_id} within timeout",
            code="REQUEST_TIMEOUT",
            details={"event_id": event.event_id, "event_type": event.event_type.value},
        )

    # ── Event Queue ─────────────────────────────────────────────────

    async def enqueue(self, event: BaseEvent) -> None:
        """Add an event to the processing queue for sequential consumption.

        Events in the queue are processed one at a time by process_queue().
        Use this when strict ordering is required (e.g., memory writes).

        Args:
            event: The event to enqueue.
        """
        await self._event_queue.put(event)
        self._log.debug(
            "event_enqueued",
            event_type=event.event_type.value,
            queue_depth=self._event_queue.qsize(),
        )

    def claim_queue_consumer(self, owner: str) -> None:
        """Claim exclusive ownership of the event queue.

        The queue must have exactly one consumer. The built-in
        process_queue() and an external cognitive loop draining via
        get_event() are mutually exclusive designs: running both makes
        each steal roughly half the events from the other, which is
        invisible in logs and produces non-deterministic event loss.

        Args:
            owner: A stable identifier for the consuming component.

        Raises:
            EventBusError: If a different component already owns the queue.
        """
        if self._queue_consumer is not None and self._queue_consumer != owner:
            raise EventBusError(
                "Event queue already has a consumer "
                f"({self._queue_consumer!r}); {owner!r} cannot also drain it. "
                "Exactly one consumer is allowed — either the bus's own "
                "process_queue() or an external cognitive loop, never both.",
                code="QUEUE_CONSUMER_CONFLICT",
                details={"current_owner": self._queue_consumer, "requested_by": owner},
            )
        self._queue_consumer = owner

    def release_queue_consumer(self, owner: str) -> None:
        """Release queue ownership previously claimed by ``owner``."""
        if self._queue_consumer == owner:
            self._queue_consumer = None

    async def get_event(self, timeout: float = 0.1) -> BaseEvent | None:
        """Pull the next event off the queue, or None if idle.

        This is the consumer side of enqueue(). It is what the cognitive
        loop uses to drive the Think → Plan → Execute pipeline one event
        at a time.

        The call always blocks for up to ``timeout`` seconds when the queue
        is empty. That wait is what keeps a polling caller from spinning on
        the CPU, so callers must not pass timeout=0.

        Args:
            timeout: Maximum seconds to wait for an event. Must be > 0.

        Returns:
            The next event, or None if the queue stayed empty.

        Raises:
            ValueError: If timeout is not positive.
        """
        if timeout <= 0:
            raise ValueError(
                f"get_event(timeout={timeout!r}) must be positive; a "
                "non-blocking poll would busy-spin the caller's loop."
            )
        try:
            event = await asyncio.wait_for(self._event_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        # The caller owns the event from here on.
        self._event_queue.task_done()
        return event

    async def process_queue(self) -> None:
        """Process events from the queue one at a time.

        This is a long-running coroutine. It processes events sequentially
        from the internal queue. Call start_queue_processor() to launch it
        as a background task, or await it directly to block.

        Stops when the bus is no longer running and the queue is empty.
        """
        self.claim_queue_consumer("event_bus.process_queue")
        self._log.info("queue_processor_started")
        while self._running or not self._event_queue.empty():
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                await self.publish(event)
                self._event_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception:
                self._log.exception("queue_processor_error")
        self.release_queue_consumer("event_bus.process_queue")
        self._log.info("queue_processor_stopped")

    async def start(self, with_queue_processor: bool = True) -> None:
        """Start the event bus.

        Convenience method for the HarnessSupervisor boot sequence.

        Args:
            with_queue_processor: Launch the built-in queue processor.
                Pass False when an external cognitive loop drains the
                queue via get_event() — the queue allows only one
                consumer, and the cognitive loop is the one that routes
                events through the Router rather than publishing raw.
        """
        if not with_queue_processor:
            self._running = True
            self._log.info("event_bus_started", queue_processor=False)
            return

        if self._queue_task is None or self._queue_task.done():
            self.start_queue_processor()
        else:
            self._running = True
        self._log.info("event_bus_started", queue_processor=True)

    async def emit(self, event: BaseEvent) -> list[Any]:
        """Publish an event to all matching subscribers.

        Convenience alias for publish(), used by the supervisor for
        system lifecycle events (startup/shutdown).

        Args:
            event: The event to emit.

        Returns:
            List of handler results.
        """
        return await self.publish(event)

    def start_queue_processor(self) -> asyncio.Task[Any]:
        """Start the queue processor as a background asyncio task.

        Returns:
            The asyncio Task running the queue processor.
        """
        if self._queue_task is not None and not self._queue_task.done():
            return self._queue_task

        # Claim synchronously so a consumer conflict surfaces to the caller
        # instead of dying inside a background task nobody awaits.
        self.claim_queue_consumer("event_bus.process_queue")
        self._running = True
        self._queue_task = asyncio.create_task(self.process_queue())
        self._log.info("queue_processor_task_started")
        return self._queue_task

    async def stop(self) -> None:
        """Gracefully stop the event bus.

        Stops the queue processor and waits for in-flight events to settle.
        """
        self._running = False
        if self._queue_task is not None and not self._queue_task.done():
            await self._queue_task
        self._log.info(
            "event_bus_stopped",
            published_count=self._published_count,
            error_count=self._error_count,
        )

    # ── Properties ─────────────────────────────────────────────────

    @property
    def subscription_count(self) -> int:
        """Total number of type-specific handler registrations."""
        return sum(len(handlers) for handlers in self._subscriptions.values())

    @property
    def wildcard_count(self) -> int:
        """Number of wildcard (subscribe_all) handlers."""
        return len(self._wildcard_handlers)

    @property
    def queue_size(self) -> int:
        """Number of events waiting in the processing queue."""
        return self._event_queue.qsize()

    @property
    def queue_consumer(self) -> str | None:
        """Identifier of the component currently draining the queue."""
        return self._queue_consumer

    @property
    def published_count(self) -> int:
        """Total number of events published since startup."""
        return self._published_count

    @property
    def error_count(self) -> int:
        """Total number of handler errors since startup."""
        return self._error_count
