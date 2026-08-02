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

from myharness.driver.capability import CapabilityDiscovery
from myharness.driver.protocol import DriverManager, UnifiedDriverProtocol
from myharness.driver.translation import ActionTranslator
from myharness.schema.driver import ExecutionProgress, ExecutionResult

__all__ = [
    "UnifiedDriverProtocol",
    "DriverManager",
    "CapabilityDiscovery",
    "ActionTranslator",
    "ExecutionResult",
    "ExecutionProgress",
]
