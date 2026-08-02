"""Capability descriptor models — what drivers and skills can do.

Capabilities are discovered (not declared) by the Harness Layer and
stored in the Capability Registry. Each capability maps to one or more
concrete actions on a specific driver.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# ── Capability Action ──────────────────────────────────────────────────


class CapabilityAction(BaseModel):
    """A single action within a capability — the atomic unit of execution."""

    name: str = Field(..., min_length=1, description="Action name, e.g., 'click', 'move_joint'")
    description: str = Field(default="")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Expected parameters schema for this action",
    )
    returns: str = Field(default="any", description="Expected return type")
    is_async: bool = Field(default=True, description="Whether the action supports async execution")


# ── Capability Descriptor ──────────────────────────────────────────────


class CapabilityDescriptor(BaseModel):
    """A registered capability — what a driver or skill can do.

    Capabilities are the bridge between the Harness Layer's abstract
    action model and concrete driver implementations.
    """

    capability_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, description="Human-readable capability name")
    description: str = Field(default="")
    driver_name: str = Field(
        ...,
        description="The driver that provides this capability",
    )
    actions: list[CapabilityAction] = Field(
        default_factory=list,
        description="The concrete actions this capability supports",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Global parameters for the capability",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Constraints: rate limits, permissions, preconditions",
    )
    version: str = Field(default="0.1.0")
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"json_schema_extra": {"source_of_truth": False}}
