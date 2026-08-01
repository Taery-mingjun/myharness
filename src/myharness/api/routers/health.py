"""Health check endpoints for Kubernetes/load-balancer readiness probes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Basic liveness probe.

    Returns 200 OK as long as the API server is running.
    """
    return {"status": "healthy", "service": "myharness"}


@router.get("/health/ready")
async def readiness_check() -> dict[str, str]:
    """Readiness probe.

    Returns 200 OK when the service is ready to accept traffic.
    In MVP, this is always true after startup.
    """
    return {"status": "ready", "service": "myharness"}
