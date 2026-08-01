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
