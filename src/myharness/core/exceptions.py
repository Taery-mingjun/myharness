"""Domain exception hierarchy for MyHarness.

All exceptions inherit from MyHarnessError, providing structured error
information with optional error codes, details, and causes.
"""

from __future__ import annotations

from typing import Any


class MyHarnessError(Exception):
    """Base exception for all MyHarness errors.

    Attributes:
        message: Human-readable error description.
        code: Machine-readable error code for programmatic handling.
        details: Additional structured error context.
        cause: The original exception that caused this error, if any.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}
        self.cause = cause

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, code={self.code!r})"


# ── Configuration ──────────────────────────────────────────────────────


class ConfigurationError(MyHarnessError):
    """Raised when application configuration is invalid or missing."""


# ── Memory ─────────────────────────────────────────────────────────────


class MemoryError(MyHarnessError):
    """Base exception for Memory System errors."""


class MemoryNotFoundError(MemoryError):
    """Raised when a requested memory entry cannot be found."""


class MemoryWriteError(MemoryError):
    """Raised when writing to memory storage fails."""


class IdentityConflictError(MemoryError):
    """Raised when an identity update conflicts with existing identity data."""


# ── LLM ────────────────────────────────────────────────────────────────


class LLMError(MyHarnessError):
    """Base exception for LLM Engine errors."""


class ProviderError(LLMError):
    """Raised when an LLM provider returns an error."""


class ProviderNotAvailableError(LLMError):
    """Raised when a requested LLM provider is not configured or reachable."""


class TokenLimitError(LLMError):
    """Raised when the LLM token limit is exceeded."""


# ── Skill ──────────────────────────────────────────────────────────────


class SkillError(MyHarnessError):
    """Base exception for Skill Store errors."""


class SkillNotFoundError(SkillError):
    """Raised when a requested skill cannot be found."""


class SkillValidationError(SkillError):
    """Raised when a skill definition fails validation."""


class SkillLifecycleError(SkillError):
    """Raised when an invalid lifecycle transition is attempted."""


# ── Driver ─────────────────────────────────────────────────────────────


class DriverError(MyHarnessError):
    """Base exception for Execution Driver errors."""


class DriverNotAvailableError(DriverError):
    """Raised when a requested driver is not available."""


class ExecutionError(DriverError):
    """Raised when a driver action execution fails."""


class CapabilityNotFoundError(DriverError):
    """Raised when a requested capability is not registered."""


# ── Event Bus ──────────────────────────────────────────────────────────


class EventBusError(MyHarnessError):
    """Raised when an event bus operation fails."""


# ── Harness ────────────────────────────────────────────────────────────


class HarnessError(MyHarnessError):
    """Raised when the Harness supervisor encounters an error."""
