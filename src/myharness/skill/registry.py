"""Skill discovery and matching.

The SkillRegistry finds the best skill for a given requirement by matching
capabilities and ranking by status, confidence, and usage.
"""

from __future__ import annotations

from typing import Any

import structlog

from myharness.schema.skill import SkillDefinition, SkillStatus
from myharness.skill.store import SkillStore

logger = structlog.get_logger(__name__)

# Status priority: higher = preferred
_STATUS_PRIORITY: dict[SkillStatus, int] = {
    SkillStatus.STABLE: 100,
    SkillStatus.VERIFIED: 80,
    SkillStatus.TESTING: 60,
    SkillStatus.DRAFT: 40,
    SkillStatus.DEPRECATED: 20,
    SkillStatus.ARCHIVED: 0,
}


class SkillRegistry:
    """Skill discovery and matching.

    Finds the best skill for a given requirement by matching capabilities
    and ranking candidates by status priority, confidence, and usage count.

    Prefers STABLE > VERIFIED > TESTING > DRAFT. ARCHIVED and DEPRECATED
    skills are excluded from matching by default.
    """

    def __init__(self, store: SkillStore) -> None:
        """Initialize the skill registry.

        Args:
            store: The skill store to query for skills.
        """
        self._store = store

    async def find_best_match(
        self,
        capability: str,
        requirements: dict | None = None,
    ) -> SkillDefinition | None:
        """Find the best matching skill for a given requirement.

        Ranking criteria (in order):
        1. Status priority (STABLE > VERIFIED > TESTING > DRAFT)
        2. Confidence score
        3. Usage count

        ARCHIVED skills are excluded. DEPRECATED skills are only
        considered if no other candidates exist.

        Args:
            capability: The capability name to match.
            requirements: Optional additional requirements dict.

        Returns:
            The best matching SkillDefinition, or None if no match found.
        """
        candidates = await self._store.list_by_capability(capability)

        if not candidates:
            logger.debug(
                "no_skills_for_capability",
                capability=capability,
            )
            return None

        # Filter and score candidates
        active_candidates = [
            s for s in candidates
            if s.status not in {SkillStatus.ARCHIVED}
        ]

        if not active_candidates:
            logger.debug(
                "no_active_skills_for_capability",
                capability=capability,
                total_candidates=len(candidates),
            )
            return None

        # If only deprecated candidates, use them as fallback
        non_deprecated = [
            s for s in active_candidates
            if s.status != SkillStatus.DEPRECATED
        ]
        pool = non_deprecated if non_deprecated else active_candidates

        # Apply additional requirement filtering
        if requirements:
            pool = self._filter_by_requirements(pool, requirements)

        if not pool:
            return None

        # Score and rank
        scored = self._rank_candidates(pool)
        best = scored[0]

        logger.info(
            "best_skill_match",
            capability=capability,
            skill_id=str(best.skill_id),
            name=best.name,
            version=best.version,
            status=best.status.value,
            confidence=best.confidence,
        )

        return best

    async def find_by_capability(self, capability: str) -> list[SkillDefinition]:
        """Find all skills providing a specific capability.

        Results are sorted by status priority and confidence.

        Args:
            capability: The capability name to match.

        Returns:
            A list of matching skill definitions, ranked by relevance.
        """
        candidates = await self._store.list_by_capability(capability)
        return self._rank_candidates(candidates)

    async def discover(self) -> list[SkillDefinition]:
        """List all available skills.

        Only returns non-archived skills, sorted by status priority.

        Returns:
            A list of all available skill definitions.
        """
        all_skills = await self._store.list_all()
        available = [
            s for s in all_skills
            if s.status != SkillStatus.ARCHIVED
        ]
        return self._rank_candidates(available)

    @staticmethod
    def _rank_candidates(
        candidates: list[SkillDefinition],
    ) -> list[SkillDefinition]:
        """Rank candidates by status priority, confidence, and usage.

        Args:
            candidates: List of skill candidates.

        Returns:
            Sorted list, best first.
        """
        return sorted(
            candidates,
            key=lambda s: (
                _STATUS_PRIORITY.get(s.status, 0),
                s.confidence,
                s.usage_count,
            ),
            reverse=True,
        )

    @staticmethod
    def _filter_by_requirements(
        candidates: list[SkillDefinition],
        requirements: dict[str, Any],
    ) -> list[SkillDefinition]:
        """Filter candidates by additional requirements.

        Currently supports filtering by:
            - driver_type: Match the skill's driver type.
            - min_confidence: Minimum confidence threshold.
            - tags: Skill must have all specified tags.

        Args:
            candidates: List of skill candidates.
            requirements: Dict of requirement filters.

        Returns:
            Filtered list of candidates.
        """
        result = list(candidates)

        if "driver_type" in requirements:
            dt = requirements["driver_type"]
            result = [s for s in result if s.driver_type == dt]

        if "min_confidence" in requirements:
            min_conf = float(requirements["min_confidence"])
            result = [s for s in result if s.confidence >= min_conf]

        if "tags" in requirements:
            required_tags = set(requirements["tags"])
            result = [
                s for s in result
                if required_tags.issubset(set(s.tags))
            ]

        return result
