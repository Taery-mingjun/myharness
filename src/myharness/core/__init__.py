"""MyHarness Core Module.

Foundation layer providing configuration, dependency injection,
exception hierarchy, type aliases, and structured logging.
"""

from myharness.core.config import Settings, get_settings
from myharness.core.exceptions import (
    CapabilityNotFoundError,
    ConfigurationError,
    DriverError,
    DriverNotAvailableError,
    EventBusError,
    ExecutionError,
    HarnessError,
    IdentityConflictError,
    LLMError,
    MemoryError,
    MemoryNotFoundError,
    MemoryWriteError,
    MyHarnessError,
    ProviderError,
    ProviderNotAvailableError,
    SkillError,
    SkillLifecycleError,
    SkillNotFoundError,
    SkillValidationError,
    TokenLimitError,
)
from myharness.core.logging import configure_logging, get_logger
from myharness.core.types import (
    DriverId,
    Embedding,
    EventId,
    JsonDict,
    MemoryId,
    SkillId,
)

__all__ = [
    # Config
    "Settings",
    "get_settings",
    # Exceptions
    "MyHarnessError",
    "ConfigurationError",
    "MemoryError",
    "MemoryNotFoundError",
    "MemoryWriteError",
    "IdentityConflictError",
    "LLMError",
    "ProviderError",
    "ProviderNotAvailableError",
    "TokenLimitError",
    "SkillError",
    "SkillNotFoundError",
    "SkillValidationError",
    "SkillLifecycleError",
    "DriverError",
    "DriverNotAvailableError",
    "ExecutionError",
    "CapabilityNotFoundError",
    "EventBusError",
    "HarnessError",
    # Types
    "MemoryId",
    "SkillId",
    "DriverId",
    "EventId",
    "Embedding",
    "JsonDict",
    # Logging
    "configure_logging",
    "get_logger",
]
