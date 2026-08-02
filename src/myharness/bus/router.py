"""Rule-based event router with priority ordering.

The Router evaluates routing rules against incoming events and dispatches
them to the appropriate targets via the EventBus. Rules are evaluated in
priority order and support pattern matching on event type, source, and
payload conditions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from myharness.core.logging import get_logger
from myharness.schema.event import BaseEvent, EventType

if TYPE_CHECKING:
    from myharness.bus.dispatcher import EventBus


@dataclass
class RouteRule:
    """A single routing rule that matches events and directs them to targets.

    Attributes:
        rule_id: Unique identifier for this rule.
        event_types: Event types this rule applies to.
        source_pattern: Optional regex pattern to match on event.source.
        payload_condition: Optional key-value pairs to match on event.payload.
                           All keys must match (AND logic).
        target: Target component identifier (e.g., "llm.engine.think").
        priority: Higher priority rules are evaluated first. Default 0.
        enabled: Whether this rule is active.
    """

    rule_id: str
    event_types: list[EventType]
    source_pattern: str | None = None
    payload_condition: dict[str, Any] | None = None
    target: str = ""
    priority: int = 0
    enabled: bool = True

    def matches(self, event: BaseEvent) -> bool:
        """Check whether this rule matches a given event.

        Args:
            event: The event to test against this rule.

        Returns:
            True if the event matches all rule conditions.
        """
        if not self.enabled:
            return False

        # Match event type
        if event.event_type not in self.event_types:
            return False

        # Match source pattern (regex)
        if self.source_pattern is not None:
            if not re.search(self.source_pattern, event.source):
                return False

        # Match payload conditions (all keys must match, AND logic)
        if self.payload_condition:
            for key, expected_value in self.payload_condition.items():
                actual_value = event.payload.get(key)
                if actual_value != expected_value:
                    return False

        return True


class Router:
    """Rule-based event router for directing events to system components.

    The Router evaluates all registered rules in priority order (descending).
    When a matching rule is found, the event is published to the EventBus
    with the rule's target set as metadata.

    Usage:
        router = Router(event_bus)
        router.add_rule(RouteRule(
            rule_id="user_to_think",
            event_types=[EventType.USER_MESSAGE],
            target="llm.engine.think",
            priority=10,
        ))
        await router.route(event)
    """

    def __init__(self, event_bus: EventBus) -> None:
        """Initialize the router.

        Args:
            event_bus: The EventBus instance to publish routed events to.
        """
        self._event_bus: EventBus = event_bus
        self._rules: dict[str, RouteRule] = {}
        self._log = get_logger(__name__, component="router")

    def add_rule(self, rule: RouteRule) -> None:
        """Register a routing rule.

        If a rule with the same rule_id already exists, it is replaced.

        Args:
            rule: The routing rule to register.
        """
        self._rules[rule.rule_id] = rule
        self._log.debug(
            "rule_added",
            rule_id=rule.rule_id,
            event_types=[et.value for et in rule.event_types],
            target=rule.target,
            priority=rule.priority,
        )

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a routing rule by ID.

        Args:
            rule_id: The ID of the rule to remove.

        Returns:
            True if the rule was found and removed, False otherwise.
        """
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._log.debug("rule_removed", rule_id=rule_id)
            return True
        return False

    def get_rule(self, rule_id: str) -> RouteRule | None:
        """Retrieve a routing rule by ID.

        Args:
            rule_id: The ID of the rule to retrieve.

        Returns:
            The RouteRule if found, None otherwise.
        """
        return self._rules.get(rule_id)

    def list_rules(self) -> list[RouteRule]:
        """List all registered rules sorted by priority (descending).

        Returns:
            List of RouteRule objects, highest priority first.
        """
        return sorted(self._rules.values(), key=lambda r: r.priority, reverse=True)

    def match(self, event: BaseEvent) -> list[RouteRule]:
        """Find all rules that match a given event.

        Rules are evaluated in priority order (descending). All matching
        rules are returned (not just the first).

        Args:
            event: The event to match against registered rules.

        Returns:
            List of matching RouteRule objects, highest priority first.
        """
        matching = [r for r in self.list_rules() if r.matches(event)]
        if matching:
            self._log.debug(
                "rules_matched",
                event_type=event.event_type.value,
                match_count=len(matching),
                matched_rules=[r.rule_id for r in matching],
            )
        else:
            self._log.debug(
                "no_rules_matched",
                event_type=event.event_type.value,
                event_id=event.event_id,
            )
        return matching

    async def route(self, event: BaseEvent) -> list[Any]:
        """Match the event against rules and publish to the EventBus.

        For each matching rule, the event's metadata is enriched with the
        rule's target and then published.

        Args:
            event: The event to route.

        Returns:
            List of results from the EventBus publish operations.
        """
        matching_rules = self.match(event)

        if not matching_rules:
            self._log.warning(
                "event_unrouted",
                event_type=event.event_type.value,
                event_id=event.event_id,
                source=event.source,
            )
            return []

        results: list[Any] = []
        for rule in matching_rules:
            # Enrich event metadata with routing information
            event.metadata["routed_by"] = rule.rule_id
            event.metadata["target"] = rule.target

            self._log.info(
                "event_routed",
                event_type=event.event_type.value,
                event_id=event.event_id,
                rule_id=rule.rule_id,
                target=rule.target,
            )
            result = await self._event_bus.publish(event)
            results.extend(result)

        return results

    @property
    def rule_count(self) -> int:
        """Number of registered routing rules."""
        return len(self._rules)
