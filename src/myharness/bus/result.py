"""Event processing result envelope.

Provides a structured, typed wrapper for results from event processing,
aggregating success/failure status, results, errors, and timing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

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
