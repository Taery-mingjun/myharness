"""MyHarness Schema Module.

Pydantic v2 data models defining the canonical data structures for
all system components: events, memory entries, skills, identity,
capabilities, and driver protocols.
"""

from myharness.schema.capability import (
    CapabilityAction,
    CapabilityDescriptor,
)
from myharness.schema.driver import (
    DriverInfo,
    DriverStatus,
    ExecutionProgress,
    ExecutionResult,
)
from myharness.schema.event import (
    BaseEvent,
    CognitiveRequestEvent,
    CompileResultEvent,
    ErrorEvent,
    EventType,
    ExecutionCompleteEvent,
    ExecutionErrorEvent,
    ExecutionProgressEvent,
    ExecutionStartEvent,
    HeartbeatEvent,
    IdentityInterpretationEvent,
    IdentityUpdateProposalEvent,
    MemoryArchiveEvent,
    MemoryReadEvent,
    MemorySearchEvent,
    MemoryUpdateEvent,
    MemoryWriteEvent,
    PlanResultEvent,
    ReflectResultEvent,
    RobotFeedbackEvent,
    SensorReadingEvent,
    SkillDiscoveredEvent,
    SkillFailedEvent,
    SkillFinishedEvent,
    SkillLoadedEvent,
    SkillStatusChangedEvent,
    SystemShutdownEvent,
    SystemStartupEvent,
    ThinkResultEvent,
    TimerTriggerEvent,
    UserMessageEvent,
    VisionResultEvent,
)
from myharness.schema.identity import (
    Identity,
    IdentityField,
    IdentityUpdateProposal,
)
from myharness.schema.memory import (
    EpisodicEntry,
    IdentityEntry,
    MemoryBatchResult,
    MemoryCategory,
    MemoryQuery,
    MemorySearchResult,
    RelationshipEntry,
    SemanticEntry,
)
from myharness.schema.skill import (
    SkillDefinition,
    SkillLifecycleTransition,
    SkillParameter,
    SkillProposal,
    SkillStatus,
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
