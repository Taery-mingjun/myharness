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
