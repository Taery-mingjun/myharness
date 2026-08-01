"""Cognitive pipeline API — the main thinking/planning/reflecting endpoint."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from myharness.api.dependencies import get_supervisor

logger = structlog.get_logger(__name__)
router = APIRouter()


class MessageRequest(BaseModel):
    """A message sent by a user to the cognitive system."""

    message: str = Field(
        ...,
        min_length=1,
        description="The user's message to process through the cognitive pipeline",
        examples=["What is the weather today?"],
    )
    user_id: str = Field(
        default="default",
        description="Identifier for the user sending the message",
    )


class MessageResponse(BaseModel):
    """The system's response after processing a user message."""

    response: str = Field(..., description="The agent's text response")
    plan: dict | None = Field(
        default=None,
        description="The execution plan generated (if any)",
    )
    reflection: dict | None = Field(
        default=None,
        description="The reflection on the interaction (if any)",
    )


class CognitiveStatus(BaseModel):
    """Current status of the cognitive system."""

    is_running: bool
    active_tasks: int
    uptime_seconds: float
    provider: str


@router.post("/message", response_model=MessageResponse)
async def send_message(
    req: MessageRequest,
    supervisor=Depends(get_supervisor),
) -> MessageResponse:
    """Send a message through the full cognitive pipeline.

    Pipeline stages:
    1. Record episode (Memory)
    2. Build context (Memory + Identity)
    3. Think (LLM)
    4. Plan (LLM + Skills)
    5. Execute (Driver) — if plan requires execution
    6. Reflect (LLM)
    7. Update memory
    8. Return response

    This is the primary interaction endpoint for the cognitive system.
    """
    logger.info(
        "cognitive_message_received",
        user_id=req.user_id,
        message_length=len(req.message),
    )

    try:
        response = await supervisor.handle_user_message(
            req.message, req.user_id
        )
        return MessageResponse(response=response)
    except Exception as exc:
        logger.error(
            "cognitive_message_failed",
            user_id=req.user_id,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Cognitive pipeline error: {exc}",
        ) from exc


@router.get("/status", response_model=CognitiveStatus)
async def get_status(supervisor=Depends(get_supervisor)) -> CognitiveStatus:
    """Get the current status of the cognitive system."""
    status = supervisor.status
    return CognitiveStatus(
        is_running=status.get("is_running", False),
        active_tasks=status.get("active_tasks", 0),
        uptime_seconds=status.get("uptime_seconds", 0.0),
        provider=getattr(supervisor._llm_engine, "active_provider_name", "unknown"),
    )
