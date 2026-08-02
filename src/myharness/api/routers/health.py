"""Health check endpoints for Kubernetes/load-balancer probes.

These are the only unauthenticated endpoints, and they are what an
orchestrator trusts to decide whether to keep sending traffic to this
instance. They therefore have to report the *actual* state of the harness.

Previously both probes returned a hardcoded 200 ("in MVP, this is always
true after startup"). After ``POST /harness/shutdown`` the supervisor was
stopped, memory backends were closed, and every real request failed — yet
``/health`` and ``/health/ready`` still answered 200, so a load balancer
happily kept routing to a dead instance.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from myharness.api.dependencies import get_supervisor

router = APIRouter()


class HealthResponse(BaseModel):
    """Liveness/readiness payload."""

    status: str
    service: str = "myharness"
    harness_running: bool
    detail: str | None = None


@router.get("/health", response_model=HealthResponse)
async def health_check(
    response: Response,
    supervisor: Any = Depends(get_supervisor),
) -> HealthResponse:
    """Liveness probe — should this instance be restarted?

    Returns 200 while the process can still serve. Returns 503 once the
    harness has been shut down, because that state is terminal in-process:
    the orchestrator must replace the instance rather than keep it in the
    pool.

    Note this keys off *has been shut down*, not *is running*. The API also
    supports a lazy mode where services are resolved from the DI container
    without an explicit boot; such an instance serves perfectly well and
    must not be reported dead.
    """
    if bool(getattr(supervisor, "is_shut_down", False)):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="unhealthy",
            harness_running=False,
            detail="Harness has been shut down — this instance should be replaced.",
        )
    return HealthResponse(
        status="healthy",
        harness_running=bool(getattr(supervisor, "_is_running", False)),
    )


@router.get("/health/ready", response_model=HealthResponse)
async def readiness_check(
    response: Response,
    supervisor: Any = Depends(get_supervisor),
) -> HealthResponse:
    """Readiness probe — can this instance serve traffic right now?

    Fails once the harness has been shut down, or once the memory subsystem
    has been closed — a closed store means any real request would fail, so
    the instance must leave the load-balancer pool immediately.
    """
    running = bool(getattr(supervisor, "_is_running", False))

    if bool(getattr(supervisor, "is_shut_down", False)):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="not_ready",
            harness_running=False,
            detail="Harness has been shut down.",
        )

    memory = getattr(supervisor, "_memory", None)
    if memory is not None and bool(getattr(memory, "is_closed", False)):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="not_ready",
            harness_running=running,
            detail="Memory subsystem is closed.",
        )

    return HealthResponse(status="ready", harness_running=running)
