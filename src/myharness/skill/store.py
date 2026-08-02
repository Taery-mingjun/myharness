"""Persistent skill storage using JSON files (source of truth).

Implements the SkillStoreInterface with file-based persistence.
Skills are organized as:
    {skills_dir}/{name}/{version}.json
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from myharness.core.exceptions import (
    SkillError,
    SkillNotFoundError,
    SkillValidationError,
)
from myharness.schema.skill import SkillDefinition, SkillStatus
from myharness.skill.interface import SkillStoreInterface
from myharness.skill.lifecycle import SkillLifecycle
from myharness.skill.storage import SkillStorage
from myharness.skill.validator import SkillValidator

logger = structlog.get_logger(__name__)


class SkillStore(SkillStoreInterface):
    """Persistent skill storage using JSON files (source of truth).

    Implements all SkillStoreInterface methods with file-based persistence.
    Uses SkillStorage for low-level file I/O and SkillValidator for
    validation before persistence.
    """

    def __init__(self, skills_dir: Path) -> None:
        """Initialize the skill store.

        Args:
            skills_dir: Root directory for skill JSON files.
        """
        self._skills_dir = Path(skills_dir)
        self._storage = SkillStorage(self._skills_dir)
        logger.info("skill_store_initialized", skills_dir=str(self._skills_dir))

    async def register(self, skill: SkillDefinition) -> SkillDefinition:
        """Register a new skill definition.

        Validates the skill before persisting it to storage.

        Args:
            skill: The skill definition to register.

        Returns:
            The registered skill definition.

        Raises:
            SkillValidationError: If the skill fails validation.
            SkillError: If a skill with the same name and version already exists.
        """
        # Validate the skill
        errors = SkillValidator.validate(skill)
        if errors:
            raise SkillValidationError(
                f"Skill validation failed for '{skill.name}': {'; '.join(errors)}",
                code="SKILL_VALIDATION_ERROR",
                details={"name": skill.name, "errors": errors},
            )

        # Check for duplicates
        existing = await self._storage.load_by_name_version(
            skill.name, skill.version
        )
        if existing is not None:
            raise SkillError(
                f"Skill '{skill.name}' version '{skill.version}' already exists",
                code="SKILL_ALREADY_EXISTS",
                details={
                    "name": skill.name,
                    "version": skill.version,
                    "existing_skill_id": str(existing.skill_id),
                },
            )

        await self._storage.save(skill)
        # Newly registered version becomes the active one (rollback pointer).
        await self._storage.save_current(skill.name, skill.version)
        logger.info(
            "skill_registered",
            skill_id=str(skill.skill_id),
            name=skill.name,
            version=skill.version,
        )
        return skill

    async def get(self, skill_id: str) -> SkillDefinition | None:
        """Retrieve a skill by its unique identifier.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            The skill definition, or None if not found.
        """
        return await self._storage.load(skill_id)

    async def get_by_name(
        self, name: str, version: str | None = None
    ) -> SkillDefinition | None:
        """Retrieve a skill by name, optionally filtered by version.

        If version is None, returns the latest version.

        Args:
            name: The skill name.
            version: Optional semantic version to match.

        Returns:
            The skill definition, or None if not found.
        """
        if version is not None:
            return await self._storage.load_by_name_version(name, version)

        # Prefer the current-version pointer (rollback-aware), falling back
        # to the newest registered version when no pointer exists.
        current = await self._storage.load_current(name)
        if current is not None:
            skill = await self._storage.load_by_name_version(name, current)
            if skill is not None:
                return skill

        # Get latest version
        versions = await self._storage.list_versions(name)
        if not versions:
            return None
        return await self._storage.load_by_name_version(name, versions[0])

    async def list_all(self) -> list[SkillDefinition]:
        """List all registered skill definitions.

        Returns:
            A list of all skill definitions.
        """
        return await self._storage.list_all()

    async def list_by_capability(self, capability: str) -> list[SkillDefinition]:
        """List skills that provide a specific capability.

        Args:
            capability: The capability name to filter by (case-insensitive).

        Returns:
            A list of matching skill definitions.
        """
        all_skills = await self._storage.list_all()
        query = capability.lower()
        return [
            s for s in all_skills
            if query in s.capability.lower()
        ]

    async def list_by_status(self, status: SkillStatus) -> list[SkillDefinition]:
        """List skills filtered by lifecycle status.

        Args:
            status: The skill status to filter by.

        Returns:
            A list of skills with the given status.
        """
        all_skills = await self._storage.list_all()
        return [s for s in all_skills if s.status == status]

    async def search(self, query: str, top_k: int = 10) -> list[SkillDefinition]:
        """Search skills by text matching on name and description.

        Uses simple case-insensitive substring matching. Results are
        ranked by relevance: exact name match > name contains > description
        contains. Within each tier, higher confidence ranks higher.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            A list of matching skill definitions, ranked by relevance.
        """
        all_skills = await self._storage.list_all()
        query_lower = query.lower()

        if not query_lower:
            return sorted(
                all_skills,
                key=lambda s: s.confidence,
                reverse=True,
            )[:top_k]

        # Scoring: name match = 100, description match = 50, tag match = 30
        scored: list[tuple[int, SkillDefinition]] = []
        for skill in all_skills:
            score = 0
            name_lower = skill.name.lower()
            if name_lower == query_lower:
                score = 100
            elif query_lower in name_lower:
                score = 80
            if query_lower in skill.description.lower():
                score += 50
            for tag in skill.tags:
                if query_lower in tag.lower():
                    score += 30
            if score > 0:
                scored.append((score, skill))

        # Sort by score descending, then by confidence descending
        scored.sort(key=lambda x: (x[0], x[1].confidence), reverse=True)
        return [s[1] for s in scored[:top_k]]

    async def update(self, skill: SkillDefinition) -> SkillDefinition:
        """Update an existing skill definition.

        Args:
            skill: The skill definition with updated fields.

        Returns:
            The updated skill definition.

        Raises:
            SkillNotFoundError: If the skill does not exist.
            SkillValidationError: If the updated skill fails validation.
        """
        existing = await self._storage.load(str(skill.skill_id))
        if existing is None:
            raise SkillNotFoundError(
                f"Skill not found: {skill.skill_id}",
                code="SKILL_NOT_FOUND",
                details={"skill_id": str(skill.skill_id)},
            )

        # Validate the updated skill
        errors = SkillValidator.validate(skill)
        if errors:
            raise SkillValidationError(
                f"Skill validation failed for '{skill.name}': {'; '.join(errors)}",
                code="SKILL_VALIDATION_ERROR",
                details={"name": skill.name, "errors": errors},
            )

        await self._storage.save(skill)
        logger.info(
            "skill_updated",
            skill_id=str(skill.skill_id),
            name=skill.name,
            version=skill.version,
        )
        return skill

    async def change_status(
        self, skill_id: str, new_status: SkillStatus, reason: str = ""
    ) -> SkillDefinition:
        """Change the lifecycle status of a skill.

        Uses SkillLifecycle to validate and record the transition.

        Args:
            skill_id: The skill identifier.
            new_status: The target lifecycle status.
            reason: The reason for the status change.

        Returns:
            The updated skill definition.

        Raises:
            SkillNotFoundError: If the skill does not exist.
            SkillLifecycleError: If the transition is invalid.
        """
        skill = await self._storage.load(skill_id)
        if skill is None:
            raise SkillNotFoundError(
                f"Skill not found: {skill_id}",
                code="SKILL_NOT_FOUND",
                details={"skill_id": skill_id},
            )

        updated = SkillLifecycle.transition(skill, new_status, reason)
        await self._storage.save(updated)
        return updated

    async def deprecate(self, skill_id: str, reason: str) -> SkillDefinition:
        """Deprecate a skill, marking it as no longer recommended.

        Args:
            skill_id: The skill identifier.
            reason: The reason for deprecation.

        Returns:
            The updated skill definition.
        """
        return await self.change_status(skill_id, SkillStatus.DEPRECATED, reason)

    async def archive(self, skill_id: str) -> SkillDefinition:
        """Archive a skill, moving it to a terminal state.

        Args:
            skill_id: The skill identifier.

        Returns:
            The updated skill definition.

        Raises:
            SkillLifecycleError: If the skill cannot be archived from
                its current status (only DEPRECATED can be archived).
        """
        return await self.change_status(
            skill_id, SkillStatus.ARCHIVED, "Archived"
        )

    async def get_version_history(self, name: str) -> list[SkillDefinition]:
        """Get all versions of a skill, ordered newest first.

        Args:
            name: The skill name.

        Returns:
            A list of all versions of the skill.
        """
        versions = await self._storage.list_versions(name)
        skills: list[SkillDefinition] = []
        for version in versions:
            skill = await self._storage.load_by_name_version(name, version)
            if skill is not None:
                skills.append(skill)
        return skills

    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics about the skill store.

        Returns:
            A dictionary with keys:
                - total_skills: Total number of skill definitions.
                - by_status: Count of skills per lifecycle status.
                - by_driver_type: Count of skills per driver type.
                - total_usage: Sum of all usage counts.
                - avg_confidence: Average confidence across all skills.
        """
        all_skills = await self._storage.list_all()

        by_status: dict[str, int] = {}
        by_driver_type: dict[str, int] = {}
        total_usage = 0
        total_confidence = 0.0

        for skill in all_skills:
            status_key = skill.status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1

            driver_key = skill.driver_type or "unknown"
            by_driver_type[driver_key] = by_driver_type.get(driver_key, 0) + 1

            total_usage += skill.usage_count
            total_confidence += skill.confidence

        return {
            "total_skills": len(all_skills),
            "by_status": by_status,
            "by_driver_type": by_driver_type,
            "total_usage": total_usage,
            "avg_confidence": (
                total_confidence / len(all_skills) if all_skills else 0.0
            ),
        }

    async def rollback_to_stable(
        self,
        skill_name: str,
        target_version: str | None = None,
    ) -> bool:
        """Roll a skill back to a previous stable version (self-healing).

        Points the current-version pointer at the target version so that
        ``get_by_name(name)`` resolves there. When ``target_version`` is
        None, the newest version whose status is STABLE is chosen.

        Args:
            skill_name: The skill name to roll back.
            target_version: Explicit version to roll back to. When None,
                the newest STABLE-status version is used.

        Returns:
            True if the pointer was moved, False if no suitable version
            exists (nothing to roll back to).
        """
        if target_version is not None:
            skill = await self._storage.load_by_name_version(
                skill_name, target_version
            )
            if skill is None:
                logger.warning(
                    "rollback_target_missing",
                    skill_name=skill_name,
                    target_version=target_version,
                )
                return False
            await self._storage.save_current(skill_name, target_version)
            logger.info(
                "skill_rolled_back",
                skill_name=skill_name,
                target_version=target_version,
            )
            return True

        # No explicit target: newest version in STABLE status.
        versions = await self._storage.list_versions(skill_name)
        for version in versions:
            skill = await self._storage.load_by_name_version(skill_name, version)
            if skill is not None and skill.status == SkillStatus.STABLE:
                await self._storage.save_current(skill_name, version)
                logger.info(
                    "skill_rolled_back",
                    skill_name=skill_name,
                    target_version=version,
                )
                return True

        logger.warning(
            "no_stable_version_for_rollback",
            skill_name=skill_name,
        )
        return False
