"""Structured logging configuration using structlog.

Provides consistent, JSON-structured logging across the entire application.
Supports both development (console) and production (JSON) formats.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from myharness.core.config import Settings


def _get_processors(settings: Settings) -> list[Any]:
    """Build the processor chain based on configuration."""
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.log_format == "json":
        shared_processors.append(structlog.processors.JSONRenderer())
    elif settings.log_format == "keyvalue":
        shared_processors.append(structlog.dev.ConsoleRenderer(colors=False))
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer())

    return shared_processors


def configure_logging(settings: Settings | None = None) -> None:
    """Initialize structured logging for the application.

    Should be called once at application startup before any loggers are used.

    Args:
        settings: Application settings. If None, uses cached get_settings().
    """
    if settings is None:
        from myharness.core.config import get_settings

        settings = get_settings()

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    # Configure structlog
    structlog.configure(
        processors=_get_processors(settings),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "openai", "faiss"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None, **context: Any) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance with optional bound context.

    Args:
        name: Logger name (typically __name__ of the calling module).
        **context: Key-value pairs to bind to all log messages from this logger.

    Returns:
        A structlog BoundLogger ready for structured logging.

    Example:
        >>> log = get_logger(__name__, component="memory")
        >>> log.info("memory_initialized", store_count=4)
    """
    logger = structlog.get_logger(name or "myharness")
    if context:
        logger = logger.bind(**context)
    return logger
