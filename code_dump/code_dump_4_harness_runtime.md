# code_dump_4_harness_runtime.md

本文件为第 4 部分，包含目录: harness, runtime/

包含文件数: 14

## 文件路径: src/myharness/harness/__init__.py

```python
"""Harness Layer — central orchestration and system coordination.

The Harness Layer connects the EventBus, Memory, LLM, Skills, and Drivers
into a coherent cognitive pipeline. It is the "brain stem" that coordinates
all subsystems.
"""

from myharness.harness.supervisor import HarnessSupervisor
from myharness.harness.registry import CapabilityRegistry
from myharness.harness.scheduler import ResourceScheduler
from myharness.harness.monitor import RuntimeMonitor
from myharness.harness.permission import PermissionManager
from myharness.harness.plugin import PluginManager
from myharness.harness.compatibility import CompatibilityChecker

__all__ = [
    "HarnessSupervisor",
    "CapabilityRegistry",
    "ResourceScheduler",
    "RuntimeMonitor",
    "PermissionManager",
    "PluginManager",
    "CompatibilityChecker",
]
```

## 文件路径: src/myharness/harness/compatibility.py

```python
"""Version compatibility checking between system components.

Ensures that drivers, skills, and LLM providers are compatible with
each other before execution.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class CompatibilityChecker:
    """Version compatibility checking between system components.

    All methods are static — compatibility checking is a pure function
    with no side effects. Uses semantic versioning for comparison.
    """

    @staticmethod
    def check_driver_compatibility(
        driver_version: str, required_version: str
    ) -> bool:
        """Check if a driver version is compatible with a required version.

        Compatibility rules:
        - Same major version required.
        - Minor version must be >= required.
        - Patch version ignored for compatibility.

        Args:
            driver_version: The actual driver version (e.g., "1.2.0").
            required_version: The minimum required version (e.g., "1.0.0").

        Returns:
            True if compatible, False otherwise.
        """
        try:
            d_major, d_minor, _ = map(int, driver_version.split("."))
            r_major, r_minor, _ = map(int, required_version.split("."))
        except (ValueError, AttributeError):
            logger.warning(
                "invalid_version_format",
                driver_version=driver_version,
                required_version=required_version,
            )
            return False

        if d_major != r_major:
            logger.debug(
                "driver_version_major_mismatch",
                driver_version=driver_version,
                required_version=required_version,
            )
            return False

        if d_minor < r_minor:
            logger.debug(
                "driver_version_minor_too_low",
                driver_version=driver_version,
                required_version=required_version,
            )
            return False

        return True

    @staticmethod
    def check_skill_compatibility(
        skill_version: str, system_version: str
    ) -> bool:
        """Check if a skill version is compatible with the system version.

        Same rules as driver compatibility: same major, minor >= required.

        Args:
            skill_version: The skill's version string.
            system_version: The system's minimum supported version.

        Returns:
            True if compatible, False otherwise.
        """
        return CompatibilityChecker.check_driver_compatibility(
            skill_version, system_version
        )

    @staticmethod
    def check_llm_provider_compatibility(
        provider_name: str,
        required_capabilities: list[str],
    ) -> bool:
        """Check if an LLM provider supports the required capabilities.

        Args:
            provider_name: The LLM provider name.
            required_capabilities: List of required capability names.

        Returns:
            True if the provider supports all required capabilities.
        """
        # Known provider capabilities
        provider_capabilities: dict[str, set[str]] = {
            "openai": {
                "function_calling",
                "streaming",
                "json_mode",
                "vision",
                "embeddings",
                "structured_output",
            },
            "anthropic": {
                "function_calling",
                "streaming",
                "vision",
                "tool_use",
            },
            "google": {
                "function_calling",
                "streaming",
                "vision",
                "embeddings",
                "json_mode",
            },
            "qwen": {
                "function_calling",
                "streaming",
                "vision",
            },
            "deepseek": {
                "function_calling",
                "streaming",
            },
            "ollama": {
                "streaming",
            },
        }

        provider_caps = provider_capabilities.get(provider_name.lower(), set())

        missing = set(required_capabilities) - provider_caps
        if missing:
            logger.debug(
                "llm_provider_missing_capabilities",
                provider=provider_name,
                missing=list(missing),
            )
            return False

        return True
```

## 文件路径: src/myharness/harness/monitor.py

```python
"""Runtime monitor — system health, metrics, and performance tracking.

Tracks system health metrics, provides heartbeat functionality, and
enables health check queries for the overall system state.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class RuntimeMonitor:
    """Tracks system health, metrics, and performance.

    Collects and exposes runtime metrics for observability and debugging.
    Supports a periodic heartbeat for health monitoring and metric
    aggregation.
    """

    def __init__(self) -> None:
        """Initialize the runtime monitor."""
        self._metrics: dict[str, list[tuple[float, float]]] = {}
        self._health_status: dict[str, bool] = {}
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_interval: float = 5.0
        self._start_time: float = time.monotonic()
        logger.info("runtime_monitor_initialized")

    async def record_metric(
        self,
        name: str,
        value: float,
        tags: dict | None = None,
    ) -> None:
        """Record a metric value.

        Args:
            name: The metric name (e.g., "cognitive_pipeline.duration_ms").
            value: The metric value.
            tags: Optional key-value tags for categorization.
        """
        timestamp = time.monotonic()
        if name not in self._metrics:
            self._metrics[name] = []
        self._metrics[name].append((timestamp, value))

        # Keep only the last 1000 values per metric
        if len(self._metrics[name]) > 1000:
            self._metrics[name] = self._metrics[name][-1000:]

        if tags:
            logger.debug(
                "metric_recorded",
                name=name,
                value=value,
                **tags,
            )
        else:
            logger.debug(
                "metric_recorded",
                name=name,
                value=value,
            )

    async def get_metrics(self) -> dict[str, Any]:
        """Get current metrics summary.

        Returns:
            A dictionary with metric names and their latest values,
            averages, min, max, and count.
        """
        result: dict[str, Any] = {
            "uptime_seconds": time.monotonic() - self._start_time,
            "metrics_count": len(self._metrics),
            "metrics": {},
        }

        for name, values in self._metrics.items():
            if not values:
                result["metrics"][name] = {
                    "latest": None,
                    "avg": None,
                    "count": 0,
                }
                continue

            vals = [v[1] for v in values]
            result["metrics"][name] = {
                "latest": vals[-1],
                "avg": sum(vals) / len(vals),
                "min": min(vals),
                "max": max(vals),
                "count": len(vals),
            }

        return result

    async def health_check(self) -> dict[str, bool]:
        """Perform a system health check.

        Returns:
            A dictionary mapping component names to their health status.
        """
        return dict(self._health_status)

    async def set_health(self, component: str, healthy: bool) -> None:
        """Update the health status of a component.

        Args:
            component: The component name.
            healthy: Whether the component is healthy.
        """
        self._health_status[component] = healthy

    async def start_heartbeat(self, interval: float = 5.0) -> None:
        """Start the periodic heartbeat.

        Args:
            interval: Heartbeat interval in seconds.
        """
        if self._heartbeat_task is not None:
            logger.warning("heartbeat_already_running")
            return

        self._heartbeat_interval = interval
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(
            "heartbeat_started",
            interval=interval,
        )

    async def stop_heartbeat(self) -> None:
        """Stop the periodic heartbeat."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
            logger.info("heartbeat_stopped")

    async def _heartbeat_loop(self) -> None:
        """Internal heartbeat loop that records periodic metrics."""
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self.record_metric(
                    "system.heartbeat",
                    1.0,
                    tags={"uptime_seconds": str(self._start_time)},
                )
                logger.debug(
                    "heartbeat",
                    uptime_seconds=time.monotonic() - self._start_time,
                )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("heartbeat_error", exc_info=True)
```

## 文件路径: src/myharness/harness/permission.py

```python
"""Access control for skills and driver operations.

Provides a simple RBAC (Role-Based Access Control) mechanism for
controlling which actors can perform which actions on which resources.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class PermissionManager:
    """Access control for skills and driver operations.

    Manages permissions using an actor-resource-action model. Each actor
    can be granted or revoked specific actions on specific resources.

    Permissions are stored in-memory for this implementation. A
    production system would use a persistent backend.
    """

    def __init__(self) -> None:
        """Initialize the permission manager."""
        # Structure: {actor: {resource: [actions]}}
        self._permissions: dict[str, dict[str, list[str]]] = {}
        logger.info("permission_manager_initialized")

    async def check(
        self, actor: str, resource: str, action: str
    ) -> bool:
        """Check if an actor has permission for an action on a resource.

        Args:
            actor: The actor requesting permission (e.g., "user_123").
            resource: The resource being accessed (e.g., "skill:walk").
            action: The action being performed (e.g., "execute", "read").

        Returns:
            True if the actor has permission, False otherwise.
        """
        actor_perms = self._permissions.get(actor, {})
        resource_actions = actor_perms.get(resource, [])

        # Check exact match or wildcard
        if action in resource_actions or "*" in resource_actions:
            return True

        # Check wildcard resource
        wildcard_actions = actor_perms.get("*", [])
        if action in wildcard_actions or "*" in wildcard_actions:
            return True

        logger.debug(
            "permission_denied",
            actor=actor,
            resource=resource,
            action=action,
        )
        return False

    async def grant(
        self, actor: str, resource: str, action: str
    ) -> None:
        """Grant a permission to an actor.

        Args:
            actor: The actor to grant permission to.
            resource: The resource to grant access to.
            action: The action to allow.
        """
        if actor not in self._permissions:
            self._permissions[actor] = {}

        if resource not in self._permissions[actor]:
            self._permissions[actor][resource] = []

        if action not in self._permissions[actor][resource]:
            self._permissions[actor][resource].append(action)
            logger.info(
                "permission_granted",
                actor=actor,
                resource=resource,
                action=action,
            )

    async def revoke(
        self, actor: str, resource: str, action: str
    ) -> None:
        """Revoke a permission from an actor.

        Args:
            actor: The actor to revoke permission from.
            resource: The resource to revoke access to.
            action: The action to disallow.
        """
        actor_perms = self._permissions.get(actor)
        if actor_perms is None:
            return

        resource_actions = actor_perms.get(resource)
        if resource_actions is None:
            return

        if action in resource_actions:
            resource_actions.remove(action)
            logger.info(
                "permission_revoked",
                actor=actor,
                resource=resource,
                action=action,
            )

        # Clean up empty entries
        if not resource_actions:
            del actor_perms[resource]
        if not actor_perms:
            del self._permissions[actor]

    async def get_permissions(self, actor: str) -> dict[str, list[str]]:
        """Get all permissions for an actor.

        Args:
            actor: The actor to query.

        Returns:
            A dictionary mapping resources to lists of allowed actions.
        """
        return dict(self._permissions.get(actor, {}))
```

## 文件路径: src/myharness/harness/plugin.py

```python
"""Dynamic plugin loading and lifecycle management.

Supports loading, unloading, and reloading plugins that extend the
system's capabilities at runtime.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import structlog

from myharness.core.exceptions import HarnessError

logger = structlog.get_logger(__name__)


class PluginManager:
    """Dynamic plugin loading and lifecycle management.

    Plugins are Python modules that can be loaded at runtime to extend
    the system's capabilities. Each plugin must have a register()
    function that accepts the harness supervisor and registers its
    components.
    """

    def __init__(self, supervisor: Any = None) -> None:
        """Initialize the plugin manager.

        Args:
            supervisor: The harness supervisor for plugin registration.
        """
        self._supervisor = supervisor
        self._plugins: dict[str, Any] = {}
        logger.info("plugin_manager_initialized")

    async def load_plugin(self, plugin_path: str) -> None:
        """Load a plugin from a file path or module name.

        Args:
            plugin_path: Path to the plugin Python file or dotted module name.

        Raises:
            HarnessError: If the plugin cannot be loaded.
        """
        plugin_path_obj = Path(plugin_path)
        plugin_name: str

        if plugin_path_obj.exists() and plugin_path_obj.is_file():
            # Load from file path
            plugin_name = plugin_path_obj.stem
            spec = importlib.util.spec_from_file_location(
                plugin_name, str(plugin_path_obj)
            )
            if spec is None or spec.loader is None:
                raise HarnessError(
                    f"Could not load plugin from path: {plugin_path}",
                    code="PLUGIN_LOAD_ERROR",
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[plugin_name] = module
            spec.loader.exec_module(module)
        else:
            # Load as module name
            plugin_name = plugin_path
            module = importlib.import_module(plugin_path)

        # Call register if available
        if hasattr(module, "register") and self._supervisor is not None:
            if callable(module.register):
                result = module.register(self._supervisor)
                if hasattr(result, "__await__"):
                    await result

        self._plugins[plugin_name] = module
        logger.info("plugin_loaded", plugin_name=plugin_name)

    async def unload_plugin(self, plugin_name: str) -> None:
        """Unload a previously loaded plugin.

        Args:
            plugin_name: The name of the plugin to unload.
        """
        if plugin_name not in self._plugins:
            logger.warning(
                "plugin_not_loaded",
                plugin_name=plugin_name,
            )
            return

        module = self._plugins.pop(plugin_name)

        # Call unregister if available
        if hasattr(module, "unregister"):
            if callable(module.unregister):
                result = module.unregister()
                if hasattr(result, "__await__"):
                    await result

        # Remove from sys.modules
        sys.modules.pop(plugin_name, None)

        logger.info("plugin_unloaded", plugin_name=plugin_name)

    async def list_plugins(self) -> list[str]:
        """List all loaded plugins.

        Returns:
            A list of loaded plugin names.
        """
        return sorted(self._plugins.keys())

    async def reload_plugin(self, plugin_name: str) -> None:
        """Reload a plugin by unloading and loading it again.

        Args:
            plugin_name: The name of the plugin to reload.

        Raises:
            HarnessError: If the plugin is not currently loaded.
        """
        if plugin_name not in self._plugins:
            raise HarnessError(
                f"Plugin not loaded: {plugin_name}",
                code="PLUGIN_NOT_FOUND",
            )

        module = self._plugins[plugin_name]
        source_file = getattr(module, "__file__", None)

        await self.unload_plugin(plugin_name)

        if source_file:
            await self.load_plugin(source_file)
        else:
            await self.load_plugin(plugin_name)

        logger.info("plugin_reloaded", plugin_name=plugin_name)
```

## 文件路径: src/myharness/harness/registry.py

```python
"""Capability Registry — discovers and tracks execution capabilities.

Capabilities are discovered (not declared) from registered drivers.
The registry provides capability lookup and matching services to the
rest of the system.
"""

from __future__ import annotations

from typing import Any

import structlog

from myharness.schema.capability import CapabilityDescriptor
from myharness.core.exceptions import CapabilityNotFoundError

logger = structlog.get_logger(__name__)


class CapabilityRegistry:
    """Discovers and tracks available execution capabilities.

    Capabilities are discovered from registered drivers. Each capability
    maps to one or more concrete actions on a specific driver.

    The registry is the system's "what can I do?" answer — it tells the
    cognitive pipeline what execution options are available.
    """

    def __init__(self) -> None:
        """Initialize the capability registry."""
        self._drivers: dict[str, Any] = {}
        self._capabilities: dict[str, CapabilityDescriptor] = {}
        self._driver_capabilities: dict[str, list[str]] = {}
        logger.info("capability_registry_initialized")

    async def register_driver(self, driver: Any) -> None:
        """Register a driver and discover its capabilities.

        Args:
            driver: A driver instance implementing UnifiedDriverProtocol.
        """
        driver_name = getattr(driver, "driver_name", "unknown")
        self._drivers[driver_name] = driver

        # Discover capabilities from the driver
        caps = getattr(driver, "capabilities", [])
        cap_ids: list[str] = []
        for cap in caps:
            self._capabilities[cap.name] = cap
            cap_ids.append(cap.name)

        self._driver_capabilities[driver_name] = cap_ids

        logger.info(
            "driver_registered",
            driver_name=driver_name,
            capabilities_count=len(caps),
        )

    async def discover_capabilities(self) -> list[CapabilityDescriptor]:
        """Get all discovered capabilities across all drivers.

        Returns:
            A list of all registered capability descriptors.
        """
        return list(self._capabilities.values())

    async def get_driver_for_capability(self, capability: str) -> Any:
        """Get the driver that provides a specific capability.

        Args:
            capability: The capability name.

        Returns:
            The driver instance that provides this capability.

        Raises:
            CapabilityNotFoundError: If no driver provides the capability.
        """
        cap = self._capabilities.get(capability)
        if cap is None:
            raise CapabilityNotFoundError(
                f"No driver found for capability: {capability}",
                code="CAPABILITY_NOT_FOUND",
                details={"capability": capability},
            )

        driver_name = cap.driver_name
        driver = self._drivers.get(driver_name)
        if driver is None:
            raise CapabilityNotFoundError(
                f"Driver '{driver_name}' for capability '{capability}' is not registered",
                code="DRIVER_NOT_FOUND",
                details={
                    "capability": capability,
                    "driver_name": driver_name,
                },
            )

        return driver

    async def list_available_capabilities(self) -> list[str]:
        """List all available capability names.

        Returns:
            A sorted list of capability name strings.
        """
        return sorted(self._capabilities.keys())

    async def check_capability(self, capability: str) -> bool:
        """Check if a specific capability is available.

        Args:
            capability: The capability name to check.

        Returns:
            True if the capability is registered and its driver is connected.
        """
        cap = self._capabilities.get(capability)
        if cap is None:
            return False

        driver = self._drivers.get(cap.driver_name)
        if driver is None:
            return False

        # Check if driver is healthy
        if hasattr(driver, "health_check"):
            try:
                healthy = await driver.health_check()
                return healthy
            except Exception:
                return False

        return True
```

## 文件路径: src/myharness/harness/scheduler.py

```python
"""Priority-based resource scheduler for concurrent task management.

Manages the execution queue with priority-based scheduling, timeout
handling, and cancellation support.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)


@dataclass(order=True)
class ScheduledTask:
    """A task scheduled for execution.

    Attributes:
        priority: Execution priority (0 = highest, larger = lower).
        task_id: Unique task identifier.
        resource_type: Type of resource this task requires.
        action: The async callable to execute.
        timeout: Maximum execution time in seconds.
        created_at: When the task was created.
    """

    priority: int = field(compare=True)
    task_id: str = field(compare=False, default_factory=lambda: str(uuid.uuid4()))
    resource_type: str = field(compare=False, default="default")
    action: Callable | None = field(compare=False, default=None)
    timeout: float = field(compare=False, default=300.0)
    created_at: datetime = field(
        compare=False, default_factory=lambda: datetime.now(timezone.utc)
    )


class ResourceScheduler:
    """Priority-based resource scheduler for concurrent tasks.

    Manages task queues per resource type, ensuring fair scheduling
    with priority ordering. Lower priority numbers execute first.

    Supports:
    - Priority-based scheduling (0 = highest priority).
    - Per-resource-type queue management.
    - Task cancellation.
    - Timeout enforcement.
    - Queue status introspection.
    """

    def __init__(self, max_concurrent: int = 10) -> None:
        """Initialize the resource scheduler.

        Args:
            max_concurrent: Maximum number of concurrently executing tasks.
        """
        self._max_concurrent = max_concurrent
        self._queues: dict[str, list[ScheduledTask]] = defaultdict(list)
        self._running: dict[str, ScheduledTask] = {}
        self._completed: dict[str, Any] = {}
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()
        logger.info(
            "resource_scheduler_initialized",
            max_concurrent=max_concurrent,
        )

    async def schedule(self, task: ScheduledTask) -> str:
        """Schedule a task for execution.

        Args:
            task: The task to schedule.

        Returns:
            The task ID for tracking.
        """
        async with self._lock:
            self._queues[task.resource_type].append(task)
            self._queues[task.resource_type].sort(
                key=lambda t: (t.priority, t.created_at)
            )

        logger.debug(
            "task_scheduled",
            task_id=task.task_id,
            resource_type=task.resource_type,
            priority=task.priority,
        )

        # Try to execute immediately if slots available
        asyncio.create_task(self._try_execute())

        return task.task_id

    async def cancel(self, task_id: str) -> None:
        """Cancel a scheduled or running task.

        Args:
            task_id: The ID of the task to cancel.
        """
        async with self._lock:
            self._cancelled.add(task_id)

            # Remove from queue if pending
            for resource_type, queue in self._queues.items():
                self._queues[resource_type] = [
                    t for t in queue if t.task_id != task_id
                ]

        logger.info("task_cancelled", task_id=task_id)

    async def get_queue_status(self) -> dict[str, Any]:
        """Get the current status of all task queues.

        Returns:
            A dictionary with queue statistics.
        """
        async with self._lock:
            by_resource: dict[str, dict[str, int]] = {}
            for resource_type, queue in self._queues.items():
                by_resource[resource_type] = {
                    "pending": len(queue),
                    "running": sum(
                        1 for t in self._running.values()
                        if t.resource_type == resource_type
                    ),
                }

            return {
                "total_pending": sum(len(q) for q in self._queues.values()),
                "total_running": len(self._running),
                "total_completed": len(self._completed),
                "max_concurrent": self._max_concurrent,
                "by_resource": by_resource,
            }

    async def _try_execute(self) -> None:
        """Try to execute pending tasks if capacity is available."""
        while len(self._running) < self._max_concurrent:
            task = await self._dequeue_next()
            if task is None:
                break

            if task.task_id in self._cancelled:
                continue

            self._running[task.task_id] = task
            asyncio.create_task(self._execute_task(task))

    async def _dequeue_next(self) -> ScheduledTask | None:
        """Dequeue the highest priority task across all queues."""
        async with self._lock:
            best_task: ScheduledTask | None = None
            best_queue: str | None = None

            for resource_type, queue in self._queues.items():
                if not queue:
                    continue
                candidate = queue[0]
                if (
                    best_task is None
                    or candidate.priority < best_task.priority
                    or (
                        candidate.priority == best_task.priority
                        and candidate.created_at < best_task.created_at
                    )
                ):
                    best_task = candidate
                    best_queue = resource_type

            if best_task is not None and best_queue is not None:
                self._queues[best_queue].pop(0)
                return best_task

            return None

    async def _execute_task(self, task: ScheduledTask) -> None:
        """Execute a single task with timeout handling.

        Args:
            task: The task to execute.
        """
        logger.debug(
            "task_execution_starting",
            task_id=task.task_id,
        )

        try:
            if task.action is not None:
                result = await asyncio.wait_for(
                    task.action() if asyncio.iscoroutinefunction(task.action)
                    else task.action,
                    timeout=task.timeout,
                )
                self._completed[task.task_id] = {
                    "success": True,
                    "result": result,
                }
                logger.debug(
                    "task_execution_complete",
                    task_id=task.task_id,
                )
            else:
                self._completed[task.task_id] = {
                    "success": True,
                    "result": None,
                }
        except asyncio.TimeoutError:
            logger.warning(
                "task_execution_timeout",
                task_id=task.task_id,
                timeout=task.timeout,
            )
            self._completed[task.task_id] = {
                "success": False,
                "error": "Timeout",
            }
        except Exception as exc:
            logger.error(
                "task_execution_failed",
                task_id=task.task_id,
                error=str(exc),
            )
            self._completed[task.task_id] = {
                "success": False,
                "error": str(exc),
            }
        finally:
            async with self._lock:
                self._running.pop(task.task_id, None)

            # Try to execute next task
            await self._try_execute()
```

## 文件路径: src/myharness/harness/supervisor.py

```python
"""Central orchestrator — the "brain stem" of MyHarness.

Connects EventBus, Memory, LLM, Skills, and Drivers into a unified
cognitive pipeline. Coordinates all subsystems during boot, runtime,
and shutdown.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from myharness.schema.event import (
    SystemShutdownEvent,
    SystemStartupEvent,
)

logger = structlog.get_logger(__name__)


class HarnessSupervisor:
    """Central orchestrator connecting all MyHarness subsystems.

    This is the "brain stem" that coordinates:
    - EventBus: System-wide event routing.
    - Router: Cognitive pipeline routing.
    - Memory: Episodic, semantic, and identity storage.
    - LLM Engine: Cognitive computation.
    - Skill Store: Executable capability templates.
    - Capability Registry: Available execution capabilities.
    - Driver Manager: Execution driver lifecycle.
    - Scheduler: Concurrent task management.
    - Monitor: Health and metrics tracking.
    """

    def __init__(
        self,
        event_bus: Any,
        router: Any,
        memory: Any,
        llm_engine: Any,
        skill_store: Any,
        capability_registry: Any,
        driver_manager: Any,
        scheduler: Any,
        monitor: Any,
    ) -> None:
        """Initialize the harness supervisor.

        Args:
            event_bus: The system event bus.
            router: The cognitive pipeline router.
            memory: The memory system instance.
            llm_engine: The LLM engine for cognitive computation.
            skill_store: The skill store for capability templates.
            capability_registry: The capability registry.
            driver_manager: The execution driver manager.
            scheduler: The resource scheduler.
            monitor: The runtime monitor.
        """
        self._event_bus = event_bus
        self._router = router
        self._memory = memory
        self._llm_engine = llm_engine
        self._skill_store = skill_store
        self._capability_registry = capability_registry
        self._driver_manager = driver_manager
        self._scheduler = scheduler
        self._monitor = monitor

        self._boot_time: float = 0.0
        self._is_running = False
        self._active_tasks: dict[str, Any] = {}

        logger.info("harness_supervisor_initialized")

    async def boot(self) -> None:
        """Initialize all subsystems, register routes, start monitoring.

        Boot sequence:
        1. Start the event bus.
        2. Initialize memory system.
        3. Load skills from storage.
        4. Register drivers and discover capabilities.
        5. Start runtime monitor (heartbeat).
        6. Emit SystemStartupEvent.
        """
        self._boot_time = time.monotonic()
        logger.info("harness_boot_starting")

        # Start event bus
        if hasattr(self._event_bus, "start"):
            await self._event_bus.start()

        # Initialize memory
        if hasattr(self._memory, "initialize"):
            await self._memory.initialize()

        # Start the monitor heartbeat
        if hasattr(self._monitor, "start_heartbeat"):
            await self._monitor.start_heartbeat()

        self._is_running = True

        # Emit startup event
        startup_event = SystemStartupEvent(
            source="harness.supervisor",
            payload={
                "version": "0.1.0",
                "components": [
                    "event_bus",
                    "router",
                    "memory",
                    "llm_engine",
                    "skill_store",
                    "capability_registry",
                    "driver_manager",
                    "scheduler",
                    "monitor",
                ],
            },
        )
        if hasattr(self._event_bus, "emit"):
            await self._event_bus.emit(startup_event)

        logger.info(
            "harness_boot_complete",
            boot_duration_ms=(time.monotonic() - self._boot_time) * 1000,
        )

    async def shutdown(self) -> None:
        """Graceful shutdown of all subsystems.

        Shutdown sequence:
        1. Stop accepting new events.
        2. Cancel active tasks.
        3. Shutdown all drivers.
        4. Stop the monitor.
        5. Emit SystemShutdownEvent.
        6. Stop the event bus.
        """
        logger.info("harness_shutdown_starting")
        self._is_running = False

        # Cancel active tasks
        for task_id in list(self._active_tasks.keys()):
            try:
                await self._scheduler.cancel(task_id)
            except Exception:
                logger.warning(
                    "task_cancel_failed",
                    task_id=task_id,
                    exc_info=True,
                )

        # Shutdown drivers
        if hasattr(self._driver_manager, "shutdown_all"):
            await self._driver_manager.shutdown_all()

        # Stop monitor
        if hasattr(self._monitor, "stop_heartbeat"):
            await self._monitor.stop_heartbeat()

        # Emit shutdown event
        shutdown_event = SystemShutdownEvent(
            source="harness.supervisor",
            payload={
                "reason": "graceful_shutdown",
                "pending_tasks": len(self._active_tasks),
            },
        )
        if hasattr(self._event_bus, "emit"):
            await self._event_bus.emit(shutdown_event)

        # Stop event bus
        if hasattr(self._event_bus, "stop"):
            await self._event_bus.stop()

        logger.info("harness_shutdown_complete")

    async def handle_user_message(
        self, message: str, user_id: str = "default"
    ) -> str:
        """Process a user message through the full cognitive pipeline.

        Pipeline stages:
        1. Record episode (Memory) — store the user message.
        2. Build context (Memory + Identity) — gather relevant history.
        3. Think (LLM) — understand the message.
        4. Plan (LLM + Skills) — determine what to do.
        5. Execute (Driver) — if plan requires execution.
        6. Reflect (LLM) — learn from the interaction.
        7. Update memory — persist insights.
        8. Return response.

        Args:
            message: The user's message text.
            user_id: The user identifier.

        Returns:
            The system's response string.
        """
        start_time = time.monotonic()
        logger.info(
            "handle_user_message",
            user_id=user_id,
            message_length=len(message),
        )

        try:
            # Stage 1: Record episode
            if hasattr(self._memory, "record_episode"):
                await self._memory.record_episode({
                    "type": "user_message",
                    "user_id": user_id,
                    "content": message,
                })

            # Stage 2: Build context
            context: dict[str, Any] = {"user_id": user_id, "message": message}
            if hasattr(self._memory, "get_context"):
                memory_context = await self._memory.get_context(
                    query=message, user_id=user_id
                )
                context.update(memory_context or {})

            # Stage 3: Think
            thought: str = ""
            if hasattr(self._llm_engine, "think"):
                thought = await self._llm_engine.think(
                    message=message, context=context
                )

            # Stage 4: Plan
            plan: dict[str, Any] | None = None
            if hasattr(self._llm_engine, "plan"):
                available_skills = await self._skill_store.list_all()
                plan = await self._llm_engine.plan(
                    thought=thought,
                    context=context,
                    available_skills=[
                        {"name": s.name, "capability": s.capability}
                        for s in available_skills
                    ],
                )

            # Stage 5: Execute (if plan requires it)
            if plan and plan.get("steps"):
                await self._execute_plan(plan, context)

            # Stage 6: Reflect
            reflection: str = ""
            if hasattr(self._llm_engine, "reflect"):
                reflection = await self._llm_engine.reflect(
                    message=message,
                    thought=thought,
                    plan=plan,
                    context=context,
                )

            # Stage 7: Update memory
            if hasattr(self._memory, "update_episode"):
                await self._memory.update_episode({
                    "type": "interaction_complete",
                    "user_id": user_id,
                    "thought": thought,
                    "plan": plan,
                    "reflection": reflection,
                })

            # Record metrics
            duration_ms = (time.monotonic() - start_time) * 1000
            if hasattr(self._monitor, "record_metric"):
                await self._monitor.record_metric(
                    "cognitive_pipeline.duration_ms",
                    duration_ms,
                    tags={"user_id": user_id},
                )

            # Stage 8: Return response
            response = thought or "I processed your message."
            logger.info(
                "handle_user_message_complete",
                user_id=user_id,
                duration_ms=duration_ms,
            )
            return response

        except Exception as exc:
            logger.error(
                "cognitive_pipeline_error",
                user_id=user_id,
                error=str(exc),
                exc_info=True,
            )
            return f"I encountered an error processing your message: {exc}"

    async def run_cognitive_loop(self) -> None:
        """Main event-driven cognitive loop.

        Continuously processes events from the event bus through the
        cognitive pipeline. Runs until shutdown is requested.
        """
        logger.info("cognitive_loop_starting")

        while self._is_running:
            try:
                # Process events from the bus
                if hasattr(self._event_bus, "get_event"):
                    event = await self._event_bus.get_event(timeout=0.1)
                    if event is not None:
                        if hasattr(self._router, "route"):
                            await self._router.route(event)

                # Record heartbeat metric
                if hasattr(self._monitor, "record_metric"):
                    await self._monitor.record_metric(
                        "cognitive_loop.iteration", 1.0
                    )

            except Exception:
                logger.error(
                    "cognitive_loop_iteration_error",
                    exc_info=True,
                )

        logger.info("cognitive_loop_stopped")

    async def _execute_plan(
        self, plan: dict[str, Any], context: dict[str, Any]
    ) -> None:
        """Execute a plan's steps using the appropriate drivers.

        Args:
            plan: The execution plan with steps.
            context: The execution context.
        """
        steps = plan.get("steps", [])
        for step in steps:
            skill_name = step.get("skill", "")
            action = step.get("action", "")
            parameters = step.get("parameters", {})

            # Find matching skill
            skill = await self._skill_store.get_by_name(skill_name)
            if skill is None:
                logger.warning(
                    "skill_not_found_for_step",
                    skill_name=skill_name,
                )
                continue

            # Execute via driver
            try:
                result = await self._driver_manager.execute(
                    driver_name=skill.driver_type,
                    action=action,
                    parameters=parameters,
                )
                logger.info(
                    "step_executed",
                    skill_name=skill_name,
                    action=action,
                    success=result.success,
                )
            except Exception as exc:
                logger.error(
                    "step_execution_failed",
                    skill_name=skill_name,
                    action=action,
                    error=str(exc),
                )

    @property
    def status(self) -> dict[str, Any]:
        """Get the current status of the harness supervisor.

        Returns:
            A dictionary with runtime status information.
        """
        return {
            "is_running": self._is_running,
            "active_tasks": len(self._active_tasks),
            "uptime_seconds": (
                time.monotonic() - self._boot_time if self._boot_time > 0 else 0.0
            ),
        }
```

## 文件路径: src/myharness/runtime/__init__.py

```python
"""Runtime Layer — event loop, state management, and interrupt handling.

The Runtime Layer manages the execution lifecycle: processing events
through the cognitive loop, maintaining observable runtime state, and
handling interruptions to the execution flow.
"""

from myharness.runtime.loop import EventLoop
from myharness.runtime.state import RuntimeState
from myharness.runtime.interrupt import InterruptHandler

__all__ = [
    "EventLoop",
    "RuntimeState",
    "InterruptHandler",
]
```

## 文件路径: src/myharness/runtime/examples/__init__.py

```python
"""Runtime examples — demonstrations of key architectural patterns.

These examples show the Walk → Obstacle → Interrupt → Replan → Resume
pattern and other runtime behaviors.
"""

from myharness.runtime.examples.walk_obstacle import demo_walk_obstacle

__all__ = [
    "demo_walk_obstacle",
]
```

## 文件路径: src/myharness/runtime/examples/walk_obstacle.py

```python
"""Demonstrates: Walk → Obstacle → Interrupt → LLM Replan → Skill Reparameterize → Continue.

This example shows how the runtime handles unexpected obstacles during
plan execution. When a "walk" skill encounters an obstacle, the interrupt
handler pauses execution, engages the LLM to create a new plan, and
resumes from the appropriate step.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def demo_walk_obstacle(supervisor: Any) -> None:
    """Run the walk-obstacle demo showing interrupt-based replanning.

    This demo simulates:
    1. A robot with a "walk" skill that encounters an obstacle.
    2. The interrupt handler pausing execution.
    3. The LLM replanning around the obstacle.
    4. A new "navigate_around" skill being parameterized.
    5. Execution resuming with the updated plan.

    Args:
        supervisor: The HarnessSupervisor instance.
    """
    logger.info("walk_obstacle_demo_starting")

    # Simulated plan: walk to a destination
    plan = {
        "plan_id": "walk-demo-001",
        "steps": [
            {
                "skill": "walk",
                "action": "move_forward",
                "parameters": {"distance_m": 10, "speed": "normal"},
            },
            {
                "skill": "walk",
                "action": "turn",
                "parameters": {"angle_deg": 90},
            },
            {
                "skill": "walk",
                "action": "move_forward",
                "parameters": {"distance_m": 5, "speed": "normal"},
            },
        ],
    }

    # Simulate an obstacle event
    obstacle_event = {
        "type": "obstacle_detected",
        "location": {"x": 5.0, "y": 0.0},
        "obstacle_type": "wall",
        "sensor": "front_lidar",
        "distance_cm": 30,
    }

    context = {
        "robot_id": "robot-001",
        "current_position": {"x": 0, "y": 0},
        "destination": {"x": 10, "y": 5},
    }

    logger.info(
        "obstacle_detected",
        obstacle=obstacle_event,
        current_plan=plan,
    )

    # Step 1: Pause current execution
    logger.info("pausing_execution")
    await asyncio.sleep(0.1)

    # Step 2: Think — what do we do about this obstacle?
    logger.info("thinking_about_obstacle")
    await asyncio.sleep(0.1)

    # Step 3: Replan — create a new plan that navigates around
    updated_plan = {
        "plan_id": "walk-demo-001-replanned",
        "steps": [
            {
                "skill": "walk",
                "action": "stop",
                "parameters": {},
            },
            {
                "skill": "navigate_around",
                "action": "find_alternate_path",
                "parameters": {
                    "obstacle_location": obstacle_event["location"],
                    "destination": context["destination"],
                },
            },
            {
                "skill": "walk",
                "action": "follow_path",
                "parameters": {
                    "path": [
                        {"x": 0, "y": -2},
                        {"x": 12, "y": -2},
                        {"x": 12, "y": 5},
                        {"x": 10, "y": 5},
                    ]
                },
            },
        ],
    }

    logger.info(
        "plan_updated",
        original_steps=len(plan["steps"]),
        updated_steps=len(updated_plan["steps"]),
    )

    # Step 4: Execute updated plan
    logger.info("resuming_execution_with_new_plan")
    for i, step in enumerate(updated_plan["steps"]):
        logger.info(
            "executing_step",
            step_index=i,
            skill=step["skill"],
            action=step["action"],
        )
        await asyncio.sleep(0.05)

    # Step 5: Report completion
    logger.info(
        "walk_obstacle_demo_complete",
        total_duration_ms=500,
        obstacle_handled=True,
    )
```

## 文件路径: src/myharness/runtime/interrupt.py

```python
"""Interrupt handler for execution flow interruptions.

Implements the Walk → Obstacle → Interrupt → Replan → Resume pattern.
When an unexpected event occurs during plan execution, the interrupt
handler pauses execution, engages the LLM to replan, reparameterizes
skills, and resumes the execution flow.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class Plan:
    """A simple plan representation for the interrupt handler.

    Represents a plan with steps that can be executed, interrupted,
    and resumed.
    """

    def __init__(
        self,
        plan_id: str = "",
        steps: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a plan.

        Args:
            plan_id: Unique plan identifier.
            steps: List of plan steps.
            context: Execution context.
        """
        self.plan_id = plan_id
        self.steps = steps or []
        self.context = context or {}
        self.current_step: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert plan to dictionary."""
        return {
            "plan_id": self.plan_id,
            "steps": self.steps,
            "context": self.context,
            "current_step": self.current_step,
        }


class InterruptHandler:
    """Handles interruptions to execution flow.

    When a Walk → Obstacle pattern is detected, the interrupt handler:
    1. Pauses the current execution.
    2. Engages the LLM to think about the interruption.
    3. Replans the remaining steps.
    4. Reparameterizes skills if needed.
    5. Resumes execution from the appropriate step.
    """

    def __init__(self, llm_engine: Any, skill_registry: Any) -> None:
        """Initialize the interrupt handler.

        Args:
            llm_engine: The LLM engine for replanning.
            skill_registry: The skill registry for reparameterization.
        """
        self._llm_engine = llm_engine
        self._skill_registry = skill_registry
        logger.info("interrupt_handler_initialized")

    async def handle_interrupt(
        self,
        current_plan: Plan | None,
        interrupt_event: dict[str, Any],
        context: dict[str, Any],
    ) -> Plan:
        """Handle an execution interruption.

        Pause, think, replan, reparameterize, return new plan.

        Args:
            current_plan: The plan being executed when interrupted.
            interrupt_event: The event that caused the interruption.
            context: The current execution context.

        Returns:
            A new or modified plan to resume execution.
        """
        logger.info(
            "handling_interrupt",
            interrupt_type=interrupt_event.get("type", "unknown"),
            plan_id=current_plan.plan_id if current_plan else "none",
        )

        # Step 1: Pause — capture current state
        paused_step = current_plan.current_step if current_plan else 0
        remaining_steps = (
            current_plan.steps[paused_step:] if current_plan else []
        )

        # Step 2: Think — ask LLM to analyze the interruption
        thought = ""
        if hasattr(self._llm_engine, "think"):
            thought = await self._llm_engine.think(
                message=f"Interruption occurred: {interrupt_event}",
                context={
                    **context,
                    "interrupt_event": interrupt_event,
                    "remaining_steps": remaining_steps,
                },
            )

        # Step 3: Replan — ask LLM to create a new plan
        new_plan = await self.replan(
            original_plan=current_plan,
            new_constraint={
                "interrupt_event": interrupt_event,
                "thought": thought,
                "remaining_steps": remaining_steps,
            },
        )

        logger.info(
            "interrupt_handled",
            plan_id=new_plan.plan_id,
            new_step_count=len(new_plan.steps),
        )

        return new_plan

    async def replan(
        self,
        original_plan: Plan | None,
        new_constraint: dict[str, Any],
    ) -> Plan:
        """Create a new plan incorporating the interruption constraint.

        Args:
            original_plan: The original plan that was interrupted.
            new_constraint: The constraint that caused the replanning.

        Returns:
            A new plan that addresses the constraint.
        """
        logger.info("replanning", constraint_type=type(new_constraint).__name__)

        # If we have an LLM engine, use it to replan
        if hasattr(self._llm_engine, "plan"):
            new_plan_dict = await self._llm_engine.plan(
                thought=new_constraint.get("thought", ""),
                context={
                    "original_plan": (
                        original_plan.to_dict() if original_plan else None
                    ),
                    "constraint": new_constraint,
                },
                available_skills=[],
            )
            if new_plan_dict:
                return Plan(
                    plan_id=new_plan_dict.get("plan_id", ""),
                    steps=new_plan_dict.get("steps", []),
                    context=new_plan_dict.get("context", {}),
                )

        # Fallback: keep remaining steps
        remaining = new_constraint.get("remaining_steps", [])
        return Plan(
            plan_id=original_plan.plan_id if original_plan else "replanned",
            steps=remaining,
            context=new_constraint,
        )

    async def resume_plan(self, plan: Plan, from_step: int = 0) -> None:
        """Resume execution of a plan from a specific step.

        Args:
            plan: The plan to resume.
            from_step: The step index to resume from (0-based).
        """
        plan.current_step = from_step
        logger.info(
            "resuming_plan",
            plan_id=plan.plan_id,
            from_step=from_step,
            total_steps=len(plan.steps),
        )
```

## 文件路径: src/myharness/runtime/loop.py

```python
"""Core cognitive event loop.

Implements P4 (Event-Driven Architecture): a single event loop that
processes events sequentially without mode switching. Each event is
routed through the cognitive pipeline: Think → Plan → Execute → Reflect.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class EventLoop:
    """Core cognitive event loop.

    Event-driven, no mode switching (P4). Processes events from the
    event bus through the cognitive pipeline. Maintains runtime state
    and handles interruptions.

    The loop runs until explicitly stopped. Each iteration processes
    one event from the queue and updates the runtime state.
    """

    def __init__(
        self,
        event_bus: Any,
        router: Any,
        state: Any,
        interrupt_handler: Any,
    ) -> None:
        """Initialize the event loop.

        Args:
            event_bus: The system event bus for receiving events.
            router: The cognitive pipeline router.
            state: The runtime state tracker.
            interrupt_handler: Handler for execution interruptions.
        """
        self._event_bus = event_bus
        self._router = router
        self._state = state
        self._interrupt_handler = interrupt_handler

        self._is_running = False
        self._loop_task: asyncio.Task | None = None
        self._event_count: int = 0
        self._start_time: float = 0.0

        logger.info("event_loop_initialized")

    async def start(self) -> None:
        """Start the event loop.

        Begins processing events from the event bus. The loop runs
        in a background task and processes events until stopped.
        """
        if self._is_running:
            logger.warning("event_loop_already_running")
            return

        self._is_running = True
        self._start_time = time.monotonic()
        self._loop_task = asyncio.create_task(self._run_loop())

        if hasattr(self._state, "is_running"):
            self._state.is_running = True
        if hasattr(self._state, "uptime_seconds"):
            self._state.uptime_seconds = 0.0

        logger.info("event_loop_started")

    async def stop(self) -> None:
        """Stop the event loop.

        Gracefully stops processing events. The loop task is cancelled
        and awaited to ensure clean shutdown.
        """
        if not self._is_running:
            return

        self._is_running = False

        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        if hasattr(self._state, "is_running"):
            self._state.is_running = False

        logger.info(
            "event_loop_stopped",
            total_events=self._event_count,
            uptime_seconds=time.monotonic() - self._start_time,
        )

    async def step(self) -> None:
        """Process one event from the queue.

        A single iteration of the cognitive loop:
        1. Get next event from the event bus.
        2. Route it through the cognitive pipeline.
        3. Update runtime state.

        This is exposed as a public method to allow manual stepping
        for debugging or testing.
        """
        if not self._is_running:
            return

        try:
            # Get next event
            event = None
            if hasattr(self._event_bus, "get_event"):
                event = await self._event_bus.get_event(timeout=0.01)

            if event is None:
                return

            # Route the event
            if hasattr(self._router, "route"):
                await self._router.route(event)

            self._event_count += 1

            # Update state
            if hasattr(self._state, "pending_events"):
                if hasattr(self._event_bus, "queue_size"):
                    self._state.pending_events = (
                        await self._event_bus.queue_size()
                    )
                else:
                    self._state.pending_events = max(
                        0, self._state.pending_events - 1
                    )

            if hasattr(self._state, "uptime_seconds"):
                self._state.uptime_seconds = (
                    time.monotonic() - self._start_time
                )

            if hasattr(self._state, "metrics"):
                self._state.metrics["total_events"] = self._event_count
                self._state.metrics["events_per_second"] = (
                    self._event_count
                    / max(self._state.uptime_seconds, 0.001)
                )

        except Exception:
            logger.error(
                "event_loop_step_error",
                event_count=self._event_count,
                exc_info=True,
            )

    async def _run_loop(self) -> None:
        """Internal loop that continuously processes events."""
        logger.info("event_loop_running")

        while self._is_running:
            await self.step()
            # Small yield to prevent CPU spinning
            await asyncio.sleep(0)

        logger.info("event_loop_exited")
```

## 文件路径: src/myharness/runtime/state.py

```python
"""Runtime state model — observable and introspectable.

The RuntimeState tracks the current execution state of the cognitive
system. It is observable by monitoring tools and introspection APIs
for debugging and observability.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RuntimeState(BaseModel):
    """Current runtime state — observable, introspectable.

    Tracks the live state of the cognitive system including the
    current plan, active skills, pending events, cognitive load,
    and runtime metrics.

    This model is designed to be serializable for monitoring and
    debugging purposes. All fields are optional with sensible defaults
    so the state can be partially populated during startup.
    """

    current_plan: dict | None = Field(
        default=None,
        description="The currently executing plan, if any",
    )
    active_skills: dict[str, Any] = Field(
        default_factory=dict,
        description="Currently loaded/active skill instances",
    )
    pending_events: int = Field(
        default=0,
        ge=0,
        description="Number of unprocessed events in the queue",
    )
    cognitive_load: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Estimated cognitive load (0.0 to 1.0)",
    )
    last_think_timestamp: float = Field(
        default=0.0,
        description="Unix timestamp of the last Think() operation",
    )
    uptime_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="System uptime in seconds",
    )
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Aggregated runtime metrics",
    )
    is_running: bool = Field(
        default=False,
        description="Whether the runtime is actively processing",
    )

    model_config = {
        "json_schema_extra": {
            "observable": True,
            "introspectable": True,
        }
    }
```
