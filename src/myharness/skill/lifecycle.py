"""Skill lifecycle state machine.

Manages valid status transitions for skill definitions through their
lifecycle: DRAFT → TESTING → VERIFIED → STABLE → DEPRECATED → ARCHIVED.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from myharness.core.exceptions import SkillLifecycleError, SkillNotFoundError
from myharness.schema.skill import (
    SkillDefinition,
    SkillLifecycleTransition,
    SkillStatus,
)

logger = structlog.get_logger(__name__)


class SkillLifecycle:
    """State machine for skill status transitions.

    Controls the valid lifecycle paths for skills. Each transition is
    recorded in the skill's lifecycle_history for audit purposes.

    Valid transitions:
        DRAFT      → TESTING
        TESTING    → DRAFT, VERIFIED
        VERIFIED   → STABLE, DRAFT
        STABLE     → DEPRECATED
        DEPRECATED → STABLE, ARCHIVED
        ARCHIVED   → (terminal — no transitions)
    """

    TRANSITIONS: dict[SkillStatus, list[SkillStatus]] = {
        SkillStatus.DRAFT: [SkillStatus.TESTING],
        SkillStatus.TESTING: [SkillStatus.DRAFT, SkillStatus.VERIFIED],
        SkillStatus.VERIFIED: [SkillStatus.STABLE, SkillStatus.DRAFT],
        SkillStatus.STABLE: [SkillStatus.DEPRECATED],
        SkillStatus.DEPRECATED: [SkillStatus.STABLE, SkillStatus.ARCHIVED],
        SkillStatus.ARCHIVED: [],
    }

    @classmethod
    def can_transition(
        cls, from_status: SkillStatus, to_status: SkillStatus
    ) -> bool:
        """Check if a lifecycle transition is allowed.

        Args:
            from_status: The current skill status.
            to_status: The desired target status.

        Returns:
            True if the transition is valid, False otherwise.
        """
        allowed = cls.TRANSITIONS.get(from_status, [])
        return to_status in allowed

    @classmethod
    def transition(
        cls,
        skill: SkillDefinition,
        to_status: SkillStatus,
        reason: str = "",
        triggered_by: str = "system",
    ) -> SkillDefinition:
        """Transition a skill to a new lifecycle status.

        Records the transition in the skill's lifecycle_history and updates
        the updated_at timestamp.

        Args:
            skill: The skill definition to transition.
            to_status: The target lifecycle status.
            reason: Human-readable reason for the transition.
            triggered_by: Identifier of who/what triggered the transition.

        Returns:
            The skill definition with updated status and history.

        Raises:
            SkillLifecycleError: If the transition is not allowed.
        """
        if skill is None:
            raise SkillNotFoundError(
                "Cannot transition None skill",
                code="SKILL_NOT_FOUND",
            )

        if not cls.can_transition(skill.status, to_status):
            allowed = cls.TRANSITIONS.get(skill.status, [])
            raise SkillLifecycleError(
                f"Invalid lifecycle transition: {skill.status.value} → "
                f"{to_status.value}. Allowed transitions: "
                f"{[s.value for s in allowed]}",
                code="SKILL_LIFECYCLE_INVALID",
                details={
                    "skill_id": str(skill.skill_id),
                    "name": skill.name,
                    "from_status": skill.status.value,
                    "to_status": to_status.value,
                },
            )

        transition_record = SkillLifecycleTransition(
            from_status=skill.status,
            to_status=to_status,
            reason=reason,
            timestamp=datetime.now(UTC),
            triggered_by=triggered_by,
        )

        skill.status = to_status
        skill.lifecycle_history.append(transition_record)
        skill.updated_at = datetime.now(UTC)

        logger.info(
            "skill_lifecycle_transition",
            skill_id=str(skill.skill_id),
            name=skill.name,
            from_status=transition_record.from_status.value,
            to_status=to_status.value,
            reason=reason,
        )

        return skill
