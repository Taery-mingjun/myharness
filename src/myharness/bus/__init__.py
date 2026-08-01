"""Event Bus module — asynchronous pub/sub event routing.

The bus module provides the foundational communication layer for MyHarness.
All system components communicate exclusively through typed events published
to the EventBus, enabling loose coupling and event-driven architecture (P4).

Public API:
    EventBus       — In-process async event bus with topic-based pub/sub
    Router         — Rule-based event router with priority ordering
    RouteRule      — Individual routing rule definition
    EventResult    — Structured event processing result envelope

    LoggingMiddleware  — Logs every event passing through the bus
    TracingMiddleware  — Injects trace/correlation IDs
    TimingMiddleware   — Measures event processing duration
"""

from myharness.bus.dispatcher import EventBus
from myharness.bus.middleware import (
    LoggingMiddleware,
    TimingMiddleware,
    TracingMiddleware,
)
from myharness.bus.result import EventResult
from myharness.bus.router import RouteRule, Router

__all__ = [
    "EventBus",
    "Router",
    "RouteRule",
    "EventResult",
    "LoggingMiddleware",
    "TracingMiddleware",
    "TimingMiddleware",
]
