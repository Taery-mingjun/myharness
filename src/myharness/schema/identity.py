"""Identity data models — the agent's canonical self-definition.

Per P0 (LLM ≠ Identity Container) and P3 (Identity Externalization):
Identity is a data asset owned by the Memory System. The LLM reads
identity via IdentityInterpretation and proposes updates via
IdentityUpdateProposal — but never directly owns or mutates identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from myharness.core.types import MemoryId


# ── Identity Fields ────────────────────────────────────────────────────


class IdentityField(StrEnum):
    """Addressable fields of the Identity model — used for targeted updates."""

    CORE_VALUES = "core_values"
    MISSION = "mission"
    PREFERENCES = "preferences"
    SELF_DESCRIPTION = "self_description"
    BEHAVIORAL_GUIDELINES = "behavioral_guidelines"


# ── Identity Model ─────────────────────────────────────────────────────


class Identity(BaseModel):
    """The agent's canonical identity — the persistent "self".

    This is the single source of truth for who the agent is. It lives in
    the Memory System and survives LLM provider switches (P8).

    The identity_id serves as both the MemoryId and the versioned identity
    reference. Version increments on any mutation.
    """

    identity_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    version: int = Field(default=1, ge=1, description="Monotonic version — incremented on each update")
    name: str = Field(default="Jarvis", description="The agent's name/callsign")
    core_values: list[str] = Field(
        default_factory=list,
        description="Immutable-ish values: e.g., ['safety', 'honesty', 'helpfulness']",
    )
    mission: str = Field(
        default="",
        description="The agent's purpose — why it exists",
    )
    preferences: dict[str, Any] = Field(
        default_factory=dict,
        description="Learned behavioral preferences and defaults",
    )
    self_description: str = Field(
        default="",
        description="The agent's understanding of its own nature, capabilities, and limitations",
    )
    behavioral_guidelines: list[str] = Field(
        default_factory=list,
        description="Explicit rules and constraints governing behavior",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def bump_version(self) -> None:
        """Increment version and update timestamp on mutation."""
        self.version += 1
        self.updated_at = datetime.now(timezone.utc)

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Identity Update Proposal ───────────────────────────────────────────


class IdentityUpdateProposal(BaseModel):
    """A proposal from the LLM Engine to modify identity.

    The LLM proposes; the Memory System decides (validates, applies, or rejects).
    This enforces P3: Identity belongs to Memory, not LLM.
    """

    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    field: IdentityField = Field(..., description="Which identity field to update")
    current_value: Any = Field(default=None, description="Current value (for validation)")
    proposed_value: Any = Field(..., description="The suggested new value")
    reasoning: str = Field(
        ...,
        min_length=1,
        description="Why this change is proposed — must cite specific experiences",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    experiences_cited: list[str] = Field(
        default_factory=list,
        description="Episode IDs that support this proposal",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
