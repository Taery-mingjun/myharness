"""Health check endpoints for Kubernetes/load-balancer probes.

These are the only unauthenticated endpoints, and they are what an
orchestrator trusts to decide whether to keep sending traffic to this
instance — and whether to kill it. The two probes answer different
questions and must not be wired to the same signal.

Previously both returned a hardcoded 200 ("in MVP, this is always true
after startup"). After ``POST /harness/shutdown`` the supervisor was
stopped, memory backends were closed, and every real request failed — yet
both probes still answered 200, so a load balancer kept routing to a dead
instance.

Wiring them to the supervisor then introduced the opposite failure: in the
API's lazy mode, resolving the supervisor builds the whole DI graph, so an
instance with (say) no LLM API key configured raised out of the *liveness*
probe. That gets the instance killed and restarted forever, and a restart
never supplies a missing API key. Liveness therefore tolerates a
supervisor that cannot be constructed; readiness does not.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from myharness.api.dependencies import get_supervisor

router = APIRouter()


class HealthResponse(BaseModel):
    """Liveness/readiness payload."""

    status: str
    service: str = "myharness"
    harness_running: bool
    detail: str | None = None


async def _resolve_supervisor() -> tuple[Any | None, Exception | None]:
    """Resolve the supervisor without letting construction errors escape.

    The probes decide for themselves what an unconstructible supervisor
    means, and they decide differently — so this returns the failure
    instead of raising it.
    """
    try:
        return await get_supervisor(), None
    except Exception as exc:  # noqa: BLE001 — probes must never 500
        return None, exc


def _describe(error: Exception | None) -> str:
    """Render a construction failure for the probe payload.

    The machine-readable code goes first when there is one: that is what
    an operator greps for when a pod is draining and they need to know
    which dependency is missing.
    """
    if error is None:
        return "Harness not constructible."

    code = getattr(error, "code", None)
    prefix = f"[{code}] " if code else ""
    return f"Harness not constructible: {prefix}{error}"


@router.get("/health", response_model=HealthResponse)
async def health_check(response: Response) -> HealthResponse:
    """Liveness probe — should this instance be restarted?

    Returns 200 while the process can still serve. Returns 503 only once
    the harness has been shut down, because that state is terminal
    in-process: the orchestrator must replace the instance.

    Deliberately narrow. A liveness probe that fails on misconfiguration
    or on a missing downstream turns a fixable outage into a restart loop,
    so anything a restart cannot fix belongs in readiness instead.

    Note this keys off *has been shut down*, not *is running*. The API also
    supports a lazy mode where services are resolved from the DI container
    without an explicit boot; such an instance serves perfectly well.
    """
    supervisor, error = await _resolve_supervisor()

    if supervisor is None:
        # The process is alive and its HTTP stack is answering. Whatever
        # is wrong is a configuration or dependency problem that restarting
        # will not fix; readiness is where it drains traffic.
        return HealthResponse(
            status="healthy",
            harness_running=False,
            detail=_describe(error),
        )

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
async def readiness_check(response: Response) -> HealthResponse:
    """Readiness probe — can this instance serve traffic right now?

    Fails when the harness cannot be constructed at all, once it has been
    shut down, or once the memory subsystem has been closed. Each means a
    real request would fail, so the instance must leave the pool — while
    liveness keeps it alive long enough for an operator to fix the cause.
    """
    supervisor, error = await _resolve_supervisor()

    if supervisor is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="not_ready",
            harness_running=False,
            detail=_describe(error),
        )

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
