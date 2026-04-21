"""Tests for StrategyPatcher (Sprint 4 — incremental patch + probation)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from research_harness.evolution.patcher import (
    PROBATION_INJECTION_THRESHOLD,
    PROBATION_POSITIVE_THRESHOLD,
    StrategyPatcher,
)
from research_harness.evolution.store import DBLessonStore, Lesson


def _insert_strategy(db, *, stage="build", key="build.test", title="Test",
                     content="Original content", version=1,
                     quality_score=0.85, status="active",
                     created_at=None):
    """Insert a test strategy and return its ID."""
    conn = db.connect()
    try:
        ts = created_at or (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        conn.execute(
            """INSERT INTO strategies
               (stage, strategy_key, title, content, scope, version,
                quality_score, gate_model, source_lesson_ids, status, created_at)
               VALUES (?, ?, ?, ?, 'global', ?, ?, 'test', '[]', ?, ?)""",
            (stage, key, title, content, version, quality_score, status, ts),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    finally:
        conn.close()


def _seed_new_lessons(db, stage="build", count=5):
    """Seed lessons created AFTER strategy (recent timestamps)."""
    store = DBLessonStore(db)
    for i in range(count):
        store.append(
            Lesson(stage=stage, content=f"New lesson {i}", lesson_type="success"),
        )


class TestStaleCheck:
    def test_not_stale_when_no_new_lessons(self, db):
        sid = _insert_strategy(db)
        patcher = StrategyPatcher(db)
        result = patcher.check_stale(sid)
        assert result.is_stale is False
        assert result.new_lesson_count == 0

    def test_stale_with_enough_new_lessons(self, db):
        sid = _insert_strategy(
            db,
            created_at=(datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        )
        _seed_new_lessons(db, count=5)

        patcher = StrategyPatcher(db)
        result = patcher.check_stale(sid)
        assert result.is_stale is True
        assert result.new_lesson_count >= 3

    def test_not_stale_with_few_new_lessons(self, db):
        sid = _insert_strategy(
            db,
            created_at=(datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        )
        _seed_new_lessons(db, count=2)

        patcher = StrategyPatcher(db)
        result = patcher.check_stale(sid)
        assert result.is_stale is False

    def test_stale_nonexistent_strategy(self, db):
        patcher = StrategyPatcher(db)
        result = patcher.check_stale(9999)
        assert result.reason == "not found"


class TestPatchStrategy:
    def test_patch_accepted(self, db):
        sid = _insert_strategy(
            db,
            created_at=(datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        )
        _seed_new_lessons(db, count=5)

        mock_patch = '{"patched_content": "Updated strategy with new insights"}'
        mock_gate = '{"scores": {"evidence_grounded": 0.9, "preserves_existing": 0.9, "specific_reusable": 0.85, "safe_to_publish": 0.9}, "overall": 0.89, "decision": "accept"}'

        call_count = [0]
        responses = [mock_patch, mock_gate]

        def mock_chat(prompt, **kwargs):
            idx = min(call_count[0], len(responses) - 1)
            call_count[0] += 1
            return responses[idx]

        mock_client = MagicMock()
        mock_client.chat = mock_chat
        mock_client.model = "test"

        with patch("research_harness.evolution.patcher._get_llm_client", return_value=mock_client):
            patcher = StrategyPatcher(db)
            result = patcher.patch_strategy(sid)

        assert result is not None
        assert result.version == 2
        assert result.status == "active"
        assert "Updated strategy" in result.content

        # Old version should be superseded
        conn = db.connect()
        try:
            old = conn.execute("SELECT status FROM strategies WHERE id = ?", (sid,)).fetchone()
            assert old["status"] == "superseded"
        finally:
            conn.close()

    def test_patch_rejected(self, db):
        sid = _insert_strategy(
            db,
            created_at=(datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
        )
        _seed_new_lessons(db, count=5)

        mock_patch = '{"patched_content": "Bad update"}'
        mock_gate = '{"scores": {"evidence_grounded": 0.3, "preserves_existing": 0.4, "specific_reusable": 0.2, "safe_to_publish": 0.3}, "overall": 0.3, "decision": "reject"}'

        call_count = [0]
        responses = [mock_patch, mock_gate]

        def mock_chat(prompt, **kwargs):
            idx = min(call_count[0], len(responses) - 1)
            call_count[0] += 1
            return responses[idx]

        mock_client = MagicMock()
        mock_client.chat = mock_chat
        mock_client.model = "test"

        with patch("research_harness.evolution.patcher._get_llm_client", return_value=mock_client):
            patcher = StrategyPatcher(db)
            result = patcher.patch_strategy(sid)

        assert result is None

        # Old version should remain active
        conn = db.connect()
        try:
            old = conn.execute("SELECT status FROM strategies WHERE id = ?", (sid,)).fetchone()
            assert old["status"] == "active"
        finally:
            conn.close()

    def test_patch_nonexistent(self, db):
        patcher = StrategyPatcher(db)
        result = patcher.patch_strategy(9999)
        assert result is None


class TestProbation:
    def test_draft_not_promoted_below_threshold(self, db):
        sid = _insert_strategy(db, status="draft")

        # Set injection_count below threshold
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE strategies SET injection_count = ?, positive_feedback = ? WHERE id = ?",
                (PROBATION_INJECTION_THRESHOLD - 1, 0, sid),
            )
            conn.commit()
        finally:
            conn.close()

        patcher = StrategyPatcher(db)
        promoted = patcher.check_promotions()
        assert sid not in promoted

    def test_draft_promoted_at_threshold(self, db):
        sid = _insert_strategy(db, status="draft")

        conn = db.connect()
        try:
            conn.execute(
                "UPDATE strategies SET injection_count = ?, positive_feedback = ? WHERE id = ?",
                (PROBATION_INJECTION_THRESHOLD, PROBATION_POSITIVE_THRESHOLD, sid),
            )
            conn.commit()
        finally:
            conn.close()

        patcher = StrategyPatcher(db)
        promoted = patcher.check_promotions()
        assert sid in promoted

        # Verify status changed
        conn = db.connect()
        try:
            row = conn.execute("SELECT status FROM strategies WHERE id = ?", (sid,)).fetchone()
            assert row["status"] == "active"
        finally:
            conn.close()

    def test_active_not_affected_by_promotion_check(self, db):
        sid = _insert_strategy(db, status="active")

        patcher = StrategyPatcher(db)
        promoted = patcher.check_promotions()
        assert sid not in promoted

    def test_get_draft_strategies(self, db):
        _insert_strategy(db, key="build.draft1", status="draft")
        _insert_strategy(db, key="build.active1", status="active")

        conn = db.connect()
        try:
            conn.execute(
                "UPDATE strategies SET injection_count = 2, positive_feedback = 0 WHERE strategy_key = 'build.draft1'"
            )
            conn.commit()
        finally:
            conn.close()

        patcher = StrategyPatcher(db)
        drafts = patcher.get_draft_strategies()
        assert len(drafts) == 1
        assert drafts[0]["strategy_key"] == "build.draft1"
        assert drafts[0]["injections_needed"] == PROBATION_INJECTION_THRESHOLD - 2
