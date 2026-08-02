# code_dump_5_driver_api.md

本文件为第 5 部分，包含目录: driver, api/

包含文件数: 25

## 文件路径: src/myharness/api/__init__.py

```python
"""MyHarness REST API module.

Provides the FastAPI application factory and all API routers for the
cognitive operating system's HTTP interface.
"""

from myharness.api.app import create_app

__all__ = ["create_app"]
```

## 文件路径: src/myharness/api/app.py

```python
"""FastAPI application factory for MyHarness.

Creates the ASGI application with all routers, middleware, and lifecycle
hooks. Supports both dependency-injected (production) and test-mode
(manual wiring) configurations.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from myharness.api.middleware.error_handler import ErrorHandlerMiddleware
from myharness.api.middleware.tracing import TracingMiddleware

logger = structlog.get_logger(__name__)


def create_app(supervisor: Any = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Application factory pattern — allows creating multiple app instances
    for testing and supports both DI-driven and manually-wired setups.

    If supervisor is None, the app will lazily build one from the DI
    container on first request (via dependencies.py).

    Args:
        supervisor: Optional pre-built HarnessSupervisor instance.
                    If None, DI container handles wiring.

    Returns:
        A fully configured FastAPI application ready to serve.
    """
    # Store supervisor reference for lifespan access
    _supervisor_ref = {"instance": supervisor}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan — handles startup and shutdown."""
        sv = _supervisor_ref["instance"]

        # On startup
        if sv is not None:
            logger.info("api_startup_with_supervisor")
            try:
                await sv.boot()
                logger.info("supervisor_booted_in_api")
            except Exception:
                logger.exception("supervisor_boot_failed")
        else:
            logger.info(
                "api_startup_without_supervisor",
                hint="Supervisor will be created lazily from DI container on first request.",
            )

        yield

        # On shutdown
        if sv is not None:
            logger.info("api_shutdown")
            try:
                await sv.shutdown()
                logger.info("supervisor_shutdown_complete")
            except Exception:
                logger.exception("supervisor_shutdown_failed")

    app = FastAPI(
        title="MyHarness API",
        description=(
            "Cognitive Operating System — REST API. "
            "MyHarness implements a four-power-separation architecture "
            "(LLM / Memory / Skill / Execution) for AI agents."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS — permissive for development, tighten for production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom middleware
    app.add_middleware(TracingMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)

    # Register API routers
    from myharness.api.routers import cognitive, memory, skill, driver, harness, health

    app.include_router(cognitive.router, prefix="/api/v1/cognitive", tags=["Cognitive"])
    app.include_router(memory.router, prefix="/api/v1/memory", tags=["Memory"])
    app.include_router(skill.router, prefix="/api/v1/skill", tags=["Skill"])
    app.include_router(driver.router, prefix="/api/v1/driver", tags=["Driver"])
    app.include_router(harness.router, prefix="/api/v1/harness", tags=["Harness"])
    app.include_router(health.router, tags=["Health"])

    logger.info("api_app_created", version="0.1.0")
    return app
```

## 文件路径: src/myharness/api/dependencies.py

```python
"""FastAPI dependency injection layer.

Provides async dependency callables for FastAPI's Depends() system.
Each function resolves its service from the lagom DI container built
by build_container() in myharness.core.di.

The container is cached via lru_cache so it's built once per process.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from myharness.core.config import get_settings

if TYPE_CHECKING:
    from lagom import Container
    from myharness.bus.dispatcher import EventBus
    from myharness.harness.supervisor import HarnessSupervisor
    from myharness.llm.engine import LLMEngine
    from myharness.memory.interface import MemorySystem
    from myharness.skill.store import SkillStore


@lru_cache(maxsize=1)
def get_container() -> "Container":
    """Build and cache the DI container.

    The container is built once per process and cached. This ensures
    all FastAPI dependency resolutions share the same service instances
    (singleton scope).

    Returns:
        The configured lagom Container instance.
    """
    settings = get_settings()
    # Defer import to avoid circular dependency at module level
    from myharness.core.di import build_container

    return build_container(settings)


async def get_supervisor() -> "HarnessSupervisor":
    """Resolve the HarnessSupervisor from the DI container.

    The supervisor is the central orchestrator. All cognitive operations
    flow through it.

    Returns:
        The singleton HarnessSupervisor instance.
    """
    container = get_container()
    from myharness.harness.supervisor import HarnessSupervisor

    return container.resolve(HarnessSupervisor)


async def get_memory() -> "MemorySystem":
    """Resolve the MemorySystem from the DI container.

    Returns:
        The singleton MemorySystem (MemoryManager) instance.
    """
    container = get_container()
    from myharness.memory.interface import MemorySystem

    return container.resolve(MemorySystem)


async def get_llm_engine() -> "LLMEngine":
    """Resolve the LLMEngine from the DI container.

    Returns:
        The singleton LLMEngine instance.
    """
    container = get_container()
    from myharness.llm.engine import LLMEngine

    return container.resolve(LLMEngine)


async def get_skill_store() -> "SkillStore":
    """Resolve the SkillStore from the DI container.

    Returns:
        The singleton SkillStore instance.
    """
    container = get_container()
    from myharness.skill.store import SkillStore

    return container.resolve(SkillStore)


async def get_event_bus() -> "EventBus":
    """Resolve the EventBus from the DI container.

    Returns:
        The singleton EventBus instance.
    """
    container = get_container()
    from myharness.bus.dispatcher import EventBus

    return container.resolve(EventBus)
```

## 文件路径: src/myharness/api/middleware/__init__.py

```python
"""API middleware — HTTP-level request/response interceptors."""

from myharness.api.middleware.tracing import TracingMiddleware
from myharness.api.middleware.error_handler import ErrorHandlerMiddleware

__all__ = ["TracingMiddleware", "ErrorHandlerMiddleware"]
```

## 文件路径: src/myharness/api/middleware/error_handler.py

```python
"""Global error handler middleware — catches unhandled exceptions in HTTP handlers."""

from __future__ import annotations

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from myharness.core.exceptions import MyHarnessError

logger = structlog.get_logger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Global error handler for unhandled exceptions.

    Catches all unhandled exceptions from route handlers and converts
    them to structured JSON error responses. MyHarnessError subclasses
    include their error code and details in the response.

    Unexpected exceptions (not MyHarnessError) return a generic 500
    without leaking internal details.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except MyHarnessError as exc:
            logger.warning(
                "domain_error_in_http",
                error_type=type(exc).__name__,
                error_code=exc.code,
                error_message=exc.message,
                path=request.url.path,
                method=request.method,
            )
            return JSONResponse(
                status_code=self._http_status_for(exc),
                content={
                    "error": {
                        "type": type(exc).__name__,
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                },
            )
        except Exception as exc:
            logger.error(
                "unhandled_error_in_http",
                error_type=type(exc).__name__,
                error_message=str(exc),
                path=request.url.path,
                method=request.method,
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "type": "InternalServerError",
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred.",
                    }
                },
            )

    @staticmethod
    def _http_status_for(exc: MyHarnessError) -> int:
        """Map MyHarnessError subclasses to HTTP status codes.

        Args:
            exc: The domain exception to map.

        Returns:
            An appropriate HTTP status code.
        """
        from myharness.core.exceptions import (
            MemoryNotFoundError,
            SkillNotFoundError,
            DriverNotAvailableError,
            CapabilityNotFoundError,
            ProviderNotAvailableError,
            SkillValidationError,
            SkillLifecycleError,
            IdentityConflictError,
        )

        # 404 — not found
        if isinstance(exc, (MemoryNotFoundError, SkillNotFoundError, CapabilityNotFoundError)):
            return 404

        # 503 — service unavailable
        if isinstance(exc, (DriverNotAvailableError, ProviderNotAvailableError)):
            return 503

        # 409 — conflict
        if isinstance(exc, IdentityConflictError):
            return 409

        # 422 — unprocessable entity (validation)
        if isinstance(exc, (SkillValidationError, SkillLifecycleError)):
            return 422

        # Default: 400 bad request
        return 400
```

## 文件路径: src/myharness/api/middleware/tracing.py

```python
"""Tracing middleware — injects request IDs and correlation headers."""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

_REQUEST_ID_HEADER = "X-Request-ID"
_CORRELATION_ID_HEADER = "X-Correlation-ID"


class TracingMiddleware(BaseHTTPMiddleware):
    """Add request ID and correlation ID to every HTTP request/response.

    If the client provides an X-Request-ID header, it is reused.
    Otherwise, a new UUIDv4 is generated. Both the request ID and
    correlation ID are attached to the structlog context for the
    duration of the request.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate request ID
        request_id = request.headers.get(
            _REQUEST_ID_HEADER, str(uuid.uuid4())
        )
        correlation_id = request.headers.get(
            _CORRELATION_ID_HEADER, str(uuid.uuid4())
        )

        # Bind to structlog context
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            correlation_id=correlation_id,
        )

        # Process the request
        response = await call_next(request)

        # Echo back the IDs in response headers
        response.headers[_REQUEST_ID_HEADER] = request_id
        response.headers[_CORRELATION_ID_HEADER] = correlation_id

        # Clean up context
        structlog.contextvars.unbind_contextvars("request_id", "correlation_id")

        return response
```

## 文件路径: src/myharness/api/routers/__init__.py

```python
"""API routers — REST endpoints for all MyHarness subsystems.

Each submodule exposes a FastAPI APIRouter instance named `router`
that is included in the main application.
"""

# Re-exports for convenience
from myharness.api.routers import cognitive, memory, skill, driver, harness, health

__all__ = ["cognitive", "memory", "skill", "driver", "harness", "health"]
```

## 文件路径: src/myharness/api/routers/cognitive.py

```python
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
```

## 文件路径: src/myharness/api/routers/driver.py

```python
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
```

## 文件路径: src/myharness/api/routers/harness.py

```python
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
```

## 文件路径: src/myharness/api/routers/health.py

```python
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
```

## 文件路径: src/myharness/api/routers/memory.py

```python
"""Memory system API — identity, episodes, knowledge, relationships."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from myharness.api.dependencies import get_memory
from myharness.schema.memory import MemoryQuery, MemorySearchResult

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
    """Request to update the agent's identity."""

    core_values: list[str] | None = None
    mission: str | None = None
    preferences: dict[str, Any] | None = None
    self_description: str | None = None
    behavioral_guidelines: list[str] | None = None


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

    Accepts partial updates — only provided fields are modified.
    The version number increments automatically on each update.
    """
    current = await memory.get_identity()

    # Apply partial updates
    from myharness.schema.memory import IdentityEntry

    updated_data = current.model_dump()
    update_dict = update.model_dump(exclude_unset=True)
    updated_data.update(update_dict)
    updated_data["version"] = current.version + 1

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


@router.get("/episodes/recent")
async def get_recent_episodes(
    limit: int = Query(default=50, ge=1, le=500, description="Max episodes to return"),
    memory=Depends(get_memory),
) -> dict[str, list[dict[str, Any]]]:
    """Get the most recent episodic memories."""
    episodes = await memory.get_recent_episodes(limit)
    return {
        "episodes": [e.model_dump(mode="json") for e in episodes],
        "count": len(episodes),
    }


# ── Stats & Maintenance ──────────────────────────────────────────────────


@router.get("/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(memory=Depends(get_memory)) -> MemoryStatsResponse:
    """Get aggregate statistics from all memory stores.

    Returns counts and metadata for each store plus index status.
    """
    stats = await memory.get_stats()
    return MemoryStatsResponse(**stats)


@router.post("/rebuild")
async def rebuild_indexes(memory=Depends(get_memory)) -> dict[str, str]:
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
```

## 文件路径: src/myharness/api/routers/skill.py

```python
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
```

## 文件路径: src/myharness/driver/__init__.py

```python
"""Driver Layer — unified execution protocol and adapter implementations.

Implements P7 (Protocol over Implementation): a unified driver protocol
that abstracts away hardware/platform details. Upper layers (LLM, Skill)
never know about specific driver implementations.

Provides:
- UnifiedDriverProtocol: Abstract interface all drivers implement.
- DriverManager: Registry and lifecycle management for drivers.
- CapabilityDiscovery: Discovers capabilities from registered drivers.
- ActionTranslator: Translates high-level actions to driver-specific calls.
- Adapters: Concrete driver implementations (API, Browser, Database, etc.).
"""

from myharness.driver.protocol import UnifiedDriverProtocol, DriverManager
from myharness.driver.capability import CapabilityDiscovery
from myharness.driver.translation import ActionTranslator
from myharness.schema.driver import ExecutionResult, ExecutionProgress

__all__ = [
    "UnifiedDriverProtocol",
    "DriverManager",
    "CapabilityDiscovery",
    "ActionTranslator",
    "ExecutionResult",
    "ExecutionProgress",
]
```

## 文件路径: src/myharness/driver/adapters/__init__.py

```python
"""Driver adapters — concrete implementations of the UnifiedDriverProtocol.

Each adapter wraps a specific execution target (API, browser, database,
robot, MCP, computer, IoT) behind the unified protocol interface.

Provides a factory function for creating adapters by type.
"""

from __future__ import annotations

from myharness.driver.adapters.api import APIDriver
from myharness.driver.adapters.browser import BrowserDriver
from myharness.driver.adapters.database import DatabaseDriver
from myharness.driver.adapters.robot import RobotDriver
from myharness.driver.adapters.mcp import MCPDriver
from myharness.driver.adapters.computer import ComputerDriver
from myharness.driver.adapters.iot import IoTDriver
from myharness.driver.protocol import UnifiedDriverProtocol

__all__ = [
    "APIDriver",
    "BrowserDriver",
    "DatabaseDriver",
    "RobotDriver",
    "MCPDriver",
    "ComputerDriver",
    "IoTDriver",
    "create_adapter",
]


def create_adapter(driver_type: str, **kwargs) -> UnifiedDriverProtocol:
    """Factory function to create a driver adapter by type.

    Args:
        driver_type: The type of driver to create. One of:
            'api', 'browser', 'database', 'robot', 'mcp', 'computer', 'iot'.
        **kwargs: Additional keyword arguments passed to the adapter constructor.

    Returns:
        A UnifiedDriverProtocol instance.

    Raises:
        ValueError: If the driver type is unknown.
    """
    adapters: dict[str, type[UnifiedDriverProtocol]] = {
        "api": APIDriver,
        "browser": BrowserDriver,
        "database": DatabaseDriver,
        "robot": RobotDriver,
        "mcp": MCPDriver,
        "computer": ComputerDriver,
        "iot": IoTDriver,
    }

    adapter_cls = adapters.get(driver_type.lower())
    if adapter_cls is None:
        raise ValueError(
            f"Unknown driver type: '{driver_type}'. "
            f"Must be one of: {list(adapters.keys())}"
        )

    return adapter_cls(**kwargs)
```

## 文件路径: src/myharness/driver/adapters/api.py

```python
"""REST API execution driver using httpx.

Provides HTTP-based execution for skills that interact with REST APIs.
Supports GET, POST, PUT, PATCH, DELETE methods with configurable base URL,
headers, and authentication.
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

import httpx
import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="http_request",
        description="Make HTTP requests to REST APIs",
        driver_name="api",
        actions=[
            CapabilityAction(
                name="get",
                description="HTTP GET request",
                parameters={"url": "string", "params": "object"},
            ),
            CapabilityAction(
                name="post",
                description="HTTP POST request",
                parameters={"url": "string", "body": "object"},
            ),
            CapabilityAction(
                name="put",
                description="HTTP PUT request",
                parameters={"url": "string", "body": "object"},
            ),
            CapabilityAction(
                name="patch",
                description="HTTP PATCH request",
                parameters={"url": "string", "body": "object"},
            ),
            CapabilityAction(
                name="delete",
                description="HTTP DELETE request",
                parameters={"url": "string"},
            ),
        ],
    ),
]


class APIDriver(UnifiedDriverProtocol):
    """REST API execution driver using httpx.

    Provides HTTP-based execution for skills that interact with REST APIs.
    Uses httpx.AsyncClient for async HTTP calls with connection pooling,
    timeout handling, and retry support.
    """

    def __init__(
        self,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the API driver.

        Args:
            base_url: Base URL for all API requests.
            headers: Default headers for all requests.
            timeout: Request timeout in seconds.
        """
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._initialized = False

        self._capabilities = _DEFAULT_CAPABILITIES
        # Update driver name in capabilities
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "api_driver_created",
            base_url=base_url,
            driver_name=self.driver_name,
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "api"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the driver — create the HTTP client."""
        if self._initialized:
            return

        self._client = httpx.AsyncClient(
            base_url=self._base_url or None,
            headers=self._headers,
            timeout=httpx.Timeout(self._timeout),
        )
        self._initialized = True
        logger.info("api_driver_initialized", base_url=self._base_url)

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an HTTP action.

        Supported actions: get, post, put, patch, delete.

        Args:
            action: The HTTP method or action name.
            parameters: Must include 'url' and optionally 'body'/'params'.
            context: Optional execution context.

        Returns:
            An ExecutionResult with the HTTP response.
        """
        if self._client is None:
            return ExecutionResult(
                success=False,
                error="Driver not initialized",
                metadata={"driver_name": self.driver_name},
            )

        start = time.monotonic()
        try:
            url = parameters.get("url", "")
            params = parameters.get("params", None)
            body = parameters.get("body", None)
            extra_headers = parameters.get("headers", None)

            method = action.lower()
            response: httpx.Response

            if method == "get":
                response = await self._client.get(
                    url, params=params, headers=extra_headers
                )
            elif method == "post":
                response = await self._client.post(
                    url, json=body, params=params, headers=extra_headers
                )
            elif method == "put":
                response = await self._client.put(
                    url, json=body, params=params, headers=extra_headers
                )
            elif method == "patch":
                response = await self._client.patch(
                    url, json=body, params=params, headers=extra_headers
                )
            elif method == "delete":
                response = await self._client.delete(
                    url, params=params, headers=extra_headers
                )
            else:
                return ExecutionResult(
                    success=False,
                    error=f"Unsupported HTTP method: {action}",
                    metadata={"driver_name": self.driver_name},
                )

            duration_ms = (time.monotonic() - start) * 1000

            try:
                response_data = response.json()
            except ValueError:
                response_data = response.text

            success = 200 <= response.status_code < 300

            return ExecutionResult(
                success=success,
                output=response_data,
                error=(
                    f"HTTP {response.status_code}: {response.reason_phrase}"
                    if not success
                    else None
                ),
                duration_ms=duration_ms,
                metadata={
                    "status_code": response.status_code,
                    "url": str(response.url),
                    "method": method,
                },
            )

        except httpx.TimeoutException as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return ExecutionResult(
                success=False,
                error=f"Request timeout: {exc}",
                duration_ms=duration_ms,
                metadata={"driver_name": self.driver_name},
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                "api_execution_error",
                action=action,
                error=str(exc),
            )
            return ExecutionResult(
                success=False,
                error=str(exc),
                duration_ms=duration_ms,
                metadata={"driver_name": self.driver_name},
            )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute an HTTP action with streaming progress.

        For API calls, streaming is simulated — the entire request
        completes before yielding progress.

        Args:
            action: The HTTP method.
            parameters: Request parameters.
            context: Optional execution context.

        Yields:
            ExecutionProgress updates.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=0.0,
            status="running",
            message="Starting HTTP request...",
        )

        yield ExecutionProgress(
            action=action,
            progress_pct=50.0,
            status="running",
            message="Waiting for response...",
        )

        result = await self.execute(action, parameters, context)

        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message="Request complete" if result.success else f"Error: {result.error}",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense API state — perform a health check request.

        Args:
            capability: The capability to sense.

        Returns:
            A dictionary with the API status.
        """
        if capability == "health" or capability == "status":
            if self._client is None:
                return {"connected": False, "error": "Not initialized"}
            try:
                response = await self._client.get("/")
                return {
                    "connected": True,
                    "status_code": response.status_code,
                    "base_url": self._base_url,
                }
            except Exception as exc:
                return {"connected": False, "error": str(exc)}
        return {"capability": capability, "available": False}

    async def health_check(self) -> bool:
        """Check if the API driver is healthy.

        Returns:
            True if the client is initialized.
        """
        return self._initialized and self._client is not None

    async def shutdown(self) -> None:
        """Gracefully shutdown the driver, closing the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._initialized = False
        logger.info("api_driver_shutdown")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the API driver.

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "initialized": self._initialized,
            "base_url": self._base_url,
            "capabilities_count": len(self._capabilities),
        }
```

## 文件路径: src/myharness/driver/adapters/browser.py

```python
"""Browser automation driver (Playwright). Stub implementation for MVP.

Provides browser-based execution for skills that interact with web pages.
In the MVP, this is a stub that returns ExecutionResult with success=False.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="browser_automation",
        description="Automate web browser interactions",
        driver_name="browser",
        actions=[
            CapabilityAction(name="navigate", description="Navigate to a URL"),
            CapabilityAction(name="click", description="Click an element"),
            CapabilityAction(name="type_text", description="Type text into an input"),
            CapabilityAction(name="screenshot", description="Take a screenshot"),
            CapabilityAction(name="extract_text", description="Extract text from page"),
            CapabilityAction(name="wait_for", description="Wait for an element"),
        ],
    ),
]


class BrowserDriver(UnifiedDriverProtocol):
    """Browser automation driver (Playwright). Stub implementation for MVP.

    In the full implementation, this would use Playwright for browser
    automation. For the MVP, it returns a stub ExecutionResult.
    """

    def __init__(self) -> None:
        """Initialize the browser driver (stub)."""
        self._capabilities = _DEFAULT_CAPABILITIES
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "browser_driver_created",
            driver_name=self.driver_name,
            note="stub_implementation",
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "browser"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the browser driver (stub — no-op)."""
        logger.info("browser_driver_initialized", note="stub")

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute a browser action (stub).

        Args:
            action: The browser action.
            parameters: Action parameters.
            context: Optional execution context.

        Returns:
            An ExecutionResult indicating the stub status.
        """
        logger.debug(
            "browser_execute_stub",
            action=action,
            parameters_keys=list(parameters.keys()),
        )
        return ExecutionResult(
            success=False,
            error=f"BrowserDriver is a stub — action '{action}' not implemented",
            metadata={
                "driver_name": self.driver_name,
                "driver_version": self.driver_version,
                "status": "stub",
            },
        )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute a browser action with streaming (stub).

        Args:
            action: The browser action.
            parameters: Action parameters.
            context: Optional execution context.

        Yields:
            A single progress update indicating stub status.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message=f"BrowserDriver is a stub — action '{action}' not implemented",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense browser state (stub).

        Args:
            capability: The capability to sense.

        Returns:
            A stub response.
        """
        return {
            "capability": capability,
            "available": False,
            "status": "stub",
            "driver_name": self.driver_name,
        }

    async def health_check(self) -> bool:
        """Check if the browser driver is healthy (stub).

        Returns:
            Always False for the stub.
        """
        return False

    async def shutdown(self) -> None:
        """Shutdown the browser driver (stub — no-op)."""
        logger.info("browser_driver_shutdown", note="stub")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the browser driver (stub).

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "status": "stub",
            "capabilities_count": len(self._capabilities),
        }
```

## 文件路径: src/myharness/driver/adapters/computer.py

```python
"""Computer Use driver. Stub implementation for MVP.

Provides computer interaction capabilities for skills that control
desktop applications, file systems, and system commands. In the MVP,
this is a stub.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="computer_control",
        description="Control computer desktop and applications",
        driver_name="computer",
        actions=[
            CapabilityAction(name="click", description="Click at screen coordinates"),
            CapabilityAction(name="type_text", description="Type text via keyboard"),
            CapabilityAction(name="screenshot", description="Capture screen"),
            CapabilityAction(name="run_command", description="Execute shell command"),
            CapabilityAction(name="open_app", description="Open an application"),
            CapabilityAction(name="read_file", description="Read a file from disk"),
            CapabilityAction(name="write_file", description="Write a file to disk"),
        ],
    ),
]


class ComputerDriver(UnifiedDriverProtocol):
    """Computer Use driver. Stub implementation for MVP.

    In the full implementation, this would use platform-specific APIs
    (pyautogui, xdotool, etc.) for computer interaction. For the MVP,
    it returns a stub ExecutionResult.
    """

    def __init__(self) -> None:
        """Initialize the computer driver (stub)."""
        self._capabilities = _DEFAULT_CAPABILITIES
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "computer_driver_created",
            driver_name=self.driver_name,
            note="stub_implementation",
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "computer"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the computer driver (stub — no-op)."""
        logger.info("computer_driver_initialized", note="stub")

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute a computer action (stub).

        Args:
            action: The computer action.
            parameters: Action parameters.
            context: Optional execution context.

        Returns:
            An ExecutionResult indicating the stub status.
        """
        logger.debug(
            "computer_execute_stub",
            action=action,
            parameters_keys=list(parameters.keys()),
        )
        return ExecutionResult(
            success=False,
            error=f"ComputerDriver is a stub — action '{action}' not implemented",
            metadata={
                "driver_name": self.driver_name,
                "driver_version": self.driver_version,
                "status": "stub",
            },
        )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute a computer action with streaming (stub).

        Args:
            action: The computer action.
            parameters: Action parameters.
            context: Optional execution context.

        Yields:
            A single progress update indicating stub status.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message=f"ComputerDriver is a stub — action '{action}' not implemented",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense computer state (stub).

        Args:
            capability: The capability to sense.

        Returns:
            A stub response.
        """
        return {
            "capability": capability,
            "available": False,
            "status": "stub",
            "driver_name": self.driver_name,
        }

    async def health_check(self) -> bool:
        """Check if the computer driver is healthy (stub).

        Returns:
            Always False for the stub.
        """
        return False

    async def shutdown(self) -> None:
        """Shutdown the computer driver (stub — no-op)."""
        logger.info("computer_driver_shutdown", note="stub")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the computer driver (stub).

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "status": "stub",
            "capabilities_count": len(self._capabilities),
        }
```

## 文件路径: src/myharness/driver/adapters/database.py

```python
"""Database execution driver. Stub implementation for MVP.

Provides database-based execution for skills that interact with SQL
or NoSQL databases. In the MVP, this is a stub.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="database_query",
        description="Execute database queries and operations",
        driver_name="database",
        actions=[
            CapabilityAction(name="query", description="Execute a SELECT query"),
            CapabilityAction(name="execute", description="Execute an INSERT/UPDATE/DELETE"),
            CapabilityAction(name="migrate", description="Run schema migrations"),
            CapabilityAction(name="backup", description="Create a database backup"),
        ],
    ),
]


class DatabaseDriver(UnifiedDriverProtocol):
    """Database execution driver. Stub implementation for MVP.

    In the full implementation, this would connect to databases via
    async drivers (asyncpg, aiomysql, etc.). For the MVP, it returns
    a stub ExecutionResult.
    """

    def __init__(self) -> None:
        """Initialize the database driver (stub)."""
        self._capabilities = _DEFAULT_CAPABILITIES
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "database_driver_created",
            driver_name=self.driver_name,
            note="stub_implementation",
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "database"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the database driver (stub — no-op)."""
        logger.info("database_driver_initialized", note="stub")

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute a database action (stub).

        Args:
            action: The database action.
            parameters: Action parameters.
            context: Optional execution context.

        Returns:
            An ExecutionResult indicating the stub status.
        """
        logger.debug(
            "database_execute_stub",
            action=action,
            parameters_keys=list(parameters.keys()),
        )
        return ExecutionResult(
            success=False,
            error=f"DatabaseDriver is a stub — action '{action}' not implemented",
            metadata={
                "driver_name": self.driver_name,
                "driver_version": self.driver_version,
                "status": "stub",
            },
        )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute a database action with streaming (stub).

        Args:
            action: The database action.
            parameters: Action parameters.
            context: Optional execution context.

        Yields:
            A single progress update indicating stub status.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message=f"DatabaseDriver is a stub — action '{action}' not implemented",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense database state (stub).

        Args:
            capability: The capability to sense.

        Returns:
            A stub response.
        """
        return {
            "capability": capability,
            "available": False,
            "status": "stub",
            "driver_name": self.driver_name,
        }

    async def health_check(self) -> bool:
        """Check if the database driver is healthy (stub).

        Returns:
            Always False for the stub.
        """
        return False

    async def shutdown(self) -> None:
        """Shutdown the database driver (stub — no-op)."""
        logger.info("database_driver_shutdown", note="stub")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the database driver (stub).

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "status": "stub",
            "capabilities_count": len(self._capabilities),
        }
```

## 文件路径: src/myharness/driver/adapters/iot.py

```python
"""IoT/MQTT driver. Stub implementation for MVP.

Provides IoT device interaction capabilities for skills that control
sensors, actuators, and smart devices via MQTT or other IoT protocols.
In the MVP, this is a stub.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="iot_device_control",
        description="Control IoT devices via MQTT or other protocols",
        driver_name="iot",
        actions=[
            CapabilityAction(name="publish", description="Publish to an MQTT topic"),
            CapabilityAction(name="subscribe", description="Subscribe to an MQTT topic"),
            CapabilityAction(name="set_device_state", description="Set a device state"),
            CapabilityAction(name="get_device_state", description="Get current device state"),
            CapabilityAction(name="discover_devices", description="Discover nearby IoT devices"),
        ],
    ),
]


class IoTDriver(UnifiedDriverProtocol):
    """IoT/MQTT driver. Stub implementation for MVP.

    In the full implementation, this would connect to MQTT brokers
    and IoT platforms using async MQTT clients (aiomqtt, etc.).
    For the MVP, it returns a stub ExecutionResult.
    """

    def __init__(self) -> None:
        """Initialize the IoT driver (stub)."""
        self._capabilities = _DEFAULT_CAPABILITIES
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "iot_driver_created",
            driver_name=self.driver_name,
            note="stub_implementation",
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "iot"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the IoT driver (stub — no-op)."""
        logger.info("iot_driver_initialized", note="stub")

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an IoT action (stub).

        Args:
            action: The IoT action.
            parameters: Action parameters.
            context: Optional execution context.

        Returns:
            An ExecutionResult indicating the stub status.
        """
        logger.debug(
            "iot_execute_stub",
            action=action,
            parameters_keys=list(parameters.keys()),
        )
        return ExecutionResult(
            success=False,
            error=f"IoTDriver is a stub — action '{action}' not implemented",
            metadata={
                "driver_name": self.driver_name,
                "driver_version": self.driver_version,
                "status": "stub",
            },
        )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute an IoT action with streaming (stub).

        Args:
            action: The IoT action.
            parameters: Action parameters.
            context: Optional execution context.

        Yields:
            A single progress update indicating stub status.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message=f"IoTDriver is a stub — action '{action}' not implemented",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense IoT device state (stub).

        Args:
            capability: The capability to sense.

        Returns:
            A stub response.
        """
        return {
            "capability": capability,
            "available": False,
            "status": "stub",
            "driver_name": self.driver_name,
        }

    async def health_check(self) -> bool:
        """Check if the IoT driver is healthy (stub).

        Returns:
            Always False for the stub.
        """
        return False

    async def shutdown(self) -> None:
        """Shutdown the IoT driver (stub — no-op)."""
        logger.info("iot_driver_shutdown", note="stub")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the IoT driver (stub).

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "status": "stub",
            "capabilities_count": len(self._capabilities),
        }
```

## 文件路径: src/myharness/driver/adapters/mcp.py

```python
"""MCP (Model Context Protocol) driver. Stub implementation for MVP.

Provides MCP-based execution for skills that interact with MCP servers.
In the MVP, this is a stub.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="mcp_tool_call",
        description="Call tools on MCP servers",
        driver_name="mcp",
        actions=[
            CapabilityAction(name="call_tool", description="Call an MCP tool"),
            CapabilityAction(name="list_tools", description="List available MCP tools"),
            CapabilityAction(name="get_resource", description="Read an MCP resource"),
            CapabilityAction(name="list_resources", description="List MCP resources"),
        ],
    ),
]


class MCPDriver(UnifiedDriverProtocol):
    """MCP protocol driver. Stub implementation for MVP.

    In the full implementation, this would connect to MCP servers
    using the Model Context Protocol. For the MVP, it returns a stub
    ExecutionResult.
    """

    def __init__(self) -> None:
        """Initialize the MCP driver (stub)."""
        self._capabilities = _DEFAULT_CAPABILITIES
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "mcp_driver_created",
            driver_name=self.driver_name,
            note="stub_implementation",
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "mcp"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the MCP driver (stub — no-op)."""
        logger.info("mcp_driver_initialized", note="stub")

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an MCP action (stub).

        Args:
            action: The MCP action.
            parameters: Action parameters.
            context: Optional execution context.

        Returns:
            An ExecutionResult indicating the stub status.
        """
        logger.debug(
            "mcp_execute_stub",
            action=action,
            parameters_keys=list(parameters.keys()),
        )
        return ExecutionResult(
            success=False,
            error=f"MCPDriver is a stub — action '{action}' not implemented",
            metadata={
                "driver_name": self.driver_name,
                "driver_version": self.driver_version,
                "status": "stub",
            },
        )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute an MCP action with streaming (stub).

        Args:
            action: The MCP action.
            parameters: Action parameters.
            context: Optional execution context.

        Yields:
            A single progress update indicating stub status.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message=f"MCPDriver is a stub — action '{action}' not implemented",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense MCP state (stub).

        Args:
            capability: The capability to sense.

        Returns:
            A stub response.
        """
        return {
            "capability": capability,
            "available": False,
            "status": "stub",
            "driver_name": self.driver_name,
        }

    async def health_check(self) -> bool:
        """Check if the MCP driver is healthy (stub).

        Returns:
            Always False for the stub.
        """
        return False

    async def shutdown(self) -> None:
        """Shutdown the MCP driver (stub — no-op)."""
        logger.info("mcp_driver_shutdown", note="stub")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the MCP driver (stub).

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "status": "stub",
            "capabilities_count": len(self._capabilities),
        }
```

## 文件路径: src/myharness/driver/adapters/robot.py

```python
"""Robot execution driver. Stub implementation for MVP.

Provides robot-based execution for skills that control physical robots
or robotic simulators. In the MVP, this is a stub.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityAction, CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress

logger = structlog.get_logger(__name__)

_DEFAULT_CAPABILITIES = [
    CapabilityDescriptor(
        name="robot_motion",
        description="Control robot motion and joints",
        driver_name="robot",
        actions=[
            CapabilityAction(name="move_joint", description="Move a single joint"),
            CapabilityAction(name="move_to", description="Move end effector to position"),
            CapabilityAction(name="grasp", description="Grasp an object"),
            CapabilityAction(name="release", description="Release grasped object"),
            CapabilityAction(name="home", description="Move to home position"),
        ],
    ),
    CapabilityDescriptor(
        name="robot_sensing",
        description="Read robot sensors",
        driver_name="robot",
        actions=[
            CapabilityAction(name="read_joint_states", description="Read all joint angles"),
            CapabilityAction(name="read_force_torque", description="Read force/torque sensor"),
            CapabilityAction(name="read_camera", description="Capture camera image"),
        ],
    ),
]


class RobotDriver(UnifiedDriverProtocol):
    """Robot execution driver. Stub implementation for MVP.

    In the full implementation, this would connect to robot hardware
    via ROS, MoveIt, or proprietary APIs. For the MVP, it returns a
    stub ExecutionResult.
    """

    def __init__(self) -> None:
        """Initialize the robot driver (stub)."""
        self._capabilities = _DEFAULT_CAPABILITIES
        for cap in self._capabilities:
            cap.driver_name = self.driver_name

        logger.info(
            "robot_driver_created",
            driver_name=self.driver_name,
            note="stub_implementation",
        )

    @property
    def driver_name(self) -> str:
        """Unique driver name."""
        return "robot"

    @property
    def driver_version(self) -> str:
        """Driver version."""
        return "0.1.0"

    @property
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        return self._capabilities

    async def initialize(self) -> None:
        """Initialize the robot driver (stub — no-op)."""
        logger.info("robot_driver_initialized", note="stub")

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute a robot action (stub).

        Args:
            action: The robot action.
            parameters: Action parameters.
            context: Optional execution context.

        Returns:
            An ExecutionResult indicating the stub status.
        """
        logger.debug(
            "robot_execute_stub",
            action=action,
            parameters_keys=list(parameters.keys()),
        )
        return ExecutionResult(
            success=False,
            error=f"RobotDriver is a stub — action '{action}' not implemented",
            metadata={
                "driver_name": self.driver_name,
                "driver_version": self.driver_version,
                "status": "stub",
            },
        )

    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute a robot action with streaming (stub).

        Args:
            action: The robot action.
            parameters: Action parameters.
            context: Optional execution context.

        Yields:
            A single progress update indicating stub status.
        """
        yield ExecutionProgress(
            action=action,
            progress_pct=100.0,
            status="finalizing",
            message=f"RobotDriver is a stub — action '{action}' not implemented",
        )

    async def sense(self, capability: str) -> dict[str, Any]:
        """Sense robot state (stub).

        Args:
            capability: The capability to sense.

        Returns:
            A stub response.
        """
        return {
            "capability": capability,
            "available": False,
            "status": "stub",
            "driver_name": self.driver_name,
        }

    async def health_check(self) -> bool:
        """Check if the robot driver is healthy (stub).

        Returns:
            Always False for the stub.
        """
        return False

    async def shutdown(self) -> None:
        """Shutdown the robot driver (stub — no-op)."""
        logger.info("robot_driver_shutdown", note="stub")

    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the robot driver (stub).

        Returns:
            A dictionary with driver status.
        """
        return {
            "driver_name": self.driver_name,
            "driver_version": self.driver_version,
            "status": "stub",
            "capabilities_count": len(self._capabilities),
        }
```

## 文件路径: src/myharness/driver/capability.py

```python
"""Capability discovery from registered drivers.

Discovers what each driver can do by inspecting its capabilities list
and provides matching services for the cognitive layer.
"""

from __future__ import annotations

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol
from myharness.schema.capability import CapabilityDescriptor

logger = structlog.get_logger(__name__)


class CapabilityDiscovery:
    """Discovers capabilities from registered drivers.

    Capabilities are discovered (not declared) — each driver reports
    its capabilities, and this class aggregates and matches them for
    the cognitive layer.
    """

    def __init__(self) -> None:
        """Initialize the capability discovery service."""
        logger.info("capability_discovery_initialized")

    async def discover_from_driver(
        self, driver: UnifiedDriverProtocol
    ) -> list[CapabilityDescriptor]:
        """Discover capabilities from a single driver.

        Args:
            driver: The driver to inspect.

        Returns:
            A list of capability descriptors from the driver.
        """
        caps = driver.capabilities
        logger.debug(
            "capabilities_discovered",
            driver_name=driver.driver_name,
            count=len(caps),
        )
        return caps

    async def match_capability(
        self,
        required: str,
        available: list[CapabilityDescriptor],
    ) -> CapabilityDescriptor | None:
        """Find the best matching capability from available options.

        Matching is case-insensitive. Returns the first exact name match,
        or the first partial name match.

        Args:
            required: The required capability name.
            available: List of available capability descriptors.

        Returns:
            The matching capability descriptor, or None if no match.
        """
        required_lower = required.lower()

        # Exact match
        for cap in available:
            if cap.name.lower() == required_lower:
                return cap

        # Partial match
        for cap in available:
            if required_lower in cap.name.lower():
                return cap

        logger.debug(
            "no_capability_match",
            required=required,
            available=[c.name for c in available],
        )
        return None
```

## 文件路径: src/myharness/driver/protocol.py

```python
"""Unified execution driver protocol and driver manager.

All execution drivers implement the UnifiedDriverProtocol, which provides
a consistent interface for the cognitive layer regardless of the underlying
execution target (robot, browser, API, database, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import structlog

from myharness.core.exceptions import DriverError, DriverNotAvailableError
from myharness.schema.capability import CapabilityDescriptor
from myharness.schema.driver import ExecutionResult, ExecutionProgress

logger = structlog.get_logger(__name__)


class UnifiedDriverProtocol(ABC):
    """Unified execution driver protocol.

    All drivers implement this protocol, providing a consistent interface
    for the cognitive layer. Per P7 (Protocol over Implementation), the
    upper layers never know about specific driver implementations.

    Each driver has:
    - A name and version for identification.
    - A set of capabilities describing what it can do.
    - An execute() method for synchronous-style execution.
    - An execute_stream() method for streaming/progress execution.
    - A sense() method for reading state from the environment.
    - Health check and lifecycle methods.
    """

    @property
    @abstractmethod
    def driver_name(self) -> str:
        """Unique driver name (e.g., 'api', 'browser', 'robot')."""
        ...

    @property
    @abstractmethod
    def driver_version(self) -> str:
        """Driver version string (semver)."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> list[CapabilityDescriptor]:
        """Capabilities this driver provides."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the driver — connect, authenticate, configure."""
        ...

    @abstractmethod
    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute an action on this driver.

        Args:
            action: The action name (e.g., 'move_joint', 'click', 'query').
            parameters: Action-specific parameters.
            context: Optional execution context (e.g., session data).

        Returns:
            An ExecutionResult with success/failure and output data.
        """
        ...

    @abstractmethod
    async def execute_stream(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[ExecutionProgress]:
        """Execute an action with streaming progress updates.

        Args:
            action: The action name.
            parameters: Action-specific parameters.
            context: Optional execution context.

        Yields:
            ExecutionProgress updates during the action.
        """
        ...

    @abstractmethod
    async def sense(self, capability: str) -> dict[str, Any]:
        """Read/sense the current state for a capability.

        Args:
            capability: The capability to sense (e.g., 'position', 'screenshot').

        Returns:
            A dictionary with the sensed data.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the driver is healthy and responsive.

        Returns:
            True if the driver is healthy.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shutdown the driver, releasing resources."""
        ...

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Get the current status of the driver.

        Returns:
            A dictionary with driver status information.
        """
        ...


class DriverManager:
    """Manages all execution drivers.

    Handles driver registration, lookup, execution routing, and lifecycle.
    The cognitive layer uses this manager to find and use drivers without
    knowing about specific implementations.
    """

    def __init__(self) -> None:
        """Initialize the driver manager."""
        self._drivers: dict[str, UnifiedDriverProtocol] = {}
        logger.info("driver_manager_initialized")

    async def register(self, driver: UnifiedDriverProtocol) -> None:
        """Register a driver with the manager.

        Args:
            driver: The driver instance to register.
        """
        await driver.initialize()
        self._drivers[driver.driver_name] = driver
        logger.info(
            "driver_registered",
            driver_name=driver.driver_name,
            driver_version=driver.driver_version,
            capabilities_count=len(driver.capabilities),
        )

    async def get(self, driver_name: str) -> UnifiedDriverProtocol | None:
        """Get a registered driver by name.

        Args:
            driver_name: The driver name to look up.

        Returns:
            The driver instance, or None if not found.
        """
        return self._drivers.get(driver_name)

    async def execute(
        self,
        driver_name: str,
        action: str,
        parameters: dict[str, Any],
    ) -> ExecutionResult:
        """Execute an action on a named driver.

        Args:
            driver_name: The driver to execute on.
            action: The action to perform.
            parameters: Action parameters.

        Returns:
            An ExecutionResult.

        Raises:
            DriverNotAvailableError: If the driver is not registered.
        """
        driver = self._drivers.get(driver_name)
        if driver is None:
            raise DriverNotAvailableError(
                f"Driver not registered: {driver_name}",
                code="DRIVER_NOT_AVAILABLE",
                details={
                    "driver_name": driver_name,
                    "available": list(self._drivers.keys()),
                },
            )

        return await driver.execute(action, parameters)

    async def list_drivers(self) -> list[str]:
        """List all registered driver names.

        Returns:
            A sorted list of driver names.
        """
        return sorted(self._drivers.keys())

    async def discover_capabilities(self) -> list[CapabilityDescriptor]:
        """Discover capabilities from all registered drivers.

        Returns:
            A list of all capability descriptors across all drivers.
        """
        all_caps: list[CapabilityDescriptor] = []
        for driver in self._drivers.values():
            all_caps.extend(driver.capabilities)
        return all_caps

    async def shutdown_all(self) -> None:
        """Shutdown all registered drivers gracefully."""
        for name, driver in list(self._drivers.items()):
            try:
                await driver.shutdown()
                logger.info("driver_shutdown", driver_name=name)
            except Exception as exc:
                logger.error(
                    "driver_shutdown_error",
                    driver_name=name,
                    error=str(exc),
                )
        self._drivers.clear()
        logger.info("all_drivers_shutdown")
```

## 文件路径: src/myharness/driver/translation.py

```python
"""Action translation — maps high-level actions to driver-specific calls.

The cognitive layer works with abstract actions (e.g., "move_forward").
This translator converts those abstract actions into the concrete
parameters that each driver understands.
"""

from __future__ import annotations

from typing import Any

import structlog

from myharness.driver.protocol import UnifiedDriverProtocol

logger = structlog.get_logger(__name__)


class ActionTranslator:
    """Translates high-level actions to driver-specific parameters.

    The cognitive layer operates on abstract actions. Each driver may
    require different parameter names or structures for the same
    conceptual action. This translator bridges that gap.
    """

    def __init__(self) -> None:
        """Initialize the action translator."""
        self._translation_maps: dict[str, dict[str, dict[str, Any]]] = {}
        logger.info("action_translator_initialized")

    async def translate(
        self,
        action: str,
        parameters: dict[str, Any],
        driver: UnifiedDriverProtocol,
    ) -> tuple[str, dict[str, Any]]:
        """Translate an action and its parameters for a specific driver.

        If no translation is registered for this driver/action pair,
        the action and parameters are passed through unchanged.

        Args:
            action: The abstract action name.
            parameters: The abstract action parameters.
            driver: The target driver.

        Returns:
            A tuple of (translated_action, translated_parameters).
        """
        driver_name = driver.driver_name

        # Check if we have a translation map for this driver
        driver_maps = self._translation_maps.get(driver_name, {})
        if action in driver_maps:
            translation = driver_maps[action]
            translated_action = translation.get("action", action)
            translated_params = self._apply_translation(
                parameters, translation.get("parameters", {})
            )
            logger.debug(
                "action_translated",
                driver_name=driver_name,
                original_action=action,
                translated_action=translated_action,
            )
            return translated_action, translated_params

        # Pass through unchanged
        return action, parameters

    async def register_translation(
        self,
        driver_name: str,
        action: str,
        translated_action: str,
        parameter_map: dict[str, str] | None = None,
    ) -> None:
        """Register a translation mapping for a driver/action pair.

        Args:
            driver_name: The driver to register for.
            action: The abstract action name.
            translated_action: The driver-specific action name.
            parameter_map: Mapping from abstract param names to driver param names.
        """
        if driver_name not in self._translation_maps:
            self._translation_maps[driver_name] = {}

        self._translation_maps[driver_name][action] = {
            "action": translated_action,
            "parameters": parameter_map or {},
        }

        logger.info(
            "translation_registered",
            driver_name=driver_name,
            action=action,
            translated_action=translated_action,
        )

    @staticmethod
    def _apply_translation(
        parameters: dict[str, Any],
        param_map: dict[str, str],
    ) -> dict[str, Any]:
        """Apply parameter name translations.

        Args:
            parameters: Original parameters with abstract names.
            param_map: Mapping from abstract names to driver names.

        Returns:
            Parameters with translated names.
        """
        translated: dict[str, Any] = {}
        for key, value in parameters.items():
            new_key = param_map.get(key, key)
            translated[new_key] = value
        return translated
```
