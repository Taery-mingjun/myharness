"""Memory system API — identity, episodes, knowledge, relationships."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from myharness.api.dependencies import get_memory
from myharness.core.exceptions import IdentityConflictError
from myharness.schema.memory import MemoryQuery

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Response Models ──────────────────────────────────────────────────────


class IdentityResponse(BaseModel):
    """The agent's current identity."""

    identity_id: str
    version: int
    name: str
    core_values: list[str]
    mission: str
    preferences: dict[str, Any]
    self_description: str
    behavioral_guidelines: list[str]
    created_at: str
    updated_at: str


class IdentityUpdateRequest(BaseModel):
    """Request to update the agent's identity.

    Only the fields present in the request body are changed; everything
    else is carried over from the current identity.
    """

    core_values: list[str] | None = None
    mission: str | None = None
    preferences: dict[str, Any] | None = None
    self_description: str | None = None
    behavioral_guidelines: list[str] | None = None
    expected_version: int | None = Field(
        default=None,
        description=(
            "Version the caller believes is current. When supplied, the "
            "update is rejected with 409 if the identity changed in the "
            "meantime — the equivalent of an If-Match header. Omit it to "
            "apply the change to whatever version is current."
        ),
    )


class SearchRequest(BaseModel):
    """Memory search query."""

    query_text: str = Field(default="", description="Natural language search query")
    categories: list[str] | None = Field(
        default=None,
        description="Memory categories to search (identity/episodic/semantic/relationship)",
    )
    tags: list[str] | None = Field(default=None, description="Filter by tags")
    top_k: int = Field(default=10, ge=1, le=100, description="Max results")
    min_importance: float = Field(default=0.0, ge=0.0, le=1.0)
    hybrid_weight: float = Field(default=0.7, ge=0.0, le=1.0)


class SearchResults(BaseModel):
    """Memory search results."""

    results: list[dict[str, Any]]
    total: int


class RecentEpisodesResponse(BaseModel):
    """Recent episodic memories.

    An explicit model rather than a ``dict[str, ...]`` annotation: the loose
    form claimed every value was a list, so FastAPI rejected the integer
    ``count`` at serialization time and turned a working handler into a 500.
    """

    episodes: list[dict[str, Any]]
    count: int


class MemoryStatsResponse(BaseModel):
    """Memory system statistics."""

    episodic: dict[str, Any]
    semantic: dict[str, Any]
    relationship: dict[str, Any]
    identity: dict[str, Any]
    indexes: dict[str, Any]


# ── Identity Endpoints ───────────────────────────────────────────────────


@router.get("/identity", response_model=IdentityResponse)
async def get_identity(memory=Depends(get_memory)) -> IdentityResponse:
    """Get the agent's current identity (self-model).

    Per P3: Identity lives in Memory, not LLM. This endpoint returns
    the canonical identity that persists across LLM provider switches.
    """
    identity = await memory.get_identity()
    return IdentityResponse(
        identity_id=str(identity.entry_id),
        version=identity.version,
        name=getattr(identity, "name", "Jarvis"),
        core_values=identity.core_values,
        mission=identity.mission,
        preferences=identity.preferences,
        self_description=identity.self_description,
        behavioral_guidelines=identity.behavioral_guidelines,
        created_at=identity.created_at.isoformat(),
        updated_at=identity.updated_at.isoformat(),
    )


@router.put("/identity")
async def update_identity(
    update: IdentityUpdateRequest,
    memory=Depends(get_memory),
) -> dict[str, Any]:
    """Update the agent's identity.

    Accepts partial updates — only provided fields are modified. The
    version number increments automatically on each update.

    This endpoint used to reject every request it received. It set
    ``version = current.version + 1`` before handing the entry to the
    store, but the store treats the incoming version as the caller's
    view of *current* state and does the increment itself — so the
    optimistic-concurrency check always saw N+1 where it expected N and
    answered "Version conflict: expected 1, got 2". The agent's identity
    was effectively read-only over HTTP.

    Pass ``expected_version`` to opt into a real conflict check.
    """
    current = await memory.get_identity()

    from myharness.schema.memory import IdentityEntry

    update_dict = update.model_dump(exclude_unset=True)
    expected = update_dict.pop("expected_version", None)

    if expected is not None and expected != current.version:
        raise IdentityConflictError(
            f"Version conflict: expected {current.version}, got {expected}",
            details={
                "expected_version": current.version,
                "provided_version": expected,
            },
        )

    updated_data = current.model_dump()
    updated_data.update(update_dict)
    # The store owns the increment; hand it the version we actually read.
    updated_data["version"] = current.version

    entry = IdentityEntry(**updated_data)
    await memory.update_identity(entry)

    logger.info("identity_updated", version=entry.version)
    return {"status": "updated", "version": entry.version}


# ── Search Endpoints ─────────────────────────────────────────────────────


@router.post("/search", response_model=SearchResults)
async def search_memory(
    query: SearchRequest,
    memory=Depends(get_memory),
) -> SearchResults:
    """Search across all memory stores.

    Supports hybrid search (vector + text) across episodic and semantic
    memory with configurable weighting and filtering.
    """
    from myharness.schema.memory import MemoryCategory

    # Build memory categories from string list
    categories = None
    if query.categories:
        categories = [MemoryCategory(c) for c in query.categories]

    mq = MemoryQuery(
        query_text=query.query_text,
        categories=categories or list(MemoryCategory),
        tags=query.tags or [],
        top_k=query.top_k,
        min_importance=query.min_importance,
        hybrid_weight=query.hybrid_weight,
    )

    results = await memory.search(mq)
    return SearchResults(
        results=[r.model_dump(mode="json") for r in results],
        total=len(results),
    )


# ── Episodic Memory Endpoints ────────────────────────────────────────────


@router.get("/episodes/recent", response_model=RecentEpisodesResponse)
async def get_recent_episodes(
    limit: int = Query(default=50, ge=1, le=500, description="Max episodes to return"),
    memory=Depends(get_memory),
) -> RecentEpisodesResponse:
    """Get the most recent episodic memories."""
    episodes = await memory.get_recent_episodes(limit)
    return RecentEpisodesResponse(
        episodes=[e.model_dump(mode="json") for e in episodes],
        count=len(episodes),
    )


# ── Stats & Maintenance ──────────────────────────────────────────────────


@router.get("/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(memory=Depends(get_memory)) -> MemoryStatsResponse:
    """Get aggregate statistics from all memory stores.

    Returns counts and metadata for each store plus index status.
    """
    stats = await memory.get_stats()
    return MemoryStatsResponse(**stats)


@router.post("/rebuild")
async def rebuild_indexes(
    memory=Depends(get_memory),
) -> dict[str, str]:
    """Rebuild all derived indexes from source data.

    Per P9: All derived data (SQLite, FAISS, FTS5) can be fully
    reconstructed from the canonical JSON/JSONL source files.
    This endpoint triggers that rebuild process.
    """
    logger.info("rebuild_indexes_requested")
    await memory.rebuild_indexes()
    logger.info("rebuild_indexes_complete")
    return {
        "status": "indexes_rebuilt",
        "message": "All derived indexes have been fully rebuilt from source data.",
    }
