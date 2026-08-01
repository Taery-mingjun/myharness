"""Abstract interface for skill storage operations.

Defines the contract that all skill store implementations must fulfill.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from myharness.schema.skill import SkillDefinition, SkillStatus


class SkillStoreInterface(ABC):
    """Abstract interface for skill storage operations.

    All methods are async to support both file-based and database-backed
    implementations without blocking the event loop.
    """

    @abstractmethod
    async def register(self, skill: SkillDefinition) -> SkillDefinition:
        """Register a new skill definition.

        Args:
            skill: The skill definition to register.

        Returns:
            The registered skill definition with assigned skill_id.

        Raises:
            SkillValidationError: If the skill definition fails validation.
            SkillError: If registration fails for any other reason.
        """
        ...

    @abstractmethod
    async def get(self, skill_id: str) -> SkillDefinition | None:
        """Retrieve a skill by its unique identifier.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            The skill definition, or None if not found.
        """
        ...

    @abstractmethod
    async def get_by_name(
        self, name: str, version: str | None = None
    ) -> SkillDefinition | None:
        """Retrieve a skill by name, optionally filtered by version.

        Args:
            name: The skill name.
            version: Optional semantic version to match. If None, returns
                     the latest version (highest semantic version).

        Returns:
            The skill definition, or None if not found.
        """
        ...

    @abstractmethod
    async def list_all(self) -> list[SkillDefinition]:
        """List all registered skill definitions.

        Returns:
            A list of all skill definitions.
        """
        ...

    @abstractmethod
    async def list_by_capability(self, capability: str) -> list[SkillDefinition]:
        """List skills that provide a specific capability.

        Args:
            capability: The capability name to filter by.

        Returns:
            A list of matching skill definitions.
        """
        ...

    @abstractmethod
    async def list_by_status(self, status: SkillStatus) -> list[SkillDefinition]:
        """List skills filtered by lifecycle status.

        Args:
            status: The skill status to filter by.

        Returns:
            A list of skills with the given status.
        """
        ...

    @abstractmethod
    async def search(self, query: str, top_k: int = 10) -> list[SkillDefinition]:
        """Search skills by text matching on name and description.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            A list of matching skill definitions, ranked by relevance.
        """
        ...

    @abstractmethod
    async def update(self, skill: SkillDefinition) -> SkillDefinition:
        """Update an existing skill definition.

        Args:
            skill: The skill definition with updated fields.

        Returns:
            The updated skill definition.

        Raises:
            SkillNotFoundError: If the skill does not exist.
        """
        ...

    @abstractmethod
    async def change_status(
        self, skill_id: str, new_status: SkillStatus, reason: str = ""
    ) -> SkillDefinition:
        """Change the lifecycle status of a skill.

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
        ...

    @abstractmethod
    async def deprecate(self, skill_id: str, reason: str) -> SkillDefinition:
        """Deprecate a skill, marking it as no longer recommended.

        Args:
            skill_id: The skill identifier.
            reason: The reason for deprecation.

        Returns:
            The updated skill definition.
        """
        ...

    @abstractmethod
    async def archive(self, skill_id: str) -> SkillDefinition:
        """Archive a skill, moving it to a terminal state.

        Args:
            skill_id: The skill identifier.

        Returns:
            The updated skill definition.
        """
        ...

    @abstractmethod
    async def get_version_history(self, name: str) -> list[SkillDefinition]:
        """Get all versions of a skill, ordered by version.

        Args:
            name: The skill name.

        Returns:
            A list of all versions of the skill.
        """
        ...

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics about the skill store.

        Returns:
            A dictionary with keys like total_skills, by_status, by_driver_type, etc.
        """
        ...
