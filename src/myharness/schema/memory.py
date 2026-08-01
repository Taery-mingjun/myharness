"""Memory data models — the canonical schemas for the Memory System.

Implements P3 (Identity Externalization) and P9 (Source/Derived Data Separation):
- Identity memory holds the agent's self-model (not the LLM)
- Episodic memory records experiences as immutable events
- Semantic memory stores factual knowledge with confidence scores
- Relationship memory tracks connections between entities
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from myharness.core.types import MemoryId, Embedding


# ── Memory Category ────────────────────────────────────────────────────


class MemoryCategory(StrEnum):
    """The four canonical memory types in MyHarness."""

    IDENTITY = "identity"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATIONSHIP = "relationship"


# ── Identity Memory ────────────────────────────────────────────────────


class IdentityEntry(BaseModel):
    """The agent's self-model — who it is, what it values, how it behaves.

    Per P3, Identity belongs to Memory, not LLM. The LLM reads identity
    via IdentityInterpretation and proposes updates via IdentityUpdateProposal,
    but does not directly own or persist identity data.
    """

    entry_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    version: int = Field(default=1, ge=1, description="Monotonic identity version counter")
    core_values: list[str] = Field(
        default_factory=list,
        description="Fundamental values that guide decision-making (e.g., honesty, safety)",
    )
    mission: str = Field(
        default="",
        description="The agent's overarching purpose or mission statement",
    )
    preferences: dict[str, Any] = Field(
        default_factory=dict,
        description="Learned preferences for interaction style, tools, defaults",
    )
    self_description: str = Field(
        default="",
        description="The agent's understanding of its own nature and capabilities",
    )
    behavioral_guidelines: list[str] = Field(
        default_factory=list,
        description="Explicit behavioral rules and constraints",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Episodic Memory ────────────────────────────────────────────────────


class EpisodicEntry(BaseModel):
    """A single experience, event, or conversation — the agent's personal history.

    Episodic entries are append-only and immutable. They form the raw data
    from which reflections, skills, and identity updates are derived.
    """

    entry_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    category: str = Field(
        default="general",
        description="Sub-category: conversation, task, observation, learning, etc.",
    )
    summary: str = Field(..., min_length=1, description="Concise summary of the episode")
    detail: str = Field(
        default="",
        description="Full narrative detail — the raw experience record",
    )
    participants: list[str] = Field(
        default_factory=list,
        description="Entities involved (user, system, other agents)",
    )
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Significance score [0,1] — higher = more likely to be recalled",
    )
    embedding: Embedding | None = Field(
        default=None,
        description="Vector embedding of summary+detail for semantic search (derived data)",
    )

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Semantic Memory ────────────────────────────────────────────────────


class SemanticEntry(BaseModel):
    """Factual knowledge: entity-attribute-value triples with confidence.

    Stores structured knowledge independent of when it was learned.
    """

    entry_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    entity: str = Field(..., description="The subject of this knowledge (person, object, concept)")
    attribute: str = Field(..., description="The property or relationship being described")
    value: Any = Field(..., description="The value of the attribute")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in this knowledge [0,1]",
    )
    source: str = Field(
        default="",
        description="Where this knowledge came from (episode_id, user_input, inference)",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    embedding: Embedding | None = Field(
        default=None,
        description="Vector embedding for semantic search (derived data)",
    )

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Relationship Memory ────────────────────────────────────────────────


class RelationshipEntry(BaseModel):
    """A directed relationship between two entities with typed relation and strength.

    Forms the social/relational graph of the agent's world model.
    """

    entry_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    entity_a: str = Field(..., description="Source entity of the relationship")
    entity_b: str = Field(..., description="Target entity of the relationship")
    relation_type: str = Field(
        ...,
        description="Type of relationship: knows, trusts, collaborates_with, reports_to, etc.",
    )
    strength: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Relationship strength [0,1]",
    )
    context: str = Field(
        default="",
        description="Contextual notes about the relationship",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Memory Query & Search ──────────────────────────────────────────────


class MemoryQuery(BaseModel):
    """A query against the memory system — supports both vector and keyword search."""

    query_text: str = Field(
        default="",
        description="Natural language query for semantic (vector) search",
    )
    query_embedding: Embedding | None = Field(
        default=None,
        description="Pre-computed embedding (skip embedding generation if provided)",
    )
    categories: list[MemoryCategory] = Field(
        default_factory=lambda: list(MemoryCategory),
        description="Which memory stores to search",
    )
    tags: list[str] = Field(default_factory=list, description="Filter by tags")
    time_range: tuple[datetime, datetime] | None = Field(
        default=None,
        description="Time window filter (start, end)",
    )
    top_k: int = Field(default=10, ge=1, le=100, description="Max results to return")
    min_importance: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum importance threshold for episodic results",
    )
    hybrid_weight: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Weight of vector vs keyword search [0=keyword-only, 1=vector-only]",
    )


class MemorySearchResult(BaseModel):
    """A single search result from the memory system."""

    entry_id: MemoryId
    category: MemoryCategory
    score: float = Field(..., description="Relevance score [0,1]")
    content: str = Field(..., description="Text representation of the matched entry")
    entry: dict[str, Any] = Field(
        default_factory=dict,
        description="Full entry data (serialized)",
    )


class MemoryBatchResult(BaseModel):
    """Result of a batch memory operation."""

    success_count: int
    failure_count: int
    results: list[MemorySearchResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    query_duration_ms: float = 0.0
