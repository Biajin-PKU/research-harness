"""Tests for ColdStartProtocol — three-phase topic bootstrap."""

from __future__ import annotations

import json

import pytest

from research_harness.evolution.cold_start_protocol import (
    ColdStartPhase,
    ColdStartProtocol,
    PhaseTargets,
)
from research_harness.storage.db import Database


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.migrate()
    return db


@pytest.fixture
def topic_id(db):
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("cold-start-topic", "Test topic for cold start"),
        )
        tid = int(cur.lastrowid)
        conn.commit()
        return tid
    finally:
        conn.close()


def _insert_papers(db, topic_id, count):
    """Insert `count` papers linked to topic via paper_topics."""
    conn = db.connect()
    try:
        for i in range(count):
            cur = conn.execute(
                "INSERT INTO papers (title, year, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?)",
                (f"Paper {i}", 2024, f"10.test/cs-{topic_id}-{i}", f"cs.{topic_id}.{i}", f"s2-cs-{topic_id}-{i}"),
            )
            paper_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
                (paper_id, topic_id),
            )
            conn.execute(
                "INSERT INTO topic_paper_notes (paper_id, topic_id, note_type, content) VALUES (?, ?, ?, ?)",
                (paper_id, topic_id, "relevance", "high"),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_paper_annotations(db, topic_id, count, section="paper_card"):
    """Insert annotations for first `count` papers in the topic."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT paper_id FROM paper_topics WHERE topic_id = ? LIMIT ?",
            (topic_id, count),
        ).fetchall()
        for row in rows:
            conn.execute(
                "INSERT INTO paper_annotations (paper_id, section, content) VALUES (?, ?, ?)",
                (row["paper_id"], section, "{}"),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_writing_observations(db, count):
    """Insert writing observation records."""
    conn = db.connect()
    try:
        for i in range(count):
            conn.execute(
                """INSERT INTO writing_observations
                   (paper_id, dimension, section, observation, example_text)
                   VALUES (?, ?, ?, ?, ?)""",
                (1, f"dim_{i}", "abstract", f'{{"pattern": "pattern_{i}"}}', f"example_{i}"),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_gap_artifact(db, topic_id, gap_count):
    """Insert a gap_detect artifact with `gap_count` gaps."""
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (?, ?, ?)",
            (topic_id, "test-proj", "test"),
        )
        gaps = [{"gap": f"Gap {i}", "description": f"Desc {i}"} for i in range(gap_count)]
        payload = json.dumps({"gaps": gaps})
        conn.execute(
            """INSERT INTO project_artifacts
               (project_id, topic_id, stage, artifact_type, payload_json, status, version)
               VALUES (1, ?, 'analyze', 'gap_detect', ?, 'active', 1)""",
            (topic_id, payload),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_writing_strategies(db, count):
    """Insert writing skill strategies."""
    conn = db.connect()
    try:
        for i in range(count):
            conn.execute(
                """INSERT INTO strategies (stage, strategy_key, title, content, status)
                   VALUES ('write', ?, ?, ?, 'active')""",
                (f"writing_skill.dim_{i}", f"Dim {i}", f"Strategy for dim_{i}"),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Seed Phase
# ---------------------------------------------------------------------------


class TestSeedPhase:
    def test_empty_topic_incomplete(self, db, topic_id):
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.check_seed_phase()
        assert progress.phase == ColdStartPhase.SEED
        assert not progress.complete
        assert progress.current["min_papers"] == 0
        assert progress.targets["min_papers"] == 50
        assert len(progress.notes) > 0

    def test_below_threshold(self, db, topic_id):
        _insert_papers(db, topic_id, 30)
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.check_seed_phase()
        assert not progress.complete
        assert progress.current["min_papers"] == 30

    def test_at_threshold(self, db, topic_id):
        _insert_papers(db, topic_id, 50)
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.check_seed_phase()
        assert progress.complete

    def test_custom_threshold(self, db, topic_id):
        _insert_papers(db, topic_id, 25)
        targets = PhaseTargets(min_papers=25)
        proto = ColdStartProtocol(db=db, topic_id=topic_id, targets=targets)
        progress = proto.check_seed_phase()
        assert progress.complete


# ---------------------------------------------------------------------------
# Index Phase
# ---------------------------------------------------------------------------


class TestIndexPhase:
    def test_no_annotations_incomplete(self, db, topic_id):
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.check_index_phase()
        assert progress.phase == ColdStartPhase.INDEX
        assert not progress.complete
        assert progress.current["min_paper_cards"] == 0
        assert progress.current["min_deep_reads"] == 0

    def test_partial_annotations(self, db, topic_id):
        _insert_papers(db, topic_id, 40)
        _insert_paper_annotations(db, topic_id, 30, "paper_card")
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.check_index_phase()
        assert not progress.complete
        assert progress.current["min_paper_cards"] == 30
        assert progress.current["min_deep_reads"] == 0

    def test_all_met(self, db, topic_id):
        _insert_papers(db, topic_id, 50)
        _insert_paper_annotations(db, topic_id, 30, "paper_card")
        _insert_paper_annotations(db, topic_id, 15, "deep_reading")
        _insert_writing_observations(db, 10)
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.check_index_phase()
        assert progress.complete


# ---------------------------------------------------------------------------
# Calibrate Phase
# ---------------------------------------------------------------------------


class TestCalibratePhase:
    def test_no_gaps_incomplete(self, db, topic_id):
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.check_calibrate_phase()
        assert progress.phase == ColdStartPhase.CALIBRATE
        assert not progress.complete

    def test_gaps_but_no_writing(self, db, topic_id):
        _insert_gap_artifact(db, topic_id, 5)
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.check_calibrate_phase()
        assert not progress.complete
        assert progress.current["min_gaps"] == 5

    def test_all_met(self, db, topic_id):
        _insert_gap_artifact(db, topic_id, 5)
        _insert_writing_strategies(db, 10)
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.check_calibrate_phase()
        assert progress.complete


# ---------------------------------------------------------------------------
# check_all
# ---------------------------------------------------------------------------


class TestCheckAll:
    def test_all_incomplete(self, db, topic_id):
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        result = proto.check_all()
        assert not result.complete
        assert result.topic_id == topic_id
        assert "seed" in result.phases
        assert "index" in result.phases
        assert "calibrate" in result.phases

    def test_fully_bootstrapped(self, db, topic_id):
        _insert_papers(db, topic_id, 55)
        _insert_paper_annotations(db, topic_id, 35, "paper_card")
        _insert_paper_annotations(db, topic_id, 20, "deep_reading")
        _insert_writing_observations(db, 12)
        _insert_gap_artifact(db, topic_id, 5)
        _insert_writing_strategies(db, 10)

        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        result = proto.check_all()
        assert result.complete
        assert result.total_papers == 55
        assert result.phases["seed"]["complete"]
        assert result.phases["index"]["complete"]
        assert result.phases["calibrate"]["complete"]


# ---------------------------------------------------------------------------
# Primitive registration
# ---------------------------------------------------------------------------


class TestPrimitiveRegistration:
    def test_cold_start_run_registered(self):
        from research_harness.primitives.registry import get_primitive_impl

        impl = get_primitive_impl("cold_start_run")
        assert impl is not None

    def test_cold_start_run_returns_output(self, db, topic_id):
        from research_harness.primitives.registry import get_primitive_impl

        impl = get_primitive_impl("cold_start_run")
        result = impl(db=db, topic_id=topic_id)
        assert result.topic_id == topic_id
        assert not result.complete


# ---------------------------------------------------------------------------
# run_* methods
# ---------------------------------------------------------------------------


class TestRunSeedPhase:
    def test_already_complete_noop(self, db, topic_id):
        _insert_papers(db, topic_id, 55)
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.run_seed_phase()
        assert progress.complete

    def test_gold_papers_ingested(self, db, topic_id):
        proto = ColdStartProtocol(
            db=db, topic_id=topic_id, gold_papers=["2401.99999"]
        )
        progress = proto.run_seed_phase()
        assert not progress.complete
        assert any("gold paper" in n.lower() or "paper_search" in n.lower() for n in progress.notes)

    def test_generates_search_queries(self, db, topic_id):
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        queries = proto._generate_seed_queries("multimodal time-series forecasting")
        assert len(queries) >= 2
        assert "survey" in queries[-1]


class TestRunIndexPhase:
    def test_generates_plan(self, db, topic_id):
        _insert_papers(db, topic_id, 50)
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.run_index_phase()
        assert not progress.complete
        assert any("paper_acquire" in n for n in progress.notes)

    def test_already_complete_noop(self, db, topic_id):
        _insert_papers(db, topic_id, 50)
        _insert_paper_annotations(db, topic_id, 30, "paper_card")
        _insert_paper_annotations(db, topic_id, 15, "deep_reading")
        _insert_writing_observations(db, 10)
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        progress = proto.run_index_phase()
        assert progress.complete


class TestRunAll:
    def test_returns_actions_and_next_steps(self, db, topic_id):
        proto = ColdStartProtocol(db=db, topic_id=topic_id)
        result = proto.run_all()
        assert not result.complete
        assert len(result.next_steps) > 0
