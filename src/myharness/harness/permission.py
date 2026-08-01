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
