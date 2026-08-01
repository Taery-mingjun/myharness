"""Memory Serializer — converts between Pydantic models and dicts.

Handles serialization/deserialization for all memory entry types,
including datetime and embedding handling for JSON compatibility.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from myharness.schema.memory import (
    EpisodicEntry,
    IdentityEntry,
    RelationshipEntry,
    SemanticEntry,
)


def entry_to_dict(
    entry: IdentityEntry | EpisodicEntry | SemanticEntry | RelationshipEntry,
) -> dict[str, Any]:
    """Convert any memory entry to a JSON-serializable dictionary.

    Args:
        entry: Any memory entry type.

    Returns:
        JSON-compatible dictionary representation.
    """
    return entry.model_dump(mode="json")


def dict_to_episodic(data: dict[str, Any]) -> EpisodicEntry:
    """Convert a dictionary to an EpisodicEntry.

    Args:
        data: Raw dictionary from SourceOfTruth or elsewhere.

    Returns:
        Parsed EpisodicEntry.

    Raises:
        ValidationError: If the data doesn't conform to the schema.
    """
    return EpisodicEntry(**data)


def dict_to_semantic(data: dict[str, Any]) -> SemanticEntry:
    """Convert a dictionary to a SemanticEntry.

    Args:
        data: Raw dictionary from SourceOfTruth or elsewhere.

    Returns:
        Parsed SemanticEntry.
    """
    return SemanticEntry(**data)


def dict_to_relationship(data: dict[str, Any]) -> RelationshipEntry:
    """Convert a dictionary to a RelationshipEntry.

    Args:
        data: Raw dictionary from SourceOfTruth or elsewhere.

    Returns:
        Parsed RelationshipEntry.
    """
    return RelationshipEntry(**data)


def dict_to_identity(data: dict[str, Any]) -> IdentityEntry:
    """Convert a dictionary to an IdentityEntry.

    Args:
        data: Raw dictionary from SourceOfTruth or elsewhere.

    Returns:
        Parsed IdentityEntry.
    """
    return IdentityEntry(**data)


class MemorySerializer:
    """Utility class for memory entry serialization/deserialization.

    Provides convenience methods for converting between Pydantic models
    and dictionary representations used by SourceOfTruth storage.
    """

    @staticmethod
    def serialize(
        entry: IdentityEntry | EpisodicEntry | SemanticEntry | RelationshipEntry,
    ) -> dict[str, Any]:
        """Serialize any memory entry to a dictionary."""
        return entry_to_dict(entry)

    @staticmethod
    def deserialize_episodic(data: dict[str, Any]) -> EpisodicEntry:
        """Deserialize an episodic entry from a dictionary."""
        return dict_to_episodic(data)

    @staticmethod
    def deserialize_semantic(data: dict[str, Any]) -> SemanticEntry:
        """Deserialize a semantic entry from a dictionary."""
        return dict_to_semantic(data)

    @staticmethod
    def deserialize_relationship(data: dict[str, Any]) -> RelationshipEntry:
        """Deserialize a relationship entry from a dictionary."""
        return dict_to_relationship(data)

    @staticmethod
    def deserialize_identity(data: dict[str, Any]) -> IdentityEntry:
        """Deserialize an identity entry from a dictionary."""
        return dict_to_identity(data)
