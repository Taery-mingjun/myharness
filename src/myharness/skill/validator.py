"""Skill definition validation.

Validates skill definitions and proposals against the schema requirements
before they are persisted or executed.
"""

from __future__ import annotations

import structlog

from myharness.schema.skill import (
    SkillDefinition,
    SkillProposal,
    SkillStatus,
)

logger = structlog.get_logger(__name__)


class SkillValidator:
    """Validates skill definitions and proposals.

    All methods are static — validation is a pure function with no side effects.
    """

    @staticmethod
    def validate(skill: SkillDefinition) -> list[str]:
        """Validate a skill definition.

        Checks structural integrity, required fields, parameter types,
        and logical consistency.

        Args:
            skill: The skill definition to validate.

        Returns:
            A list of validation error messages. Empty list means valid.
        """
        errors: list[str] = []

        # Required fields
        if not skill.name or not skill.name.strip():
            errors.append("Skill name is required and must not be empty")
        elif len(skill.name) > 128:
            errors.append(f"Skill name exceeds 128 characters: '{skill.name}'")

        if not skill.version:
            errors.append("Skill version is required")
        elif not SkillValidator._is_valid_semver(skill.version):
            errors.append(f"Invalid semver format: '{skill.version}'")

        # Status must be a valid enum value
        if skill.status not in SkillStatus:
            errors.append(f"Invalid skill status: '{skill.status}'")

        # Capability should be specified for non-draft skills
        if skill.status != SkillStatus.DRAFT and not skill.capability:
            errors.append(
                f"Skill '{skill.name}' in status '{skill.status}' "
                "must have a capability defined"
            )

        # Validate parameters
        param_names: set[str] = set()
        for param in skill.parameters:
            if not param.name:
                errors.append("Skill parameter has empty name")
                continue
            if param.name in param_names:
                errors.append(f"Duplicate parameter name: '{param.name}'")
            param_names.add(param.name)

            valid_types = {"string", "int", "float", "bool", "array", "object"}
            if param.type not in valid_types:
                errors.append(
                    f"Parameter '{param.name}' has invalid type '{param.type}'. "
                    f"Must be one of: {valid_types}"
                )

            if param.required and param.default is not None:
                logger.debug(
                    "required_param_with_default",
                    skill_name=skill.name,
                    param_name=param.name,
                )

        # Confidence must be in range
        if not 0.0 <= skill.confidence <= 1.0:
            errors.append(
                f"Confidence must be between 0.0 and 1.0, got {skill.confidence}"
            )

        # Timeout must be non-negative
        if skill.timeout_seconds < 0:
            errors.append(
                f"Timeout must be non-negative, got {skill.timeout_seconds}"
            )

        # Driver type must be a known value
        known_drivers = {
            "api", "browser", "database", "robot",
            "mcp", "computer", "iot",
        }
        if skill.driver_type and skill.driver_type not in known_drivers:
            errors.append(
                f"Unknown driver type '{skill.driver_type}'. "
                f"Must be one of: {known_drivers}"
            )

        # Action template should not be empty for verified/stable skills
        if skill.status in {SkillStatus.VERIFIED, SkillStatus.STABLE}:
            if not skill.action_template:
                errors.append(
                    f"Skill '{skill.name}' is {skill.status.value} but has "
                    "no action template defined"
                )

        errors.extend(SkillValidator._validate_action_boundary(skill))

        return errors

    @staticmethod
    def _validate_action_boundary(skill: SkillDefinition) -> list[str]:
        """Validate the skill's declared driver-action boundary.

        The boundary is what stops a skill from becoming a general-purpose
        handle to its driver, so an incoherent one is a real defect rather
        than a style issue — most importantly a skill whose own templated
        action sits outside its allowlist, which can never execute.
        """
        errors: list[str] = []
        declared = skill.allowed_actions or []

        seen: set[str] = set()
        for entry in declared:
            if not isinstance(entry, str) or not entry.strip():
                errors.append(
                    f"Skill '{skill.name}' has an empty entry in allowed_actions"
                )
                continue
            name = entry.strip()
            if name in seen:
                errors.append(
                    f"Skill '{skill.name}' lists action '{name}' twice in "
                    "allowed_actions"
                )
            seen.add(name)

        if "*" in seen and len(seen) > 1:
            errors.append(
                f"Skill '{skill.name}' combines the '*' wildcard with named "
                f"actions {sorted(seen - {'*'})}; the wildcard already grants "
                "them, so the narrower entries are misleading"
            )

        # A skill whose template action is outside its own allowlist can
        # never run its template — the boundary would reject it at dispatch.
        template = skill.action_template or {}
        templated = template.get("action") if isinstance(template, dict) else None
        if (
            seen
            and "*" not in seen
            and isinstance(templated, str)
            and templated.strip()
            and templated.strip() not in seen
        ):
            errors.append(
                f"Skill '{skill.name}' templates action '{templated.strip()}' "
                f"but its allowed_actions are {sorted(seen)}; the skill could "
                "never execute its own template"
            )

        return errors

    @staticmethod
    def validate_proposal(proposal: SkillProposal) -> list[str]:
        """Validate a skill proposal.

        Args:
            proposal: The skill proposal to validate.

        Returns:
            A list of validation error messages. Empty list means valid.
        """
        errors: list[str] = []

        if not proposal.suggested_name or not proposal.suggested_name.strip():
            errors.append("Proposal must have a suggested name")
        elif len(proposal.suggested_name) > 128:
            errors.append(
                f"Proposal name exceeds 128 characters: '{proposal.suggested_name}'"
            )

        if not proposal.description:
            errors.append("Proposal should have a description")

        known_drivers = {
            "api", "browser", "database", "robot",
            "mcp", "computer", "iot",
        }
        if proposal.driver_type not in known_drivers:
            errors.append(
                f"Unknown driver type '{proposal.driver_type}'. "
                f"Must be one of: {known_drivers}"
            )

        if not 0.0 <= proposal.confidence_estimate <= 1.0:
            errors.append(
                f"Confidence estimate must be between 0.0 and 1.0, "
                f"got {proposal.confidence_estimate}"
            )

        if not proposal.reasoning:
            errors.append("Proposal must include reasoning for why the skill should be created")

        return errors

    @staticmethod
    def _is_valid_semver(version: str) -> bool:
        """Check if a version string follows semantic versioning."""
        parts = version.split(".")
        if len(parts) != 3:
            return False
        for part in parts:
            if not part.isdigit():
                return False
        return True
