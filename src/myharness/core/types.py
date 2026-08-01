"""Shared type aliases and NewType definitions.

These provide semantic meaning to primitive types throughout the codebase
while maintaining full IDE type-checking support.
"""

from __future__ import annotations

from typing import Any, NewType

# ── Strongly-Typed Identifiers ────────────────────────────────────────

MemoryId = NewType("MemoryId", str)
"""Unique identifier for a memory entry across all stores."""

SkillId = NewType("SkillId", str)
"""Unique identifier for a skill definition."""

DriverId = NewType("DriverId", str)
"""Unique identifier for an execution driver instance."""

EventId = NewType("EventId", str)
"""Unique identifier for an event in the bus."""

# ── Domain Type Aliases ───────────────────────────────────────────────

Embedding = list[float]
"""A vector embedding — variable-length list of floating-point values."""

JsonDict = dict[str, Any]
"""A generic JSON-compatible dictionary for unstructured data."""

MemoryEntry = dict[str, Any]
"""A memory entry as a generic dictionary."""

SkillActionTemplate = dict[str, Any]
"""A skill action template as a generic dictionary."""

DriverConfig = dict[str, Any]
"""A driver configuration as a generic dictionary."""
