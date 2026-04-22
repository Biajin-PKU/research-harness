"""Tests for NudgeManager (Sprint 4 — nudge mechanism)."""

from __future__ import annotations


from research_harness.evolution.nudge import NudgeManager


class TestNudgeManager:
    def test_no_nudge_before_interval(self, db):
        mgr = NudgeManager(db, "sess-n1", interval=10)
        for _ in range(9):
            mgr.tick()
        nudge = mgr.check_nudge(stage="build")
        assert nudge is None

    def test_nudge_at_interval(self, db):
        mgr = NudgeManager(db, "sess-n2", interval=5)
        for _ in range(5):
            mgr.tick()
        nudge = mgr.check_nudge(stage="build")
        assert nudge is not None
        assert nudge.nudge_type == "strategy_extraction"

    def test_nudge_resets_after_delivery(self, db):
        mgr = NudgeManager(db, "sess-n3", interval=3)
        for _ in range(3):
            mgr.tick()
        nudge1 = mgr.check_nudge(stage="build")
        assert nudge1 is not None

        # Should not nudge immediately again
        mgr.tick()
        nudge2 = mgr.check_nudge(stage="build")
        assert nudge2 is None

        # After another interval
        for _ in range(2):
            mgr.tick()
        nudge3 = mgr.check_nudge(stage="build")
        assert nudge3 is not None

    def test_reflection_prompt_priority(self, db):
        mgr = NudgeManager(db, "sess-n4", interval=1)
        mgr.tick()
        nudge = mgr.check_nudge(
            stage="experiment",
            experiment_count=3,
            reflection_interval=3,
        )
        assert nudge is not None
        assert nudge.nudge_type == "reflection_prompt"
        assert nudge.priority == "high"

    def test_cost_awareness(self, db):
        mgr = NudgeManager(db, "sess-n5", interval=1)
        mgr.tick()
        nudge = mgr.check_nudge(stage="build", cost_usd=2.50)
        assert nudge is not None
        assert nudge.nudge_type == "cost_awareness"
        assert "$2.50" in nudge.message

    def test_format_nudge(self, db):
        mgr = NudgeManager(db, "sess-n6")
        from research_harness.evolution.models import NudgeDecision

        nudge = NudgeDecision(
            nudge_type="strategy_extraction",
            message="Consider extracting strategies",
            priority="medium",
        )
        formatted = mgr.format_nudge(nudge)
        assert "[NUDGE!]" in formatted
        assert "Consider extracting" in formatted

    def test_format_nudge_high_priority(self, db):
        mgr = NudgeManager(db, "sess-n7")
        from research_harness.evolution.models import NudgeDecision

        nudge = NudgeDecision(
            nudge_type="reflection_prompt",
            message="Time to reflect",
            priority="high",
        )
        formatted = mgr.format_nudge(nudge)
        assert "[NUDGE!!]" in formatted

    def test_nudge_recorded_in_db(self, db):
        mgr = NudgeManager(db, "sess-n8", interval=1)
        mgr.tick()
        mgr.check_nudge(stage="build")

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM nudge_log WHERE session_id = 'sess-n8'"
            ).fetchone()
            assert row is not None
            assert row["nudge_type"] == "strategy_extraction"
        finally:
            conn.close()

    def test_record_acceptance(self, db):
        mgr = NudgeManager(db, "sess-n9", interval=1)
        mgr.tick()
        mgr.check_nudge(stage="build")
        mgr.record_acceptance("strategy_extraction")

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT accepted FROM nudge_log WHERE session_id = 'sess-n9'"
            ).fetchone()
            assert row["accepted"] == 1
        finally:
            conn.close()

    def test_get_nudge_stats(self, db):
        mgr = NudgeManager(db, "sess-n10", interval=1)

        mgr.tick()
        mgr.check_nudge(stage="build")
        mgr.tick()
        mgr.check_nudge(stage="build")
        mgr.record_acceptance("strategy_extraction")

        stats = mgr.get_nudge_stats()
        assert "strategy_extraction" in stats
        assert stats["strategy_extraction"]["delivered"] == 2
        assert stats["strategy_extraction"]["accepted"] == 1

    def test_call_count_property(self, db):
        mgr = NudgeManager(db, "sess-n11")
        assert mgr.call_count == 0
        mgr.tick()
        mgr.tick()
        assert mgr.call_count == 2
