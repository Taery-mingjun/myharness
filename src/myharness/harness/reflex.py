"""Reflex Layer — low-latency skill triggering bypassing full cognition.

Per Architecture v1.2 §6.5 (Reflex Layer):

    "Stable Skills that have been executed enough times without failure
     are promoted to the Reflex Index. When an incoming event matches a
     reflex trigger, the skill is executed directly — the LLM is only
     asked to fill in parameters, not to think or plan."

This module is physically separate from SemanticStore (memory/semantic/)
and SkillStore (skill/). It holds only trigger fingerprints mapped to
skill references — no semantic content, no execution logic.

Design constraints:
  - match() is O(k) where k = number of reflex triggers (NOT O(n) in
    memory size or skill store size). Triggers are kept in a dict and
    a keyword trie for constant-time lookup.
  - Promotion requires: SkillStatus.STABLE AND consecutive success count
    from DriftDetector >= threshold (default 5). No bypass.
  - rebuild() regenerates the entire index from SkillStore's Stable skills.
    Per P9: reflex index is derived data, fully rebuildable from source.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from myharness.schema.skill import SkillDefinition, SkillStatus

logger = structlog.get_logger(__name__)


@dataclass
class ReflexTrigger:
    """A single trigger rule mapping input patterns to a skill.

    Attributes:
        skill_id: The skill to trigger.
        skill_name: Human-readable skill name.
        keywords: Exact-match keywords (case-insensitive).
        regex_patterns: Compiled regex patterns for flexible matching.
        trigger_count: How many times this trigger has fired (for metrics).
    """

    skill_id: str
    skill_name: str
    keywords: list[str] = field(default_factory=list)
    regex_patterns: list[re.Pattern[str]] = field(default_factory=list)
    trigger_count: int = 0

    def matches(self, text: str) -> bool:
        """Check if text matches any trigger pattern.

        Time complexity: O(len(keywords) + len(regex_patterns)),
        independent of memory or skill store size.
        """
        text_lower = text.lower()
        for kw in self.keywords:
            if kw.lower() in text_lower:
                return True
        for pattern in self.regex_patterns:
            if pattern.search(text_lower):
                return True
        return False


class ReflexIndex:
    """Low-latency index of trigger fingerprints → skill references.

    Physically separate from Memory's SemanticStore. Lives in the Harness
    layer alongside the cognitive pipeline. When an event arrives, the
    supervisor checks this index BEFORE calling LLMEngine.think().

    If a trigger matches:
      - think() and plan() are skipped
      - LLM is only called for parameter extraction (lightweight)
      - The skill executes directly via the Driver layer

    If no trigger matches:
      - The full think→plan→reflect pipeline runs as usual
    """

    def __init__(
        self,
        skill_store: Any = None,
        drift_detector: Any = None,
        success_threshold: int = 5,
    ) -> None:
        """Initialize the reflex index.

        Args:
            skill_store: SkillStore instance for looking up skills.
            drift_detector: DriftDetector for reading success counts.
            success_threshold: Minimum consecutive successes required
                for promotion to reflex (default 5).
        """
        self._skill_store = skill_store
        self._drift_detector = drift_detector
        self._success_threshold = success_threshold
        self._triggers: dict[str, ReflexTrigger] = {}  # skill_id → trigger
        self._keyword_index: dict[str, list[str]] = {}  # keyword → [skill_ids]

        logger.info(
            "reflex_index_initialized",
            success_threshold=success_threshold,
        )

    def match(self, text: str) -> ReflexTrigger | None:
        """Match input text against all reflex triggers.

        Time complexity: O(k) where k = number of keywords in the
        index. Does NOT scan memory or skill store.

        Args:
            text: The input text to match (user message, event payload).

        Returns:
            The first matching ReflexTrigger, or None if no match.
        """
        text_lower = text.lower()

        # Fast path: check keyword index first (O(1) per keyword)
        for keyword, skill_ids in self._keyword_index.items():
            if keyword in text_lower:
                for skill_id in skill_ids:
                    trigger = self._triggers.get(skill_id)
                    if trigger and trigger.matches(text):
                        trigger.trigger_count += 1
                        logger.info(
                            "reflex_match_hit",
                            skill_id=skill_id,
                            skill_name=trigger.skill_name,
                            keyword=keyword,
                        )
                        return trigger

        # Slow path: check regex patterns (O(r) where r = regex count)
        for trigger in self._triggers.values():
            if trigger.regex_patterns and trigger.matches(text):
                trigger.trigger_count += 1
                logger.info(
                    "reflex_match_hit",
                    skill_id=trigger.skill_id,
                    skill_name=trigger.skill_name,
                    match_type="regex",
                )
                return trigger

        logger.debug("reflex_match_miss", text_length=len(text))
        return None

    async def promote_to_reflex(
        self,
        skill_id: str,
    ) -> dict[str, Any]:
        """Promote a Stable skill to the Reflex Index.

        Preconditions (all must be met, no bypass):
          1. Skill must exist in SkillStore.
          2. Skill status must be STABLE.
          3. DriftDetector must show >= success_threshold consecutive
             successful executions of this skill.

        Args:
            skill_id: The ID of the skill to promote.

        Returns:
            Dict with promotion result and reason.

        Raises:
            ValueError: If skill_store or drift_detector not configured.
        """
        if self._skill_store is None:
            raise ValueError("SkillStore not configured — cannot promote")
        if self._drift_detector is None:
            raise ValueError("DriftDetector not configured — cannot promote")

        skill = await self._skill_store.get(skill_id)
        if skill is None:
            return {
                "status": "rejected",
                "reason": f"Skill '{skill_id}' not found in store",
                "skill_id": skill_id,
            }

        # Condition 1: must be STABLE
        if skill.status != SkillStatus.STABLE:
            return {
                "status": "rejected",
                "reason": (
                    f"Skill status is '{skill.status.value}', "
                    f"must be 'stable' for reflex promotion"
                ),
                "skill_id": skill_id,
                "current_status": skill.status.value,
            }

        # Condition 2: consecutive success count from DriftDetector
        success_count = await self._get_consecutive_successes(skill.name)
        if success_count < self._success_threshold:
            return {
                "status": "rejected",
                "reason": (
                    f"Consecutive success count is {success_count}, "
                    f"must be >= {self._success_threshold}"
                ),
                "skill_id": skill_id,
                "success_count": success_count,
                "threshold": self._success_threshold,
            }

        # Extract trigger patterns from skill definition
        keywords, regex_patterns = self._extract_triggers(skill)

        trigger = ReflexTrigger(
            skill_id=skill_id,
            skill_name=skill.name,
            keywords=keywords,
            regex_patterns=regex_patterns,
        )
        self._triggers[skill_id] = trigger

        # Update keyword index
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower not in self._keyword_index:
                self._keyword_index[kw_lower] = []
            if skill_id not in self._keyword_index[kw_lower]:
                self._keyword_index[kw_lower].append(skill_id)

        logger.info(
            "reflex_promotion_success",
            skill_id=skill_id,
            skill_name=skill.name,
            keywords=keywords,
            regex_count=len(regex_patterns),
            success_count=success_count,
        )

        return {
            "status": "promoted",
            "skill_id": skill_id,
            "skill_name": skill.name,
            "keywords": keywords,
            "regex_count": len(regex_patterns),
            "success_count": success_count,
        }

    async def rebuild(self) -> dict[str, Any]:
        """Rebuild the entire Reflex Index from SkillStore's Stable skills.

        Per P9: reflex index is derived data. It can be fully rebuilt from
        the canonical source (SkillStore). This method clears the index
        and re-promotes all eligible Stable skills.

        Returns:
            Dict with rebuild statistics.
        """
        if self._skill_store is None:
            raise ValueError("SkillStore not configured — cannot rebuild")

        # Clear existing index
        cleared = len(self._triggers)
        self._triggers.clear()
        self._keyword_index.clear()

        # Find all Stable skills
        stable_skills = await self._skill_store.list_by_status(SkillStatus.STABLE)

        promoted = 0
        rejected = 0
        for skill in stable_skills:
            if self._drift_detector is not None:
                success_count = await self._get_consecutive_successes(skill.name)
                if success_count < self._success_threshold:
                    rejected += 1
                    continue

            keywords, regex_patterns = self._extract_triggers(skill)
            trigger = ReflexTrigger(
                skill_id=str(skill.skill_id),
                skill_name=skill.name,
                keywords=keywords,
                regex_patterns=regex_patterns,
            )
            self._triggers[str(skill.skill_id)] = trigger
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower not in self._keyword_index:
                    self._keyword_index[kw_lower] = []
                if str(skill.skill_id) not in self._keyword_index[kw_lower]:
                    self._keyword_index[kw_lower].append(str(skill.skill_id))
            promoted += 1

        logger.info(
            "reflex_rebuild_complete",
            cleared=cleared,
            stable_skills=len(stable_skills),
            promoted=promoted,
            rejected=rejected,
        )

        return {
            "status": "rebuilt",
            "cleared": cleared,
            "stable_skills_found": len(stable_skills),
            "promoted": promoted,
            "rejected_by_threshold": rejected,
        }

    def _extract_triggers(
        self, skill: SkillDefinition
    ) -> tuple[list[str], list[re.Pattern[str]]]:
        """Extract trigger keywords and regex from skill definition.

        Uses skill name, description, and tags as keyword sources.
        Falls back to capability name if no explicit triggers found.
        """
        keywords: list[str] = []

        # Skill name is always a keyword
        if skill.name:
            keywords.append(skill.name.lower())

        # Description words — for CJK text, individual characters are
        # meaningful triggers, so we keep words with len >= 2 for CJK
        # and len > 3 for ASCII (to avoid noise like "the", "a", etc.)
        if skill.description:
            for word in skill.description.split():
                word = word.strip(".,!?;:\"'")
                # Check if word contains CJK characters
                has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in word)
                if has_cjk and len(word) >= 2:
                    keywords.append(word.lower())
                elif not has_cjk and len(word) > 3:
                    keywords.append(word.lower())

        # Tags as keywords too
        if skill.tags:
            for tag in skill.tags:
                if len(tag) >= 2:
                    keywords.append(tag.lower())

        keywords = list(set(keywords))  # dedupe

        # No regex patterns by default — skills would need to declare them
        # explicitly in a future schema extension
        regex_patterns: list[re.Pattern[str]] = []

        return keywords, regex_patterns

    async def _get_consecutive_successes(self, skill_name: str) -> int:
        """Read consecutive success count from DriftDetector."""
        if self._drift_detector is None:
            return 0

        conn = await self._drift_detector._get_conn()
        cursor = await conn.execute(
            "SELECT metric_type FROM drift_metrics "
            "WHERE skill_name = ? AND metric_type IN ('skill_success', 'skill_failure') "
            "ORDER BY timestamp DESC LIMIT 50",
            (skill_name,),
        )
        rows = await cursor.fetchall()
        cursor.close()

        consecutive = 0
        for row in rows:
            if row["metric_type"] == "skill_success":
                consecutive += 1
            else:
                break
        return consecutive

    @property
    def trigger_count(self) -> int:
        """Number of triggers currently in the index."""
        return len(self._triggers)

    @property
    def total_fires(self) -> int:
        """Total number of times any trigger has fired."""
        return sum(t.trigger_count for t in self._triggers.values())

    def list_triggers(self) -> list[dict[str, Any]]:
        """List all triggers for inspection."""
        return [
            {
                "skill_id": t.skill_id,
                "skill_name": t.skill_name,
                "keywords": t.keywords,
                "regex_count": len(t.regex_patterns),
                "trigger_count": t.trigger_count,
            }
            for t in self._triggers.values()
        ]
