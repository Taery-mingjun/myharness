"""Access control for skills and driver operations.

Provides an RBAC (Role-Based Access Control) mechanism for controlling
which actors may perform which actions on which resources.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

DefaultPolicy = Literal["allow", "deny"]

WILDCARD = "*"


class PermissionManager:
    """Access control for skills and driver operations.

    Manages permissions using an actor-resource-action model. Each actor
    can be granted or revoked specific actions on specific resources.

    The default policy is ``deny``: an actor with no matching grant is
    refused. A permission system that defaults to ``allow`` only reports
    on traffic it was going to permit anyway, so opting into permissive
    mode has to be an explicit, visible decision.

    Permissions are stored in-memory. A production deployment backs this
    with a persistent store; the interface is async so that swap needs no
    caller changes.
    """

    def __init__(
        self,
        default_policy: DefaultPolicy = "deny",
        superusers: Iterable[str] = (),
    ) -> None:
        """Initialize the permission manager.

        Args:
            default_policy: What to do when no grant matches — ``"deny"``
                (fail closed, the default) or ``"allow"``.
            superusers: Actors seeded with ``*`` on ``*``. Deny-by-default
                would otherwise lock out the single-agent deployment,
                whose one actor has nobody to be distinguished from; the
                container seeds the configured system actor here so the
                policy is fail-closed for everyone else from the start.

        Raises:
            ValueError: If ``default_policy`` is not a known policy.
        """
        if default_policy not in ("allow", "deny"):
            raise ValueError(
                f"default_policy must be 'allow' or 'deny', got {default_policy!r}"
            )

        # Structure: {actor: {resource: {actions}}}
        self._permissions: dict[str, dict[str, set[str]]] = {}
        self._default_policy: DefaultPolicy = default_policy

        for actor in superusers:
            if not actor:
                continue
            self._permissions[actor] = {WILDCARD: {WILDCARD}}
            logger.info("permission_superuser_seeded", actor=actor)

        if default_policy == "allow":
            logger.warning(
                "permission_manager_permissive",
                detail=(
                    "default_policy='allow' — every unmatched request is "
                    "authorised. Grants are advisory only in this mode."
                ),
            )
        logger.info("permission_manager_initialized", default_policy=default_policy)

    @property
    def default_policy(self) -> DefaultPolicy:
        """The policy applied when no grant matches a request."""
        return self._default_policy

    async def check(self, actor: str, resource: str, action: str) -> bool:
        """Check if an actor has permission for an action on a resource.

        Matching considers, in order: the exact resource, then the
        wildcard resource ``"*"``. Within a resource, the exact action and
        the wildcard action ``"*"`` both match.

        Args:
            actor: The actor requesting permission (e.g., "user_123").
            resource: The resource being accessed (e.g., "skill:walk").
            action: The action being performed (e.g., "execute", "read").

        Returns:
            True if the actor has permission, False otherwise.
        """
        actor_perms = self._permissions.get(actor, {})

        for candidate in (resource, WILDCARD):
            actions = actor_perms.get(candidate)
            if actions and (action in actions or WILDCARD in actions):
                return True

        if self._default_policy == "allow":
            logger.debug(
                "permission_allowed_by_default",
                actor=actor,
                resource=resource,
                action=action,
            )
            return True

        logger.info(
            "permission_denied",
            actor=actor,
            resource=resource,
            action=action,
        )
        return False

    async def grant(self, actor: str, resource: str, action: str) -> None:
        """Grant a permission to an actor.

        Args:
            actor: The actor to grant permission to.
            resource: The resource to grant access to.
            action: The action to allow.
        """
        actions = self._permissions.setdefault(actor, {}).setdefault(resource, set())
        if action not in actions:
            actions.add(action)
            logger.info(
                "permission_granted",
                actor=actor,
                resource=resource,
                action=action,
            )

    async def revoke(self, actor: str, resource: str, action: str) -> None:
        """Revoke a permission from an actor.

        Revoking a specific action also strips a wildcard grant on that
        resource. Otherwise ``revoke(actor, res, "delete")`` would report
        success while ``check(actor, res, "delete")`` kept returning True
        through the surviving ``"*"`` — a revocation that revokes nothing
        is worse than no revocation at all, because it is believed.

        Args:
            actor: The actor to revoke permission from.
            resource: The resource to revoke access to.
            action: The action to disallow.
        """
        actor_perms = self._permissions.get(actor)
        if actor_perms is None:
            return

        actions = actor_perms.get(resource)
        if actions is None:
            return

        removed = set()
        if action in actions:
            actions.discard(action)
            removed.add(action)

        if action != WILDCARD and WILDCARD in actions:
            actions.discard(WILDCARD)
            removed.add(WILDCARD)
            logger.warning(
                "permission_wildcard_revoked",
                actor=actor,
                resource=resource,
                detail=(
                    f"revoking '{action}' also removed the '*' grant, which "
                    "would otherwise have kept the action allowed"
                ),
            )

        if removed:
            logger.info(
                "permission_revoked",
                actor=actor,
                resource=resource,
                actions=sorted(removed),
            )

        # Clean up empty entries
        if not actions:
            del actor_perms[resource]
        if not actor_perms:
            del self._permissions[actor]

    async def revoke_all(self, actor: str) -> None:
        """Remove every grant held by an actor.

        Args:
            actor: The actor to strip of all permissions.
        """
        if self._permissions.pop(actor, None) is not None:
            logger.info("permission_revoked_all", actor=actor)

    async def get_permissions(self, actor: str) -> dict[str, list[str]]:
        """Get all permissions for an actor.

        Returns a deep copy. The previous shallow ``dict(...)`` handed the
        caller the manager's own mutable action lists, so any consumer —
        an API handler serialising a response, a report — could append
        ``"*"`` to the returned value and silently escalate that actor to
        full access on the live manager.

        Args:
            actor: The actor to query.

        Returns:
            A dictionary mapping resources to sorted lists of allowed actions.
        """
        return {
            resource: sorted(actions)
            for resource, actions in self._permissions.get(actor, {}).items()
        }

    async def list_actors(self) -> list[str]:
        """List every actor holding at least one grant.

        Returns:
            A sorted list of actor identifiers.
        """
        return sorted(self._permissions)
