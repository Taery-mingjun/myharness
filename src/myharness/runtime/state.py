"""Runtime state model — observable and introspectable.

The RuntimeState tracks the current execution state of the cognitive
system. It is observable by monitoring tools and introspection APIs
for debugging and observability.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RuntimeState(BaseModel):
    """Current runtime state — observable, introspectable.

    Tracks the live state of the cognitive system including the
    current plan, active skills, pending events, cognitive load,
    and runtime metrics.

    This model is designed to be serializable for monitoring and
    debugging purposes. All fields are optional with sensible defaults
    so the state can be partially populated during startup.
    """

    current_plan: dict | None = Field(
        default=None,
        description="The currently executing plan, if any",
    )
    active_skills: dict[str, Any] = Field(
        default_factory=dict,
        description="Currently loaded/active skill instances",
    )
    pending_events: int = Field(
        default=0,
        ge=0,
        description="Number of unprocessed events in the queue",
    )
    cognitive_load: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Estimated cognitive load (0.0 to 1.0)",
    )
    last_think_timestamp: float = Field(
        default=0.0,
        description="Unix timestamp of the last Think() operation",
    )
    uptime_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="System uptime in seconds",
    )
    error_count: int = Field(
        default=0,
        ge=0,
        description="Event fetch/dispatch failures since the loop started",
    )
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Aggregated runtime metrics",
    )
    is_running: bool = Field(
        default=False,
        description="Whether the runtime is actively processing",
    )

    model_config = {
        # Validate on assignment as well. This object is mutated field by
        # field while the loop runs, so without this the declared bounds
        # (ge/le) would only ever apply at construction — a negative queue
        # depth or an out-of-range cognitive load would slip silently into
        # whatever monitoring reads this state.
        "validate_assignment": True,
        "json_schema_extra": {
            "observable": True,
            "introspectable": True,
        },
    }
