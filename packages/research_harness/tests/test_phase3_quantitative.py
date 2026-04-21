"""Tests for Phase 3: quantitative extraction primitives."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from research_harness.storage.db import Database


def _insert_paper(conn, pid, title, **extra):
    cols = {"id": pid, "title": title, "s2_id": f"s2_{pid}", "arxiv_id": f"arxiv_{pid}", "doi": f"10.test/{pid}"}
    cols.update(extra)
    keys = ", ".join(cols.keys())
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(f"INSERT INTO papers ({keys}) VALUES ({placeholders})", list(cols.values()))


# ---------------------------------------------------------------------------
# Migration 023
# ---------------------------------------------------------------------------

class TestMigration023:
    def test_tables_exist(self, db, conn):
        for t in ("extracted_tables", "extracted_figures", "aggregated_metrics"):
            conn.execute(f"SELECT COUNT(*) FROM {t}")


# ---------------------------------------------------------------------------
# table_extract
# ---------------------------------------------------------------------------

class TestTableExtract:
    def test_extracts_tables(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Results Paper")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.execute(
            "INSERT INTO paper_annotations (paper_id, section, content) VALUES (1, 'summary', 'We compare methods A and B on dataset X.')"
        )
        conn.commit()

        mock_response = json.dumps({"tables": [
            {"table_number": 1, "caption": "Results on Dataset X",
             "headers": ["Method", "Accuracy", "F1"],
             "rows": [["DQN", "0.95", "0.93"], ["PPO", "0.91", "0.89"]],
             "source_page": 5},
        ]})

        with patch("research_harness.execution.llm_primitives._get_client") as mock_client, \
             patch("research_harness.execution.llm_primitives._client_chat", return_value=mock_response):
            mock_client.return_value = MagicMock()
            from research_harness.execution.llm_primitives import table_extract
            result = table_extract(db=db, paper_id=1)

        assert result.paper_id == 1
        assert len(result.tables) == 1
        t = result.tables[0]
        assert t.table_number == 1
        assert len(t.headers) == 3
        assert len(t.rows) == 2

        # Check DB
        conn2 = db.connect()
        rows = conn2.execute("SELECT * FROM extracted_tables WHERE paper_id = 1").fetchall()
        conn2.close()
        assert len(rows) == 1

    def test_empty_paper(self, db, conn):
        _insert_paper(conn, 1, "Empty Paper")
        conn.commit()

        from research_harness.execution.llm_primitives import table_extract
        result = table_extract(db=db, paper_id=1)
        assert len(result.tables) == 0


# ---------------------------------------------------------------------------
# figure_interpret
# ---------------------------------------------------------------------------

class TestFigureInterpret:
    def test_interprets_figures(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Visual Paper")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.execute(
            "INSERT INTO paper_annotations (paper_id, section, content) VALUES (1, 'summary', 'Figure 1 shows the training curve.')"
        )
        conn.commit()

        mock_response = json.dumps({"figures": [
            {"figure_number": 1, "caption": "Training loss over epochs",
             "interpretation": "Shows convergence after 50 epochs",
             "key_data_points": ["Loss drops from 2.0 to 0.1", "Converges at epoch 50"],
             "figure_type": "line_plot"},
        ]})

        with patch("research_harness.execution.llm_primitives._get_client") as mock_client, \
             patch("research_harness.execution.llm_primitives._client_chat", return_value=mock_response):
            mock_client.return_value = MagicMock()
            from research_harness.execution.llm_primitives import figure_interpret
            result = figure_interpret(db=db, paper_id=1)

        assert result.paper_id == 1
        assert len(result.figures) == 1
        f = result.figures[0]
        assert f.figure_type == "line_plot"
        assert len(f.key_data_points) == 2


# ---------------------------------------------------------------------------
# metrics_aggregate
# ---------------------------------------------------------------------------

class TestMetricsAggregate:
    def test_aggregates_from_tables(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Paper A")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.execute(
            "INSERT INTO extracted_tables (paper_id, table_number, caption, headers, rows) "
            "VALUES (1, 1, 'Results on MNIST', ?, ?)",
            (json.dumps(["Method", "Accuracy", "F1"]),
             json.dumps([["DQN", "0.95", "0.93"], ["PPO", "0.91", "0.89"]])),
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import metrics_aggregate
        result = metrics_aggregate(db=db, topic_id=1)

        assert result.papers_processed == 1
        assert len(result.metrics) >= 2  # At least 2 rows * 2 metrics
        assert "DQN" in result.methods
        assert "PPO" in result.methods

    def test_aggregates_from_compiled_summary(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        compiled = json.dumps({
            "overview": "...", "methods": ["MyMethod"], "claims": [], "limitations": [],
            "metrics": [
                {"dataset": "CIFAR", "metric": "accuracy", "value": "0.96"},
                {"dataset": "MNIST", "metric": "accuracy", "value": "0.99"},
            ],
            "relations": [],
        })
        _insert_paper(conn, 1, "Paper B", compiled_summary=compiled)
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.commit()

        from research_harness.primitives.analysis_impls import metrics_aggregate
        result = metrics_aggregate(db=db, topic_id=1)

        assert result.papers_processed == 1
        assert len(result.metrics) == 2
        assert "CIFAR" in result.datasets
        assert "MNIST" in result.datasets
        # Text-sourced metrics have lower confidence
        assert all(m.confidence == 0.5 for m in result.metrics)
        assert all(m.source_type == "text" for m in result.metrics)

    def test_empty_topic(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'empty')")
        conn.commit()

        from research_harness.primitives.analysis_impls import metrics_aggregate
        result = metrics_aggregate(db=db, topic_id=1)
        assert result.papers_processed == 0
        assert len(result.metrics) == 0


# ---------------------------------------------------------------------------
# dataset_index
# ---------------------------------------------------------------------------

class TestDatasetIndex:
    def test_builds_index(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        compiled = json.dumps({
            "overview": "...", "methods": [], "claims": [], "limitations": [],
            "metrics": [
                {"dataset": "MNIST", "metric": "accuracy", "value": "0.99"},
                {"dataset": "MNIST", "metric": "F1", "value": "0.98"},
                {"dataset": "CIFAR", "metric": "accuracy", "value": "0.95"},
            ],
            "relations": [],
        })
        _insert_paper(conn, 1, "Paper A", compiled_summary=compiled)
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.commit()

        from research_harness.primitives.analysis_impls import dataset_index
        result = dataset_index(db=db, topic_id=1)
        assert len(result.datasets) == 2
        mnist = next(d for d in result.datasets if d.dataset == "MNIST")
        assert mnist.count == 1
        assert "accuracy" in mnist.metrics
        assert "F1" in mnist.metrics


# ---------------------------------------------------------------------------
# author_coverage
# ---------------------------------------------------------------------------

class TestAuthorCoverage:
    def test_lists_authors(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Paper A", authors="Alice, Bob, Charlie")
        _insert_paper(conn, 2, "Paper B", authors="Alice, David")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'high')")
        conn.commit()

        from research_harness.primitives.analysis_impls import author_coverage
        result = author_coverage(db=db, topic_id=1)
        assert result.total_papers == 2
        # Alice appears in both papers
        alice = next(a for a in result.authors if a.name == "Alice")
        assert alice.paper_count == 2

    def test_filter_by_author(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Paper A", authors="Alice, Bob")
        conn.execute("INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')")
        conn.commit()

        from research_harness.primitives.analysis_impls import author_coverage
        result = author_coverage(db=db, topic_id=1, author_name="alice")
        assert len(result.authors) == 1
        assert result.authors[0].name == "Alice"


# ---------------------------------------------------------------------------
# Spec registration
# ---------------------------------------------------------------------------

class TestPhase3SpecRegistration:
    def test_all_specs_registered(self):
        from research_harness.primitives import PRIMITIVE_REGISTRY
        for name in ("table_extract", "figure_interpret", "metrics_aggregate",
                      "dataset_index", "author_coverage"):
            assert name in PRIMITIVE_REGISTRY
