"""IdentityStore — manages the agent's persistent self-model.

Per P3 (Identity Externalization): Identity belongs to Memory, not LLM.
The LLM reads identity and proposes updates, but this store owns the data.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from myharness.core.exceptions import (
    IdentityConflictError,
    MemoryCorruptionError,
)
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
        # Updates are read-check-write. Without serialisation two callers
        # can both read version N, both pass the conflict check, and both
        # write N+1 — the second silently discards the first, which is
        # exactly what the version check exists to prevent.
        self._update_lock = asyncio.Lock()

    async def get_identity(self) -> IdentityEntry:
        """Return the current identity, recovering or creating as needed.

        On first access with no stored identity, a default IdentityEntry
        is created, persisted, and returned.

        A *damaged* identity file is a different situation entirely and
        is handled separately. The storage layer used to report a corrupt
        file as a missing one, so this method took the "create a default"
        branch: the agent came back with no mission, no values and no
        history, and the only copy of the real one was overwritten in the
        process. Now the damaged file is quarantined and the newest
        readable version from history is restored.

        Raises:
            MemoryCorruptionError: If the identity is damaged and no
                readable version exists to restore. Refusing to start is
                the correct outcome — an agent that silently resumes as
                someone else is worse than one that does not resume.
        """
        try:
            data = await self._source.read("identity", IDENTITY_KEY)
        except MemoryCorruptionError as exc:
            return await self._recover_identity(exc)

        if data is None:
            entry = IdentityEntry()
            await self._persist(entry)
            logger.info("IdentityStore: created default identity")
            return entry

        try:
            return IdentityEntry(**data)
        except Exception as exc:
            # Parseable JSON that is not a valid identity is corruption
            # too — e.g. a partially rewritten file that still happens to
            # close its braces, or a schema change applied by hand.
            return await self._recover_identity(
                MemoryCorruptionError(
                    "Stored identity does not match the IdentityEntry schema",
                    details={"key": IDENTITY_KEY},
                    cause=exc,
                )
            )

    async def _recover_identity(self, failure: MemoryCorruptionError) -> IdentityEntry:
        """Restore the newest readable identity version after corruption.

        The damaged file is moved aside rather than deleted so a human
        can still salvage it. History files are written before every
        update, so in practice the most that is lost is the last change.
        """
        logger.error(
            "IdentityStore: current identity is unreadable, attempting recovery",
            error=str(failure),
        )

        candidates = await self._source.get_all_identity_versions(
            exclude_keys=(IDENTITY_KEY,)
        )
        restored: IdentityEntry | None = None
        for data in candidates:
            try:
                restored = IdentityEntry(**data)
                break
            except Exception:
                continue

        quarantined = await self._source.quarantine("identity", IDENTITY_KEY)

        if restored is None:
            logger.critical(
                "IdentityStore: no readable identity version to restore",
                quarantined=quarantined,
            )
            raise MemoryCorruptionError(
                "The agent's identity is unreadable and no prior version "
                "could be restored. Refusing to start with a blank self-model; "
                f"the damaged file was preserved at {quarantined}.",
                details={"quarantined": quarantined},
                cause=failure,
            ) from failure

        await self._source.write(
            "identity", IDENTITY_KEY, restored.model_dump(mode="json")
        )
        logger.warning(
            "IdentityStore: restored identity from history",
            restored_version=restored.version,
            quarantined=quarantined,
        )
        return restored

    async def update_identity(self, entry: IdentityEntry) -> None:
        """Update the identity, bumping its version.

        ``entry.version`` is the caller's view of the *current* version,
        not the version it wants to write; this method owns the
        increment. Writes ``identity_v{n}.json`` before the current
        pointer so the new state is never single-copy.

        The whole read-check-write runs under a lock, so two concurrent
        updates serialise and the loser gets a conflict rather than
        silently overwriting the winner.

        Raises:
            IdentityConflictError: If a version conflict is detected.
        """
        async with self._update_lock:
            current = await self.get_identity()

            if entry.version != current.version:
                raise IdentityConflictError(
                    f"Version conflict: expected {current.version}, got {entry.version}",
                    details={
                        "expected_version": current.version,
                        "provided_version": entry.version,
                    },
                )

            entry.version = current.version + 1
            entry.updated_at = datetime.now(timezone.utc)
            await self._persist(entry)

            logger.info(
                "IdentityStore: updated identity",
                old_version=current.version,
                new_version=entry.version,
            )

    async def _persist(self, entry: IdentityEntry) -> None:
        """Write a version file first, then the current pointer.

        Order matters. Previously the *previous* version was archived and
        the new one was written only to ``current_identity.json``, so the
        newest state — the one the agent is actually using — existed in
        exactly one place. Corrupt that file and the newest self-model is
        gone even though a full history sits next to it.

        Writing ``identity_v{n}.json`` first means the current pointer is
        rebuildable at every instant, which is what P9 asks for: the
        versioned files are the source, and current is derived. A crash
        between the two writes leaves an orphan version file, which
        recovery picks up on the next read.
        """
        payload = entry.model_dump(mode="json")
        await self._source.write("identity", f"identity_v{entry.version}", payload)
        await self._source.write("identity", IDENTITY_KEY, payload)

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
        """Get all versions of the identity, newest first.

        Reads the versioned files only. ``current_identity.json`` is a
        pointer to the newest of them and would otherwise show up twice.
        """
        all_versions = await self._source.get_all_identity_versions(
            exclude_keys=(IDENTITY_KEY,)
        )
        entries: list[IdentityEntry] = []
        for data in all_versions:
            try:
                entries.append(IdentityEntry(**data))
            except Exception:
                logger.warning("IdentityStore: failed to parse history entry", data=data)
        return entries
