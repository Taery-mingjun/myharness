"""Tests for the EventBus and Router."""

from __future__ import annotations

import asyncio
import pytest

from myharness.schema.event import EventType, BaseEvent


class TestEventBus:
    async def test_publish_to_subscriber(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe(EventType.USER_MESSAGE, handler)
        event = BaseEvent(event_type=EventType.USER_MESSAGE, source="test")
        await event_bus.publish(event)

        assert len(received) == 1
        assert received[0].event_type == EventType.USER_MESSAGE

    async def test_wildcard_handler(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe_all(handler)
        await event_bus.publish(BaseEvent(event_type=EventType.USER_MESSAGE, source="test"))
        await event_bus.publish(BaseEvent(event_type=EventType.HEARTBEAT, source="test"))

        assert len(received) == 2

    async def test_unsubscribe(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe(EventType.USER_MESSAGE, handler)
        event_bus.unsubscribe(EventType.USER_MESSAGE, handler)
        await event_bus.publish(BaseEvent(event_type=EventType.USER_MESSAGE, source="test"))

        assert len(received) == 0

    async def test_multiple_handlers(self, event_bus):
        results = []

        async def handler1(event):
            results.append("h1")

        async def handler2(event):
            results.append("h2")

        event_bus.subscribe(EventType.USER_MESSAGE, handler1)
        event_bus.subscribe(EventType.USER_MESSAGE, handler2)
        await event_bus.publish(BaseEvent(event_type=EventType.USER_MESSAGE, source="test"))

        assert "h1" in results
        assert "h2" in results

    async def test_request_response(self, event_bus):
        async def handler(event):
            return "response"

        event_bus.subscribe(EventType.COGNITIVE_REQUEST, handler)
        result = await event_bus.request(
            BaseEvent(event_type=EventType.COGNITIVE_REQUEST, source="test"),
            timeout=5.0,
        )

        assert result == "response"

    async def test_queue_enqueue(self, event_bus):
        event = BaseEvent(event_type=EventType.USER_MESSAGE, source="test")
        await event_bus.enqueue(event)
        assert event_bus.queue_size == 1

    async def test_middleware(self, event_bus):
        middleware_called = []

        async def test_middleware(bus, event):
            middleware_called.append(True)
            return event

        event_bus.add_middleware(test_middleware)

        async def handler(event):
            pass

        event_bus.subscribe(EventType.USER_MESSAGE, handler)
        await event_bus.publish(BaseEvent(event_type=EventType.USER_MESSAGE, source="test"))

        assert len(middleware_called) == 1


class TestRouter:
    async def test_add_and_match_rule(self, event_bus, router):
        from myharness.bus.router import RouteRule

        rule = RouteRule(
            rule_id="test-rule",
            event_types=[EventType.USER_MESSAGE],
            target="test.target",
        )
        router.add_rule(rule)

        event = BaseEvent(event_type=EventType.USER_MESSAGE, source="test")
        matches = router.match(event)

        assert len(matches) == 1
        assert matches[0].rule_id == "test-rule"

    async def test_no_match(self, event_bus, router):
        from myharness.bus.router import RouteRule

        rule = RouteRule(
            rule_id="test-rule",
            event_types=[EventType.HEARTBEAT],
            target="test.target",
        )
        router.add_rule(rule)

        event = BaseEvent(event_type=EventType.USER_MESSAGE, source="test")
        matches = router.match(event)

        assert len(matches) == 0

    async def test_priority_ordering(self, event_bus, router):
        from myharness.bus.router import RouteRule

        rule1 = RouteRule(rule_id="low", event_types=[EventType.USER_MESSAGE], target="low", priority=0)
        rule2 = RouteRule(rule_id="high", event_types=[EventType.USER_MESSAGE], target="high", priority=10)

        router.add_rule(rule1)
        router.add_rule(rule2)

        event = BaseEvent(event_type=EventType.USER_MESSAGE, source="test")
        matches = router.match(event)

        # Higher priority first
        assert matches[0].rule_id == "high"
        assert matches[1].rule_id == "low"
