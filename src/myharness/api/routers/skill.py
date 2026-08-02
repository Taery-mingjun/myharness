"""Skill store API — register, search, and manage executable skills."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from myharness.api.dependencies import get_skill_store
from myharness.schema.skill import SkillStatus

logger = structlog.get_logger(__name__)
router = APIRouter()


class SkillCreateRequest(BaseModel):
    """Request to register a new skill."""

    name: str = Field(..., min_length=1, description="Unique skill name")
    version: str = Field(default="0.1.0", description="Semantic version")
    description: str = Field(default="", description="What this skill does")
    capability: str = Field(..., description="The capability this skill provides")
    driver_type: str = Field(default="api", description="Target driver type")
    action_template: dict[str, Any] = Field(default_factory=dict)
    allowed_actions: list[str] = Field(
        default_factory=list,
        description="Driver actions this skill may invoke. Empty derives the "
        "allowlist from action_template; ['*'] deliberately removes the limit.",
    )
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=60.0)


class SkillStatusRequest(BaseModel):
    """Request to change a skill's lifecycle status."""

    status: str = Field(..., description="Target status (draft/testing/verified/stable/deprecated/archived)")
    reason: str = Field(default="", description="Reason for the status change")


class SkillResponse(BaseModel):
    """Skill definition response."""

    skill_id: str
    name: str
    version: str
    description: str
    status: str
    capability: str
    driver_type: str
    confidence: float
    usage_count: int
    tags: list[str]


class SkillListResponse(BaseModel):
    """List of skills."""

    skills: list[dict[str, Any]]
    total: int


def _skill_to_response(skill) -> dict[str, Any]:
    """Convert a SkillDefinition to a JSON-safe response dict."""
    return skill.model_dump(mode="json")


# ── CRUD Endpoints ───────────────────────────────────────────────────────


@router.get("/", response_model=SkillListResponse)
async def list_skills(
    status: str | None = Query(default=None, description="Filter by status"),
    capability: str | None = Query(default=None, description="Filter by capability"),
    skill_store=Depends(get_skill_store),
) -> SkillListResponse:
    """List all registered skills, with optional filters."""
    if capability:
        skills = await skill_store.list_by_capability(capability)
    elif status:
        skills = await skill_store.list_by_status(SkillStatus(status))
    else:
        skills = await skill_store.list_all()

    return SkillListResponse(
        skills=[_skill_to_response(s) for s in skills],
        total=len(skills),
    )


@router.get("/search/{query}", response_model=SkillListResponse)
async def search_skills(
    query: str,
    top_k: int = Query(default=10, ge=1, le=100),
    skill_store=Depends(get_skill_store),
) -> SkillListResponse:
    """Search skills by name, description, or tags."""
    skills = await skill_store.search(query, top_k)
    return SkillListResponse(
        skills=[_skill_to_response(s) for s in skills],
        total=len(skills),
    )


@router.get("/{skill_id}")
async def get_skill(
    skill_id: str,
    skill_store=Depends(get_skill_store),
) -> dict[str, Any]:
    """Get a specific skill by ID."""
    skill = await skill_store.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return _skill_to_response(skill)


@router.post("/", status_code=201)
async def create_skill(
    req: SkillCreateRequest,
    skill_store=Depends(get_skill_store),
) -> dict[str, Any]:
    """Register a new skill definition."""
    from myharness.schema.skill import SkillDefinition, SkillParameter

    parameters = [
        SkillParameter(
            name=p.get("name", ""),
            type=p.get("type", "string"),
            description=p.get("description", ""),
            required=p.get("required", False),
            default=p.get("default"),
            enum_values=p.get("enum_values"),
        )
        for p in req.parameters
    ]

    skill = SkillDefinition(
        name=req.name,
        version=req.version,
        description=req.description,
        capability=req.capability,
        driver_type=req.driver_type,
        action_template=req.action_template,
        allowed_actions=req.allowed_actions,
        parameters=parameters,
        input_schema=req.input_schema,
        output_schema=req.output_schema,
        confidence=req.confidence,
        tags=req.tags,
        timeout_seconds=req.timeout_seconds,
    )

    result = await skill_store.register(skill)
    logger.info("skill_created", skill_id=str(result.skill_id), name=result.name)
    return _skill_to_response(result)


@router.put("/{skill_id}")
async def update_skill(
    skill_id: str,
    update_data: dict[str, Any],
    skill_store=Depends(get_skill_store),
) -> dict[str, Any]:
    """Update an existing skill definition."""
    existing = await skill_store.get(skill_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")

    from myharness.schema.skill import SkillDefinition

    merged = existing.model_dump()
    merged.update(update_data)
    merged["skill_id"] = skill_id  # Preserve the original ID

    updated = SkillDefinition(**merged)
    result = await skill_store.update(updated)
    return _skill_to_response(result)


@router.put("/{skill_id}/status")
async def change_skill_status(
    skill_id: str,
    req: SkillStatusRequest,
    skill_store=Depends(get_skill_store),
) -> dict[str, Any]:
    """Change a skill's lifecycle status.

    Valid transitions:
    - DRAFT → TESTING
    - TESTING → DRAFT, VERIFIED
    - VERIFIED → STABLE, DRAFT
    - STABLE → DEPRECATED
    - DEPRECATED → STABLE, ARCHIVED
    - ARCHIVED → (terminal)
    """
    try:
        new_status = SkillStatus(req.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {req.status}. Valid values: {[s.value for s in SkillStatus]}",
        )

    try:
        result = await skill_store.change_status(skill_id, new_status, req.reason)
        logger.info(
            "skill_status_changed",
            skill_id=skill_id,
            new_status=req.status,
            reason=req.reason,
        )
        return _skill_to_response(result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{skill_id}/versions")
async def get_version_history(
    skill_id: str,
    skill_store=Depends(get_skill_store),
) -> dict[str, Any]:
    """Get version history for a skill."""
    skill = await skill_store.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")

    versions = await skill_store.get_version_history(skill.name)
    return {
        "name": skill.name,
        "versions": [_skill_to_response(v) for v in versions],
        "count": len(versions),
    }


@router.get("/stats/overview")
async def get_skill_stats(skill_store=Depends(get_skill_store)) -> dict[str, Any]:
    """Get aggregate skill store statistics."""
    return await skill_store.get_stats()
