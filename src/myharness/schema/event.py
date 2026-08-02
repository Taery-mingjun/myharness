"""Event type definitions and event data models.

All system communication flows through typed events. Every event has a
unique ID, timestamp, source identifier, and optional correlation/causation
IDs for tracing the causal chain through the system.

Per Protocol 14.1 (docs/protocol/01-event-schema.md):
- BaseEvent carries the common fields: id, type, timestamp, source,
  correlation/causation ids, priority, payload, metadata.
- Every concrete event class has a typed payload model describing its
  canonical payload format.
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
        priority: Scheduling priority [0..9], 5 = normal (Protocol 14.1).
        payload: Event-specific data payload (typed per event class).
        metadata: Arbitrary key-value metadata for observability.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(default="unknown")
    correlation_id: str | None = Field(default=None)
    causation_id: str | None = Field(default=None)
    priority: int = Field(default=5, ge=0, le=9, description="Scheduling priority [0..9]")
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def _ensure_utc(cls, v: Any) -> datetime:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ── Payload Models (Protocol 14.1: canonical per-event payload formats) ─


class UserMessagePayload(BaseModel):
    """Payload for USER_MESSAGE — a message from a human user."""

    content: str = ""
    attachments: list[Any] = Field(default_factory=list)
    role: str = "user"


class VisionResultPayload(BaseModel):
    """Payload for VISION_RESULT — a computer vision processing result."""

    image_id: str = ""
    detections: list[Any] = Field(default_factory=list)
    descriptions: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class SensorReadingPayload(BaseModel):
    """Payload for SENSOR_READING — a reading from the environment."""

    sensor_id: str = ""
    sensor_type: str = ""
    value: Any = None
    unit: str = ""
    accuracy: float | None = None


class TimerTriggerPayload(BaseModel):
    """Payload for TIMER_TRIGGER — a scheduled timer has fired."""

    timer_id: str = ""
    scheduled_at: str = ""
    reason: str = ""


class CognitiveRequestPayload(BaseModel):
    """Payload for COGNITIVE_REQUEST — initiate a cognitive cycle."""

    query: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    priority: int = 5


class ThinkResultPayload(BaseModel):
    """Payload for THINK_RESULT — output of the LLM Think() operation."""

    thought: str = ""
    reasoning_trace: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    tokens_used: int = 0


class PlanResultPayload(BaseModel):
    """Payload for PLAN_RESULT — output of the LLM Plan() operation."""

    plan_id: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    estimated_cost: float = 0.0
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


class ReflectResultPayload(BaseModel):
    """Payload for REFLECT_RESULT — learning from experience."""

    experience_id: str = ""
    insights: list[str] = Field(default_factory=list)
    skill_update_proposals: list[dict[str, Any]] = Field(default_factory=list)
    identity_insights: list[dict[str, Any]] = Field(default_factory=list)


class CompileResultPayload(BaseModel):
    """Payload for COMPILE_RESULT — turning reflection into skill."""

    skill_proposal: dict[str, Any] = Field(default_factory=dict)
    compiled_from: list[str] = Field(default_factory=list)
    validation_results: list[dict[str, Any]] = Field(default_factory=list)


class IdentityInterpretationPayload(BaseModel):
    """Payload for IDENTITY_INTERPRETATION — LLM's reading of identity."""

    current_identity: dict[str, Any] = Field(default_factory=dict)
    contextual_interpretation: str = ""
    relevant_aspects: list[str] = Field(default_factory=list)


class IdentityUpdateProposalPayload(BaseModel):
    """Payload for IDENTITY_UPDATE_PROPOSAL — LLM's identity change proposal."""

    field: str = ""
    current_value: Any = None
    proposed_value: Any = None
    reasoning: str = ""
    confidence: float = 0.0


class MemoryReadPayload(BaseModel):
    """Payload for MEMORY_READ — request to read from memory."""

    entry_id: str = ""
    category: str = ""
    filters: dict[str, Any] = Field(default_factory=dict)


class MemoryWritePayload(BaseModel):
    """Payload for MEMORY_WRITE — write an entry to memory."""

    category: str = ""
    entry: dict[str, Any] = Field(default_factory=dict)
    overwrite: bool = False


class MemorySearchPayload(BaseModel):
    """Payload for MEMORY_SEARCH — search across memory stores."""

    query: str = ""
    categories: list[str] = Field(default_factory=list)
    top_k: int = 10
    filters: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdatePayload(BaseModel):
    """Payload for MEMORY_UPDATE — update an existing memory entry."""

    entry_id: str = ""
    updates: dict[str, Any] = Field(default_factory=dict)
    version: int | None = None


class MemoryArchivePayload(BaseModel):
    """Payload for MEMORY_ARCHIVE — archive a memory entry (soft-delete)."""

    entry_id: str = ""
    reason: str = ""


class SkillDiscoveredPayload(BaseModel):
    """Payload for SKILL_DISCOVERED — a new capability has been found."""

    capability: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    suggested_skill_name: str = ""


class SkillLoadedPayload(BaseModel):
    """Payload for SKILL_LOADED — a skill loaded for execution."""

    skill_id: str = ""
    version: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    driver: str = ""


class SkillFinishedPayload(BaseModel):
    """Payload for SKILL_FINISHED — a skill completed successfully."""

    skill_id: str = ""
    result: Any = None
    duration_ms: float = 0.0
    resources_used: dict[str, Any] = Field(default_factory=dict)


class SkillFailedPayload(BaseModel):
    """Payload for SKILL_FAILED — a skill failed during execution."""

    skill_id: str = ""
    error: str = ""
    stage: str = ""
    retry_count: int = 0


class SkillStatusChangedPayload(BaseModel):
    """Payload for SKILL_STATUS_CHANGED — a lifecycle status change."""

    skill_id: str = ""
    from_status: str = ""
    to_status: str = ""
    reason: str = ""


class ExecutionStartPayload(BaseModel):
    """Payload for EXECUTION_START — an execution action started."""

    action: str = ""
    driver_id: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    task_id: str = ""


class ExecutionProgressPayload(BaseModel):
    """Payload for EXECUTION_PROGRESS — progress update from execution."""

    task_id: str = ""
    progress_pct: float = 0.0
    status: str = ""
    message: str = ""


class ExecutionCompletePayload(BaseModel):
    """Payload for EXECUTION_COMPLETE — an execution action completed."""

    task_id: str = ""
    result: Any = None
    duration_ms: float = 0.0


class ExecutionErrorPayload(BaseModel):
    """Payload for EXECUTION_ERROR — an execution action errored."""

    task_id: str = ""
    error: str = ""
    error_type: str = ""
    recoverable: bool = False


class RobotFeedbackPayload(BaseModel):
    """Payload for ROBOT_FEEDBACK — feedback from a robotic driver."""

    robot_id: str = ""
    sensor_data: dict[str, Any] = Field(default_factory=dict)
    joint_states: dict[str, Any] = Field(default_factory=dict)
    status: str = ""


class SystemStartupPayload(BaseModel):
    """Payload for SYSTEM_STARTUP — emitted once at initialization."""

    version: str = ""
    components: list[str] = Field(default_factory=list)
    config_hash: str = ""


class SystemShutdownPayload(BaseModel):
    """Payload for SYSTEM_SHUTDOWN — graceful shutdown."""

    reason: str = ""
    pending_tasks: int = 0


class ErrorPayload(BaseModel):
    """Payload for ERROR — a system-level error occurred."""

    error_type: str = ""
    message: str = ""
    stack_trace: str = ""
    component: str = ""


class HeartbeatPayload(BaseModel):
    """Payload for HEARTBEAT — periodic health monitoring."""

    uptime_seconds: float = 0.0
    active_tasks: int = 0
    memory_usage_mb: float = 0.0


# ── External Input Events ─────────────────────────────────────────────


class UserMessageEvent(BaseEvent):
    """A message from a human user to the cognitive system."""

    event_type: ClassVar[EventType] = EventType.USER_MESSAGE
    payload: UserMessagePayload = Field(default_factory=UserMessagePayload)


class VisionResultEvent(BaseEvent):
    """Result from a computer vision processing step."""

    event_type: ClassVar[EventType] = EventType.VISION_RESULT
    payload: VisionResultPayload = Field(default_factory=VisionResultPayload)


class SensorReadingEvent(BaseEvent):
    """A sensor reading from the physical or digital environment."""

    event_type: ClassVar[EventType] = EventType.SENSOR_READING
    payload: SensorReadingPayload = Field(default_factory=SensorReadingPayload)


class TimerTriggerEvent(BaseEvent):
    """A scheduled timer has fired."""

    event_type: ClassVar[EventType] = EventType.TIMER_TRIGGER
    payload: TimerTriggerPayload = Field(default_factory=TimerTriggerPayload)


# ── Cognitive Pipeline Events ─────────────────────────────────────────


class CognitiveRequestEvent(BaseEvent):
    """Request to initiate a cognitive processing cycle."""

    event_type: ClassVar[EventType] = EventType.COGNITIVE_REQUEST
    payload: CognitiveRequestPayload = Field(default_factory=CognitiveRequestPayload)


class ThinkResultEvent(BaseEvent):
    """Result of the LLM Think() operation."""

    event_type: ClassVar[EventType] = EventType.THINK_RESULT
    payload: ThinkResultPayload = Field(default_factory=ThinkResultPayload)


class PlanResultEvent(BaseEvent):
    """Result of the LLM Plan() operation."""

    event_type: ClassVar[EventType] = EventType.PLAN_RESULT
    payload: PlanResultPayload = Field(default_factory=PlanResultPayload)


class ReflectResultEvent(BaseEvent):
    """Result of the LLM Reflect() operation — learning from experience."""

    event_type: ClassVar[EventType] = EventType.REFLECT_RESULT
    payload: ReflectResultPayload = Field(default_factory=ReflectResultPayload)


class CompileResultEvent(BaseEvent):
    """Result of the LLM Compile() operation — turning reflection into skill."""

    event_type: ClassVar[EventType] = EventType.COMPILE_RESULT
    payload: CompileResultPayload = Field(default_factory=CompileResultPayload)


# ── Identity Events ───────────────────────────────────────────────────


class IdentityInterpretationEvent(BaseEvent):
    """LLM's interpretation of the current identity state."""

    event_type: ClassVar[EventType] = EventType.IDENTITY_INTERPRETATION
    payload: IdentityInterpretationPayload = Field(default_factory=IdentityInterpretationPayload)


class IdentityUpdateProposalEvent(BaseEvent):
    """LLM's proposal to update identity based on experience."""

    event_type: ClassVar[EventType] = EventType.IDENTITY_UPDATE_PROPOSAL
    payload: IdentityUpdateProposalPayload = Field(default_factory=IdentityUpdateProposalPayload)


# ── Memory Operation Events ───────────────────────────────────────────


class MemoryReadEvent(BaseEvent):
    """Request to read from memory."""

    event_type: ClassVar[EventType] = EventType.MEMORY_READ
    payload: MemoryReadPayload = Field(default_factory=MemoryReadPayload)


class MemoryWriteEvent(BaseEvent):
    """Write an entry to memory."""

    event_type: ClassVar[EventType] = EventType.MEMORY_WRITE
    payload: MemoryWritePayload = Field(default_factory=MemoryWritePayload)


class MemorySearchEvent(BaseEvent):
    """Search across memory stores."""

    event_type: ClassVar[EventType] = EventType.MEMORY_SEARCH
    payload: MemorySearchPayload = Field(default_factory=MemorySearchPayload)


class MemoryUpdateEvent(BaseEvent):
    """Update an existing memory entry."""

    event_type: ClassVar[EventType] = EventType.MEMORY_UPDATE
    payload: MemoryUpdatePayload = Field(default_factory=MemoryUpdatePayload)


class MemoryArchiveEvent(BaseEvent):
    """Archive a memory entry (soft-delete)."""

    event_type: ClassVar[EventType] = EventType.MEMORY_ARCHIVE
    payload: MemoryArchivePayload = Field(default_factory=MemoryArchivePayload)


# ── Skill Lifecycle Events ────────────────────────────────────────────


class SkillDiscoveredEvent(BaseEvent):
    """A new capability has been discovered and can be turned into a skill."""

    event_type: ClassVar[EventType] = EventType.SKILL_DISCOVERED
    payload: SkillDiscoveredPayload = Field(default_factory=SkillDiscoveredPayload)


class SkillLoadedEvent(BaseEvent):
    """A skill has been loaded into the runtime for execution."""

    event_type: ClassVar[EventType] = EventType.SKILL_LOADED
    payload: SkillLoadedPayload = Field(default_factory=SkillLoadedPayload)


class SkillFinishedEvent(BaseEvent):
    """A skill has completed execution successfully."""

    event_type: ClassVar[EventType] = EventType.SKILL_FINISHED
    payload: SkillFinishedPayload = Field(default_factory=SkillFinishedPayload)


class SkillFailedEvent(BaseEvent):
    """A skill has failed during execution."""

    event_type: ClassVar[EventType] = EventType.SKILL_FAILED
    payload: SkillFailedPayload = Field(default_factory=SkillFailedPayload)


class SkillStatusChangedEvent(BaseEvent):
    """A skill's lifecycle status has changed."""

    event_type: ClassVar[EventType] = EventType.SKILL_STATUS_CHANGED
    payload: SkillStatusChangedPayload = Field(default_factory=SkillStatusChangedPayload)


# ── Execution Events ──────────────────────────────────────────────────


class ExecutionStartEvent(BaseEvent):
    """An execution action has started on a driver."""

    event_type: ClassVar[EventType] = EventType.EXECUTION_START
    payload: ExecutionStartPayload = Field(default_factory=ExecutionStartPayload)


class ExecutionProgressEvent(BaseEvent):
    """Progress update from an ongoing execution."""

    event_type: ClassVar[EventType] = EventType.EXECUTION_PROGRESS
    payload: ExecutionProgressPayload = Field(default_factory=ExecutionProgressPayload)


class ExecutionCompleteEvent(BaseEvent):
    """An execution action has completed."""

    event_type: ClassVar[EventType] = EventType.EXECUTION_COMPLETE
    payload: ExecutionCompletePayload = Field(default_factory=ExecutionCompletePayload)


class ExecutionErrorEvent(BaseEvent):
    """An execution action encountered an error."""

    event_type: ClassVar[EventType] = EventType.EXECUTION_ERROR
    payload: ExecutionErrorPayload = Field(default_factory=ExecutionErrorPayload)


class RobotFeedbackEvent(BaseEvent):
    """Feedback from a robotic execution driver."""

    event_type: ClassVar[EventType] = EventType.ROBOT_FEEDBACK
    payload: RobotFeedbackPayload = Field(default_factory=RobotFeedbackPayload)


# ── System Events ─────────────────────────────────────────────────────


class SystemStartupEvent(BaseEvent):
    """System is starting up — emitted once at initialization."""

    event_type: ClassVar[EventType] = EventType.SYSTEM_STARTUP
    payload: SystemStartupPayload = Field(default_factory=SystemStartupPayload)


class SystemShutdownEvent(BaseEvent):
    """System is shutting down gracefully."""

    event_type: ClassVar[EventType] = EventType.SYSTEM_SHUTDOWN
    payload: SystemShutdownPayload = Field(default_factory=SystemShutdownPayload)


class ErrorEvent(BaseEvent):
    """A system-level error has occurred."""

    event_type: ClassVar[EventType] = EventType.ERROR
    payload: ErrorPayload = Field(default_factory=ErrorPayload)


class HeartbeatEvent(BaseEvent):
    """Periodic heartbeat for health monitoring."""

    event_type: ClassVar[EventType] = EventType.HEARTBEAT
    payload: HeartbeatPayload = Field(default_factory=HeartbeatPayload)
