"""Tests for StrategyDistiller (Sprint 2 — strategy distillation pipeline)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from research_harness.evolution.distiller import StrategyDistiller, QUALITY_THRESHOLD
from research_harness.evolution.store import DBLessonStore, Lesson
from research_harness.evolution.trajectory import TrajectoryRecorder


class TestStrategyDistiller:
    def _seed_lessons(self, db, stage: str = "build", count: int = 5):
        """Seed lesson DB with test data."""
        store = DBLessonStore(db)
        for i in range(count):
            store.append(
                Lesson(
                    stage=stage,
                    content=f"Test lesson {i}: use CrossRef before S2",
                    lesson_type="success" if i % 2 == 0 else "failure",
                    tags=[stage, "test"],
                ),
            )
        return store

    def _seed_trajectories(self, db, stage: str = "build", count: int = 3):
        """Seed trajectory DB with test data."""
        for i in range(count):
            rec = TrajectoryRecorder(db, f"test-sess-{i}")
            rec.record_tool_call(
                "paper_search",
                stage=stage,
                topic_id=1,
                input_summary=f"query={i}",
                output_summary="found papers",
            )

    def test_distill_insufficient_lessons(self, db, tmp_path):
        """Should skip when not enough lessons."""
        self._seed_lessons(db, count=2)
        distiller = StrategyDistiller(db, tmp_path / "strategies")
        result = distiller.distill_stage("build", min_lessons=3)
        assert result.strategies_created == 0
        assert result.strategies_skipped == 0

    def test_distill_force_with_few_lessons(self, db, tmp_path):
        """force=True should proceed even with few lessons."""
        self._seed_lessons(db, count=1)

        mock_llm_response_aggregate = '{"themes": [{"theme_key": "test_strategy", "title": "Test", "summary": "A test", "evidence_ids": [], "scope": "global"}]}'
        mock_llm_response_distill = '{"content": "## When to Apply\\nAlways"}'
        mock_llm_response_gate = '{"scores": {"evidence_grounded": 0.9, "preserves_existing": 0.8, "specific_reusable": 0.85, "safe_to_publish": 0.9}, "overall": 0.86, "decision": "accept", "reasoning": "Good"}'

        call_count = [0]
        responses = [
            mock_llm_response_aggregate,
            mock_llm_response_distill,
            mock_llm_response_gate,
        ]

        def mock_chat(prompt, **kwargs):
            idx = min(call_count[0], len(responses) - 1)
            call_count[0] += 1
            return responses[idx]

        mock_client = MagicMock()
        mock_client.chat = mock_chat
        mock_client.model = "test-model"

        with patch(
            "research_harness.evolution.distiller._get_llm_client",
            return_value=mock_client,
        ):
            distiller = StrategyDistiller(db, tmp_path / "strategies")
            result = distiller.distill_stage("build", force=True)

        assert result.strategies_created == 1
        assert len(result.quality_scores) == 1
        assert result.quality_scores[0] >= QUALITY_THRESHOLD

    def test_distill_quality_gate_rejects(self, db, tmp_path):
        """Low quality score should store as draft, not active."""
        self._seed_lessons(db, count=5)

        mock_aggregate = '{"themes": [{"theme_key": "bad_strat", "title": "Bad", "summary": "Weak", "evidence_ids": [], "scope": "global"}]}'
        mock_distill = '{"content": "Generic advice"}'
        mock_gate = '{"scores": {"evidence_grounded": 0.3, "preserves_existing": 0.4, "specific_reusable": 0.2, "safe_to_publish": 0.5}, "overall": 0.35, "decision": "reject", "reasoning": "Not grounded"}'

        call_count = [0]
        responses = [mock_aggregate, mock_distill, mock_gate]

        def mock_chat(prompt, **kwargs):
            idx = min(call_count[0], len(responses) - 1)
            call_count[0] += 1
            return responses[idx]

        mock_client = MagicMock()
        mock_client.chat = mock_chat
        mock_client.model = "test-model"

        with patch(
            "research_harness.evolution.distiller._get_llm_client",
            return_value=mock_client,
        ):
            distiller = StrategyDistiller(db, tmp_path / "strategies")
            result = distiller.distill_stage("build")

        assert result.strategies_created == 0
        assert result.strategies_skipped == 1

        # Verify stored as draft in DB
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT status FROM strategies WHERE strategy_key = 'build.bad_strat'"
            ).fetchone()
            assert row is not None
            assert row["status"] == "draft"
        finally:
            conn.close()

    def test_strategy_file_written(self, db, tmp_path):
        """Verify STRATEGY.md file is created for the stage."""
        self._seed_lessons(db, count=5)

        mock_aggregate = '{"themes": [{"theme_key": "file_test", "title": "File Test", "summary": "Test", "evidence_ids": [], "scope": "global"}]}'
        mock_distill = '{"content": "## Steps\\n1. Do this"}'
        mock_gate = '{"scores": {"evidence_grounded": 0.9, "preserves_existing": 0.9, "specific_reusable": 0.9, "safe_to_publish": 0.9}, "overall": 0.9, "decision": "accept", "reasoning": "OK"}'

        call_count = [0]
        responses = [mock_aggregate, mock_distill, mock_gate]

        def mock_chat(prompt, **kwargs):
            idx = min(call_count[0], len(responses) - 1)
            call_count[0] += 1
            return responses[idx]

        mock_client = MagicMock()
        mock_client.chat = mock_chat
        mock_client.model = "test-model"

        strat_dir = tmp_path / "strategies"
        with patch(
            "research_harness.evolution.distiller._get_llm_client",
            return_value=mock_client,
        ):
            distiller = StrategyDistiller(db, strat_dir)
            distiller.distill_stage("build")

        # Check file exists
        md_path = strat_dir / "build.md"
        assert md_path.exists()
        content = md_path.read_text()
        assert "File Test" in content
        assert "Do this" in content

    def test_version_increments(self, db, tmp_path):
        """Running distill twice should create version 2 and supersede version 1."""
        self._seed_lessons(db, count=5)

        mock_aggregate = '{"themes": [{"theme_key": "versioned", "title": "V Test", "summary": "S", "evidence_ids": [], "scope": "global"}]}'
        mock_distill = '{"content": "Strategy content"}'
        mock_gate = '{"scores": {"evidence_grounded": 0.9, "preserves_existing": 0.9, "specific_reusable": 0.9, "safe_to_publish": 0.9}, "overall": 0.9, "decision": "accept", "reasoning": "OK"}'

        call_count = [0]
        responses = [mock_aggregate, mock_distill, mock_gate]

        def mock_chat(prompt, **kwargs):
            idx = min(call_count[0] % 3, 2)
            call_count[0] += 1
            return responses[idx]

        mock_client = MagicMock()
        mock_client.chat = mock_chat
        mock_client.model = "test-model"

        with patch(
            "research_harness.evolution.distiller._get_llm_client",
            return_value=mock_client,
        ):
            distiller = StrategyDistiller(db, tmp_path / "strategies")
            distiller.distill_stage("build")
            distiller.distill_stage("build")

        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT version, status FROM strategies WHERE strategy_key = 'build.versioned' ORDER BY version"
            ).fetchall()
            assert len(rows) == 2
            assert rows[0]["status"] == "superseded"
            assert rows[1]["status"] == "active"
            assert rows[1]["version"] == 2
        finally:
            conn.close()

    def test_collect_evidence_includes_trajectories(self, db, tmp_path):
        """Evidence collection should include both lessons and trajectories."""
        self._seed_lessons(db, count=3)
        self._seed_trajectories(db, count=2)

        distiller = StrategyDistiller(db, tmp_path / "strategies")
        evidence = distiller._collect_evidence("build")
        assert evidence["lesson_count"] == 3
        assert evidence["trajectory_count"] > 0
        assert "paper_search" in evidence["evidence_text"]

    def test_distill_all(self, db, tmp_path):
        """distill_all should process all stages with enough lessons."""
        store = DBLessonStore(db)
        for i in range(5):
            store.append(Lesson(stage="build", content=f"build lesson {i}"))
            store.append(Lesson(stage="analyze", content=f"analyze lesson {i}"))
        # Only 1 lesson for propose — should skip
        store.append(Lesson(stage="propose", content="single propose lesson"))

        mock_aggregate = '{"themes": []}'
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_aggregate)
        mock_client.model = "test"

        with patch(
            "research_harness.evolution.distiller._get_llm_client",
            return_value=mock_client,
        ):
            distiller = StrategyDistiller(db, tmp_path / "strategies")
            results = distiller.distill_all(min_lessons=3)

        stages = [r.stage for r in results]
        assert "build" in stages
        assert "analyze" in stages
        # propose is in results but with 0 strategies (insufficient lessons)
        propose_result = [r for r in results if r.stage == "propose"]
        if propose_result:
            assert propose_result[0].strategies_created == 0
