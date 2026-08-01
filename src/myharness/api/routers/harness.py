"""Harness supervisor API — system status and lifecycle control."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException

from myharness.api.dependencies import get_supervisor

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/status")
async def get_harness_status(
    supervisor=Depends(get_supervisor),
) -> dict[str, Any]:
    """Get the full status of the Harness supervisor and all subsystems.

    Returns runtime state including:
    - Whether the system is running
    - Number of active cognitive tasks
    - Uptime since boot
    - Active LLM provider
    """
    status = supervisor.status
    # Enrich with additional info
    status["active_provider"] = getattr(
        supervisor._llm_engine, "active_provider_name", "unknown"
    )
    return status


@router.post("/shutdown")
async def shutdown_harness(
    supervisor=Depends(get_supervisor),
) -> dict[str, str]:
    """Initiate a graceful shutdown of the entire harness.

    Shutdown sequence:
    1. Stop accepting new events
    2. Cancel all active tasks
    3. Shutdown all execution drivers
    4. Stop the runtime monitor
    5. Emit shutdown event
    6. Stop the event bus
    """
    logger.warning("shutdown_requested")
    try:
        await supervisor.shutdown()
        return {
            "status": "shutting_down",
            "message": "All subsystems are shutting down gracefully.",
        }
    except Exception as exc:
        logger.error("shutdown_failed", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Shutdown failed: {exc}",
        ) from exc


@router.get("/health")
async def subsystem_health(
    supervisor=Depends(get_supervisor),
) -> dict[str, Any]:
    """Check the health of all subsystems."""
    health = {
        "harness": supervisor.status.get("is_running", False),
        "event_bus": hasattr(supervisor._event_bus, "published_count"),
        "memory": True,  # Memory is always available (file-based)
        "llm": False,
        "drivers": 0,
    }

    # Check LLM health
    if hasattr(supervisor._llm_engine, "_provider"):
        try:
            health["llm"] = await supervisor._llm_engine._provider.health_check()
        except Exception:
            pass

    # Check driver count
    dm = getattr(supervisor, "_driver_manager", None)
    if dm:
        health["drivers"] = len(await dm.list_drivers())

    overall = all(health.values()) if health else False
    return {"overall_healthy": overall, "subsystems": health}
