"""Driver API — list drivers, discover capabilities, execute actions."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from myharness.api.dependencies import get_supervisor

logger = structlog.get_logger(__name__)
router = APIRouter()


class ExecuteRequest(BaseModel):
    """Request to execute an action through a driver."""

    driver: str = Field(..., description="Driver name (api, browser, robot, etc.)")
    action: str = Field(..., description="Action to execute")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific parameters",
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description="Optional execution context",
    )


class ExecuteResponse(BaseModel):
    """Result of a driver action execution."""

    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0


class DriverInfo(BaseModel):
    """Information about a registered driver."""

    name: str
    version: str
    capabilities: list[dict[str, Any]]
    is_healthy: bool


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/")
async def list_drivers(
    supervisor=Depends(get_supervisor),
) -> dict[str, Any]:
    """List all registered execution drivers."""
    dm = getattr(supervisor, "_driver_manager", None)
    if dm is None:
        return {"drivers": [], "count": 0}

    drivers = await dm.list_drivers()
    driver_details = []
    for name in drivers:
        d = await dm.get(name)
        if d:
            healthy = False
            try:
                healthy = await d.health_check()
            except Exception:
                pass
            driver_details.append({
                "name": d.driver_name,
                "version": d.driver_version,
                "capabilities": [
                    c.model_dump(mode="json") if hasattr(c, "model_dump") else c
                    for c in d.capabilities
                ],
                "is_healthy": healthy,
            })

    return {"drivers": driver_details, "count": len(driver_details)}


@router.get("/capabilities")
async def list_capabilities(
    supervisor=Depends(get_supervisor),
) -> dict[str, Any]:
    """List all discovered capabilities across all drivers."""
    cr = getattr(supervisor, "_capability_registry", None)
    if cr is None:
        return {"capabilities": [], "count": 0}

    capabilities = await cr.list_available_capabilities()
    return {"capabilities": capabilities, "count": len(capabilities)}


@router.post("/execute", response_model=ExecuteResponse)
async def execute_action(
    req: ExecuteRequest,
    supervisor=Depends(get_supervisor),
) -> ExecuteResponse:
    """Execute an action through a named driver.

    The action is translated through the driver protocol and executed
    on the appropriate execution target.
    """
    dm = getattr(supervisor, "_driver_manager", None)
    if dm is None:
        raise HTTPException(status_code=503, detail="Driver manager not available")

    import time

    start = time.monotonic()
    try:
        result = await dm.execute(req.driver, req.action, req.parameters)
        duration_ms = (time.monotonic() - start) * 1000

        if hasattr(result, "model_dump"):
            result_dict = result.model_dump(mode="json")
        else:
            result_dict = result

        return ExecuteResponse(
            success=result_dict.get("success", True),
            output=result_dict.get("output"),
            error=result_dict.get("error"),
            duration_ms=round(duration_ms, 2),
        )
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error("driver_execute_error", driver=req.driver, action=req.action, error=str(exc))
        return ExecuteResponse(
            success=False,
            error=str(exc),
            duration_ms=round(duration_ms, 2),
        )
