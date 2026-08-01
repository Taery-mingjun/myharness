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
