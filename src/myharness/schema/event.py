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
