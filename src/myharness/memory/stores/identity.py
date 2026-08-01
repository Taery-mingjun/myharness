"""IdentityStore — manages the agent's persistent self-model.

Per P3 (Identity Externalization): Identity belongs to Memory, not LLM.
The LLM reads identity and proposes updates, but this store owns the data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import structlog

from myharness.core.exceptions import IdentityConflictError, MemoryNotFoundError
from myharness.schema.identity import IdentityField, IdentityUpdateProposal
from myharness.schema.memory import IdentityEntry

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth

logger = structlog.get_logger(__name__)

IDENTITY_KEY = "current_identity"


class IdentityStore:
    """Manages the agent's identity — the persistent self-model.

    Stores identity as versioned JSON files in the SourceOfTruth.
    Each update creates a new version file while updating the canonical
    "current_identity.json" entry.
    """

    def __init__(self, source: SourceOfTruth) -> None:
        self._source = source

    async def get_identity(self) -> IdentityEntry:
        """Return the current identity or create a default one.

        On first access with no stored identity, a default IdentityEntry
        is created, persisted, and returned.
        """
        data = await self._source.read("identity", IDENTITY_KEY)
        if data is None:
            entry = IdentityEntry()
            await self._source.write(
                "identity", IDENTITY_KEY, entry.model_dump(mode="json")
            )
            logger.info("IdentityStore: created default identity")
            return entry
        return IdentityEntry(**data)

    async def update_identity(self, entry: IdentityEntry) -> None:
        """Update the identity atomically.

        Saves the current version as history (identity_v{version}.json),
        then writes the new version as current_identity.json.

        Raises:
            IdentityConflictError: If a version conflict is detected.
        """
        current = await self.get_identity()

        if entry.version != current.version:
            raise IdentityConflictError(
                f"Version conflict: expected {current.version}, got {entry.version}",
                details={
                    "expected_version": current.version,
                    "provided_version": entry.version,
                },
            )

        # Save current as history before overwriting
        history_key = f"identity_v{current.version}"
        await self._source.write(
            "identity",
            history_key,
            current.model_dump(mode="json"),
        )

        # Bump version and write new identity
        entry.version = current.version + 1
        entry.updated_at = datetime.now(timezone.utc)
        await self._source.write(
            "identity", IDENTITY_KEY, entry.model_dump(mode="json")
        )

        logger.info(
            "IdentityStore: updated identity",
            old_version=current.version,
            new_version=entry.version,
        )

    async def apply_proposal(
        self, proposal: IdentityUpdateProposal
    ) -> IdentityEntry:
        """Validate and apply an identity update proposal from the LLM.

        The LLM proposes; the Memory System decides. Validates the proposal
        against the current identity state before applying.

        Args:
            proposal: The LLM's suggested identity change.

        Returns:
            The updated IdentityEntry after applying the proposal.

        Raises:
            IdentityConflictError: If validation fails or field is not recognized.
        """
        current = await self.get_identity()

        # Validate the proposal
        self._validate_proposal(proposal, current)

        # Apply the update
        field = proposal.field
        if field == IdentityField.CORE_VALUES:
            current.core_values = proposal.proposed_value
        elif field == IdentityField.MISSION:
            current.mission = proposal.proposed_value
        elif field == IdentityField.PREFERENCES:
            current.preferences = proposal.proposed_value
        elif field == IdentityField.SELF_DESCRIPTION:
            current.self_description = proposal.proposed_value
        elif field == IdentityField.BEHAVIORAL_GUIDELINES:
            current.behavioral_guidelines = proposal.proposed_value
        else:
            raise IdentityConflictError(
                f"Unknown identity field: {field}",
                details={"field": str(field)},
            )

        await self.update_identity(current)
        logger.info(
            "IdentityStore: applied proposal",
            field=str(field),
            proposal_id=proposal.proposal_id,
        )
        return current

    def _validate_proposal(
        self,
        proposal: IdentityUpdateProposal,
        current: IdentityEntry,
    ) -> None:
        """Validate a proposal against the current identity state."""
        if proposal.confidence < 0.3:
            raise IdentityConflictError(
                f"Proposal confidence too low: {proposal.confidence}",
                details={"proposal_id": proposal.proposal_id, "confidence": proposal.confidence},
            )

        if not proposal.reasoning:
            raise IdentityConflictError(
                "Proposal missing reasoning",
                details={"proposal_id": proposal.proposal_id},
            )

        field = proposal.field
        if field == IdentityField.CORE_VALUES:
            current_value = current.core_values
        elif field == IdentityField.MISSION:
            current_value = current.mission
        elif field == IdentityField.PREFERENCES:
            current_value = current.preferences
        elif field == IdentityField.SELF_DESCRIPTION:
            current_value = current.self_description
        elif field == IdentityField.BEHAVIORAL_GUIDELINES:
            current_value = current.behavioral_guidelines
        else:
            raise IdentityConflictError(
                f"Unknown identity field: {field}",
                details={"field": str(field)},
            )

        # If current_value was provided in proposal, verify it matches
        if proposal.current_value is not None and proposal.current_value != current_value:
            raise IdentityConflictError(
                f"Stale proposal: current value for {field} has changed",
                details={
                    "field": str(field),
                    "expected": str(proposal.current_value)[:200],
                    "actual": str(current_value)[:200],
                },
            )

    async def get_history(self) -> list[IdentityEntry]:
        """Get all historical versions of the identity, newest first."""
        all_versions = await self._source.get_all_identity_versions()
        entries: list[IdentityEntry] = []
        for data in all_versions:
            try:
                entries.append(IdentityEntry(**data))
            except Exception:
                logger.warning("IdentityStore: failed to parse history entry", data=data)
        return entries
