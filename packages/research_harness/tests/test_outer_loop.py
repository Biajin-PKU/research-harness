"""Tests for OuterLoop (Sprint 3 — dual loop meta-reflection)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from research_harness.evolution.outer_loop import OuterLoop


def _create_topic(db, name="test-topic"):
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)", (name, "Test")
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    finally:
        conn.close()


def _create_project(db, topic_id, name="test-project"):
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (?, ?, ?)",
            (topic_id, name, "Test project"),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    finally:
        conn.close()


class TestOuterLoop:
    def test_log_experiment(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db)

        eid = loop.log_experiment(pid, tid, "H1: method A > baseline")
        assert eid > 0

    def test_experiment_number_increments(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db)

        loop.log_experiment(pid, tid, "H1")
        loop.log_experiment(pid, tid, "H2")
        loop.log_experiment(pid, tid, "H3")

        history = loop.get_experiment_history(pid)
        nums = [e.experiment_number for e in history]
        assert nums == [1, 2, 3]

    def test_log_with_metrics(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db)

        _eid = loop.log_experiment(
            pid,
            tid,
            "H1: transformer beats RNN",
            primary_metric_name="accuracy",
            primary_metric_value=0.95,
            metrics={"accuracy": 0.95, "f1": 0.92},
            outcome="success",
            notes="Clear improvement",
        )

        history = loop.get_experiment_history(pid)
        assert len(history) == 1
        assert history[0].primary_metric_value == 0.95
        assert history[0].outcome == "success"
        assert history[0].metrics["f1"] == 0.92

    def test_should_reflect_false_when_not_enough(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=3)

        loop.log_experiment(pid, tid, "H1")
        loop.log_experiment(pid, tid, "H2")

        assert loop.should_reflect(pid) is False

    def test_should_reflect_true_at_interval(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=3)

        for i in range(3):
            loop.log_experiment(pid, tid, f"H{i + 1}")

        assert loop.should_reflect(pid) is True

    def test_should_reflect_resets_after_reflection(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=3)

        for i in range(3):
            loop.log_experiment(pid, tid, f"H{i + 1}")

        mock_response = '{"decision": "DEEPEN", "reasoning": "Good progress", "patterns": "Consistent improvement", "next_hypothesis": "H4", "confidence": 0.7}'
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_response)
        mock_client.model = "test-model"

        with patch(
            "research_harness.evolution.outer_loop._get_llm_client",
            return_value=mock_client,
        ):
            reflection = loop.reflect(pid, tid)

        assert reflection is not None
        assert reflection.decision == "DEEPEN"

        # After reflection, should_reflect should be False (no new experiments)
        assert loop.should_reflect(pid) is False

        # Add more experiments → should become True again
        for i in range(3):
            loop.log_experiment(pid, tid, f"H{i + 4}")
        assert loop.should_reflect(pid) is True

    def test_reflect_deepen(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=2)

        loop.log_experiment(pid, tid, "H1", outcome="partial")
        loop.log_experiment(pid, tid, "H2", outcome="partial")

        mock_response = '{"decision": "DEEPEN", "reasoning": "Promising but needs refinement", "patterns": "Partial results improving", "next_hypothesis": "H3 with tuned params", "confidence": 0.6}'
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_response)
        mock_client.model = "test"

        with patch(
            "research_harness.evolution.outer_loop._get_llm_client",
            return_value=mock_client,
        ):
            r = loop.reflect(pid, tid)

        assert r.decision == "DEEPEN"
        assert r.reflection_number == 1

    def test_reflect_pivot(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=2)

        loop.log_experiment(pid, tid, "H1", outcome="failure")
        loop.log_experiment(pid, tid, "H2", outcome="failure")

        mock_response = '{"decision": "PIVOT", "reasoning": "Approach not working", "patterns": "Consistent failures", "next_hypothesis": "Try completely different method", "confidence": 0.8}'
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_response)
        mock_client.model = "test"

        with patch(
            "research_harness.evolution.outer_loop._get_llm_client",
            return_value=mock_client,
        ):
            r = loop.reflect(pid, tid)

        assert r.decision == "PIVOT"

    def test_reflect_conclude(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=2)

        loop.log_experiment(
            pid, tid, "H1", outcome="success", primary_metric_value=0.95
        )
        loop.log_experiment(
            pid, tid, "H2", outcome="success", primary_metric_value=0.96
        )

        mock_response = '{"decision": "CONCLUDE", "reasoning": "Strong results, ready to write", "patterns": "Consistent high performance", "next_hypothesis": "", "confidence": 0.9}'
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_response)
        mock_client.model = "test"

        with patch(
            "research_harness.evolution.outer_loop._get_llm_client",
            return_value=mock_client,
        ):
            r = loop.reflect(pid, tid)

        assert r.decision == "CONCLUDE"

    def test_reflect_returns_none_when_not_ready(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=3)

        loop.log_experiment(pid, tid, "H1")
        r = loop.reflect(pid, tid)
        assert r is None

    def test_reflect_force(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=10)

        loop.log_experiment(pid, tid, "H1")

        mock_response = '{"decision": "DEEPEN", "reasoning": "Forced reflection", "patterns": "N/A", "next_hypothesis": "H2", "confidence": 0.3}'
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_response)
        mock_client.model = "test"

        with patch(
            "research_harness.evolution.outer_loop._get_llm_client",
            return_value=mock_client,
        ):
            r = loop.reflect(pid, tid, force=True)

        assert r is not None
        assert r.decision == "DEEPEN"

    def test_reflection_history(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=2)

        for i in range(4):
            loop.log_experiment(pid, tid, f"H{i + 1}")

        mock_response = '{"decision": "DEEPEN", "reasoning": "R", "patterns": "P", "next_hypothesis": "N", "confidence": 0.5}'
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_response)
        mock_client.model = "test"

        with patch(
            "research_harness.evolution.outer_loop._get_llm_client",
            return_value=mock_client,
        ):
            loop.reflect(pid, tid)
            # Add 2 more to trigger second reflection
            loop.log_experiment(pid, tid, "H5")
            loop.log_experiment(pid, tid, "H6")
            loop.reflect(pid, tid)

        history = loop.get_reflection_history(pid)
        assert len(history) == 2
        assert history[0].reflection_number == 1
        assert history[1].reflection_number == 2

    def test_get_experiment_count(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db)

        assert loop.get_experiment_count(pid) == 0
        loop.log_experiment(pid, tid, "H1")
        loop.log_experiment(pid, tid, "H2")
        assert loop.get_experiment_count(pid) == 2

    def test_invalid_decision_defaults_to_deepen(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)
        loop = OuterLoop(db, reflection_interval=1)
        loop.log_experiment(pid, tid, "H1")

        mock_response = '{"decision": "INVALID", "reasoning": "Bad", "patterns": "", "confidence": 0.1}'
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_response)
        mock_client.model = "test"

        with patch(
            "research_harness.evolution.outer_loop._get_llm_client",
            return_value=mock_client,
        ):
            r = loop.reflect(pid, tid)

        assert r.decision == "DEEPEN"


class TestExperimentLogPrimitive:
    def test_experiment_log_primitive(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)

        from research_harness.primitives.evolution_impls import experiment_log

        result = experiment_log(
            db=db,
            project_id=pid,
            topic_id=tid,
            hypothesis="Test hypothesis",
            outcome="success",
        )
        assert result.experiment_id > 0
        assert result.experiment_number == 1


class TestMetaReflectPrimitive:
    def test_meta_reflect_not_ready(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)

        from research_harness.primitives.evolution_impls import meta_reflect

        result = meta_reflect(db=db, project_id=pid, topic_id=tid)
        assert result.decision == ""
        assert "Not enough" in result.reasoning

    def test_meta_reflect_with_transition(self, db):
        tid = _create_topic(db)
        pid = _create_project(db, tid)

        from research_harness.evolution.outer_loop import OuterLoop

        loop = OuterLoop(db, reflection_interval=1)
        loop.log_experiment(pid, tid, "H1", outcome="success")

        mock_response = '{"decision": "CONCLUDE", "reasoning": "Done", "patterns": "P", "next_hypothesis": "", "confidence": 0.9}'
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_response)
        mock_client.model = "test"

        from research_harness.primitives.evolution_impls import meta_reflect

        with patch(
            "research_harness.evolution.outer_loop._get_llm_client",
            return_value=mock_client,
        ):
            result = meta_reflect(db=db, project_id=pid, topic_id=tid, force=True)

        assert result.decision == "CONCLUDE"
        assert result.should_transition is True
        assert result.transition_target == "write"
