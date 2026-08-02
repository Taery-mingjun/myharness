"""FastAPI application factory for MyHarness.

Creates the ASGI application with all routers, middleware, and lifecycle
hooks. Supports both dependency-injected (production) and test-mode
(manual wiring) configurations.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from myharness.api.middleware.error_handler import ErrorHandlerMiddleware
from myharness.api.middleware.tracing import TracingMiddleware
from myharness.core.config import get_settings

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

    # CORS — explicit allowlist only (no wildcard), read from settings
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=False,
        allow_methods=settings.api_cors_methods,
        allow_headers=settings.api_cors_headers,
    )

    # Custom middleware
    app.add_middleware(TracingMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)

    # Register API routers
    from myharness.api.dependencies import verify_api_key
    from myharness.api.routers import cognitive, memory, skill, driver, harness, health

    # Authentication is applied at the ROUTER level, not per-endpoint.
    #
    # Per-endpoint `Depends(verify_api_key)` is a fail-open pattern: every new
    # route is unauthenticated until someone remembers to decorate it, and
    # nothing fails loudly when they forget. That is exactly what happened
    # here — reads and the entire cognitive router were publicly reachable
    # while the auth dependency existed and looked correct.
    #
    # Binding the dependency to include_router() inverts the default: a new
    # endpoint is protected the moment it is added, and exposing one requires
    # a deliberate, reviewable change below.
    protected = [Depends(verify_api_key)]

    app.include_router(
        cognitive.router,
        prefix="/api/v1/cognitive",
        tags=["Cognitive"],
        dependencies=protected,
    )
    app.include_router(
        memory.router,
        prefix="/api/v1/memory",
        tags=["Memory"],
        dependencies=protected,
    )
    app.include_router(
        skill.router,
        prefix="/api/v1/skill",
        tags=["Skill"],
        dependencies=protected,
    )
    app.include_router(
        driver.router,
        prefix="/api/v1/driver",
        tags=["Driver"],
        dependencies=protected,
    )
    app.include_router(
        harness.router,
        prefix="/api/v1/harness",
        tags=["Harness"],
        dependencies=protected,
    )

    # Health is intentionally public: load balancers and orchestrators probe
    # it without credentials. It must therefore never leak internal state.
    app.include_router(health.router, tags=["Health"])

    logger.info("api_app_created", version="0.1.0")
    return app
