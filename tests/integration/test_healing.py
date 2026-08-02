"""Tests for harness/healing.py — DriftDetector and RollbackManager.

Verifies:
1. DriftDetector correctly tracks consecutive failures and generates
   rollback candidates when the threshold is crossed.
2. RollbackManager does NOT execute any rollback without human confirmation.
3. Metrics persist across process restarts (SQLite-backed).
4. Manual flagging works alongside automatic detection.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from myharness.harness.healing import (
    DriftDetector,
    MetricType,
    RollbackManager,
    RollbackReason,
    RollbackStatus,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Isolated SQLite path for each test."""
    return tmp_path / "drift.db"


@pytest.fixture
async def detector(db_path: Path) -> DriftDetector:
    """A DriftDetector with threshold=3 for faster test cycles."""
    d = DriftDetector(db_path=db_path, failure_threshold=3, window_size=50)
    yield d
    await d.close()


@pytest.fixture
def rollback_manager(detector: DriftDetector) -> RollbackManager:
    """RollbackManager without a real SkillStore (skill_rolled_back=False)."""
    return RollbackManager(drift_detector=detector, skill_store=None)


# ── DriftDetector Tests ────────────────────────────────────────────────


class TestDriftDetector:

    async def test_record_metric_persists(self, detector: DriftDetector):
        """Metrics are written to SQLite and survive reconnection."""
        await detector.record_skill_execution("greet", True)
        await detector.record_skill_execution("greet", False, {"error": "timeout"})

        # Reopen detector to simulate process restart
        db_path = detector._db_path
        await detector.close()
        detector2 = DriftDetector(db_path=db_path, failure_threshold=3)
        rate = await detector2.get_failure_rate("greet")
        await detector2.close()

        assert rate == 0.5, f"Expected 0.5, got {rate}"

    async def test_no_candidate_below_threshold(self, detector: DriftDetector):
        """2 failures with threshold=3 → no rollback candidate."""
        await detector.record_skill_execution("search", False)
        await detector.record_skill_execution("search", False)

        pending = await detector.get_pending_candidates()
        assert len(pending) == 0, f"Expected 0 candidates, got {len(pending)}"

    async def test_candidate_generated_at_threshold(self, detector: DriftDetector):
        """3 consecutive failures with threshold=3 → exactly 1 candidate."""
        await detector.record_skill_execution("weather", False)
        await detector.record_skill_execution("weather", False)
        await detector.record_skill_execution("weather", False)

        pending = await detector.get_pending_candidates()
        assert len(pending) == 1, f"Expected 1 candidate, got {len(pending)}"
        assert pending[0]["skill_name"] == "weather"
        assert pending[0]["reason"] == "consecutive_failures"
        assert pending[0]["status"] == "pending"

    async def test_success_resets_consecutive_count(self, detector: DriftDetector):
        """A success between failures resets the consecutive counter."""
        await detector.record_skill_execution("calc", False)
        await detector.record_skill_execution("calc", False)
        await detector.record_skill_execution("calc", True)  # resets
        await detector.record_skill_execution("calc", False)
        await detector.record_skill_execution("calc", False)

        # Only 2 consecutive after reset, threshold=3 → no candidate
        pending = await detector.get_pending_candidates()
        assert len(pending) == 0

    async def test_multiple_skills_tracked_independently(self, detector: DriftDetector):
        """Failures in skill A don't trigger rollback for skill B."""
        await detector.record_skill_execution("skill_a", False)
        await detector.record_skill_execution("skill_a", False)
        await detector.record_skill_execution("skill_a", False)
        await detector.record_skill_execution("skill_b", False)

        pending = await detector.get_pending_candidates()
        assert len(pending) == 1
        assert pending[0]["skill_name"] == "skill_a"

    async def test_identity_veto_tracking(self, detector: DriftDetector):
        """Identity vetoes are recorded as metrics."""
        await detector.record_identity_veto("honesty_rule", {"context": "test"})
        await detector.record_identity_veto("honesty_rule")

        conn = await detector._get_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM drift_metrics WHERE metric_type = 'identity_veto'"
        )
        row = await cursor.fetchone()
        cursor.close()
        assert row["cnt"] == 2

    async def test_anomaly_tracking(self, detector: DriftDetector):
        """Anomalous responses are recorded."""
        await detector.record_anomaly("llm_engine", {"type": "json_parse_failure"})

        conn = await detector._get_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM drift_metrics WHERE metric_type = 'anomaly_response'"
        )
        row = await cursor.fetchone()
        cursor.close()
        assert row["cnt"] == 1

    async def test_failure_rate_calculation(self, detector: DriftDetector):
        """Failure rate is correctly computed over the window."""
        for _ in range(7):
            await detector.record_skill_execution("test_skill", True)
        for _ in range(3):
            await detector.record_skill_execution("test_skill", False)

        rate = await detector.get_failure_rate("test_skill", window=50)
        assert rate == 0.3, f"Expected 0.3, got {rate}"


# ── RollbackManager Tests ──────────────────────────────────────────────


class TestRollbackManager:

    async def test_no_rollback_without_confirmation(
        self, detector: DriftDetector, rollback_manager: RollbackManager
    ):
        """DriftDetector generates candidate, but RollbackManager does NOT
        auto-execute — candidate stays 'pending' until human confirms.
        """
        # Trigger 3 consecutive failures
        for _ in range(3):
            await detector.record_skill_execution("critical_skill", False)

        # Candidate exists but is pending
        pending = await rollback_manager.list_pending()
        assert len(pending) == 1
        assert pending[0].status == RollbackStatus.PENDING

        # Skill was NOT rolled back (skill_store=None → skill_rolled_back=False)
        # But the candidate is still pending, not confirmed
        assert pending[0].status != RollbackStatus.CONFIRMED

    async def test_confirm_rollback_executes(
        self, detector: DriftDetector, rollback_manager: RollbackManager
    ):
        """Human confirmation changes status to 'confirmed'."""
        for _ in range(3):
            await detector.record_skill_execution("broken_skill", False)

        pending = await rollback_manager.list_pending()
        candidate_id = pending[0].candidate_id

        result = await rollback_manager.confirm_rollback(candidate_id, confirmed_by="admin")

        assert result["status"] == "confirmed"
        assert result["skill_name"] == "broken_skill"
        assert result["confirmed_by"] == "admin"
        assert result["skill_rolled_back"] is False  # no SkillStore connected

        # Verify no more pending candidates
        pending_after = await rollback_manager.list_pending()
        assert len(pending_after) == 0

    async def test_reject_rollback(self, detector: DriftDetector, rollback_manager: RollbackManager):
        """Human rejection changes status to 'rejected'."""
        for _ in range(3):
            await detector.record_skill_execution("rejected_skill", False)

        pending = await rollback_manager.list_pending()
        candidate_id = pending[0].candidate_id

        result = await rollback_manager.reject_rollback(candidate_id, reason="false alarm")

        assert result["status"] == "rejected"
        pending_after = await rollback_manager.list_pending()
        assert len(pending_after) == 0

    async def test_confirm_nonexistent_candidate_fails(
        self, rollback_manager: RollbackManager
    ):
        """Confirming a non-existent candidate returns error."""
        result = await rollback_manager.confirm_rollback("nonexistent-id")
        assert result["status"] == "error"

    async def test_manual_flag(self, detector: DriftDetector, rollback_manager: RollbackManager):
        """Manual flagging creates a candidate without DriftDetector trigger."""
        candidate_id = await rollback_manager.manual_flag(
            "suspicious_skill",
            "Operator noticed unexpected behavior",
            target_version="1.2.0",
        )

        pending = await rollback_manager.list_pending()
        assert len(pending) == 1
        assert pending[0].candidate_id == candidate_id
        assert pending[0].reason == RollbackReason.MANUAL_FLAG
        assert pending[0].target_version == "1.2.0"

    async def test_metrics_survive_restart(
        self, detector: DriftDetector, db_path: Path
    ):
        """Full cycle: record → close → reopen → verify candidates persist."""
        # Record 3 failures
        for _ in range(3):
            await detector.record_skill_execution("persistent_skill", False)

        # Close and reopen
        await detector.close()
        detector2 = DriftDetector(db_path=db_path, failure_threshold=3)
        pending = await detector2.get_pending_candidates()

        assert len(pending) == 1
        assert pending[0]["skill_name"] == "persistent_skill"
        await detector2.close()
