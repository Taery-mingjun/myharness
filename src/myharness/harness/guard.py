"""Authorisation gate between a plan step and a driver call.

The architecture separates the four powers so that the Skill power
*constrains* the Execution power. Without a gate that separation is
nominal: the executor resolves a skill only to read its ``driver_type``
and then forwards an arbitrary action string to that driver.

That gap is directly reachable from untrusted input. Plan steps are
produced by the LLM, and the LLM's context includes retrieved memories
and tool output. A single injected instruction turns an approved
read-only skill into a handle for any action its driver can perform:

    skill  read_weather   -> driver "api", template {"action": "get_weather"}
    step   skill_name="read_weather", action="delete_all_records",
           parameters={"method": "DELETE", "url": "https://internal/admin"}

The ExecutionGuard closes it by checking, before every driver call, that
the skill exists, is not retired, declares the action, and that the actor
holds a grant for it.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import structlog

from myharness.core.exceptions import PermissionDeniedError
from myharness.schema.skill import (
    SkillStatus,
    action_is_permitted,
    resolve_allowed_actions,
)

logger = structlog.get_logger(__name__)

DEFAULT_SYSTEM_ACTOR = "system"

#: Action verb used when authorising a skill invocation against the RBAC layer.
EXECUTE_ACTION = "execute"

#: Denials kept in memory for inspection. Bounded on purpose: a hostile plan
#: can produce denials in a loop, and an unbounded audit list would turn a
#: blocked attack into an out-of-memory kill. The durable record is the log.
DENIAL_HISTORY_LIMIT = 256


class ExecutionGuard:
    """Authorises a (skill, action, actor) triple before it reaches a driver.

    The skill-boundary checks are unconditional. They are the defence
    against a hostile plan, and a defence that can be turned off by not
    wiring a dependency is not a defence — so the supervisor builds a
    default guard when none is injected.

    The actor check is only applied when a permission manager is supplied,
    because actor identity is a deployment concern: a single-agent install
    has exactly one actor and nothing to distinguish.
    """

    def __init__(
        self,
        permission_manager: Any = None,
        system_actor: str = DEFAULT_SYSTEM_ACTOR,
        enforce: bool = True,
        denial_history_limit: int = DENIAL_HISTORY_LIMIT,
    ) -> None:
        """Initialize the execution guard.

        Args:
            permission_manager: Optional RBAC manager exposing an async
                ``check(actor, resource, action)``. When omitted, the
                actor check is skipped and only the skill boundary applies.
            system_actor: Actor attributed to plan steps that carry no
                explicit actor.
            enforce: When False the guard runs every check and logs each
                denial as ``execution_denied_audit_only`` but permits the
                call. Intended for staging a policy against live traffic
                before turning it on — never for production.
            denial_history_limit: How many recent denials to keep in memory.
                Oldest entries are dropped; the log keeps the full record.

        Raises:
            TypeError: If ``permission_manager`` is supplied but has no
                usable ``check`` method.
        """
        if permission_manager is not None and not callable(
            getattr(permission_manager, "check", None)
        ):
            raise TypeError(
                "permission_manager must expose an async check(actor, "
                f"resource, action) method; got {type(permission_manager).__name__}"
            )

        self._permissions = permission_manager
        self._system_actor = system_actor or DEFAULT_SYSTEM_ACTOR
        self._enforce = enforce
        self._denials: deque[dict[str, Any]] = deque(
            maxlen=max(1, int(denial_history_limit))
        )

        if not enforce:
            logger.warning(
                "execution_guard_audit_only",
                detail=(
                    "enforce=False — denials are logged but the call still "
                    "runs. The skill boundary is not being enforced."
                ),
            )

    @property
    def enforcing(self) -> bool:
        """Whether denials actually block execution."""
        return self._enforce

    @property
    def system_actor(self) -> str:
        """The actor attributed to steps with no explicit actor."""
        return self._system_actor

    @property
    def denials(self) -> list[dict[str, Any]]:
        """The most recent denials this guard produced, oldest first.

        Bounded by ``denial_history_limit``. Treat the log as the complete
        record; this is a convenience view for tests and operators.
        """
        return list(self._denials)

    async def authorize(
        self,
        skill: Any,
        action: str,
        skill_name: str = "",
        actor: str | None = None,
    ) -> None:
        """Authorise one driver call, or refuse it.

        Args:
            skill: The resolved skill definition, or None if lookup failed.
            action: The driver action the plan step wants to perform.
            skill_name: Name the step asked for — used in the denial when
                ``skill`` is None and there is nothing else to report.
            actor: The requesting actor; defaults to the system actor.

        Raises:
            PermissionDeniedError: If any check fails and the guard is
                enforcing.
        """
        subject = actor or self._system_actor
        name = str(getattr(skill, "name", "") or skill_name or "<unknown>")

        # 1. The step must name a skill that exists. A plan referring to a
        #    skill that was never registered is broken or hostile; the old
        #    executor logged a warning and moved on to the next step.
        if skill is None:
            await self._deny(
                code="SKILL_NOT_FOUND",
                reason=f"No skill registered under the name '{skill_name}'",
                skill_name=skill_name,
                action=action,
                actor=subject,
            )
            return

        # 2. Retired skills must not execute. An operator who archives a
        #    skill has withdrawn it; the store still serves it by name.
        status = getattr(skill, "status", None)
        if status == SkillStatus.ARCHIVED:
            await self._deny(
                code="SKILL_ARCHIVED",
                reason=f"Skill '{name}' is archived and must not be executed",
                skill_name=name,
                action=action,
                actor=subject,
            )
            return

        if status == SkillStatus.DEPRECATED:
            logger.warning(
                "deprecated_skill_executed",
                skill_name=name,
                action=action,
                actor=subject,
            )

        # 3. The action must be inside the skill's declared boundary.
        if not resolve_allowed_actions(skill):
            await self._deny(
                code="ACTION_NOT_PERMITTED",
                reason=(
                    f"Skill '{name}' declares no executable action; it cannot "
                    "authorise anything"
                ),
                skill_name=name,
                action=action,
                actor=subject,
            )
            return

        permitted = getattr(skill, "permits_action", None)
        allowed = (
            bool(permitted(action))
            if callable(permitted)
            else action_is_permitted(skill, action)
        )
        if not allowed:
            await self._deny(
                code="ACTION_NOT_PERMITTED",
                reason=(
                    f"Action '{action}' is outside the boundary of skill "
                    f"'{name}' (allowed: {sorted(resolve_allowed_actions(skill))})"
                ),
                skill_name=name,
                action=action,
                actor=subject,
            )
            return

        # 4. The actor must hold a grant — only when RBAC is configured.
        if self._permissions is not None:
            granted = await self._permissions.check(
                subject, f"skill:{name}", EXECUTE_ACTION
            )
            if not granted:
                await self._deny(
                    code="ACTOR_NOT_PERMITTED",
                    reason=(
                        f"Actor '{subject}' is not permitted to execute "
                        f"skill '{name}'"
                    ),
                    skill_name=name,
                    action=action,
                    actor=subject,
                )
                return

        logger.debug(
            "execution_authorized",
            skill_name=name,
            action=action,
            actor=subject,
        )

    async def _deny(
        self,
        code: str,
        reason: str,
        skill_name: str,
        action: str,
        actor: str,
    ) -> None:
        """Record a denial, then raise unless the guard is audit-only."""
        record = {
            "code": code,
            "reason": reason,
            "skill_name": skill_name,
            "action": action,
            "actor": actor,
        }
        self._denials.append(record)

        if not self._enforce:
            logger.warning("execution_denied_audit_only", **record)
            return

        logger.error("execution_denied", **record)
        raise PermissionDeniedError(reason, code=code, details=record)
