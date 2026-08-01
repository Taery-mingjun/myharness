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
