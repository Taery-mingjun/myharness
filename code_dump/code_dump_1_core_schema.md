# code_dump_1_core_schema.md

本文件为第 1 部分，包含目录: core, schema/

包含文件数: 13

## 文件路径: src/myharness/core/__init__.py

```python
"""MyHarness Core Module.

Foundation layer providing configuration, dependency injection,
exception hierarchy, type aliases, and structured logging.
"""

from myharness.core.config import Settings, get_settings
from myharness.core.exceptions import (
    MyHarnessError,
    ConfigurationError,
    MemoryError,
    MemoryNotFoundError,
    MemoryWriteError,
    IdentityConflictError,
    LLMError,
    ProviderError,
    ProviderNotAvailableError,
    TokenLimitError,
    SkillError,
    SkillNotFoundError,
    SkillValidationError,
    SkillLifecycleError,
    DriverError,
    DriverNotAvailableError,
    ExecutionError,
    CapabilityNotFoundError,
    EventBusError,
    HarnessError,
)
from myharness.core.types import (
    MemoryId,
    SkillId,
    DriverId,
    EventId,
    Embedding,
    JsonDict,
)
from myharness.core.logging import configure_logging, get_logger

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
```

## 文件路径: src/myharness/core/config.py

```python
"""Application settings via pydantic-settings.

All configuration is loaded from environment variables prefixed with MYH_,
with .env file support for local development.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration.

    Loads from environment variables (MYH_* prefix) and .env file.
    """

    model_config = SettingsConfigDict(
        env_prefix="MYH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM Providers ──────────────────────────────────────────────────

    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_default_model: str = Field(default="gpt-4o", description="Default OpenAI model")

    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    anthropic_default_model: str = Field(
        default="claude-3-opus-20240229", description="Default Anthropic model"
    )

    google_api_key: str = Field(default="", description="Google AI API key")
    google_default_model: str = Field(
        default="gemini-2.0-flash", description="Default Google Gemini model"
    )

    qwen_api_key: str = Field(default="", description="Qwen (通义千问) API key")
    qwen_default_model: str = Field(default="qwen-max", description="Default Qwen model")

    deepseek_api_key: str = Field(default="", description="DeepSeek API key")
    deepseek_default_model: str = Field(
        default="deepseek-chat", description="Default DeepSeek model"
    )

    ollama_base_url: str = Field(
        default="http://localhost:11434", description="Ollama base URL for local models"
    )
    ollama_default_model: str = Field(
        default="llama3.1", description="Default local model via Ollama"
    )

    default_llm_provider: str = Field(
        default="openai",
        description="Default LLM provider: openai|anthropic|google|qwen|deepseek|local",
    )

    # ── Data Storage ───────────────────────────────────────────────────

    data_dir: Path = Field(default=Path("./data"), description="Root data directory")
    embedding_dimension: int = Field(
        default=1536, description="Default embedding vector dimension"
    )
    vector_index_type: str = Field(
        default="IVFFlat", description="FAISS index type (IVFFlat, Flat, HNSW, etc.)"
    )

    # ── API Server ─────────────────────────────────────────────────────

    api_host: str = Field(default="0.0.0.0", description="API server host")
    api_port: int = Field(default=8000, description="API server port")
    api_debug: bool = Field(default=False, description="Enable debug mode")

    # ── Logging ────────────────────────────────────────────────────────

    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="json", description="Log format: json|console|keyvalue"
    )

    # ── Runtime ────────────────────────────────────────────────────────

    cognitive_loop_interval_ms: int = Field(
        default=100, description="Cognitive loop polling interval in milliseconds"
    )
    max_concurrent_tasks: int = Field(
        default=10, description="Maximum concurrent cognitive tasks"
    )
    default_task_timeout: float = Field(
        default=300.0, description="Default task timeout in seconds"
    )

    @property
    def memory_source_dir(self) -> Path:
        """Directory for memory source-of-truth (JSON) files."""
        return self.data_dir / "memory" / "source"

    @property
    def memory_derived_dir(self) -> Path:
        """Directory for memory derived (rebuildable) data."""
        return self.data_dir / "memory" / "derived"

    @property
    def memory_index_dir(self) -> Path:
        """Directory for memory vector and text indexes."""
        return self.data_dir / "memory" / "indexes"

    @property
    def skills_dir(self) -> Path:
        """Directory for skill definition files."""
        return self.data_dir / "skills"

    def ensure_directories(self) -> None:
        """Create all required data directories if they don't exist."""
        for d in [
            self.memory_source_dir,
            self.memory_derived_dir,
            self.memory_index_dir,
            self.skills_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    settings = Settings()
    settings.ensure_directories()
    return settings
```

## 文件路径: src/myharness/core/di.py

```python
"""Dependency Injection container — wires all MyHarness components together.

The DI container builds the complete object graph, respecting the strict
module dependency order required by the four-power-separation architecture.

Wiring order (bottom-up):
1. Configuration — Settings (no dependencies)
2. Storage — SourceOfTruth, DerivedStorage, VectorIndex, TextIndex
3. Memory Stores — IdentityStore, EpisodicStore, SemanticStore, RelationshipStore
4. Memory Manager — depends on all stores
5. LLM Provider — depends on config
6. Context Builder — depends on memory
7. LLM Engine — depends on provider + context builder
8. Skill Store — depends on storage
9. Event Bus — no dependencies
10. Router — depends on bus
11. Drivers — depends on config
12. Capability Registry — no dependencies
13. Scheduler, Monitor — no dependencies
14. Harness Supervisor — depends on everything
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from lagom import Container
    from myharness.core.config import Settings

logger = structlog.get_logger(__name__)


def build_container(settings: "Settings") -> "Container":
    """Build the complete dependency injection container.

    All services are registered as singletons (lagom default). The
    container can be used to resolve any service by its type.

    The wiring is done in strict dependency order. Services that depend
    on other services are registered after their dependencies.

    Args:
        settings: Application settings loaded from environment/.env.

    Returns:
        A fully configured lagom Container ready for resolution.
    """
    from lagom import Container

    container = Container()

    # ── Level 0: Settings ──────────────────────────────────────────────
    from myharness.core.config import Settings as SettingsCls

    container[SettingsCls] = settings

    # ── Level 1: Storage (no dependencies) ─────────────────────────────
    from myharness.memory.storage.source import SourceOfTruth
    from myharness.memory.storage.derived import DerivedStorage
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.indexing.text import TextIndex

    container[SourceOfTruth] = lambda c: SourceOfTruth(settings.memory_source_dir)
    container[DerivedStorage] = lambda c: DerivedStorage(
        settings.memory_derived_dir / "metadata.db"
    )
    container[VectorIndex] = lambda c: VectorIndex(
        dimension=settings.embedding_dimension,
        index_path=settings.memory_index_dir / "vectors.faiss",
    )
    container[TextIndex] = lambda c: TextIndex(
        settings.memory_derived_dir / "fts.db"
    )

    # ── Level 2: Memory Stores (depend on storage) ─────────────────────
    from myharness.memory.stores.identity import IdentityStore
    from myharness.memory.stores.episodic import EpisodicStore
    from myharness.memory.stores.semantic import SemanticStore
    from myharness.memory.stores.relationship import RelationshipStore

    container[IdentityStore] = lambda c: IdentityStore(c[SourceOfTruth])
    container[EpisodicStore] = lambda c: EpisodicStore(
        c[SourceOfTruth], c[DerivedStorage], c[VectorIndex], c[TextIndex]
    )
    container[SemanticStore] = lambda c: SemanticStore(
        c[SourceOfTruth], c[VectorIndex], c[TextIndex]
    )
    container[RelationshipStore] = lambda c: RelationshipStore(c[SourceOfTruth])

    # ── Level 3: Memory Manager (depends on all stores) ────────────────
    from myharness.memory.manager import MemoryManager
    from myharness.memory.interface import MemorySystem

    container[MemoryManager] = lambda c: MemoryManager(
        identity=c[IdentityStore],
        episodic=c[EpisodicStore],
        semantic=c[SemanticStore],
        relationship=c[RelationshipStore],
    )
    # Register MemoryManager under the MemorySystem interface for polymorphic resolution
    container[MemorySystem] = lambda c: c[MemoryManager]

    # ── Level 4: LLM Provider (depends on config) ─────────────────────
    from myharness.llm.providers import create_provider
    from myharness.llm.interfaces import LLMProvider

    container[LLMProvider] = lambda c: create_provider(
        settings.default_llm_provider, settings
    )

    # ── Level 5: Context Builder (depends on memory) ──────────────────
    from myharness.llm.context import ContextBuilder

    container[ContextBuilder] = lambda c: ContextBuilder(c[MemorySystem])

    # ── Level 6: LLM Engine (depends on provider + context builder) ───
    from myharness.llm.engine import LLMEngine

    container[LLMEngine] = lambda c: LLMEngine(
        provider=c[LLMProvider], context_builder=c[ContextBuilder]
    )

    # ── Level 7: Skill Store & Registry (depend on storage) ───────────
    from myharness.skill.store import SkillStore
    from myharness.skill.registry import SkillRegistry

    container[SkillStore] = lambda c: SkillStore(settings.skills_dir)
    container[SkillRegistry] = lambda c: SkillRegistry(c[SkillStore])

    # ── Level 8: Event Bus & Router (no dependencies) ─────────────────
    from myharness.bus.dispatcher import EventBus
    from myharness.bus.router import Router

    container[EventBus] = EventBus()
    container[Router] = lambda c: Router(c[EventBus])

    # ── Level 9: Driver Manager (no dependencies) ─────────────────────
    from myharness.driver.protocol import DriverManager

    container[DriverManager] = DriverManager()

    # ── Level 10: Harness Components (no dependencies) ────────────────
    from myharness.harness.registry import CapabilityRegistry
    from myharness.harness.scheduler import ResourceScheduler
    from myharness.harness.monitor import RuntimeMonitor

    container[CapabilityRegistry] = lambda c: CapabilityRegistry()
    container[ResourceScheduler] = lambda c: ResourceScheduler()
    container[RuntimeMonitor] = RuntimeMonitor()

    # ── Level 11: Harness Supervisor (depends on everything) ──────────
    from myharness.harness.supervisor import HarnessSupervisor

    container[HarnessSupervisor] = lambda c: HarnessSupervisor(
        event_bus=c[EventBus],
        router=c[Router],
        memory=c[MemorySystem],
        llm_engine=c[LLMEngine],
        skill_store=c[SkillStore],
        capability_registry=c[CapabilityRegistry],
        driver_manager=c[DriverManager],
        scheduler=c[ResourceScheduler],
        monitor=c[RuntimeMonitor],
    )

    logger.info(
        "di_container_built",
        provider=settings.default_llm_provider,
        embedding_dimension=settings.embedding_dimension,
    )

    return container
```

## 文件路径: src/myharness/core/exceptions.py

```python
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
```

## 文件路径: src/myharness/core/logging.py

```python
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
```

## 文件路径: src/myharness/core/types.py

```python
"""Shared type aliases and NewType definitions.

These provide semantic meaning to primitive types throughout the codebase
while maintaining full IDE type-checking support.
"""

from __future__ import annotations

from typing import Any, NewType

# ── Strongly-Typed Identifiers ────────────────────────────────────────

MemoryId = NewType("MemoryId", str)
"""Unique identifier for a memory entry across all stores."""

SkillId = NewType("SkillId", str)
"""Unique identifier for a skill definition."""

DriverId = NewType("DriverId", str)
"""Unique identifier for an execution driver instance."""

EventId = NewType("EventId", str)
"""Unique identifier for an event in the bus."""

# ── Domain Type Aliases ───────────────────────────────────────────────

Embedding = list[float]
"""A vector embedding — variable-length list of floating-point values."""

JsonDict = dict[str, Any]
"""A generic JSON-compatible dictionary for unstructured data."""

MemoryEntry = dict[str, Any]
"""A memory entry as a generic dictionary."""

SkillActionTemplate = dict[str, Any]
"""A skill action template as a generic dictionary."""

DriverConfig = dict[str, Any]
"""A driver configuration as a generic dictionary."""
```

## 文件路径: src/myharness/schema/__init__.py

```python
"""MyHarness Schema Module.

Pydantic v2 data models defining the canonical data structures for
all system components: events, memory entries, skills, identity,
capabilities, and driver protocols.
"""

from myharness.schema.event import (
    BaseEvent,
    EventType,
    UserMessageEvent,
    VisionResultEvent,
    SensorReadingEvent,
    TimerTriggerEvent,
    CognitiveRequestEvent,
    ThinkResultEvent,
    PlanResultEvent,
    ReflectResultEvent,
    CompileResultEvent,
    IdentityInterpretationEvent,
    IdentityUpdateProposalEvent,
    SkillDiscoveredEvent,
    SkillLoadedEvent,
    SkillFinishedEvent,
    SkillFailedEvent,
    SkillStatusChangedEvent,
    ExecutionStartEvent,
    ExecutionProgressEvent,
    ExecutionCompleteEvent,
    ExecutionErrorEvent,
    RobotFeedbackEvent,
    SystemStartupEvent,
    SystemShutdownEvent,
    ErrorEvent,
    HeartbeatEvent,
    MemoryReadEvent,
    MemoryWriteEvent,
    MemorySearchEvent,
    MemoryUpdateEvent,
    MemoryArchiveEvent,
)
from myharness.schema.memory import (
    MemoryCategory,
    IdentityEntry,
    EpisodicEntry,
    SemanticEntry,
    RelationshipEntry,
    MemoryQuery,
    MemorySearchResult,
    MemoryBatchResult,
)
from myharness.schema.skill import (
    SkillStatus,
    SkillParameter,
    SkillDefinition,
    SkillProposal,
    SkillLifecycleTransition,
)
from myharness.schema.identity import (
    Identity,
    IdentityUpdateProposal,
    IdentityField,
)
from myharness.schema.capability import (
    CapabilityDescriptor,
    CapabilityAction,
)
from myharness.schema.driver import (
    ExecutionResult,
    ExecutionProgress,
    DriverStatus,
    DriverInfo,
)

__all__ = [
    # Event
    "BaseEvent",
    "EventType",
    "UserMessageEvent",
    "VisionResultEvent",
    "SensorReadingEvent",
    "TimerTriggerEvent",
    "CognitiveRequestEvent",
    "ThinkResultEvent",
    "PlanResultEvent",
    "ReflectResultEvent",
    "CompileResultEvent",
    "IdentityInterpretationEvent",
    "IdentityUpdateProposalEvent",
    "SkillDiscoveredEvent",
    "SkillLoadedEvent",
    "SkillFinishedEvent",
    "SkillFailedEvent",
    "SkillStatusChangedEvent",
    "ExecutionStartEvent",
    "ExecutionProgressEvent",
    "ExecutionCompleteEvent",
    "ExecutionErrorEvent",
    "RobotFeedbackEvent",
    "SystemStartupEvent",
    "SystemShutdownEvent",
    "ErrorEvent",
    "HeartbeatEvent",
    "MemoryReadEvent",
    "MemoryWriteEvent",
    "MemorySearchEvent",
    "MemoryUpdateEvent",
    "MemoryArchiveEvent",
    # Memory
    "MemoryCategory",
    "IdentityEntry",
    "EpisodicEntry",
    "SemanticEntry",
    "RelationshipEntry",
    "MemoryQuery",
    "MemorySearchResult",
    "MemoryBatchResult",
    # Skill
    "SkillStatus",
    "SkillParameter",
    "SkillDefinition",
    "SkillProposal",
    "SkillLifecycleTransition",
    # Identity
    "Identity",
    "IdentityUpdateProposal",
    "IdentityField",
    # Capability
    "CapabilityDescriptor",
    "CapabilityAction",
    # Driver
    "ExecutionResult",
    "ExecutionProgress",
    "DriverStatus",
    "DriverInfo",
]
```

## 文件路径: src/myharness/schema/capability.py

```python
"""Capability descriptor models — what drivers and skills can do.

Capabilities are discovered (not declared) by the Harness Layer and
stored in the Capability Registry. Each capability maps to one or more
concrete actions on a specific driver.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ── Capability Action ──────────────────────────────────────────────────


class CapabilityAction(BaseModel):
    """A single action within a capability — the atomic unit of execution."""

    name: str = Field(..., min_length=1, description="Action name, e.g., 'click', 'move_joint'")
    description: str = Field(default="")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Expected parameters schema for this action",
    )
    returns: str = Field(default="any", description="Expected return type")
    is_async: bool = Field(default=True, description="Whether the action supports async execution")


# ── Capability Descriptor ──────────────────────────────────────────────


class CapabilityDescriptor(BaseModel):
    """A registered capability — what a driver or skill can do.

    Capabilities are the bridge between the Harness Layer's abstract
    action model and concrete driver implementations.
    """

    capability_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, description="Human-readable capability name")
    description: str = Field(default="")
    driver_name: str = Field(
        ...,
        description="The driver that provides this capability",
    )
    actions: list[CapabilityAction] = Field(
        default_factory=list,
        description="The concrete actions this capability supports",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Global parameters for the capability",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Constraints: rate limits, permissions, preconditions",
    )
    version: str = Field(default="0.1.0")
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"json_schema_extra": {"source_of_truth": False}}
```

## 文件路径: src/myharness/schema/driver.py

```python
"""Driver protocol models — execution layer abstractions.

Implements P7 (Protocol over Implementation): MyHarness defines a
unified driver protocol that abstracts away hardware/platform details.
Upper layers (LLM, Skill) never know about specific driver implementations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from myharness.core.types import DriverId


# ── Execution Result ───────────────────────────────────────────────────


class ExecutionResult(BaseModel):
    """The result of a driver action execution."""

    success: bool = Field(..., description="Whether the action completed successfully")
    output: Any = Field(default=None, description="Action output data")
    error: str | None = Field(default=None, description="Error message if failed")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Execution wall-clock time")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Driver-specific metadata (e.g., request_id, endpoint)",
    )


# ── Execution Progress ─────────────────────────────────────────────────


class ExecutionProgress(BaseModel):
    """Progress update during a long-running action."""

    action: str = Field(..., description="The action being executed")
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    status: str = Field(default="running", description="Status: running, waiting, finalizing")
    message: str = Field(default="", description="Human-readable progress message")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Driver Status ──────────────────────────────────────────────────────


class DriverStatus(BaseModel):
    """Health and status of an execution driver."""

    connected: bool = Field(default=False)
    capabilities_count: int = Field(default=0, ge=0)
    last_heartbeat: datetime | None = Field(default=None)
    version: str = Field(default="0.1.0")
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Driver Info ────────────────────────────────────────────────────────


class DriverInfo(BaseModel):
    """Static information about a registered driver."""

    driver_id: DriverId
    name: str = Field(..., min_length=1)
    driver_type: str = Field(..., description="robot, browser, api, mcp, computer, database, iot")
    version: str = Field(default="0.1.0")
    description: str = Field(default="")
    status: DriverStatus = Field(default_factory=DriverStatus)
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

## 文件路径: src/myharness/schema/event.py

```python
"""Event type definitions and event data models.

All system communication flows through typed events. Every event has a
unique ID, timestamp, source identifier, and optional correlation/causation
IDs for tracing the causal chain through the system.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator


# ── Event Type Enumeration ────────────────────────────────────────────


class EventType(StrEnum):
    """All recognized event types in the MyHarness system."""

    # External input
    USER_MESSAGE = "user.message"
    VISION_RESULT = "vision.result"
    SENSOR_READING = "sensor.reading"
    TIMER_TRIGGER = "timer.trigger"

    # Cognitive pipeline
    COGNITIVE_REQUEST = "cognitive.request"
    THINK_RESULT = "cognitive.think.result"
    PLAN_RESULT = "cognitive.plan.result"
    REFLECT_RESULT = "cognitive.reflect.result"
    COMPILE_RESULT = "cognitive.compile.result"

    # Identity
    IDENTITY_INTERPRETATION = "identity.interpretation"
    IDENTITY_UPDATE_PROPOSAL = "identity.update_proposal"

    # Memory operations
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_SEARCH = "memory.search"
    MEMORY_UPDATE = "memory.update"
    MEMORY_ARCHIVE = "memory.archive"

    # Skill lifecycle
    SKILL_DISCOVERED = "skill.discovered"
    SKILL_LOADED = "skill.loaded"
    SKILL_FINISHED = "skill.finished"
    SKILL_FAILED = "skill.failed"
    SKILL_STATUS_CHANGED = "skill.status_changed"

    # Execution
    EXECUTION_START = "execution.start"
    EXECUTION_PROGRESS = "execution.progress"
    EXECUTION_COMPLETE = "execution.complete"
    EXECUTION_ERROR = "execution.error"
    ROBOT_FEEDBACK = "execution.robot_feedback"

    # System
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    ERROR = "system.error"
    HEARTBEAT = "system.heartbeat"


# ── Base Event ─────────────────────────────────────────────────────────


class BaseEvent(BaseModel):
    """Base class for all events in the system.

    Attributes:
        event_id: Universally unique event identifier.
        event_type: Discriminator for event routing.
        timestamp: When the event was created (UTC).
        source: Component that emitted the event (e.g. "llm.engine", "memory.system").
        correlation_id: Links events belonging to the same cognitive task.
        causation_id: The event_id that directly caused this event (event sourcing).
        payload: Event-specific data payload.
        metadata: Arbitrary key-value metadata for observability.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(default="unknown")
    correlation_id: str | None = Field(default=None)
    causation_id: str | None = Field(default=None)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _ensure_utc(cls, v: Any) -> datetime:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ── External Input Events ─────────────────────────────────────────────


class UserMessageEvent(BaseEvent):
    """A message from a human user to the cognitive system."""

    event_type: ClassVar[EventType] = EventType.USER_MESSAGE
    payload: dict[str, Any]  # { "content": str, "attachments": list, "role": str }


class VisionResultEvent(BaseEvent):
    """Result from a computer vision processing step."""

    event_type: ClassVar[EventType] = EventType.VISION_RESULT
    payload: dict[str, Any]  # { "image_id", "detections", "descriptions", "confidence" }


class SensorReadingEvent(BaseEvent):
    """A sensor reading from the physical or digital environment."""

    event_type: ClassVar[EventType] = EventType.SENSOR_READING
    payload: dict[str, Any]  # { "sensor_id", "sensor_type", "value", "unit", "accuracy" }


class TimerTriggerEvent(BaseEvent):
    """A scheduled timer has fired."""

    event_type: ClassVar[EventType] = EventType.TIMER_TRIGGER
    payload: dict[str, Any]  # { "timer_id", "scheduled_at", "reason" }


# ── Cognitive Pipeline Events ─────────────────────────────────────────


class CognitiveRequestEvent(BaseEvent):
    """Request to initiate a cognitive processing cycle."""

    event_type: ClassVar[EventType] = EventType.COGNITIVE_REQUEST
    payload: dict[str, Any]  # { "query", "context", "priority" }


class ThinkResultEvent(BaseEvent):
    """Result of the LLM Think() operation."""

    event_type: ClassVar[EventType] = EventType.THINK_RESULT
    payload: dict[str, Any]  # { "thought", "reasoning_trace", "confidence", "tokens_used" }


class PlanResultEvent(BaseEvent):
    """Result of the LLM Plan() operation."""

    event_type: ClassVar[EventType] = EventType.PLAN_RESULT
    payload: dict[str, Any]  # { "plan_id", "steps", "estimated_cost", "alternatives" }


class ReflectResultEvent(BaseEvent):
    """Result of the LLM Reflect() operation — learning from experience."""

    event_type: ClassVar[EventType] = EventType.REFLECT_RESULT
    payload: dict[str, Any]  # { "experience_id", "insights", "skill_update_proposals", "identity_insights" }


class CompileResultEvent(BaseEvent):
    """Result of the LLM Compile() operation — turning reflection into skill."""

    event_type: ClassVar[EventType] = EventType.COMPILE_RESULT
    payload: dict[str, Any]  # { "skill_proposal", "compiled_from", "validation_results" }


# ── Identity Events ───────────────────────────────────────────────────


class IdentityInterpretationEvent(BaseEvent):
    """LLM's interpretation of the current identity state."""

    event_type: ClassVar[EventType] = EventType.IDENTITY_INTERPRETATION
    payload: dict[str, Any]  # { "current_identity", "contextual_interpretation", "relevant_aspects" }


class IdentityUpdateProposalEvent(BaseEvent):
    """LLM's proposal to update identity based on experience."""

    event_type: ClassVar[EventType] = EventType.IDENTITY_UPDATE_PROPOSAL
    payload: dict[str, Any]  # { "field", "current_value", "proposed_value", "reasoning", "confidence" }


# ── Memory Operation Events ───────────────────────────────────────────


class MemoryReadEvent(BaseEvent):
    """Request to read from memory."""

    event_type: ClassVar[EventType] = EventType.MEMORY_READ
    payload: dict[str, Any]  # { "entry_id", "category", "filters" }


class MemoryWriteEvent(BaseEvent):
    """Write an entry to memory."""

    event_type: ClassVar[EventType] = EventType.MEMORY_WRITE
    payload: dict[str, Any]  # { "category", "entry", "overwrite" }


class MemorySearchEvent(BaseEvent):
    """Search across memory stores."""

    event_type: ClassVar[EventType] = EventType.MEMORY_SEARCH
    payload: dict[str, Any]  # { "query", "categories", "top_k", "filters" }


class MemoryUpdateEvent(BaseEvent):
    """Update an existing memory entry."""

    event_type: ClassVar[EventType] = EventType.MEMORY_UPDATE
    payload: dict[str, Any]  # { "entry_id", "updates", "version" }


class MemoryArchiveEvent(BaseEvent):
    """Archive a memory entry (soft-delete)."""

    event_type: ClassVar[EventType] = EventType.MEMORY_ARCHIVE
    payload: dict[str, Any]  # { "entry_id", "reason" }


# ── Skill Lifecycle Events ────────────────────────────────────────────


class SkillDiscoveredEvent(BaseEvent):
    """A new capability has been discovered and can be turned into a skill."""

    event_type: ClassVar[EventType] = EventType.SKILL_DISCOVERED
    payload: dict[str, Any]  # { "capability", "context", "suggested_skill_name" }


class SkillLoadedEvent(BaseEvent):
    """A skill has been loaded into the runtime for execution."""

    event_type: ClassVar[EventType] = EventType.SKILL_LOADED
    payload: dict[str, Any]  # { "skill_id", "version", "parameters", "driver" }


class SkillFinishedEvent(BaseEvent):
    """A skill has completed execution successfully."""

    event_type: ClassVar[EventType] = EventType.SKILL_FINISHED
    payload: dict[str, Any]  # { "skill_id", "result", "duration_ms", "resources_used" }


class SkillFailedEvent(BaseEvent):
    """A skill has failed during execution."""

    event_type: ClassVar[EventType] = EventType.SKILL_FAILED
    payload: dict[str, Any]  # { "skill_id", "error", "stage", "retry_count" }


class SkillStatusChangedEvent(BaseEvent):
    """A skill's lifecycle status has changed."""

    event_type: ClassVar[EventType] = EventType.SKILL_STATUS_CHANGED
    payload: dict[str, Any]  # { "skill_id", "from_status", "to_status", "reason" }


# ── Execution Events ──────────────────────────────────────────────────


class ExecutionStartEvent(BaseEvent):
    """An execution action has started on a driver."""

    event_type: ClassVar[EventType] = EventType.EXECUTION_START
    payload: dict[str, Any]  # { "action", "driver_id", "parameters", "task_id" }


class ExecutionProgressEvent(BaseEvent):
    """Progress update from an ongoing execution."""

    event_type: ClassVar[EventType] = EventType.EXECUTION_PROGRESS
    payload: dict[str, Any]  # { "task_id", "progress_pct", "status", "message" }


class ExecutionCompleteEvent(BaseEvent):
    """An execution action has completed."""

    event_type: ClassVar[EventType] = EventType.EXECUTION_COMPLETE
    payload: dict[str, Any]  # { "task_id", "result", "duration_ms" }


class ExecutionErrorEvent(BaseEvent):
    """An execution action encountered an error."""

    event_type: ClassVar[EventType] = EventType.EXECUTION_ERROR
    payload: dict[str, Any]  # { "task_id", "error", "error_type", "recoverable" }


class RobotFeedbackEvent(BaseEvent):
    """Feedback from a robotic execution driver."""

    event_type: ClassVar[EventType] = EventType.ROBOT_FEEDBACK
    payload: dict[str, Any]  # { "robot_id", "sensor_data", "joint_states", "status" }


# ── System Events ─────────────────────────────────────────────────────


class SystemStartupEvent(BaseEvent):
    """System is starting up — emitted once at initialization."""

    event_type: ClassVar[EventType] = EventType.SYSTEM_STARTUP
    payload: dict[str, Any]  # { "version", "components", "config_hash" }


class SystemShutdownEvent(BaseEvent):
    """System is shutting down gracefully."""

    event_type: ClassVar[EventType] = EventType.SYSTEM_SHUTDOWN
    payload: dict[str, Any]  # { "reason", "pending_tasks" }


class ErrorEvent(BaseEvent):
    """A system-level error has occurred."""

    event_type: ClassVar[EventType] = EventType.ERROR
    payload: dict[str, Any]  # { "error_type", "message", "stack_trace", "component" }


class HeartbeatEvent(BaseEvent):
    """Periodic heartbeat for health monitoring."""

    event_type: ClassVar[EventType] = EventType.HEARTBEAT
    payload: dict[str, Any]  # { "uptime_seconds", "active_tasks", "memory_usage_mb" }
```

## 文件路径: src/myharness/schema/identity.py

```python
"""Identity data models — the agent's canonical self-definition.

Per P0 (LLM ≠ Identity Container) and P3 (Identity Externalization):
Identity is a data asset owned by the Memory System. The LLM reads
identity via IdentityInterpretation and proposes updates via
IdentityUpdateProposal — but never directly owns or mutates identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from myharness.core.types import MemoryId


# ── Identity Fields ────────────────────────────────────────────────────


class IdentityField(StrEnum):
    """Addressable fields of the Identity model — used for targeted updates."""

    CORE_VALUES = "core_values"
    MISSION = "mission"
    PREFERENCES = "preferences"
    SELF_DESCRIPTION = "self_description"
    BEHAVIORAL_GUIDELINES = "behavioral_guidelines"


# ── Identity Model ─────────────────────────────────────────────────────


class Identity(BaseModel):
    """The agent's canonical identity — the persistent "self".

    This is the single source of truth for who the agent is. It lives in
    the Memory System and survives LLM provider switches (P8).

    The identity_id serves as both the MemoryId and the versioned identity
    reference. Version increments on any mutation.
    """

    identity_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    version: int = Field(default=1, ge=1, description="Monotonic version — incremented on each update")
    name: str = Field(default="Jarvis", description="The agent's name/callsign")
    core_values: list[str] = Field(
        default_factory=list,
        description="Immutable-ish values: e.g., ['safety', 'honesty', 'helpfulness']",
    )
    mission: str = Field(
        default="",
        description="The agent's purpose — why it exists",
    )
    preferences: dict[str, Any] = Field(
        default_factory=dict,
        description="Learned behavioral preferences and defaults",
    )
    self_description: str = Field(
        default="",
        description="The agent's understanding of its own nature, capabilities, and limitations",
    )
    behavioral_guidelines: list[str] = Field(
        default_factory=list,
        description="Explicit rules and constraints governing behavior",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def bump_version(self) -> None:
        """Increment version and update timestamp on mutation."""
        self.version += 1
        self.updated_at = datetime.now(timezone.utc)

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Identity Update Proposal ───────────────────────────────────────────


class IdentityUpdateProposal(BaseModel):
    """A proposal from the LLM Engine to modify identity.

    The LLM proposes; the Memory System decides (validates, applies, or rejects).
    This enforces P3: Identity belongs to Memory, not LLM.
    """

    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    field: IdentityField = Field(..., description="Which identity field to update")
    current_value: Any = Field(default=None, description="Current value (for validation)")
    proposed_value: Any = Field(..., description="The suggested new value")
    reasoning: str = Field(
        ...,
        min_length=1,
        description="Why this change is proposed — must cite specific experiences",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    experiences_cited: list[str] = Field(
        default_factory=list,
        description="Episode IDs that support this proposal",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

## 文件路径: src/myharness/schema/memory.py

```python
"""Memory data models — the canonical schemas for the Memory System.

Implements P3 (Identity Externalization) and P9 (Source/Derived Data Separation):
- Identity memory holds the agent's self-model (not the LLM)
- Episodic memory records experiences as immutable events
- Semantic memory stores factual knowledge with confidence scores
- Relationship memory tracks connections between entities
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from myharness.core.types import MemoryId, Embedding


# ── Memory Category ────────────────────────────────────────────────────


class MemoryCategory(StrEnum):
    """The four canonical memory types in MyHarness."""

    IDENTITY = "identity"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATIONSHIP = "relationship"


# ── Identity Memory ────────────────────────────────────────────────────


class IdentityEntry(BaseModel):
    """The agent's self-model — who it is, what it values, how it behaves.

    Per P3, Identity belongs to Memory, not LLM. The LLM reads identity
    via IdentityInterpretation and proposes updates via IdentityUpdateProposal,
    but does not directly own or persist identity data.
    """

    entry_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    version: int = Field(default=1, ge=1, description="Monotonic identity version counter")
    core_values: list[str] = Field(
        default_factory=list,
        description="Fundamental values that guide decision-making (e.g., honesty, safety)",
    )
    mission: str = Field(
        default="",
        description="The agent's overarching purpose or mission statement",
    )
    preferences: dict[str, Any] = Field(
        default_factory=dict,
        description="Learned preferences for interaction style, tools, defaults",
    )
    self_description: str = Field(
        default="",
        description="The agent's understanding of its own nature and capabilities",
    )
    behavioral_guidelines: list[str] = Field(
        default_factory=list,
        description="Explicit behavioral rules and constraints",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Episodic Memory ────────────────────────────────────────────────────


class EpisodicEntry(BaseModel):
    """A single experience, event, or conversation — the agent's personal history.

    Episodic entries are append-only and immutable. They form the raw data
    from which reflections, skills, and identity updates are derived.
    """

    entry_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    category: str = Field(
        default="general",
        description="Sub-category: conversation, task, observation, learning, etc.",
    )
    summary: str = Field(..., min_length=1, description="Concise summary of the episode")
    detail: str = Field(
        default="",
        description="Full narrative detail — the raw experience record",
    )
    participants: list[str] = Field(
        default_factory=list,
        description="Entities involved (user, system, other agents)",
    )
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Significance score [0,1] — higher = more likely to be recalled",
    )
    embedding: Embedding | None = Field(
        default=None,
        description="Vector embedding of summary+detail for semantic search (derived data)",
    )

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Semantic Memory ────────────────────────────────────────────────────


class SemanticEntry(BaseModel):
    """Factual knowledge: entity-attribute-value triples with confidence.

    Stores structured knowledge independent of when it was learned.
    """

    entry_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    entity: str = Field(..., description="The subject of this knowledge (person, object, concept)")
    attribute: str = Field(..., description="The property or relationship being described")
    value: Any = Field(..., description="The value of the attribute")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in this knowledge [0,1]",
    )
    source: str = Field(
        default="",
        description="Where this knowledge came from (episode_id, user_input, inference)",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    embedding: Embedding | None = Field(
        default=None,
        description="Vector embedding for semantic search (derived data)",
    )

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Relationship Memory ────────────────────────────────────────────────


class RelationshipEntry(BaseModel):
    """A directed relationship between two entities with typed relation and strength.

    Forms the social/relational graph of the agent's world model.
    """

    entry_id: MemoryId = Field(default_factory=lambda: MemoryId(str(uuid.uuid4())))
    entity_a: str = Field(..., description="Source entity of the relationship")
    entity_b: str = Field(..., description="Target entity of the relationship")
    relation_type: str = Field(
        ...,
        description="Type of relationship: knows, trusts, collaborates_with, reports_to, etc.",
    )
    strength: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Relationship strength [0,1]",
    )
    context: str = Field(
        default="",
        description="Contextual notes about the relationship",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Memory Query & Search ──────────────────────────────────────────────


class MemoryQuery(BaseModel):
    """A query against the memory system — supports both vector and keyword search."""

    query_text: str = Field(
        default="",
        description="Natural language query for semantic (vector) search",
    )
    query_embedding: Embedding | None = Field(
        default=None,
        description="Pre-computed embedding (skip embedding generation if provided)",
    )
    categories: list[MemoryCategory] = Field(
        default_factory=lambda: list(MemoryCategory),
        description="Which memory stores to search",
    )
    tags: list[str] = Field(default_factory=list, description="Filter by tags")
    time_range: tuple[datetime, datetime] | None = Field(
        default=None,
        description="Time window filter (start, end)",
    )
    top_k: int = Field(default=10, ge=1, le=100, description="Max results to return")
    min_importance: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum importance threshold for episodic results",
    )
    hybrid_weight: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Weight of vector vs keyword search [0=keyword-only, 1=vector-only]",
    )


class MemorySearchResult(BaseModel):
    """A single search result from the memory system."""

    entry_id: MemoryId
    category: MemoryCategory
    score: float = Field(..., description="Relevance score [0,1]")
    content: str = Field(..., description="Text representation of the matched entry")
    entry: dict[str, Any] = Field(
        default_factory=dict,
        description="Full entry data (serialized)",
    )


class MemoryBatchResult(BaseModel):
    """Result of a batch memory operation."""

    success_count: int
    failure_count: int
    results: list[MemorySearchResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    query_duration_ms: float = 0.0
```

## 文件路径: src/myharness/schema/skill.py

```python
"""Skill data models — executable capability templates.

Skills are compiled from experience (P5: Skill Accumulation) and stored
as versioned, parameterized action templates. They have no thinking
capability — only execution templates.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from myharness.core.types import SkillId


# ── Skill Lifecycle States ─────────────────────────────────────────────


class SkillStatus(StrEnum):
    """Skill lifecycle states per Section 5.2 of the architecture spec."""

    DRAFT = "draft"
    TESTING = "testing"
    VERIFIED = "verified"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


# ── Valid Transitions ──────────────────────────────────────────────────

SKILL_LIFECYCLE_TRANSITIONS: dict[SkillStatus, set[SkillStatus]] = {
    SkillStatus.DRAFT: {SkillStatus.TESTING, SkillStatus.ARCHIVED},
    SkillStatus.TESTING: {SkillStatus.VERIFIED, SkillStatus.DRAFT},
    SkillStatus.VERIFIED: {SkillStatus.STABLE, SkillStatus.TESTING},
    SkillStatus.STABLE: {SkillStatus.DEPRECATED},
    SkillStatus.DEPRECATED: {SkillStatus.STABLE, SkillStatus.ARCHIVED},
    SkillStatus.ARCHIVED: set(),  # Terminal state
}


class SkillLifecycleTransition(BaseModel):
    """Records a lifecycle state change for audit trail."""

    from_status: SkillStatus
    to_status: SkillStatus
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    triggered_by: str = "system"

    @model_validator(mode="after")
    def _validate_transition(self) -> "SkillLifecycleTransition":
        allowed = SKILL_LIFECYCLE_TRANSITIONS.get(self.from_status, set())
        if self.to_status not in allowed:
            raise ValueError(
                f"Invalid lifecycle transition: {self.from_status} → {self.to_status}. "
                f"Allowed: {allowed}"
            )
        return self


# ── Skill Parameter ────────────────────────────────────────────────────


class SkillParameter(BaseModel):
    """A single parameter for a skill — defines what the skill accepts."""

    name: str = Field(..., min_length=1, description="Parameter name")
    type: str = Field(default="string", description="Expected type: string, int, float, bool, array, object")
    description: str = Field(default="", description="What this parameter controls")
    required: bool = Field(default=True)
    default: Any = Field(default=None)
    enum_values: list[Any] | None = Field(default=None, description="Allowed values if constrained")
    validation: str | None = Field(
        default=None,
        description="Validation rule expression or regex pattern",
    )


# ── Skill Definition ───────────────────────────────────────────────────


class SkillDefinition(BaseModel):
    """A complete skill — the executable capability template.

    Per Section 5.1: Name, Version, Input, Output, Parameters, Boundary,
    Capability, Confidence.

    Per P5: Skills are the result of the Learning process, not the process itself.
    """

    skill_id: SkillId = Field(default_factory=lambda: SkillId(str(uuid.uuid4())))
    name: str = Field(..., min_length=1, description="Unique skill name (e.g., 'walk', 'grab')")
    version: str = Field(default="0.1.0", description="Semantic version")
    description: str = Field(default="", description="What this skill does")

    status: SkillStatus = Field(default=SkillStatus.DRAFT)

    # I/O schemas
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    # Parameters
    parameters: list[SkillParameter] = Field(default_factory=list)

    # Capability descriptor
    capability: str = Field(default="", description="High-level capability name")

    # Constraints
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    # Execution binding
    driver_type: str = Field(
        default="api",
        description="Target driver: robot, browser, api, mcp, computer, database, iot",
    )
    action_template: dict[str, Any] = Field(
        default_factory=dict,
        description="The actual execution template — driver-specific action definition",
    )

    # Runtime config
    timeout_seconds: float = Field(default=60.0, ge=0.0)
    retry_policy: dict[str, Any] = Field(
        default_factory=lambda: {"max_retries": 3, "backoff": "exponential"},
    )

    # Metrics
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Estimated reliability")
    usage_count: int = Field(default=0, ge=0)

    # Metadata
    author: str = Field(default="system")
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Provenance — where this skill came from
    compiled_from: list[str] = Field(
        default_factory=list,
        description="Episode IDs or experience references that produced this skill",
    )
    parent_skill_id: SkillId | None = Field(
        default=None,
        description="Parent skill if this is a specialization or variant",
    )

    # Lifecycle history
    lifecycle_history: list[SkillLifecycleTransition] = Field(default_factory=list)

    model_config = {"json_schema_extra": {"source_of_truth": True}}


# ── Skill Proposal (from LLM Reflection → Compile) ────────────────────


class SkillProposal(BaseModel):
    """A proposal from the LLM to create or update a skill.

    Generated during Compile() from reflection insights.
    """

    suggested_name: str = Field(..., min_length=1)
    description: str = Field(default="")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    driver_type: str = Field(default="api")
    action_template: dict[str, Any] = Field(default_factory=dict)
    compiled_from: list[str] = Field(default_factory=list)
    reasoning: str = Field(
        default="",
        description="Why this skill should be created — the reflection insight",
    )
    confidence_estimate: float = Field(default=0.5, ge=0.0, le=1.0)
```
