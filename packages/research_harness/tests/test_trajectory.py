"""Tests for trajectory recorder (Sprint 1 — self-evolution foundation)."""

from __future__ import annotations


from research_harness.evolution.trajectory import TrajectoryRecorder


class TestTrajectoryRecorder:
    def test_record_tool_call(self, db):
        rec = TrajectoryRecorder(db, "sess-001")
        eid = rec.record_tool_call(
            "paper_search",
            stage="build",
            topic_id=1,
            input_summary="query=transformers",
            output_summary="found 20 papers",
            success=True,
            cost_usd=0.01,
            latency_ms=500,
        )
        assert eid > 0

    def test_get_session_trajectory(self, db):
        rec = TrajectoryRecorder(db, "sess-002")
        rec.record_tool_call("paper_search", stage="build", input_summary="q1")
        rec.record_tool_call("paper_ingest", stage="build", input_summary="q2")
        rec.record_decision("skip_paper", "Low relevance", stage="build")

        events = rec.get_session_trajectory()
        assert len(events) == 3
        assert events[0].tool_name == "paper_search"
        assert events[1].tool_name == "paper_ingest"
        assert events[2].event_type == "decision"

    def test_sequence_ordering(self, db):
        rec = TrajectoryRecorder(db, "sess-003")
        rec.record_tool_call("tool_a", stage="build")
        rec.record_tool_call("tool_b", stage="build")
        rec.record_tool_call("tool_c", stage="build")

        events = rec.get_session_trajectory()
        seqs = [e.sequence_number for e in events]
        assert seqs == sorted(seqs)

    def test_record_error_recovery(self, db):
        rec = TrajectoryRecorder(db, "sess-004")
        eid = rec.record_error_recovery(
            "S2 rate limit hit",
            "Switched to CrossRef provider",
            stage="build",
            topic_id=1,
        )
        assert eid > 0
        events = rec.get_session_trajectory()
        assert events[0].event_type == "error_recovery"
        assert events[0].success is False

    def test_record_gate_outcome(self, db):
        rec = TrajectoryRecorder(db, "sess-005")
        eid = rec.record_gate_outcome(
            "coverage_gate",
            "passed",
            "50 papers >= threshold",
            stage="build",
            topic_id=1,
        )
        assert eid > 0
        events = rec.get_session_trajectory()
        assert events[0].event_type == "gate_outcome"
        assert events[0].output_summary == "passed"

    def test_record_user_override(self, db):
        rec = TrajectoryRecorder(db, "sess-006")
        eid = rec.record_user_override(
            "Changed search query from X to Y",
            "User preferred more specific terms",
            stage="build",
        )
        assert eid > 0
        events = rec.get_session_trajectory()
        assert events[0].event_type == "user_override"

    def test_get_stage_trajectories(self, db):
        rec1 = TrajectoryRecorder(db, "sess-a")
        rec1.record_tool_call("paper_search", stage="build", topic_id=1)
        rec1.record_tool_call("paper_ingest", stage="build", topic_id=1)

        rec2 = TrajectoryRecorder(db, "sess-b")
        rec2.record_tool_call("gap_detect", stage="analyze", topic_id=1)

        build_events = TrajectoryRecorder.get_stage_trajectories(db, "build")
        assert len(build_events) == 2
        assert all(e.stage == "build" for e in build_events)

        analyze_events = TrajectoryRecorder.get_stage_trajectories(db, "analyze")
        assert len(analyze_events) == 1

    def test_get_stage_trajectories_with_topic(self, db):
        rec = TrajectoryRecorder(db, "sess-c")
        rec.record_tool_call("paper_search", stage="build", topic_id=1)
        rec.record_tool_call("paper_search", stage="build", topic_id=2)

        events = TrajectoryRecorder.get_stage_trajectories(db, "build", topic_id=1)
        assert len(events) == 1
        assert events[0].topic_id == 1

    def test_format_trajectory_text(self, db):
        rec = TrajectoryRecorder(db, "sess-d")
        rec.record_tool_call(
            "paper_search",
            stage="build",
            input_summary="query=attention",
            output_summary="found 15 papers",
            success=True,
            cost_usd=0.005,
        )
        rec.record_tool_call(
            "paper_ingest",
            stage="build",
            input_summary="arxiv:2401.12345",
            output_summary="ingested successfully",
            success=True,
        )
        events = rec.get_session_trajectory()
        text = TrajectoryRecorder.format_trajectory_text(events)
        assert "paper_search" in text
        assert "paper_ingest" in text
        assert "found 15 papers" in text

    def test_format_empty_trajectory(self):
        text = TrajectoryRecorder.format_trajectory_text([])
        assert "no trajectory events" in text

    def test_parent_event_id(self, db):
        rec = TrajectoryRecorder(db, "sess-e")
        parent_id = rec.record_tool_call("deep_read", stage="analyze")
        _child_id = rec.record_tool_call(
            "paper_summarize",
            stage="analyze",
            parent_event_id=parent_id,
        )
        events = rec.get_session_trajectory()
        assert events[1].parent_event_id == parent_id

    def test_get_session_ids_for_stage(self, db):
        rec1 = TrajectoryRecorder(db, "sess-x1")
        rec1.record_tool_call("paper_search", stage="build")
        rec2 = TrajectoryRecorder(db, "sess-x2")
        rec2.record_tool_call("paper_search", stage="build")

        ids = TrajectoryRecorder.get_session_ids_for_stage(db, "build")
        assert "sess-x1" in ids
        assert "sess-x2" in ids
