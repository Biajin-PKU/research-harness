"""Tests for Phase 1 auxiliary features: duplicate detection, survey detection, CLI commands."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from research_harness.cli import main
from research_harness.primitives.impls import (
    _detect_survey_paper,
    _find_duplicate_candidates,
    _normalize_title,
    _title_similarity,
)
from research_harness.storage.db import Database


def _insert_paper(conn, pid, title, **extra):
    """Insert a paper with unique s2_id/arxiv_id/doi to avoid constraint violations."""
    cols = {"id": pid, "title": title, "s2_id": f"s2_{pid}", "arxiv_id": f"arxiv_{pid}", "doi": f"10.test/{pid}"}
    cols.update(extra)
    keys = ", ".join(cols.keys())
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(f"INSERT INTO papers ({keys}) VALUES ({placeholders})", list(cols.values()))


# ---------------------------------------------------------------------------
# Title normalization and similarity
# ---------------------------------------------------------------------------

class TestTitleNormalization:
    def test_lowercase_and_strip(self):
        assert _normalize_title("  Hello World!  ") == "hello world"

    def test_remove_punctuation(self):
        assert _normalize_title("A: Survey of Methods (2024)") == "a survey of methods 2024"

    def test_collapse_whitespace(self):
        assert _normalize_title("deep   learning   models") == "deep learning models"


class TestTitleSimilarity:
    def test_identical(self):
        assert _title_similarity("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert _title_similarity("abc", "xyz") == 0.0

    def test_partial_overlap(self):
        sim = _title_similarity("deep learning for nlp", "deep learning for vision")
        assert 0.5 < sim < 1.0

    def test_empty(self):
        assert _title_similarity("", "hello") == 0.0


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    def test_finds_similar_title(self, db, conn):
        _insert_paper(conn, 1, "Deep Reinforcement Learning for Bidding Optimization")
        _insert_paper(conn, 2, "Deep Reinforcement Learning for Bidding Optimization in Ads")
        conn.commit()

        candidates = _find_duplicate_candidates(conn, "Deep Reinforcement Learning for Bidding Optimization in Ads", exclude_id=2)
        assert len(candidates) >= 1
        assert candidates[0]["id"] == 1

    def test_no_duplicate_for_different_titles(self, db, conn):
        _insert_paper(conn, 1, "Quantum Computing Basics")
        conn.commit()

        candidates = _find_duplicate_candidates(conn, "Deep Learning for NLP")
        assert len(candidates) == 0

    def test_excludes_self(self, db, conn):
        _insert_paper(conn, 1, "Exact Same Title")
        conn.commit()

        candidates = _find_duplicate_candidates(conn, "Exact Same Title", exclude_id=1)
        assert len(candidates) == 0

    def test_topic_scoped(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'topic-a')")
        conn.execute("INSERT INTO topics (id, name) VALUES (2, 'topic-b')")
        _insert_paper(conn, 1, "Budget Allocation Methods")
        _insert_paper(conn, 2, "Budget Allocation Methods Extended")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 2, 'high')")
        conn.commit()

        # Scoped to topic 1 — should only find paper 1
        candidates = _find_duplicate_candidates(conn, "Budget Allocation Methods Extended", topic_id=1)
        assert all(c["id"] == 1 for c in candidates)

    def test_short_title_returns_empty(self, db, conn):
        assert _find_duplicate_candidates(conn, "Hi") == []


# ---------------------------------------------------------------------------
# Survey detection
# ---------------------------------------------------------------------------

class TestSurveyDetection:
    def test_detects_survey_title(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "A Survey of Auto-Bidding Methods")
        conn.commit()

        result = _detect_survey_paper(conn, 1, "A Survey of Auto-Bidding Methods", topic_id=1)
        assert result is True

        note = conn.execute(
            "SELECT * FROM topic_paper_notes WHERE paper_id = 1 AND note_type = 'survey_flag'",
        ).fetchone()
        assert note is not None

    def test_no_flag_for_normal_paper(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Budget Pacing for Online Ads")
        conn.commit()

        result = _detect_survey_paper(conn, 1, "Budget Pacing for Online Ads", topic_id=1)
        assert result is False

    def test_idempotent(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "A Comprehensive Review of RL")
        conn.commit()

        _detect_survey_paper(conn, 1, "A Comprehensive Review of RL", topic_id=1)
        _detect_survey_paper(conn, 1, "A Comprehensive Review of RL", topic_id=1)

        notes = conn.execute(
            "SELECT COUNT(*) as cnt FROM topic_paper_notes WHERE paper_id = 1 AND note_type = 'survey_flag'",
        ).fetchone()
        assert notes["cnt"] == 1

    def test_meta_analysis(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "A Meta-Analysis of Ad Auction Results")
        conn.commit()

        assert _detect_survey_paper(conn, 1, "A Meta-Analysis of Ad Auction Results", topic_id=1) is True


# ---------------------------------------------------------------------------
# CLI: paper move
# ---------------------------------------------------------------------------

class TestPaperMoveCLI:
    def test_move_paper(self, runner, tmp_path, monkeypatch):
        db_path = tmp_path / "cli.db"
        monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
        db = Database(db_path)
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'src'), (2, 'dst')")
        _insert_paper(conn, 1, "Paper A")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.commit()
        conn.close()

        result = runner.invoke(main, ["paper", "move", "1", "--from-topic", "src", "--to-topic", "dst"])
        assert result.exit_code == 0
        assert "Moved 1/1" in result.output

        conn = db.connect()
        in_dst = conn.execute("SELECT * FROM paper_topics WHERE paper_id = 1 AND topic_id = 2").fetchone()
        in_src = conn.execute("SELECT * FROM paper_topics WHERE paper_id = 1 AND topic_id = 1").fetchone()
        conn.close()
        assert in_dst is not None
        assert in_src is None


class TestPaperBulkUpdateCLI:
    def test_bulk_update_relevance(self, runner, tmp_path, monkeypatch):
        db_path = tmp_path / "cli.db"
        monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
        db = Database(db_path)
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "P1")
        _insert_paper(conn, 2, "P2")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'medium'), (2, 1, 'medium')")
        conn.commit()
        conn.close()

        result = runner.invoke(main, ["paper", "bulk-update", "1", "2", "--relevance", "high", "--topic", "test"])
        assert result.exit_code == 0
        assert "Updated 2/2" in result.output

        conn = db.connect()
        rows = conn.execute("SELECT relevance FROM paper_topics WHERE topic_id = 1").fetchall()
        conn.close()
        assert all(r["relevance"] == "high" for r in rows)


# ---------------------------------------------------------------------------
# CLI: topic stats
# ---------------------------------------------------------------------------

class TestTopicStatsCLI:
    def test_stats_output(self, runner, tmp_path, monkeypatch):
        db_path = tmp_path / "cli.db"
        monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
        db = Database(db_path)
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test-topic')")
        _insert_paper(conn, 1, "P1", year=2024, venue="NeurIPS", status="annotated")
        _insert_paper(conn, 2, "P2", year=2023, venue="ICML", status="meta_only")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high'), (2, 1, 'medium')")
        conn.commit()
        conn.close()

        result = runner.invoke(main, ["topic", "stats", "test-topic"])
        assert result.exit_code == 0
        assert "test-topic" in result.output
        assert "2 papers" in result.output
        assert "NeurIPS" in result.output

    def test_stats_json(self, runner, tmp_path, monkeypatch):
        db_path = tmp_path / "cli.db"
        monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
        db = Database(db_path)
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test-topic')")
        _insert_paper(conn, 1, "P1")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.commit()
        conn.close()

        result = runner.invoke(main, ["--json", "topic", "stats", "test-topic"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_papers"] == 1
