"""Harness Layer — central orchestration and system coordination.

The Harness Layer connects the EventBus, Memory, LLM, Skills, and Drivers
into a coherent cognitive pipeline. It is the "brain stem" that coordinates
all subsystems.
"""

from myharness.harness.compatibility import CompatibilityChecker
from myharness.harness.guard import ExecutionGuard
from myharness.harness.monitor import RuntimeMonitor
from myharness.harness.permission import PermissionManager
from myharness.harness.plugin import PluginManager
from myharness.harness.registry import CapabilityRegistry
from myharness.harness.scheduler import ResourceScheduler
from myharness.harness.supervisor import HarnessSupervisor

__all__ = [
    "HarnessSupervisor",
    "CapabilityRegistry",
    "ResourceScheduler",
    "RuntimeMonitor",
    "ExecutionGuard",
    "PermissionManager",
    "PluginManager",
    "CompatibilityChecker",
]
