"""Low-level JSON file operations for skill persistence.

Skills are stored as JSON files in a directory hierarchy:
    {skills_dir}/{skill_name}/{version}.json

The JSON file is the source of truth for each skill version.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from myharness.core.exceptions import SkillError, SkillNotFoundError
from myharness.schema.skill import SkillDefinition

logger = structlog.get_logger(__name__)


class SkillStorage:
    """Low-level JSON file operations for skill definitions.

    Handles reading and writing individual skill JSON files. Does not
    implement business logic — that belongs in SkillStore.
    """

    def __init__(self, skills_dir: Path) -> None:
        """Initialize the skill storage layer.

        Args:
            skills_dir: Root directory where skill JSON files are stored.
        """
        self._skills_dir = skills_dir
        self._skills_dir.mkdir(parents=True, exist_ok=True)

    def _skill_path(self, name: str, version: str) -> Path:
        """Get the file path for a skill name/version pair."""
        safe_name = name.replace("/", "_").replace("\\", "_")
        return self._skills_dir / safe_name / f"{version}.json"

    def _skill_dir(self, name: str) -> Path:
        """Get the directory for a skill name."""
        safe_name = name.replace("/", "_").replace("\\", "_")
        return self._skills_dir / safe_name

    async def save(self, skill: SkillDefinition) -> None:
        """Save a skill definition to its JSON file.

        Args:
            skill: The skill definition to persist.

        Raises:
            SkillError: If the file cannot be written.
        """
        skill.updated_at = datetime.now(UTC)
        file_path = self._skill_path(skill.name, skill.version)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = skill.model_dump(mode="json")
            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            logger.debug(
                "skill_saved",
                skill_id=str(skill.skill_id),
                name=skill.name,
                version=skill.version,
                path=str(file_path),
            )
        except OSError as exc:
            raise SkillError(
                f"Failed to save skill {skill.name}@{skill.version}: {exc}",
                code="SKILL_SAVE_ERROR",
                details={"path": str(file_path)},
                cause=exc,
            ) from exc

    async def load(self, skill_id: str) -> SkillDefinition | None:
        """Load a skill definition by its skill_id.

        This scans all skill directories to find the matching skill_id.
        For direct lookups, prefer load_by_name_version.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            The skill definition, or None if not found.
        """
        if not self._skills_dir.exists():
            return None

        for skill_dir in self._skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            for json_file in skill_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    if data.get("skill_id") == skill_id:
                        return SkillDefinition(**data)
                except (json.JSONDecodeError, KeyError, ValueError):
                    logger.warning(
                        "corrupt_skill_file", path=str(json_file)
                    )
        return None

    async def load_by_name_version(
        self, name: str, version: str
    ) -> SkillDefinition | None:
        """Load a skill definition by name and version.

        Args:
            name: The skill name.
            version: The semantic version string.

        Returns:
            The skill definition, or None if not found.
        """
        file_path = self._skill_path(name, version)
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return SkillDefinition(**data)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "corrupt_skill_file",
                path=str(file_path),
                error=str(exc),
            )
            return None

    async def list_versions(self, name: str) -> list[str]:
        """List all available versions for a skill name.

        Args:
            name: The skill name.

        Returns:
            A list of version strings, sorted by semantic version.
        """
        skill_dir = self._skill_dir(name)
        if not skill_dir.exists():
            return []

        versions: list[str] = []
        for json_file in sorted(skill_dir.glob("*.json")):
            stem = json_file.stem
            if stem not in versions:
                versions.append(stem)

        return self._sort_semver(versions)

    async def list_all(self) -> list[SkillDefinition]:
        """List all skill definitions from all directories.

        Returns:
            A list of all persisted skill definitions.
        """
        if not self._skills_dir.exists():
            return []

        skills: list[SkillDefinition] = []
        for skill_dir in sorted(self._skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            for json_file in sorted(skill_dir.glob("*.json")):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    skills.append(SkillDefinition(**data))
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    logger.warning(
                        "corrupt_skill_file",
                        path=str(json_file),
                        error=str(exc),
                    )

        return skills

    async def delete(self, skill_id: str) -> None:
        """Delete a skill definition from storage.

        Args:
            skill_id: The unique skill identifier.

        Raises:
            SkillNotFoundError: If the skill is not found.
        """
        skill = await self.load(skill_id)
        if skill is None:
            raise SkillNotFoundError(
                f"Skill not found: {skill_id}",
                code="SKILL_NOT_FOUND",
                details={"skill_id": skill_id},
            )

        file_path = self._skill_path(skill.name, skill.version)
        if file_path.exists():
            file_path.unlink()
            logger.debug(
                "skill_deleted",
                skill_id=str(skill.skill_id),
                name=skill.name,
                version=skill.version,
            )

        # Clean up empty directories
        skill_dir = self._skill_dir(skill.name)
        if skill_dir.exists() and not any(skill_dir.iterdir()):
            skill_dir.rmdir()

    @staticmethod
    def _sort_semver(versions: list[str]) -> list[str]:
        """Sort version strings semantically (newest first)."""

        def _key(v: str) -> tuple[int, ...]:
            try:
                return tuple(int(x) for x in v.split("."))
            except ValueError:
                return (0, 0, 0)

        return sorted(versions, key=_key, reverse=True)
