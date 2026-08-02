"""Skill data models — executable capability templates.

Skills are compiled from experience (P5: Skill Accumulation) and stored
as versioned, parameterized action templates. They have no thinking
capability — only execution templates.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from myharness.core.types import SkillId


# ── Skill Lifecycle States ─────────────────────────────────────────────


class SkillStatus(StrEnum):
    """Skill lifecycle states per Section 5.2 of the architecture spec."""

    DRAFT = "draft"
    TESTING = "testing"
    VERIFIED = "verified"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


# ── Valid Transitions ──────────────────────────────────────────────────

SKILL_LIFECYCLE_TRANSITIONS: dict[SkillStatus, set[SkillStatus]] = {
    SkillStatus.DRAFT: {SkillStatus.TESTING, SkillStatus.ARCHIVED},
    SkillStatus.TESTING: {SkillStatus.VERIFIED, SkillStatus.DRAFT},
    SkillStatus.VERIFIED: {SkillStatus.STABLE, SkillStatus.TESTING},
    SkillStatus.STABLE: {SkillStatus.DEPRECATED},
    SkillStatus.DEPRECATED: {SkillStatus.STABLE, SkillStatus.ARCHIVED},
    SkillStatus.ARCHIVED: set(),  # Terminal state
}


class SkillLifecycleTransition(BaseModel):
    """Records a lifecycle state change for audit trail."""

    from_status: SkillStatus
    to_status: SkillStatus
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    triggered_by: str = "system"

    @model_validator(mode="after")
    def _validate_transition(self) -> "SkillLifecycleTransition":
        allowed = SKILL_LIFECYCLE_TRANSITIONS.get(self.from_status, set())
        if self.to_status not in allowed:
            raise ValueError(
                f"Invalid lifecycle transition: {self.from_status} → {self.to_status}. "
                f"Allowed: {allowed}"
            )
        return self


# ── Skill Parameter ────────────────────────────────────────────────────


class SkillParameter(BaseModel):
    """A single parameter for a skill — defines what the skill accepts."""

    name: str = Field(..., min_length=1, description="Parameter name")
    type: str = Field(default="string", description="Expected type: string, int, float, bool, array, object")
    description: str = Field(default="", description="What this parameter controls")
    required: bool = Field(default=True)
    default: Any = Field(default=None)
    enum_values: list[Any] | None = Field(default=None, description="Allowed values if constrained")
    validation: str | None = Field(
        default=None,
        description="Validation rule expression or regex pattern",
    )


# ── Skill Definition ───────────────────────────────────────────────────


class SkillDefinition(BaseModel):
    """A complete skill — the executable capability template.

    Per Section 5.1: Name, Version, Input, Output, Parameters, Boundary,
    Capability, Confidence.

    Per P5: Skills are the result of the Learning process, not the process itself.
    """

    skill_id: SkillId = Field(default_factory=lambda: SkillId(str(uuid.uuid4())))
    name: str = Field(..., min_length=1, description="Unique skill name (e.g., 'walk', 'grab')")
    version: str = Field(default="0.1.0", description="Semantic version")
    description: str = Field(default="", description="What this skill does")

    status: SkillStatus = Field(default=SkillStatus.DRAFT)

    # I/O schemas
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    # Parameters
    parameters: list[SkillParameter] = Field(default_factory=list)

    # Capability descriptor
    capability: str = Field(default="", description="High-level capability name")

    # Constraints
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    # Execution binding
    driver_type: str = Field(
        default="api",
        description="Target driver: robot, browser, api, mcp, computer, database, iot",
    )
    action_template: dict[str, Any] = Field(
        default_factory=dict,
        description="The actual execution template — driver-specific action definition",
    )
    allowed_actions: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit allowlist of driver actions this skill may invoke. "
            "Empty means the allowlist is derived from action_template "
            "(see resolve_allowed_actions). Use ['*'] to deliberately grant "
            "the skill unrestricted access to its driver."
        ),
    )

    # Runtime config
    timeout_seconds: float = Field(default=60.0, ge=0.0)
    retry_policy: dict[str, Any] = Field(
        default_factory=lambda: {"max_retries": 3, "backoff": "exponential"},
    )

    # Metrics
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Estimated reliability")
    usage_count: int = Field(default=0, ge=0)

    # Metadata
    author: str = Field(default="system")
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Provenance — where this skill came from
    compiled_from: list[str] = Field(
        default_factory=list,
        description="Episode IDs or experience references that produced this skill",
    )
    parent_skill_id: SkillId | None = Field(
        default=None,
        description="Parent skill if this is a specialization or variant",
    )

    # Lifecycle history
    lifecycle_history: list[SkillLifecycleTransition] = Field(default_factory=list)

    model_config = {"json_schema_extra": {"source_of_truth": True}}

    def permits_action(self, action: str) -> bool:
        """Whether this skill authorises ``action`` on its driver.

        The execution layer resolves a skill to a ``driver_type`` and then
        asks the driver to perform an action. Without this check the skill
        is only a pointer to a driver, and any action string that reaches
        the executor — including one produced by a prompt-injected plan —
        runs with the skill's privileges.
        """
        return action_is_permitted(self, action)


def resolve_allowed_actions(skill: Any) -> set[str]:
    """Resolve the set of driver actions a skill definition authorises.

    Accepts any skill-shaped object (not just :class:`SkillDefinition`) so
    the execution guard can evaluate duck-typed skills without silently
    waving them through.

    Resolution order, first match wins:

    1. ``allowed_actions`` — the explicit operator-authored allowlist.
    2. ``action_template["actions"]`` — a template listing several actions.
    3. ``action_template["action"]`` — the single templated action.
    4. ``{skill.name}`` — a skill named ``walk`` may perform ``walk``.

    Step 4 is the conservative default: it keeps skills that predate the
    allowlist working for their own action while still refusing every
    other action on the driver.
    """
    explicit = getattr(skill, "allowed_actions", None) or []
    if isinstance(explicit, (list, tuple, set)):
        names = {str(a).strip() for a in explicit if str(a).strip()}
        if names:
            return names

    template = getattr(skill, "action_template", None) or {}
    if isinstance(template, dict):
        listed = template.get("actions")
        if isinstance(listed, (list, tuple, set)):
            names = {str(a).strip() for a in listed if str(a).strip()}
            if names:
                return names

        single = template.get("action")
        if isinstance(single, str) and single.strip():
            return {single.strip()}

    name = str(getattr(skill, "name", "") or "").strip()
    return {name} if name else set()


def action_is_permitted(skill: Any, action: str) -> bool:
    """Check ``action`` against a skill's resolved allowlist.

    An empty action is never permitted — an unnamed action carries no
    intent to authorise.
    """
    if not isinstance(action, str) or not action.strip():
        return False

    allowed = resolve_allowed_actions(skill)
    return "*" in allowed or action.strip() in allowed


# ── Skill Proposal (from LLM Reflection → Compile) ────────────────────


class SkillProposal(BaseModel):
    """A proposal from the LLM to create or update a skill.

    Generated during Compile() from reflection insights.
    """

    suggested_name: str = Field(..., min_length=1)
    description: str = Field(default="")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    driver_type: str = Field(default="api")
    action_template: dict[str, Any] = Field(default_factory=dict)
    allowed_actions: list[str] = Field(
        default_factory=list,
        description="Driver actions the proposed skill should be allowed to invoke",
    )
    compiled_from: list[str] = Field(default_factory=list)
    reasoning: str = Field(
        default="",
        description="Why this skill should be created — the reflection insight",
    )
    confidence_estimate: float = Field(default=0.5, ge=0.0, le=1.0)
