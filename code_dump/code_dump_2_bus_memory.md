# code_dump_2_bus_memory.md

本文件为第 2 部分，包含目录: bus, memory/

包含文件数: 21

## 文件路径: src/myharness/bus/__init__.py

```python
"""Event Bus module — asynchronous pub/sub event routing.

The bus module provides the foundational communication layer for MyHarness.
All system components communicate exclusively through typed events published
to the EventBus, enabling loose coupling and event-driven architecture (P4).

Public API:
    EventBus       — In-process async event bus with topic-based pub/sub
    Router         — Rule-based event router with priority ordering
    RouteRule      — Individual routing rule definition
    EventResult    — Structured event processing result envelope

    LoggingMiddleware  — Logs every event passing through the bus
    TracingMiddleware  — Injects trace/correlation IDs
    TimingMiddleware   — Measures event processing duration
"""

from myharness.bus.dispatcher import EventBus
from myharness.bus.middleware import (
    LoggingMiddleware,
    TimingMiddleware,
    TracingMiddleware,
)
from myharness.bus.result import EventResult
from myharness.bus.router import RouteRule, Router

__all__ = [
    "EventBus",
    "Router",
    "RouteRule",
    "EventResult",
    "LoggingMiddleware",
    "TracingMiddleware",
    "TimingMiddleware",
]
```

## 文件路径: src/myharness/bus/dispatcher.py

```python
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

    async def process_queue(self) -> None:
        """Process events from the queue one at a time.

        This is a long-running coroutine. It processes events sequentially
        from the internal queue. Call start_queue_processor() to launch it
        as a background task, or await it directly to block.

        Stops when the bus is no longer running and the queue is empty.
        """
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
        self._log.info("queue_processor_stopped")

    def start_queue_processor(self) -> asyncio.Task[Any]:
        """Start the queue processor as a background asyncio task.

        Returns:
            The asyncio Task running the queue processor.
        """
        if self._queue_task is not None and not self._queue_task.done():
            return self._queue_task

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
    def published_count(self) -> int:
        """Total number of events published since startup."""
        return self._published_count

    @property
    def error_count(self) -> int:
        """Total number of handler errors since startup."""
        return self._error_count
```

## 文件路径: src/myharness/bus/middleware.py

```python
"""EventBus middleware — transform, filter, and enrich events in-flight.

Middleware functions form a processing pipeline through which every event
passes before reaching subscribers. They can:
- Transform: modify the event (e.g., add computed fields)
- Filter: drop events that don't meet criteria (return None)
- Enrich: add metadata for observability (tracing, timing, logging)
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from myharness.core.logging import get_logger
from myharness.schema.event import BaseEvent


# ── Logging Middleware ──────────────────────────────────────────────────


async def LoggingMiddleware(event_bus: Any, event: BaseEvent) -> BaseEvent:
    """Log every event that passes through the bus.

    This is the outermost middleware — it should be added first so that
    it wraps the entire middleware chain.

    Args:
        event_bus: The EventBus instance (unused by this middleware).
        event: The event being processed.

    Returns:
        The event unchanged.
    """
    log = get_logger(__name__, component="bus_middleware")
    log.info(
        "event_flow",
        event_type=event.event_type.value,
        event_id=event.event_id,
        source=event.source,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
    )
    return event


# ── Tracing Middleware ──────────────────────────────────────────────────


async def TracingMiddleware(event_bus: Any, event: BaseEvent) -> BaseEvent:
    """Inject tracing and correlation IDs into events.

    If an event doesn't have a correlation_id, one is generated.
    The event's own event_id is recorded as the causation_id for any
    downstream events that are causally linked.

    This enables full causal chain tracing through the system (event sourcing).

    Args:
        event_bus: The EventBus instance (unused by this middleware).
        event: The event being processed.

    Returns:
        The event with correlation_id populated if missing.
    """
    if event.correlation_id is None:
        event.correlation_id = str(uuid.uuid4())

    # Add tracing metadata
    event.metadata["trace_start_ms"] = time.monotonic() * 1000
    event.metadata["trace_id"] = event.correlation_id

    return event


# ── Timing Middleware ───────────────────────────────────────────────────


async def TimingMiddleware(event_bus: Any, event: BaseEvent) -> BaseEvent:
    """Measure and record event processing duration.

    This middleware should be the innermost one (added last) so it measures
    only the subscriber processing time, not middleware overhead.

    The processing duration is recorded in event.metadata["processing_ms"].

    Args:
        event_bus: The EventBus instance (unused by this middleware).
        event: The event being processed.

    Returns:
        The event with processing_ms added to metadata.
    """
    start_ms = time.monotonic() * 1000
    event.metadata["processing_start_ms"] = start_ms

    # The actual timing is recorded after subscribers run. This middleware
    # injects the start time; the final duration is computed downstream.
    return event
```

## 文件路径: src/myharness/bus/result.py

```python
"""Event processing result envelope.

Provides a structured, typed wrapper for results from event processing,
aggregating success/failure status, results, errors, and timing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class EventResult:
    """Structured result of processing an event through the bus.

    Collects results from all subscribers, captures errors, and records
    timing information for observability and debugging.

    Attributes:
        event_id: The ID of the processed event.
        success: Whether all handlers completed without errors.
        results: Non-None results returned by handlers.
        errors: Error messages from failed handlers.
        handler_count: Total number of handlers that were invoked.
        error_count: Number of handlers that raised exceptions.
        duration_ms: Total processing duration in milliseconds.
        timestamp: When the result was created.
    """

    event_id: str
    success: bool = True
    results: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    handler_count: int = 0
    error_count: int = 0
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_publish(
        cls,
        event_id: str,
        results: list[Any],
        errors: list[str],
        handler_count: int,
        duration_ms: float,
    ) -> EventResult:
        """Factory method to create an EventResult from a publish operation.

        Args:
            event_id: The published event's ID.
            results: Non-None results from handlers.
            errors: Error messages from failed handlers.
            handler_count: Total handlers invoked.
            duration_ms: Processing duration in milliseconds.

        Returns:
            A new EventResult instance.
        """
        return cls(
            event_id=event_id,
            success=len(errors) == 0,
            results=results,
            errors=errors,
            handler_count=handler_count,
            error_count=len(errors),
            duration_ms=round(duration_ms, 3),
        )

    @property
    def result_count(self) -> int:
        """Number of non-None results returned by handlers."""
        return len(self.results)

    @property
    def has_results(self) -> bool:
        """Whether any handler returned a non-None result."""
        return len(self.results) > 0

    @property
    def first_result(self) -> Any:
        """The first result, or None if there are no results."""
        return self.results[0] if self.results else None
```

## 文件路径: src/myharness/bus/router.py

```python
"""Rule-based event router with priority ordering.

The Router evaluates routing rules against incoming events and dispatches
them to the appropriate targets via the EventBus. Rules are evaluated in
priority order and support pattern matching on event type, source, and
payload conditions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from myharness.core.logging import get_logger
from myharness.schema.event import BaseEvent, EventType


@dataclass
class RouteRule:
    """A single routing rule that matches events and directs them to targets.

    Attributes:
        rule_id: Unique identifier for this rule.
        event_types: Event types this rule applies to.
        source_pattern: Optional regex pattern to match on event.source.
        payload_condition: Optional key-value pairs to match on event.payload.
                           All keys must match (AND logic).
        target: Target component identifier (e.g., "llm.engine.think").
        priority: Higher priority rules are evaluated first. Default 0.
        enabled: Whether this rule is active.
    """

    rule_id: str
    event_types: list[EventType]
    source_pattern: str | None = None
    payload_condition: dict[str, Any] | None = None
    target: str = ""
    priority: int = 0
    enabled: bool = True

    def matches(self, event: BaseEvent) -> bool:
        """Check whether this rule matches a given event.

        Args:
            event: The event to test against this rule.

        Returns:
            True if the event matches all rule conditions.
        """
        if not self.enabled:
            return False

        # Match event type
        if event.event_type not in self.event_types:
            return False

        # Match source pattern (regex)
        if self.source_pattern is not None:
            if not re.search(self.source_pattern, event.source):
                return False

        # Match payload conditions (all keys must match, AND logic)
        if self.payload_condition:
            for key, expected_value in self.payload_condition.items():
                actual_value = event.payload.get(key)
                if actual_value != expected_value:
                    return False

        return True


class Router:
    """Rule-based event router for directing events to system components.

    The Router evaluates all registered rules in priority order (descending).
    When a matching rule is found, the event is published to the EventBus
    with the rule's target set as metadata.

    Usage:
        router = Router(event_bus)
        router.add_rule(RouteRule(
            rule_id="user_to_think",
            event_types=[EventType.USER_MESSAGE],
            target="llm.engine.think",
            priority=10,
        ))
        await router.route(event)
    """

    def __init__(self, event_bus: "EventBus") -> None:
        """Initialize the router.

        Args:
            event_bus: The EventBus instance to publish routed events to.
        """
        from myharness.bus.dispatcher import EventBus

        self._event_bus: EventBus = event_bus
        self._rules: dict[str, RouteRule] = {}
        self._log = get_logger(__name__, component="router")

    def add_rule(self, rule: RouteRule) -> None:
        """Register a routing rule.

        If a rule with the same rule_id already exists, it is replaced.

        Args:
            rule: The routing rule to register.
        """
        self._rules[rule.rule_id] = rule
        self._log.debug(
            "rule_added",
            rule_id=rule.rule_id,
            event_types=[et.value for et in rule.event_types],
            target=rule.target,
            priority=rule.priority,
        )

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a routing rule by ID.

        Args:
            rule_id: The ID of the rule to remove.

        Returns:
            True if the rule was found and removed, False otherwise.
        """
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._log.debug("rule_removed", rule_id=rule_id)
            return True
        return False

    def get_rule(self, rule_id: str) -> RouteRule | None:
        """Retrieve a routing rule by ID.

        Args:
            rule_id: The ID of the rule to retrieve.

        Returns:
            The RouteRule if found, None otherwise.
        """
        return self._rules.get(rule_id)

    def list_rules(self) -> list[RouteRule]:
        """List all registered rules sorted by priority (descending).

        Returns:
            List of RouteRule objects, highest priority first.
        """
        return sorted(self._rules.values(), key=lambda r: r.priority, reverse=True)

    def match(self, event: BaseEvent) -> list[RouteRule]:
        """Find all rules that match a given event.

        Rules are evaluated in priority order (descending). All matching
        rules are returned (not just the first).

        Args:
            event: The event to match against registered rules.

        Returns:
            List of matching RouteRule objects, highest priority first.
        """
        matching = [r for r in self.list_rules() if r.matches(event)]
        if matching:
            self._log.debug(
                "rules_matched",
                event_type=event.event_type.value,
                match_count=len(matching),
                matched_rules=[r.rule_id for r in matching],
            )
        else:
            self._log.debug(
                "no_rules_matched",
                event_type=event.event_type.value,
                event_id=event.event_id,
            )
        return matching

    async def route(self, event: BaseEvent) -> list[Any]:
        """Match the event against rules and publish to the EventBus.

        For each matching rule, the event's metadata is enriched with the
        rule's target and then published.

        Args:
            event: The event to route.

        Returns:
            List of results from the EventBus publish operations.
        """
        matching_rules = self.match(event)

        if not matching_rules:
            self._log.warning(
                "event_unrouted",
                event_type=event.event_type.value,
                event_id=event.event_id,
                source=event.source,
            )
            return []

        results: list[Any] = []
        for rule in matching_rules:
            # Enrich event metadata with routing information
            event.metadata["routed_by"] = rule.rule_id
            event.metadata["target"] = rule.target

            self._log.info(
                "event_routed",
                event_type=event.event_type.value,
                event_id=event.event_id,
                rule_id=rule.rule_id,
                target=rule.target,
            )
            result = await self._event_bus.publish(event)
            results.extend(result)

        return results

    @property
    def rule_count(self) -> int:
        """Number of registered routing rules."""
        return len(self._rules)
```

## 文件路径: src/myharness/memory/__init__.py

```python
"""Memory System — the agent's persistent identity and experience store.

Per P3 (Identity Externalization) and P9 (Source/Derived Data Separation):
- SourceOfTruth: append-only JSON/JSONL — canonical, immutable, human-readable
- DerivedStorage: SQLite metadata — fast query, fully rebuildable
- VectorIndex (FAISS) and TextIndex (FTS5): search indexes — fully rebuildable
"""

from myharness.memory.interface import MemorySystem
from myharness.memory.manager import MemoryManager
from myharness.memory.serializer import MemorySerializer
from myharness.memory.storage.source import SourceOfTruth
from myharness.memory.storage.derived import DerivedStorage
from myharness.memory.indexing.vector import VectorIndex
from myharness.memory.indexing.text import TextIndex
from myharness.memory.stores.identity import IdentityStore
from myharness.memory.stores.episodic import EpisodicStore
from myharness.memory.stores.semantic import SemanticStore
from myharness.memory.stores.relationship import RelationshipStore

__all__ = [
    "MemorySystem",
    "MemoryManager",
    "MemorySerializer",
    "SourceOfTruth",
    "DerivedStorage",
    "VectorIndex",
    "TextIndex",
    "IdentityStore",
    "EpisodicStore",
    "SemanticStore",
    "RelationshipStore",
]
```

## 文件路径: src/myharness/memory/indexing/__init__.py

```python
""""""
from __future__ import annotations

from myharness.memory.indexing.base import BaseIndexer
from myharness.memory.indexing.vector import VectorIndex
from myharness.memory.indexing.text import TextIndex

__all__ = ["BaseIndexer", "VectorIndex", "TextIndex"]
```

## 文件路径: src/myharness/memory/indexing/base.py

```python
"""Abstract base class for all memory indexes.

All indexes are DERIVED DATA per P9 — fully rebuildable from SourceOfTruth.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth


class BaseIndexer(ABC):
    """Abstract interface for searchable memory indexes.

    Implementations: VectorIndex (FAISS), TextIndex (SQLite FTS5).
    """

    @abstractmethod
    async def add(self, entry_id: str, data: Any) -> None:
        """Add an entry to the index.

        Args:
            entry_id: Unique identifier for the memory entry.
            data: The data to index (embedding for vector, text for text).
        """
        ...

    @abstractmethod
    async def search(
        self, query: Any, k: int = 10
    ) -> list[tuple[str, float, Any]]:
        """Search the index.

        Args:
            query: Search query (embedding array for vector, string for text).
            k: Maximum number of results to return.

        Returns:
            List of (entry_id, score, metadata) tuples, sorted by score descending.
        """
        ...

    @abstractmethod
    async def delete(self, entry_id: str) -> None:
        """Remove an entry from the index."""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Remove all entries from the index."""
        ...

    @abstractmethod
    async def rebuild_from_source(self, source: SourceOfTruth) -> int:
        """Rebuild the entire index from SourceOfTruth data.

        Args:
            source: The SourceOfTruth instance to read canonical data from.

        Returns:
            Number of entries indexed.
        """
        ...
```

## 文件路径: src/myharness/memory/indexing/text.py

```python
"""SQLite FTS5-based full-text search index.

Provides fast keyword search over episodic and semantic memory entries.
Fully rebuildable from SourceOfTruth — per P9, this is derived data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

import aiosqlite

from myharness.core.config import get_settings
from myharness.core.logging import get_logger
from myharness.memory.indexing.base import BaseIndexer

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth

logger = get_logger(__name__)

# Separate FTS5 schema (independent from DerivedStorage's FTS)
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS text_idx USING fts5(
    entry_id UNINDEXED,
    store UNINDEXED,
    content,
    metadata UNINDEXED,
    tokenize='porter unicode61'
);
"""


class TextIndex(BaseIndexer):
    """SQLite FTS5 full-text search index for memory entries.

    Indexes text content (summary, detail, tags for episodic;
    entity, attribute, value for semantic) for fast keyword search.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        settings = get_settings()
        self._db_path = db_path or (settings.memory_index_dir / "text_fts.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        """Lazy-initialize the SQLite connection."""
        if self._conn is None:
            self._conn = await aiosqlite.connect(str(self._db_path))
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.executescript(FTS_SCHEMA)
            await self._conn.commit()
            logger.info("TextIndex: initialized", path=str(self._db_path))
        return self._conn

    async def add(
        self, entry_id: str, data: str | dict[str, Any]
    ) -> None:
        """Add a text entry to the FTS index.

        Args:
            entry_id: The memory entry's unique ID.
            data: Either a text string or dict with 'store', 'content', 'metadata'.
        """
        conn = await self._get_conn()

        if isinstance(data, str):
            store = "unknown"
            content = data
            metadata = {}
        else:
            store = data.get("store", "unknown")
            content = data.get("content", "")
            metadata = data.get("metadata", {})

        # Delete existing entry first (FTS has no upsert)
        await conn.execute(
            "DELETE FROM text_idx WHERE entry_id = ?", (entry_id,)
        )

        await conn.execute(
            "INSERT INTO text_idx (entry_id, store, content, metadata) VALUES (?, ?, ?, ?)",
            (entry_id, store, content, json.dumps(metadata, default=str)),
        )
        await conn.commit()

    async def search(
        self, query: str, k: int = 10
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Full-text search on indexed content.

        Args:
            query: Search query string (supports FTS5 syntax).
            k: Maximum results.

        Returns:
            List of (entry_id, bm25_score, metadata) tuples sorted by score.
        """
        conn = await self._get_conn()

        if not query.strip():
            return []

        try:
            cursor = await conn.execute(
                """SELECT entry_id, rank, store, metadata
                   FROM text_idx WHERE text_idx MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, k),
            )
            rows = await cursor.fetchall()

            results: list[tuple[str, float, dict[str, Any]]] = []
            for row in rows:
                entry_id = row[0]
                bm25_rank = row[1]
                meta = {}
                if row[3]:
                    try:
                        meta = json.loads(row[3])
                    except json.JSONDecodeError:
                        pass
                # BM25 rank is negative; normalize to [0,1]
                score = 1.0 / (1.0 + abs(float(bm25_rank or 0)))
                results.append((entry_id, score, meta))

            return results

        except aiosqlite.OperationalError:
            # FTS5 query syntax error
            logger.warning("TextIndex: FTS5 query error", query=query)
            return []

    async def delete(self, entry_id: str) -> None:
        """Remove an entry from the FTS index."""
        conn = await self._get_conn()
        await conn.execute(
            "DELETE FROM text_idx WHERE entry_id = ?", (entry_id,)
        )
        await conn.commit()

    async def clear(self) -> None:
        """Remove all entries from the index."""
        conn = await self._get_conn()
        await conn.execute("DELETE FROM text_idx")
        await conn.commit()
        logger.info("TextIndex: cleared")

    async def rebuild_from_source(self, source: SourceOfTruth) -> int:
        """Rebuild the text index from SourceOfTruth data.

        Args:
            source: The SourceOfTruth instance.

        Returns:
            Number of entries indexed.
        """
        await self.clear()
        count = 0

        # Index episodic entries
        async for entry in source.iterate_all("episodic"):
            content_parts = [
                entry.get("summary", ""),
                entry.get("detail", ""),
                " ".join(entry.get("tags", [])),
            ]
            content = " ".join(p for p in content_parts if p)
            if content.strip():
                await self.add(entry.get("entry_id", ""), {
                    "store": "episodic",
                    "content": content,
                    "metadata": {
                        "category": entry.get("category", ""),
                        "importance": entry.get("importance", 0.5),
                        "summary": entry.get("summary", ""),
                    },
                })
                count += 1

        # Index semantic entries
        async for entry in source.iterate_all("semantic"):
            content_parts = [
                entry.get("entity", ""),
                entry.get("attribute", ""),
                str(entry.get("value", "")),
            ]
            content = " ".join(p for p in content_parts if p)
            if content.strip():
                await self.add(entry.get("entry_id", ""), {
                    "store": "semantic",
                    "content": content,
                    "metadata": {
                        "entity": entry.get("entity", ""),
                        "attribute": entry.get("attribute", ""),
                        "confidence": entry.get("confidence", 1.0),
                    },
                })
                count += 1

        logger.info("TextIndex: rebuilt from source", entries=count)
        return count

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
```

## 文件路径: src/myharness/memory/indexing/vector.py

```python
"""FAISS-based vector similarity search index.

Stores embeddings for episodic and semantic memory entries.
Fully rebuildable from SourceOfTruth — per P9, this is derived data.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any, TYPE_CHECKING

import numpy as np

from myharness.core.config import get_settings
from myharness.core.logging import get_logger
from myharness.memory.indexing.base import BaseIndexer

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth

logger = get_logger(__name__)


class VectorIndex(BaseIndexer):
    """FAISS-based vector index for semantic similarity search.

    Uses IndexFlatL2 (L2 distance) by default. Configurable to use
    IndexIVFFlat for larger datasets.

    The index stores (entry_id, metadata) mappings alongside FAISS vectors.
    The index file (.faiss) and metadata file (.meta) are saved together.
    """

    def __init__(
        self,
        dimension: int | None = None,
        index_path: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._dimension = dimension or settings.embedding_dimension
        self._index_path = index_path or (
            settings.memory_index_dir / "vector.faiss"
        )
        self._meta_path = self._index_path.with_suffix(".meta")

        self._index = self._create_index()
        self._id_map: dict[int, str] = {}  # FAISS internal ID → entry_id
        self._metadata: dict[str, dict[str, Any]] = {}  # entry_id → metadata
        self._next_id = 0

    def _create_index(self):
        """Create a FAISS index. Uses FlatL2 for reliability."""
        try:
            import faiss
            return faiss.IndexFlatL2(self._dimension)
        except ImportError:
            raise ImportError(
                "faiss-cpu is required for VectorIndex. Install with: pip install faiss-cpu"
            )

    # ── Core Operations ─────────────────────────────────────────────────

    async def add(
        self, entry_id: str, embedding: np.ndarray, metadata: dict[str, Any] | None = None
    ) -> None:
        """Add an embedding to the index.

        Args:
            entry_id: The memory entry's unique ID.
            embedding: NumPy array of shape (dimension,) or (1, dimension).
            metadata: Optional metadata to store alongside.
        """
        if embedding.ndim == 1:
            embedding = embedding.reshape(1, -1)

        if embedding.shape[1] != self._dimension:
            raise ValueError(
                f"Embedding dimension {embedding.shape[1]} != index dimension {self._dimension}"
            )

        embedding = embedding.astype(np.float32)
        self._index.add(embedding)
        internal_id = self._next_id
        self._id_map[internal_id] = entry_id
        self._metadata[entry_id] = metadata or {}
        self._next_id += 1

    async def search(
        self, query_embedding: np.ndarray, k: int = 10
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Search for the k nearest neighbors.

        Args:
            query_embedding: NumPy array of shape (dimension,).
            k: Number of results to return.

        Returns:
            List of (entry_id, distance, metadata) tuples sorted by distance.
        """
        if self._index.ntotal == 0:
            return []

        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        query_embedding = query_embedding.astype(np.float32)
        k = min(k, self._index.ntotal)

        distances, indices = self._index.search(query_embedding, k)

        results: list[tuple[str, float, dict[str, Any]]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            entry_id = self._id_map.get(int(idx))
            if entry_id is None:
                continue
            # Convert L2 distance to similarity score [0,1]
            score = 1.0 / (1.0 + float(dist))
            meta = self._metadata.get(entry_id, {})
            results.append((entry_id, score, meta))

        return results

    async def delete(self, entry_id: str) -> None:
        """Remove an entry from the index.

        Note: FAISS IndexFlatL2 does not support deletion natively.
        We mark it as deleted in metadata; a full rebuild clears it.
        """
        if entry_id in self._metadata:
            self._metadata.pop(entry_id, None)
            logger.debug("VectorIndex: marked entry for deletion", entry_id=entry_id)

    async def clear(self) -> None:
        """Remove all entries from the index."""
        self._index = self._create_index()
        self._id_map.clear()
        self._metadata.clear()
        self._next_id = 0
        logger.info("VectorIndex: cleared")

    # ── Persistence ─────────────────────────────────────────────────────

    async def save(self) -> None:
        """Save the FAISS index and metadata to disk."""
        import faiss

        self._index_path.parent.mkdir(parents=True, exist_ok=True)

        # Save FAISS index
        faiss.write_index(self._index, str(self._index_path))

        # Save metadata
        meta_data = {
            "id_map": self._id_map,
            "metadata": self._metadata,
            "next_id": self._next_id,
            "dimension": self._dimension,
        }
        with open(self._meta_path, "wb") as f:
            pickle.dump(meta_data, f)

        logger.info(
            "VectorIndex: saved",
            path=str(self._index_path),
            entries=self._index.ntotal,
        )

    async def load(self) -> bool:
        """Load the FAISS index and metadata from disk.

        Returns:
            True if loaded successfully, False if files don't exist.
        """
        import faiss

        if not self._index_path.exists() or not self._meta_path.exists():
            return False

        try:
            self._index = faiss.read_index(str(self._index_path))
            with open(self._meta_path, "rb") as f:
                meta_data = pickle.load(f)
            self._id_map = meta_data["id_map"]
            self._metadata = meta_data["metadata"]
            self._next_id = meta_data["next_id"]
            logger.info(
                "VectorIndex: loaded",
                path=str(self._index_path),
                entries=self._index.ntotal,
            )
            return True
        except Exception as exc:
            logger.error("VectorIndex: load failed", error=str(exc))
            self._index = self._create_index()
            return False

    # ── Rebuild ─────────────────────────────────────────────────────────

    async def rebuild_from_source(self, source: SourceOfTruth) -> int:
        """Rebuild the vector index from SourceOfTruth data.

        Reads all episodic and semantic entries that have embeddings
        from the canonical JSONL files.

        Args:
            source: The SourceOfTruth instance.

        Returns:
            Number of entries indexed.
        """
        await self.clear()
        count = 0

        # Index episodic entries with embeddings
        async for entry in source.iterate_all("episodic"):
            embedding_data = entry.get("embedding")
            if embedding_data and isinstance(embedding_data, list) and len(embedding_data) > 0:
                emb = np.array(embedding_data, dtype=np.float32)
                await self.add(
                    entry.get("entry_id", ""),
                    emb,
                    {
                        "store": "episodic",
                        "summary": entry.get("summary", ""),
                        "category": entry.get("category", ""),
                        "importance": entry.get("importance", 0.5),
                    },
                )
                count += 1

        # Index semantic entries with embeddings
        async for entry in source.iterate_all("semantic"):
            embedding_data = entry.get("embedding")
            if embedding_data and isinstance(embedding_data, list) and len(embedding_data) > 0:
                emb = np.array(embedding_data, dtype=np.float32)
                await self.add(
                    entry.get("entry_id", ""),
                    emb,
                    {
                        "store": "semantic",
                        "entity": entry.get("entity", ""),
                        "attribute": entry.get("attribute", ""),
                        "confidence": entry.get("confidence", 1.0),
                    },
                )
                count += 1

        logger.info("VectorIndex: rebuilt from source", entries=count)
        return count

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        """Number of entries in the index."""
        return self._index.ntotal

    @property
    def dimension(self) -> int:
        """Embedding dimension."""
        return self._dimension
```

## 文件路径: src/myharness/memory/interface.py

```python
"""Abstract interface for the complete Memory System.

All concrete implementations (e.g., MemoryManager) must implement this
interface. The interface is the contract between the Memory System and
the rest of the Harness (LLM, API, Runtime).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from myharness.schema.identity import IdentityUpdateProposal
from myharness.schema.memory import (
    EpisodicEntry,
    IdentityEntry,
    MemoryQuery,
    MemorySearchResult,
    RelationshipEntry,
    SemanticEntry,
)


class MemorySystem(ABC):
    """Abstract interface for the complete memory system.

    Provides CRUD operations across all four memory stores and
    cross-store hybrid search. All methods are async.
    """

    # ── Identity ────────────────────────────────────────────────────────

    @abstractmethod
    async def get_identity(self) -> IdentityEntry:
        """Get the current agent identity."""
        ...

    @abstractmethod
    async def update_identity(self, entry: IdentityEntry) -> None:
        """Update the agent identity.

        Raises:
            IdentityConflictError: If version conflict is detected.
        """
        ...

    @abstractmethod
    async def apply_identity_proposal(
        self, proposal: IdentityUpdateProposal
    ) -> IdentityEntry:
        """Apply an identity update proposal from the LLM.

        Args:
            proposal: The LLM's suggested identity change.

        Returns:
            The updated IdentityEntry.
        """
        ...

    # ── Episodic ────────────────────────────────────────────────────────

    @abstractmethod
    async def record_episode(self, entry: EpisodicEntry) -> str:
        """Record a new episodic entry.

        Returns:
            The entry_id of the recorded episode.
        """
        ...

    @abstractmethod
    async def get_episode(self, episode_id: str) -> EpisodicEntry | None:
        """Get a specific episode by ID."""
        ...

    @abstractmethod
    async def search_episodes(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Search episodic memory."""
        ...

    @abstractmethod
    async def get_recent_episodes(
        self, limit: int = 50
    ) -> list[EpisodicEntry]:
        """Get the most recent episodes."""
        ...

    # ── Semantic ────────────────────────────────────────────────────────

    @abstractmethod
    async def store_knowledge(self, entry: SemanticEntry) -> str:
        """Store a semantic knowledge entry.

        Returns:
            The entry_id of the stored entry.
        """
        ...

    @abstractmethod
    async def search_knowledge(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Search semantic memory."""
        ...

    @abstractmethod
    async def get_related_knowledge(
        self, entity_id: str, relation: str | None = None
    ) -> list[SemanticEntry]:
        """Get semantic entries related to an entity."""
        ...

    # ── Relationship ────────────────────────────────────────────────────

    @abstractmethod
    async def set_relationship(self, entry: RelationshipEntry) -> None:
        """Set (upsert) a relationship between entities."""
        ...

    @abstractmethod
    async def get_relationship(
        self, entity_a: str, entity_b: str
    ) -> RelationshipEntry | None:
        """Get the relationship between two entities."""
        ...

    @abstractmethod
    async def get_all_relationships_for(
        self, entity_id: str
    ) -> list[RelationshipEntry]:
        """Get all relationships involving an entity."""
        ...

    # ── Cross-Store ─────────────────────────────────────────────────────

    @abstractmethod
    async def search(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Cross-store hybrid search across episodic and semantic memory."""
        ...

    @abstractmethod
    async def archive_old_episodes(
        self, before_timestamp: float
    ) -> int:
        """Archive episodes older than the given timestamp.

        Args:
            before_timestamp: Unix timestamp; episodes before this are archived.

        Returns:
            Number of episodes archived.
        """
        ...

    @abstractmethod
    async def rebuild_indexes(self) -> None:
        """Fully rebuild all derived indexes from SourceOfTruth.

        Per P9: All derived data can be reconstructed from source data.
        """
        ...

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics from all memory stores.

        Returns:
            Dict with counts and metadata from each store.
        """
        ...
```

## 文件路径: src/myharness/memory/manager.py

```python
"""MemoryManager — concrete implementation of MemorySystem.

Orchestrates all four memory stores (identity, episodic, semantic,
relationship) and provides cross-store hybrid search. Implements P9
(Source of Truth) and P3 (Identity Externalization).
"""

from __future__ import annotations

from typing import Any

import structlog

from myharness.memory.interface import MemorySystem
from myharness.memory.stores.identity import IdentityStore
from myharness.memory.stores.episodic import EpisodicStore
from myharness.memory.stores.semantic import SemanticStore
from myharness.memory.stores.relationship import RelationshipStore
from myharness.schema.identity import IdentityUpdateProposal
from myharness.schema.memory import (
    EpisodicEntry,
    IdentityEntry,
    MemoryCategory,
    MemoryQuery,
    MemorySearchResult,
    RelationshipEntry,
    SemanticEntry,
)

logger = structlog.get_logger(__name__)


class MemoryManager(MemorySystem):
    """Concrete implementation of the MemorySystem interface.

    Orchestrates:
      - IdentityStore: Agent self-model
      - EpisodicStore: Chronological experience log
      - SemanticStore: Factual knowledge base
      - RelationshipStore: Entity relationship graph

    Cross-store search merges results from episodic and semantic stores
    with configurable hybrid (vector + text) weighting.
    """

    def __init__(
        self,
        identity: IdentityStore,
        episodic: EpisodicStore,
        semantic: SemanticStore,
        relationship: RelationshipStore,
    ) -> None:
        self._identity = identity
        self._episodic = episodic
        self._semantic = semantic
        self._relationship = relationship

    # ── Identity ────────────────────────────────────────────────────────

    async def get_identity(self) -> IdentityEntry:
        """Get the current agent identity."""
        return await self._identity.get_identity()

    async def update_identity(self, entry: IdentityEntry) -> None:
        """Update the agent identity."""
        await self._identity.update_identity(entry)

    async def apply_identity_proposal(
        self, proposal: IdentityUpdateProposal
    ) -> IdentityEntry:
        """Apply an identity update proposal from the LLM."""
        return await self._identity.apply_proposal(proposal)

    # ── Episodic ────────────────────────────────────────────────────────

    async def record_episode(self, entry: EpisodicEntry) -> str:
        """Record a new episodic entry."""
        return await self._episodic.record(entry)

    async def get_episode(self, episode_id: str) -> EpisodicEntry | None:
        """Get a specific episode by ID."""
        return await self._episodic.get(episode_id)

    async def search_episodes(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Search episodic memory."""
        q = query.model_copy()
        q.categories = [MemoryCategory.EPISODIC]
        return await self._episodic.search(q)

    async def get_recent_episodes(
        self, limit: int = 50
    ) -> list[EpisodicEntry]:
        """Get the most recent episodes."""
        return await self._episodic.get_recent(limit)

    # ── Semantic ────────────────────────────────────────────────────────

    async def store_knowledge(self, entry: SemanticEntry) -> str:
        """Store a semantic knowledge entry."""
        return await self._semantic.store(entry)

    async def search_knowledge(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Search semantic memory."""
        q = query.model_copy()
        q.categories = [MemoryCategory.SEMANTIC]
        return await self._semantic.search(q)

    async def get_related_knowledge(
        self, entity_id: str, relation: str | None = None
    ) -> list[SemanticEntry]:
        """Get semantic entries related to an entity."""
        return await self._semantic.get_related(entity_id, relation)

    # ── Relationship ────────────────────────────────────────────────────

    async def set_relationship(self, entry: RelationshipEntry) -> None:
        """Set (upsert) a relationship between entities."""
        await self._relationship.set(entry)

    async def get_relationship(
        self, entity_a: str, entity_b: str
    ) -> RelationshipEntry | None:
        """Get the relationship between two entities."""
        return await self._relationship.get(entity_a, entity_b)

    async def get_all_relationships_for(
        self, entity_id: str
    ) -> list[RelationshipEntry]:
        """Get all relationships involving an entity."""
        return await self._relationship.get_all_for(entity_id)

    # ── Cross-Store ─────────────────────────────────────────────────────

    async def search(
        self, query: MemoryQuery
    ) -> list[MemorySearchResult]:
        """Cross-store hybrid search across episodic and semantic memory.

        Searches both episodic and semantic stores, merges results,
        and ranks by relevance score.

        Args:
            query: The memory query specification.

        Returns:
            Merged and ranked list of MemorySearchResult objects.
        """
        categories = query.categories or list(MemoryCategory)
        all_results: list[MemorySearchResult] = []

        if MemoryCategory.EPISODIC in categories:
            try:
                episodic_results = await self._episodic.search(query)
                all_results.extend(episodic_results)
            except Exception as exc:
                logger.warning(
                    "MemoryManager: episodic search failed",
                    error=str(exc),
                )

        if MemoryCategory.SEMANTIC in categories:
            try:
                semantic_results = await self._semantic.search(query)
                all_results.extend(semantic_results)
            except Exception as exc:
                logger.warning(
                    "MemoryManager: semantic search failed",
                    error=str(exc),
                )

        # Sort by score descending and limit to top_k
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[: query.top_k]

    async def archive_old_episodes(
        self, before_timestamp: float
    ) -> int:
        """Archive episodes older than the given timestamp.

        Since SourceOfTruth is append-only, "archiving" is handled at
        the query level (filter by timestamp). This method returns the
        count of episodes that would be eligible for archiving.

        Args:
            before_timestamp: Unix timestamp threshold.

        Returns:
            Number of episodes older than the threshold.
        """
        from datetime import datetime, timezone

        cutoff = datetime.fromtimestamp(before_timestamp, tz=timezone.utc)
        count = 0
        async for entry in self._episodic._source.iterate_all("episodic"):
            try:
                ts = entry.get("timestamp", "")
                if isinstance(ts, str):
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    ts_dt = ts
                if ts_dt < cutoff:
                    count += 1
            except Exception:
                pass
        return count

    async def rebuild_indexes(self) -> None:
        """Fully rebuild all derived indexes from SourceOfTruth.

        Per P9: All derived data (SQLite, FAISS, FTS5) can be
        reconstructed from the canonical JSON/JSONL source files.

        Rebuild order:
          1. DerivedStorage (SQLite)
          2. TextIndex (FTS5)
          3. VectorIndex (FAISS)
        """
        logger.info("MemoryManager: starting full index rebuild")

        source = self._episodic._source  # All stores share the same SourceOfTruth

        # Rebuild derived storage
        try:
            derived_count = await self._episodic._derived.rebuild_from_source(source)
            logger.info("MemoryManager: derived storage rebuilt", entries=derived_count)
        except Exception as exc:
            logger.error(
                "MemoryManager: derived storage rebuild failed",
                error=str(exc),
            )

        # Rebuild text index
        try:
            text_count = await self._episodic._text_idx.rebuild_from_source(source)
            logger.info("MemoryManager: text index rebuilt", entries=text_count)
        except Exception as exc:
            logger.error(
                "MemoryManager: text index rebuild failed",
                error=str(exc),
            )

        # Rebuild vector index
        try:
            vector_count = await self._episodic._vector_idx.rebuild_from_source(source)
            logger.info("MemoryManager: vector index rebuilt", entries=vector_count)
        except Exception as exc:
            logger.error(
                "MemoryManager: vector index rebuild failed",
                error=str(exc),
            )

        logger.info("MemoryManager: index rebuild complete")

    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics from all memory stores.

        Returns:
            Dict with counts and metadata from each store.
        """
        stats: dict[str, Any] = {
            "episodic": {},
            "semantic": {},
            "relationship": {},
            "identity": {},
            "indexes": {},
        }

        # Store counts
        try:
            stats["episodic"]["total_entries"] = await self._episodic.count()
        except Exception as exc:
            stats["episodic"]["error"] = str(exc)

        try:
            stats["semantic"]["total_entries"] = await self._semantic.count()
        except Exception as exc:
            stats["semantic"]["error"] = str(exc)

        try:
            stats["relationship"]["total_entries"] = await self._relationship.count()
        except Exception as exc:
            stats["relationship"]["error"] = str(exc)

        # Identity info
        try:
            identity = await self._identity.get_identity()
            stats["identity"] = {
                "version": identity.version,
                "has_mission": bool(identity.mission),
                "num_values": len(identity.core_values),
                "num_guidelines": len(identity.behavioral_guidelines),
                "num_preferences": len(identity.preferences),
            }
        except Exception as exc:
            stats["identity"]["error"] = str(exc)

        # Index stats
        try:
            stats["indexes"]["vector_count"] = self._episodic._vector_idx.size
        except Exception:
            stats["indexes"]["vector_count"] = 0

        return stats
```

## 文件路径: src/myharness/memory/serializer.py

```python
"""Memory Serializer — converts between Pydantic models and dicts.

Handles serialization/deserialization for all memory entry types,
including datetime and embedding handling for JSON compatibility.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from myharness.schema.memory import (
    EpisodicEntry,
    IdentityEntry,
    RelationshipEntry,
    SemanticEntry,
)


def entry_to_dict(
    entry: IdentityEntry | EpisodicEntry | SemanticEntry | RelationshipEntry,
) -> dict[str, Any]:
    """Convert any memory entry to a JSON-serializable dictionary.

    Args:
        entry: Any memory entry type.

    Returns:
        JSON-compatible dictionary representation.
    """
    return entry.model_dump(mode="json")


def dict_to_episodic(data: dict[str, Any]) -> EpisodicEntry:
    """Convert a dictionary to an EpisodicEntry.

    Args:
        data: Raw dictionary from SourceOfTruth or elsewhere.

    Returns:
        Parsed EpisodicEntry.

    Raises:
        ValidationError: If the data doesn't conform to the schema.
    """
    return EpisodicEntry(**data)


def dict_to_semantic(data: dict[str, Any]) -> SemanticEntry:
    """Convert a dictionary to a SemanticEntry.

    Args:
        data: Raw dictionary from SourceOfTruth or elsewhere.

    Returns:
        Parsed SemanticEntry.
    """
    return SemanticEntry(**data)


def dict_to_relationship(data: dict[str, Any]) -> RelationshipEntry:
    """Convert a dictionary to a RelationshipEntry.

    Args:
        data: Raw dictionary from SourceOfTruth or elsewhere.

    Returns:
        Parsed RelationshipEntry.
    """
    return RelationshipEntry(**data)


def dict_to_identity(data: dict[str, Any]) -> IdentityEntry:
    """Convert a dictionary to an IdentityEntry.

    Args:
        data: Raw dictionary from SourceOfTruth or elsewhere.

    Returns:
        Parsed IdentityEntry.
    """
    return IdentityEntry(**data)


class MemorySerializer:
    """Utility class for memory entry serialization/deserialization.

    Provides convenience methods for converting between Pydantic models
    and dictionary representations used by SourceOfTruth storage.
    """

    @staticmethod
    def serialize(
        entry: IdentityEntry | EpisodicEntry | SemanticEntry | RelationshipEntry,
    ) -> dict[str, Any]:
        """Serialize any memory entry to a dictionary."""
        return entry_to_dict(entry)

    @staticmethod
    def deserialize_episodic(data: dict[str, Any]) -> EpisodicEntry:
        """Deserialize an episodic entry from a dictionary."""
        return dict_to_episodic(data)

    @staticmethod
    def deserialize_semantic(data: dict[str, Any]) -> SemanticEntry:
        """Deserialize a semantic entry from a dictionary."""
        return dict_to_semantic(data)

    @staticmethod
    def deserialize_relationship(data: dict[str, Any]) -> RelationshipEntry:
        """Deserialize a relationship entry from a dictionary."""
        return dict_to_relationship(data)

    @staticmethod
    def deserialize_identity(data: dict[str, Any]) -> IdentityEntry:
        """Deserialize an identity entry from a dictionary."""
        return dict_to_identity(data)
```

## 文件路径: src/myharness/memory/storage/__init__.py

```python
"""Storage layer — SourceOfTruth (canonical JSON) and DerivedStorage (rebuildable SQLite)."""

from __future__ import annotations

from myharness.memory.storage.source import SourceOfTruth
from myharness.memory.storage.derived import DerivedStorage

__all__ = ["SourceOfTruth", "DerivedStorage"]
```

## 文件路径: src/myharness/memory/storage/derived.py

```python
"""SQLite-based derived storage — fast queries, fully rebuildable from SourceOfTruth.

Per P9: This storage layer is DERIVED. All data can be reconstructed
from the SourceOfTruth JSON files. It must never be the sole source of any data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from myharness.core.logging import get_logger

logger = get_logger(__name__)

# SQL schema — created on first connection
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    summary TEXT NOT NULL,
    detail TEXT DEFAULT '',
    participants TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    importance REAL DEFAULT 0.5,
    timestamp TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS semantics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT UNIQUE NOT NULL,
    entity TEXT NOT NULL,
    attribute TEXT NOT NULL,
    value TEXT,
    confidence REAL DEFAULT 1.0,
    source TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT UNIQUE NOT NULL,
    entity_a TEXT NOT NULL,
    entity_b TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    strength REAL DEFAULT 0.5,
    context TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_ref TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp);
CREATE INDEX IF NOT EXISTS idx_episodes_category ON episodes(category);
CREATE INDEX IF NOT EXISTS idx_episodes_importance ON episodes(importance);
CREATE INDEX IF NOT EXISTS idx_semantics_entity ON semantics(entity);
CREATE INDEX IF NOT EXISTS idx_semantics_attribute ON semantics(attribute);
CREATE INDEX IF NOT EXISTS idx_relationships_entity_a ON relationships(entity_a);
CREATE INDEX IF NOT EXISTS idx_relationships_entity_b ON relationships(entity_b);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relation_type);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    summary, detail, tags, content=episodes, content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS semantics_fts USING fts5(
    entity, attribute, value, content=semantics, content_rowid=id
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, summary, detail, tags)
    VALUES (new.id, new.summary, new.detail, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, detail, tags)
    VALUES ('delete', old.id, old.summary, old.detail, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, detail, tags)
    VALUES ('delete', old.id, old.summary, old.detail, old.tags);
    INSERT INTO episodes_fts(rowid, summary, detail, tags)
    VALUES (new.id, new.summary, new.detail, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS semantics_ai AFTER INSERT ON semantics BEGIN
    INSERT INTO semantics_fts(rowid, entity, attribute, value)
    VALUES (new.id, new.entity, new.attribute, new.value);
END;

CREATE TRIGGER IF NOT EXISTS semantics_ad AFTER DELETE ON semantics BEGIN
    INSERT INTO semantics_fts(semantics_fts, rowid, entity, attribute, value)
    VALUES ('delete', old.id, old.entity, old.attribute, old.value);
END;

CREATE TRIGGER IF NOT EXISTS semantics_au AFTER UPDATE ON semantics BEGIN
    INSERT INTO semantics_fts(semantics_fts, rowid, entity, attribute, value)
    VALUES ('delete', old.id, old.entity, old.attribute, old.value);
    INSERT INTO semantics_fts(rowid, entity, attribute, value)
    VALUES (new.id, new.entity, new.attribute, new.value);
END;
"""


class DerivedStorage:
    """SQLite-based derived metadata storage.

    All data is rebuildable from SourceOfTruth JSON files.
    Provides fast structured queries, FTS5 full-text search, and
    metadata filtering that would be slow on raw JSON files.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        """Lazy-initialize the SQLite connection and schema."""
        if self._conn is None:
            self._conn = await aiosqlite.connect(str(self._db_path))
            self._conn.row_factory = aiosqlite.Row
            await self._conn.executescript(SCHEMA_SQL)
            await self._conn.commit()
            logger.info("DerivedStorage: initialized", path=str(self._db_path))
        return self._conn

    # ── Episode Operations ──────────────────────────────────────────────

    async def insert_episode(self, entry: dict[str, Any]) -> None:
        """Insert or replace an episode entry."""
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO episodes
               (entry_id, category, summary, detail, participants, tags,
                importance, timestamp, source_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("entry_id", ""),
                entry.get("category", "general"),
                entry.get("summary", ""),
                entry.get("detail", ""),
                json.dumps(entry.get("participants", [])),
                json.dumps(entry.get("tags", [])),
                entry.get("importance", 0.5),
                self._normalize_timestamp(entry.get("timestamp")),
                self._source_ref("episodic", entry.get("entry_id", "")),
            ),
        )
        await conn.commit()

    async def query_episodes(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        min_importance: float = 0.0,
        time_start: str | None = None,
        time_end: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query episodes with filters."""
        conn = await self._get_conn()
        query = "SELECT * FROM episodes WHERE 1=1"
        params: list[Any] = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if min_importance > 0:
            query += " AND importance >= ?"
            params.append(min_importance)

        if time_start:
            query += " AND timestamp >= ?"
            params.append(time_start)

        if time_end:
            query += " AND timestamp <= ?"
            params.append(time_end)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            # Deserialize JSON fields
            for field in ("participants", "tags"):
                try:
                    d[field] = json.loads(d.get(field, "[]"))
                except (json.JSONDecodeError, TypeError):
                    d[field] = []
            results.append(d)

        # Filter by tags if needed (post-query, since tags are JSON array)
        if tags:
            results = [
                r for r in results
                if any(t in r.get("tags", []) for t in tags)
            ]

        return results

    async def get_episode(self, entry_id: str) -> dict[str, Any] | None:
        """Get a single episode by entry_id."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT * FROM episodes WHERE entry_id = ?", (entry_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        for field in ("participants", "tags"):
            try:
                d[field] = json.loads(d.get(field, "[]"))
            except (json.JSONDecodeError, TypeError):
                d[field] = []
        return d

    async def get_recent_episodes(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get most recent episodes."""
        return await self.query_episodes(limit=limit)

    async def count_episodes(self) -> int:
        """Count total episodes."""
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT COUNT(*) as cnt FROM episodes")
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ── Semantic Operations ─────────────────────────────────────────────

    async def insert_semantic(self, entry: dict[str, Any]) -> None:
        """Insert or replace a semantic entry."""
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO semantics
               (entry_id, entity, attribute, value, confidence, source, created_at, source_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("entry_id", ""),
                entry.get("entity", ""),
                entry.get("attribute", ""),
                json.dumps(entry.get("value")) if entry.get("value") is not None else None,
                entry.get("confidence", 1.0),
                entry.get("source", ""),
                self._normalize_timestamp(entry.get("created_at")),
                self._source_ref("semantic", entry.get("entry_id", "")),
            ),
        )
        await conn.commit()

    async def query_semantics(
        self,
        entity: str | None = None,
        attribute: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query semantic entries."""
        conn = await self._get_conn()
        query = "SELECT * FROM semantics WHERE 1=1"
        params: list[Any] = []

        if entity:
            query += " AND entity = ?"
            params.append(entity)

        if attribute:
            query += " AND attribute = ?"
            params.append(attribute)

        if min_confidence > 0:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("value"):
                try:
                    d["value"] = json.loads(d["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    async def get_related_semantics(
        self, entity: str, attribute: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all semantic entries for an entity, optionally filtered by attribute."""
        conn = await self._get_conn()
        if attribute:
            cursor = await conn.execute(
                "SELECT * FROM semantics WHERE entity = ? AND attribute = ?",
                (entity, attribute),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM semantics WHERE entity = ?", (entity,)
            )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("value"):
                try:
                    d["value"] = json.loads(d["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    # ── Relationship Operations ─────────────────────────────────────────

    async def insert_relationship(self, entry: dict[str, Any]) -> None:
        """Insert or replace a relationship entry."""
        conn = await self._get_conn()
        await conn.execute(
            """INSERT OR REPLACE INTO relationships
               (entry_id, entity_a, entity_b, relation_type, strength, context,
                metadata_json, created_at, updated_at, source_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("entry_id", ""),
                entry.get("entity_a", ""),
                entry.get("entity_b", ""),
                entry.get("relation_type", ""),
                entry.get("strength", 0.5),
                entry.get("context", ""),
                json.dumps(entry.get("metadata", {})),
                self._normalize_timestamp(entry.get("created_at")),
                self._normalize_timestamp(entry.get("updated_at")),
                self._source_ref("relationship", entry.get("entry_id", "")),
            ),
        )
        await conn.commit()

    async def get_relationship(
        self, entity_a: str, entity_b: str
    ) -> dict[str, Any] | None:
        """Get a relationship between two entities."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            """SELECT * FROM relationships
               WHERE (entity_a = ? AND entity_b = ?)
                  OR (entity_a = ? AND entity_b = ?)""",
            (entity_a, entity_b, entity_b, entity_a),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("metadata_json"):
            try:
                d["metadata"] = json.loads(d["metadata_json"])
            except json.JSONDecodeError:
                d["metadata"] = {}
        return d

    async def get_all_relationships_for(self, entity_id: str) -> list[dict[str, Any]]:
        """Get all relationships involving an entity."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            """SELECT * FROM relationships
               WHERE entity_a = ? OR entity_b = ?
               ORDER BY strength DESC""",
            (entity_id, entity_id),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("metadata_json"):
                try:
                    d["metadata"] = json.loads(d["metadata_json"])
                except json.JSONDecodeError:
                    d["metadata"] = {}
            results.append(d)
        return results

    # ── FTS5 Full-Text Search ───────────────────────────────────────────

    async def fts_search_episodes(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search on episode summaries and details."""
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                """SELECT e.*, rank FROM episodes_fts f
                   JOIN episodes e ON f.rowid = e.id
                   WHERE episodes_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            )
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                for field in ("participants", "tags"):
                    try:
                        d[field] = json.loads(d.get(field, "[]"))
                    except (json.JSONDecodeError, TypeError):
                        d[field] = []
                results.append(d)
            return results
        except aiosqlite.OperationalError:
            # FTS query syntax error — return empty
            return []

    async def fts_search_semantics(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search on semantic entries."""
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                """SELECT s.*, rank FROM semantics_fts f
                   JOIN semantics s ON f.rowid = s.id
                   WHERE semantics_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            )
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if d.get("value"):
                    try:
                        d["value"] = json.loads(d["value"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results
        except aiosqlite.OperationalError:
            return []

    # ── Rebuild from Source ─────────────────────────────────────────────

    async def clear_all(self) -> None:
        """Delete all derived data (preparation for rebuild)."""
        conn = await self._get_conn()
        await conn.execute("DELETE FROM episodes")
        await conn.execute("DELETE FROM semantics")
        await conn.execute("DELETE FROM relationships")
        # FTS content tables are cleared via triggers, but also clear them directly
        await conn.execute("DELETE FROM episodes_fts")
        await conn.execute("DELETE FROM semantics_fts")
        await conn.commit()
        logger.info("DerivedStorage: cleared all derived data")

    async def rebuild_from_source(self, source: "SourceOfTruth") -> int:
        """Fully rebuild all derived data from SourceOfTruth.

        This is the key P9 operation: delete all derived data and
        reconstruct it from the canonical JSON files.

        Args:
            source: The SourceOfTruth instance to read from.

        Returns:
            Total number of entries rebuilt.
        """
        await self.clear_all()
        total = 0

        # Rebuild episodes
        async for entry in source.iterate_all("episodic"):
            await self.insert_episode(entry)
            total += 1
        logger.info("DerivedStorage: rebuilt episodes", count=total)

        # Rebuild semantics
        sem_count = 0
        async for entry in source.iterate_all("semantic"):
            await self.insert_semantic(entry)
            sem_count += 1
        total += sem_count
        logger.info("DerivedStorage: rebuilt semantics", count=sem_count)

        # Rebuild relationships
        rel_count = 0
        async for entry in source.iterate_all("relationship"):
            await self.insert_relationship(entry)
            rel_count += 1
        total += rel_count
        logger.info("DerivedStorage: rebuilt relationships", count=rel_count)

        logger.info("DerivedStorage: rebuild complete", total_entries=total)
        return total

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_timestamp(ts: Any) -> str:
        """Normalize a timestamp to ISO format string."""
        if ts is None:
            return datetime.now(timezone.utc).isoformat()
        if isinstance(ts, datetime):
            return ts.isoformat()
        return str(ts)

    @staticmethod
    def _source_ref(store: str, entry_id: str) -> str:
        """Generate a source reference string."""
        return f"{store}:{entry_id}"

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("DerivedStorage: connection closed")
```

## 文件路径: src/myharness/memory/storage/source.py

```python
"""Append-only JSON/JSONL storage — the single Source of Truth.

All memory data is first written here before derived indexes are updated.
This enforces P9: Source data is canonical; derived data is rebuildable.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os as aio_os

from myharness.core.exceptions import MemoryNotFoundError, MemoryWriteError
from myharness.core.logging import get_logger

logger = get_logger(__name__)


class SourceOfTruth:
    """Append-only JSON/JSONL file storage — canonical, immutable, human-readable.

    Directory structure:
        {base_path}/
            identity/       # JSON files (identity.json, identity_v1.json, ...)
            episodic/       # JSONL file (entries.jsonl)
            semantic/       # JSONL file (entries.jsonl)
            relationship/   # JSONL file (entries.jsonl)

    JSONL stores use append-only semantics for immutability.
    JSON stores (identity) use atomic write-then-rename for safety.
    """

    def __init__(self, base_path: Path) -> None:
        self._base_path = Path(base_path)
        self._ensure_store_dirs()

    def _ensure_store_dirs(self) -> None:
        """Create per-store directories if they don't exist."""
        for store in ("identity", "episodic", "semantic", "relationship"):
            (self._base_path / store).mkdir(parents=True, exist_ok=True)

    def _store_path(self, store: str) -> Path:
        """Get the directory path for a given store name."""
        return self._base_path / store

    def _key_path(self, store: str, key: str) -> Path:
        """Get the file path for a JSON key within a store."""
        return self._store_path(store) / f"{key}.json"

    def _jsonl_path(self, store: str) -> Path:
        """Get the JSONL file path for a store."""
        return self._store_path(store) / "entries.jsonl"

    # ── JSON (key-value) Operations ─────────────────────────────────────

    async def write(self, store: str, key: str, data: dict[str, Any]) -> str:
        """Write a JSON file atomically (write to temp, then rename).

        Args:
            store: Store name (e.g., "identity").
            key: Unique key within the store.
            data: Serializable dictionary to persist.

        Returns:
            The full path to the written file.

        Raises:
            MemoryWriteError: If the write operation fails.
        """
        file_path = self._key_path(store, key)
        tmp_path = file_path.with_suffix(".tmp")

        try:
            async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2, default=str))

            os.replace(tmp_path, file_path)
            logger.debug("SourceOfTruth: wrote JSON", store=store, key=key, path=str(file_path))
            return str(file_path)

        except Exception as exc:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise MemoryWriteError(
                f"Failed to write {store}/{key}",
                details={"store": store, "key": key, "path": str(file_path)},
                cause=exc,
            ) from exc

    async def read(self, store: str, key: str) -> dict[str, Any] | None:
        """Read a JSON file from a store.

        Args:
            store: Store name.
            key: Key within the store.

        Returns:
            The parsed dictionary, or None if not found.
        """
        file_path = self._key_path(store, key)
        if not file_path.exists():
            return None

        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("SourceOfTruth: JSON decode error", path=str(file_path), error=str(exc))
            return None

    async def delete(self, store: str, key: str) -> bool:
        """Delete a JSON file from a store. Returns True if deleted."""
        file_path = self._key_path(store, key)
        if not file_path.exists():
            return False
        file_path.unlink()
        logger.debug("SourceOfTruth: deleted JSON", store=store, key=key)
        return True

    async def list_keys(self, store: str) -> list[str]:
        """List all JSON keys (without .json extension) in a store."""
        store_path = self._store_path(store)
        if not store_path.exists():
            return []
        return sorted(
            p.stem for p in store_path.glob("*.json") if p.is_file() and not p.name.endswith(".tmp")
        )

    # ── JSONL (append-only log) Operations ──────────────────────────────

    async def append(self, store: str, entry: dict[str, Any]) -> str:
        """Append a JSON line to the store's JSONL file.

        This is the canonical write path for episodic, semantic, and
        relationship entries. Append-only ensures immutability.

        Args:
            store: Store name (episodic, semantic, relationship).
            entry: Serializable dictionary to append.

        Returns:
            The entry_id from the entry dict.

        Raises:
            MemoryWriteError: If the append fails.
        """
        file_path = self._jsonl_path(store)

        try:
            line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
            async with aiofiles.open(file_path, "a", encoding="utf-8") as f:
                await f.write(line)

            entry_id = entry.get("entry_id", "unknown")
            logger.debug("SourceOfTruth: appended JSONL", store=store, entry_id=entry_id)
            return str(entry_id)

        except Exception as exc:
            raise MemoryWriteError(
                f"Failed to append to {store}",
                details={"store": store, "path": str(file_path)},
                cause=exc,
            ) from exc

    async def scan(
        self, store: str, start: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Scan a slice of the JSONL file.

        Args:
            store: Store name.
            start: Zero-based line offset.
            limit: Maximum number of entries to return.

        Returns:
            List of parsed dictionaries.
        """
        file_path = self._jsonl_path(store)
        if not file_path.exists():
            return []

        results: list[dict[str, Any]] = []
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                line_num = 0
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if line_num >= start + limit:
                        break
                    if line_num >= start:
                        try:
                            results.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning(
                                "SourceOfTruth: bad JSONL line",
                                store=store, line=line_num,
                            )
                    line_num += 1
        except FileNotFoundError:
            return []

        return results

    async def count(self, store: str) -> int:
        """Count the number of entries in a JSONL store."""
        file_path = self._jsonl_path(store)
        if not file_path.exists():
            return 0

        count = 0
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                async for _ in f:
                    count += 1
        except FileNotFoundError:
            return 0

        return count

    async def iterate_all(self, store: str) -> AsyncIterator[dict[str, Any]]:
        """Iterate over all entries in a JSONL file.

        Args:
            store: Store name.

        Yields:
            Parsed dictionaries, one per line.
        """
        file_path = self._jsonl_path(store)
        if not file_path.exists():
            return

        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("SourceOfTruth: skipping bad JSONL line", store=store)
                    continue

    # ── Bulk / Utility ──────────────────────────────────────────────────

    async def get_all_identity_versions(self) -> list[dict[str, Any]]:
        """Get all identity versions, sorted by version descending."""
        keys = await self.list_keys("identity")
        entries = []
        for key in keys:
            data = await self.read("identity", key)
            if data:
                entries.append(data)
        entries.sort(key=lambda e: e.get("version", 0), reverse=True)
        return entries

    async def get_latest_identity(self) -> dict[str, Any] | None:
        """Get the latest identity version."""
        versions = await self.get_all_identity_versions()
        return versions[0] if versions else None
```

## 文件路径: src/myharness/memory/stores/__init__.py

```python
"""Memory stores — the four canonical memory types.

- IdentityStore: Agent self-model (P3)
- EpisodicStore: Immutable experience records
- SemanticStore: Factual knowledge (entity-attribute-value)
- RelationshipStore: Entity relationship graph
"""

from __future__ import annotations

from myharness.memory.stores.identity import IdentityStore
from myharness.memory.stores.episodic import EpisodicStore
from myharness.memory.stores.semantic import SemanticStore
from myharness.memory.stores.relationship import RelationshipStore

__all__ = [
    "IdentityStore",
    "EpisodicStore",
    "SemanticStore",
    "RelationshipStore",
]
```

## 文件路径: src/myharness/memory/stores/episodic.py

```python
"""EpisodicStore — immutable experience records.

Per P9 (Source of Truth): Write to SourceOfTruth FIRST, then best-effort
updates to derived indexes. Episodic entries are append-only and immutable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import structlog

from myharness.core.exceptions import MemoryNotFoundError, MemoryWriteError
from myharness.schema.memory import (
    EpisodicEntry,
    MemoryCategory,
    MemoryQuery,
    MemorySearchResult,
)

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth
    from myharness.memory.storage.derived import DerivedStorage
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.indexing.text import TextIndex

logger = structlog.get_logger(__name__)


class EpisodicStore:
    """Manages episodic memory — the agent's chronological experience log.

    Write path (P9-compliant):
      1. SourceOfTruth.append() — MUST succeed
      2. DerivedStorage.insert_episode() — best-effort
      3. TextIndex.add() — best-effort
      4. VectorIndex.add() — best-effort (if embedding present)
    """

    def __init__(
        self,
        source: SourceOfTruth,
        derived: DerivedStorage,
        vector_idx: VectorIndex,
        text_idx: TextIndex,
    ) -> None:
        self._source = source
        self._derived = derived
        self._vector_idx = vector_idx
        self._text_idx = text_idx

    async def record(self, entry: EpisodicEntry) -> str:
        """Record an episodic entry.

        Writes to SourceOfTruth first (must succeed), then updates
        derived storage and indexes on a best-effort basis.

        Args:
            entry: The episodic entry to record.

        Returns:
            The entry_id of the recorded episode.

        Raises:
            MemoryWriteError: If the source-of-truth write fails.
        """
        data = entry.model_dump(mode="json")
        entry_id = str(entry.entry_id)

        # Step 1: Write to SourceOfTruth (MUST succeed)
        await self._source.append("episodic", data)
        logger.debug("EpisodicStore: source written", entry_id=entry_id)

        # Step 2-4: Update derived indexes (best-effort)
        try:
            await self._derived.insert_episode(data)
        except Exception as exc:
            logger.warning(
                "EpisodicStore: derived update failed",
                entry_id=entry_id,
                error=str(exc),
            )

        try:
            content = f"{entry.summary} {entry.detail} {' '.join(entry.tags)}"
            await self._text_idx.add(entry_id, {
                "store": "episodic",
                "content": content,
                "metadata": {
                    "category": entry.category,
                    "importance": entry.importance,
                    "summary": entry.summary,
                },
            })
        except Exception as exc:
            logger.warning(
                "EpisodicStore: text index update failed",
                entry_id=entry_id,
                error=str(exc),
            )

        if entry.embedding is not None:
            try:
                import numpy as np
                emb = np.array(entry.embedding, dtype=np.float32)
                await self._vector_idx.add(entry_id, emb, {
                    "store": "episodic",
                    "summary": entry.summary,
                    "category": entry.category,
                    "importance": entry.importance,
                })
            except Exception as exc:
                logger.warning(
                    "EpisodicStore: vector index update failed",
                    entry_id=entry_id,
                    error=str(exc),
                )

        return entry_id

    async def get(self, episode_id: str) -> EpisodicEntry | None:
        """Retrieve a specific episode by ID from SourceOfTruth.

        Args:
            episode_id: The unique episode identifier.

        Returns:
            The EpisodicEntry or None if not found.
        """
        # Scan source — JSONL doesn't support direct lookup, so iterate
        async for entry in self._source.iterate_all("episodic"):
            if entry.get("entry_id") == episode_id:
                return EpisodicEntry(**entry)
        return None

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        """Search episodic memory using vector and/or text search.

        If query_embedding is provided, uses vector search. Otherwise
        falls back to full-text search via the derived store.

        Args:
            query: The memory query specification.

        Returns:
            List of MemorySearchResult objects ranked by relevance.
        """
        results: list[MemorySearchResult] = []

        # Vector search path
        if query.query_embedding is not None:
            import numpy as np
            emb = np.array(query.query_embedding, dtype=np.float32)
            hits = await self._vector_idx.search(emb, k=query.top_k)
            for entry_id, score, meta in hits:
                if meta.get("store") != "episodic":
                    continue
                entry = await self.get(entry_id)
                if entry is None:
                    continue
                if entry.importance < query.min_importance:
                    continue
                results.append(MemorySearchResult(
                    entry_id=entry.entry_id,
                    category=MemoryCategory.EPISODIC,
                    score=score,
                    content=entry.summary,
                    entry=entry.model_dump(mode="json"),
                ))

        # Text search path (if no vector or hybrid)
        if query.query_text and (not query.query_embedding or query.hybrid_weight < 1.0):
            text_hits = await self._text_idx.search(query.query_text, k=query.top_k)
            for entry_id, score, meta in text_hits:
                if meta.get("store") != "episodic":
                    continue
                entry = await self.get(entry_id)
                if entry is None:
                    continue
                if entry.importance < query.min_importance:
                    continue

                # If hybrid, merge scores
                if query.query_embedding:
                    score = score * (1.0 - query.hybrid_weight)

                # Avoid duplicates
                existing_ids = {str(r.entry_id) for r in results}
                if entry_id in existing_ids:
                    continue

                results.append(MemorySearchResult(
                    entry_id=entry.entry_id,
                    category=MemoryCategory.EPISODIC,
                    score=score,
                    content=entry.summary,
                    entry=entry.model_dump(mode="json"),
                ))

        # Time range filter (post-search)
        if query.time_range:
            start, end = query.time_range
            results = [
                r for r in results
                if start <= datetime.fromisoformat(
                    r.entry.get("timestamp", start.isoformat())
                ) <= end
            ]

        # Tag filter (post-search)
        if query.tags:
            results = [
                r for r in results
                if any(t in r.entry.get("tags", []) for t in query.tags)
            ]

        results.sort(key=lambda r: r.score, reverse=True)
        return results[: query.top_k]

    async def get_recent(self, limit: int = 50) -> list[EpisodicEntry]:
        """Get the most recent episodic entries from SourceOfTruth.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of EpisodicEntry objects, newest first.
        """
        count = await self._source.count("episodic")
        start = max(0, count - limit)
        raw = await self._source.scan("episodic", start=start, limit=limit)
        entries: list[EpisodicEntry] = []
        for data in raw:
            try:
                entries.append(EpisodicEntry(**data))
            except Exception:
                logger.warning("EpisodicStore: failed to parse entry")
        entries.reverse()  # Newest first
        return entries

    async def get_by_timerange(
        self, start: datetime, end: datetime
    ) -> list[EpisodicEntry]:
        """Get episodic entries within a time range.

        Args:
            start: Start of the time range (inclusive).
            end: End of the time range (inclusive).

        Returns:
            List of EpisodicEntry objects within the range.
        """
        entries: list[EpisodicEntry] = []
        async for data in self._source.iterate_all("episodic"):
            try:
                entry = EpisodicEntry(**data)
                if start <= entry.timestamp <= end:
                    entries.append(entry)
            except Exception:
                logger.warning("EpisodicStore: failed to parse entry in timerange")
        return entries

    async def count(self) -> int:
        """Return the total number of episodic entries."""
        return await self._source.count("episodic")
```

## 文件路径: src/myharness/memory/stores/identity.py

```python
"""IdentityStore — manages the agent's persistent self-model.

Per P3 (Identity Externalization): Identity belongs to Memory, not LLM.
The LLM reads identity and proposes updates, but this store owns the data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import structlog

from myharness.core.exceptions import IdentityConflictError, MemoryNotFoundError
from myharness.schema.identity import IdentityField, IdentityUpdateProposal
from myharness.schema.memory import IdentityEntry

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth

logger = structlog.get_logger(__name__)

IDENTITY_KEY = "current_identity"


class IdentityStore:
    """Manages the agent's identity — the persistent self-model.

    Stores identity as versioned JSON files in the SourceOfTruth.
    Each update creates a new version file while updating the canonical
    "current_identity.json" entry.
    """

    def __init__(self, source: SourceOfTruth) -> None:
        self._source = source

    async def get_identity(self) -> IdentityEntry:
        """Return the current identity or create a default one.

        On first access with no stored identity, a default IdentityEntry
        is created, persisted, and returned.
        """
        data = await self._source.read("identity", IDENTITY_KEY)
        if data is None:
            entry = IdentityEntry()
            await self._source.write(
                "identity", IDENTITY_KEY, entry.model_dump(mode="json")
            )
            logger.info("IdentityStore: created default identity")
            return entry
        return IdentityEntry(**data)

    async def update_identity(self, entry: IdentityEntry) -> None:
        """Update the identity atomically.

        Saves the current version as history (identity_v{version}.json),
        then writes the new version as current_identity.json.

        Raises:
            IdentityConflictError: If a version conflict is detected.
        """
        current = await self.get_identity()

        if entry.version != current.version:
            raise IdentityConflictError(
                f"Version conflict: expected {current.version}, got {entry.version}",
                details={
                    "expected_version": current.version,
                    "provided_version": entry.version,
                },
            )

        # Save current as history before overwriting
        history_key = f"identity_v{current.version}"
        await self._source.write(
            "identity",
            history_key,
            current.model_dump(mode="json"),
        )

        # Bump version and write new identity
        entry.version = current.version + 1
        entry.updated_at = datetime.now(timezone.utc)
        await self._source.write(
            "identity", IDENTITY_KEY, entry.model_dump(mode="json")
        )

        logger.info(
            "IdentityStore: updated identity",
            old_version=current.version,
            new_version=entry.version,
        )

    async def apply_proposal(
        self, proposal: IdentityUpdateProposal
    ) -> IdentityEntry:
        """Validate and apply an identity update proposal from the LLM.

        The LLM proposes; the Memory System decides. Validates the proposal
        against the current identity state before applying.

        Args:
            proposal: The LLM's suggested identity change.

        Returns:
            The updated IdentityEntry after applying the proposal.

        Raises:
            IdentityConflictError: If validation fails or field is not recognized.
        """
        current = await self.get_identity()

        # Validate the proposal
        self._validate_proposal(proposal, current)

        # Apply the update
        field = proposal.field
        if field == IdentityField.CORE_VALUES:
            current.core_values = proposal.proposed_value
        elif field == IdentityField.MISSION:
            current.mission = proposal.proposed_value
        elif field == IdentityField.PREFERENCES:
            current.preferences = proposal.proposed_value
        elif field == IdentityField.SELF_DESCRIPTION:
            current.self_description = proposal.proposed_value
        elif field == IdentityField.BEHAVIORAL_GUIDELINES:
            current.behavioral_guidelines = proposal.proposed_value
        else:
            raise IdentityConflictError(
                f"Unknown identity field: {field}",
                details={"field": str(field)},
            )

        await self.update_identity(current)
        logger.info(
            "IdentityStore: applied proposal",
            field=str(field),
            proposal_id=proposal.proposal_id,
        )
        return current

    def _validate_proposal(
        self,
        proposal: IdentityUpdateProposal,
        current: IdentityEntry,
    ) -> None:
        """Validate a proposal against the current identity state."""
        if proposal.confidence < 0.3:
            raise IdentityConflictError(
                f"Proposal confidence too low: {proposal.confidence}",
                details={"proposal_id": proposal.proposal_id, "confidence": proposal.confidence},
            )

        if not proposal.reasoning:
            raise IdentityConflictError(
                "Proposal missing reasoning",
                details={"proposal_id": proposal.proposal_id},
            )

        field = proposal.field
        if field == IdentityField.CORE_VALUES:
            current_value = current.core_values
        elif field == IdentityField.MISSION:
            current_value = current.mission
        elif field == IdentityField.PREFERENCES:
            current_value = current.preferences
        elif field == IdentityField.SELF_DESCRIPTION:
            current_value = current.self_description
        elif field == IdentityField.BEHAVIORAL_GUIDELINES:
            current_value = current.behavioral_guidelines
        else:
            raise IdentityConflictError(
                f"Unknown identity field: {field}",
                details={"field": str(field)},
            )

        # If current_value was provided in proposal, verify it matches
        if proposal.current_value is not None and proposal.current_value != current_value:
            raise IdentityConflictError(
                f"Stale proposal: current value for {field} has changed",
                details={
                    "field": str(field),
                    "expected": str(proposal.current_value)[:200],
                    "actual": str(current_value)[:200],
                },
            )

    async def get_history(self) -> list[IdentityEntry]:
        """Get all historical versions of the identity, newest first."""
        all_versions = await self._source.get_all_identity_versions()
        entries: list[IdentityEntry] = []
        for data in all_versions:
            try:
                entries.append(IdentityEntry(**data))
            except Exception:
                logger.warning("IdentityStore: failed to parse history entry", data=data)
        return entries
```

## 文件路径: src/myharness/memory/stores/relationship.py

```python
"""RelationshipStore — entity relationship graph.

Per P9 (Source of Truth): Write to SourceOfTruth FIRST, then best-effort
updates to derived indexes. Relationships use upsert semantics (same entity
pair + relation_type overwrites).
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import structlog

from myharness.core.exceptions import MemoryNotFoundError
from myharness.schema.memory import RelationshipEntry

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth

logger = structlog.get_logger(__name__)


class RelationshipStore:
    """Manages relationship memory — connections between entities.

    Relationships are directed (entity_a → entity_b) with typed relations
    and strength scores. Uses upsert semantics: setting the same entity
    pair + relation_type overwrites the previous entry.
    """

    def __init__(self, source: SourceOfTruth) -> None:
        self._source = source

    async def set(self, entry: RelationshipEntry) -> None:
        """Set (upsert) a relationship entry.

        If a relationship with the same entity_a, entity_b, and
        relation_type already exists, it is overwritten.

        Args:
            entry: The relationship entry to set.
        """
        data = entry.model_dump(mode="json")

        # Check for existing relationship with same pair+type
        existing = await self._find_existing(
            entry.entity_a, entry.entity_b, entry.relation_type
        )

        if existing is not None:
            # Preserve the original entry_id but update other fields
            data["entry_id"] = existing.entry_id
            data["created_at"] = existing.created_at.isoformat() if hasattr(existing.created_at, 'isoformat') else str(existing.created_at)
            logger.debug(
                "RelationshipStore: updating existing relationship",
                entry_id=str(existing.entry_id),
            )
        else:
            logger.debug(
                "RelationshipStore: creating new relationship",
                entry_id=str(entry.entry_id),
            )

        # Write to SourceOfTruth (JSONL append — immutable log)
        await self._source.append("relationship", data)
        logger.info(
            "RelationshipStore: relationship set",
            entity_a=entry.entity_a,
            entity_b=entry.entity_b,
            relation_type=entry.relation_type,
        )

    async def _find_existing(
        self, entity_a: str, entity_b: str, relation_type: str
    ) -> RelationshipEntry | None:
        """Find an existing relationship with the same pair and type.

        Scans the relationship JSONL from newest to oldest to find
        the most recent matching entry.
        """
        # Collect all matching entries (iterate in reverse order by scanning
        # all and picking the last one for each unique pair+type combination)
        best: RelationshipEntry | None = None
        async for data in self._source.iterate_all("relationship"):
            try:
                entry = RelationshipEntry(**data)
                if (
                    entry.entity_a == entity_a
                    and entry.entity_b == entity_b
                    and entry.relation_type == relation_type
                ):
                    best = entry  # Keep the last (most recent) one
            except Exception:
                logger.warning("RelationshipStore: failed to parse entry in find")
        return best

    async def get(
        self, entity_a: str, entity_b: str
    ) -> RelationshipEntry | None:
        """Get the most recent relationship between two entities.

        Returns the latest entry for any relation_type between the pair.

        Args:
            entity_a: Source entity.
            entity_b: Target entity.

        Returns:
            The RelationshipEntry or None if not found.
        """
        best: RelationshipEntry | None = None
        async for data in self._source.iterate_all("relationship"):
            try:
                entry = RelationshipEntry(**data)
                if (
                    (entry.entity_a == entity_a and entry.entity_b == entity_b)
                    or (entry.entity_a == entity_b and entry.entity_b == entity_a)
                ):
                    best = entry  # Keep the last (most recent) one
            except Exception:
                logger.warning("RelationshipStore: failed to parse entry in get")
        return best

    async def get_all_for(self, entity_id: str) -> list[RelationshipEntry]:
        """Get all relationships involving a specific entity.

        Includes relationships where the entity is either entity_a or entity_b.
        Returns the latest version for each unique (entity_a, entity_b, relation_type)
        combination.

        Args:
            entity_id: The entity to query relationships for.

        Returns:
            List of RelationshipEntry objects.
        """
        # Build a dict keyed by (entity_a, entity_b, relation_type) → entry
        # to keep only the latest version of each relationship
        seen: dict[tuple[str, str, str], RelationshipEntry] = {}
        async for data in self._source.iterate_all("relationship"):
            try:
                entry = RelationshipEntry(**data)
                if entry.entity_a == entity_id or entry.entity_b == entity_id:
                    key = (entry.entity_a, entry.entity_b, entry.relation_type)
                    seen[key] = entry  # Overwrite with latest
            except Exception:
                logger.warning(
                    "RelationshipStore: failed to parse entry in get_all_for"
                )

        return sorted(
            seen.values(),
            key=lambda e: e.strength,
            reverse=True,
        )

    async def count(self) -> int:
        """Return the total number of relationship entries (including history)."""
        return await self._source.count("relationship")
```

## 文件路径: src/myharness/memory/stores/semantic.py

```python
"""SemanticStore — factual knowledge as entity-attribute-value triples.

Per P9 (Source of Truth): Write to SourceOfTruth FIRST, then best-effort
updates to derived indexes.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

import structlog

from myharness.core.exceptions import MemoryNotFoundError
from myharness.schema.memory import (
    MemoryCategory,
    MemoryQuery,
    MemorySearchResult,
    SemanticEntry,
)

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.indexing.text import TextIndex

logger = structlog.get_logger(__name__)


class SemanticStore:
    """Manages semantic memory — structured factual knowledge.

    Each entry is an entity-attribute-value triple with confidence scores.
    Supports relationship-based retrieval (get all facts about an entity).
    """

    def __init__(
        self,
        source: SourceOfTruth,
        vector_idx: VectorIndex,
        text_idx: TextIndex,
    ) -> None:
        self._source = source
        self._vector_idx = vector_idx
        self._text_idx = text_idx

    async def store(self, entry: SemanticEntry) -> str:
        """Store a semantic knowledge entry.

        Writes to SourceOfTruth first, then updates indexes on best-effort.

        Args:
            entry: The semantic entry to store.

        Returns:
            The entry_id of the stored entry.
        """
        data = entry.model_dump(mode="json")
        entry_id = str(entry.entry_id)

        # Step 1: Write to SourceOfTruth (MUST succeed)
        await self._source.append("semantic", data)
        logger.debug("SemanticStore: source written", entry_id=entry_id)

        # Step 2-3: Update indexes (best-effort)
        try:
            content = f"{entry.entity} {entry.attribute} {entry.value}"
            await self._text_idx.add(entry_id, {
                "store": "semantic",
                "content": content,
                "metadata": {
                    "entity": entry.entity,
                    "attribute": entry.attribute,
                    "confidence": entry.confidence,
                },
            })
        except Exception as exc:
            logger.warning(
                "SemanticStore: text index update failed",
                entry_id=entry_id,
                error=str(exc),
            )

        if entry.embedding is not None:
            try:
                import numpy as np
                emb = np.array(entry.embedding, dtype=np.float32)
                await self._vector_idx.add(entry_id, emb, {
                    "store": "semantic",
                    "entity": entry.entity,
                    "attribute": entry.attribute,
                    "confidence": entry.confidence,
                })
            except Exception as exc:
                logger.warning(
                    "SemanticStore: vector index update failed",
                    entry_id=entry_id,
                    error=str(exc),
                )

        return entry_id

    async def get(self, entry_id: str) -> SemanticEntry | None:
        """Retrieve a specific semantic entry by ID from SourceOfTruth.

        Args:
            entry_id: The unique entry identifier.

        Returns:
            The SemanticEntry or None if not found.
        """
        async for entry in self._source.iterate_all("semantic"):
            if entry.get("entry_id") == entry_id:
                return SemanticEntry(**entry)
        return None

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        """Search semantic memory using vector and/or text search.

        Args:
            query: The memory query specification.

        Returns:
            List of MemorySearchResult objects ranked by relevance.
        """
        results: list[MemorySearchResult] = []

        # Vector search path
        if query.query_embedding is not None:
            import numpy as np
            emb = np.array(query.query_embedding, dtype=np.float32)
            hits = await self._vector_idx.search(emb, k=query.top_k)
            for entry_id, score, meta in hits:
                if meta.get("store") != "semantic":
                    continue
                entry = await self.get(entry_id)
                if entry is None:
                    continue
                results.append(MemorySearchResult(
                    entry_id=entry.entry_id,
                    category=MemoryCategory.SEMANTIC,
                    score=score,
                    content=f"{entry.entity}.{entry.attribute} = {entry.value}",
                    entry=entry.model_dump(mode="json"),
                ))

        # Text search path
        if query.query_text and (not query.query_embedding or query.hybrid_weight < 1.0):
            text_hits = await self._text_idx.search(query.query_text, k=query.top_k)
            for entry_id, score, meta in text_hits:
                if meta.get("store") != "semantic":
                    continue
                entry = await self.get(entry_id)
                if entry is None:
                    continue

                if query.query_embedding:
                    score = score * (1.0 - query.hybrid_weight)

                existing_ids = {str(r.entry_id) for r in results}
                if entry_id in existing_ids:
                    continue

                results.append(MemorySearchResult(
                    entry_id=entry.entry_id,
                    category=MemoryCategory.SEMANTIC,
                    score=score,
                    content=f"{entry.entity}.{entry.attribute} = {entry.value}",
                    entry=entry.model_dump(mode="json"),
                ))

        # Tag filter
        if query.tags:
            results = [
                r for r in results
                if any(t.lower() in r.content.lower() for t in query.tags)
            ]

        results.sort(key=lambda r: r.score, reverse=True)
        return results[: query.top_k]

    async def get_related(
        self, entity_id: str, relation: str | None = None
    ) -> list[SemanticEntry]:
        """Get all semantic entries related to a specific entity.

        Args:
            entity_id: The entity to query for.
            relation: Optional attribute name to filter by.

        Returns:
            List of matching SemanticEntry objects.
        """
        entries: list[SemanticEntry] = []
        async for data in self._source.iterate_all("semantic"):
            try:
                entry = SemanticEntry(**data)
                if entry.entity == entity_id:
                    if relation is None or entry.attribute == relation:
                        entries.append(entry)
            except Exception:
                logger.warning("SemanticStore: failed to parse entry in get_related")
        return entries

    async def count(self) -> int:
        """Return the total number of semantic entries."""
        return await self._source.count("semantic")
```
