"""Driver protocol models — execution layer abstractions.

Implements P7 (Protocol over Implementation): MyHarness defines a
unified driver protocol that abstracts away hardware/platform details.
Upper layers (LLM, Skill) never know about specific driver implementations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from myharness.core.types import DriverId


# ── Execution Result ───────────────────────────────────────────────────


class ExecutionResult(BaseModel):
    """The result of a driver action execution."""

    success: bool = Field(..., description="Whether the action completed successfully")
    output: Any = Field(default=None, description="Action output data")
    error: str | None = Field(default=None, description="Error message if failed")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Execution wall-clock time")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Driver-specific metadata (e.g., request_id, endpoint)",
    )


# ── Execution Progress ─────────────────────────────────────────────────


class ExecutionProgress(BaseModel):
    """Progress update during a long-running action."""

    action: str = Field(..., description="The action being executed")
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    status: str = Field(default="running", description="Status: running, waiting, finalizing")
    message: str = Field(default="", description="Human-readable progress message")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Driver Status ──────────────────────────────────────────────────────


class DriverStatus(BaseModel):
    """Health and status of an execution driver."""

    connected: bool = Field(default=False)
    capabilities_count: int = Field(default=0, ge=0)
    last_heartbeat: datetime | None = Field(default=None)
    version: str = Field(default="0.1.0")
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Driver Info ────────────────────────────────────────────────────────


class DriverInfo(BaseModel):
    """Static information about a registered driver."""

    driver_id: DriverId
    name: str = Field(..., min_length=1)
    driver_type: str = Field(..., description="robot, browser, api, mcp, computer, database, iot")
    version: str = Field(default="0.1.0")
    description: str = Field(default="")
    status: DriverStatus = Field(default_factory=DriverStatus)
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
