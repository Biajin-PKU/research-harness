"""Tests for Phase 2: cross-paper analysis primitives."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def _insert_paper(conn, pid, title, **extra):
    """Insert a paper with unique identifiers."""
    cols = {
        "id": pid,
        "title": title,
        "s2_id": f"s2_{pid}",
        "arxiv_id": f"arxiv_{pid}",
        "doi": f"10.test/{pid}",
    }
    cols.update(extra)
    keys = ", ".join(cols.keys())
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO papers ({keys}) VALUES ({placeholders})", list(cols.values())
    )


# ---------------------------------------------------------------------------
# reading_prioritize
# ---------------------------------------------------------------------------


class TestReadingPrioritize:
    def test_ranks_by_composite_score(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        # Paper 1: high citations, old
        _insert_paper(
            conn,
            1,
            "Old High-Cited Paper",
            year=2018,
            citation_count=500,
            status="annotated",
        )
        # Paper 2: low citations, recent
        _insert_paper(
            conn,
            2,
            "New Low-Cited Paper",
            year=2025,
            citation_count=5,
            status="meta_only",
        )
        # Paper 3: medium everything
        _insert_paper(
            conn, 3, "Medium Paper", year=2022, citation_count=50, status="annotated"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (3, 1, 'medium')"
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import reading_prioritize

        result = reading_prioritize(db=db, topic_id=1)

        assert result.total_papers == 3
        assert len(result.ranked) == 3
        # All scores should be > 0
        assert all(p.score > 0 for p in result.ranked)
        # Should be sorted descending
        scores = [p.score for p in result.ranked]
        assert scores == sorted(scores, reverse=True)

    def test_limit(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        for i in range(1, 6):
            _insert_paper(conn, i, f"Paper {i}", year=2024, citation_count=i * 10)
            conn.execute(
                f"INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES ({i}, 1, 'medium')"
            )
        conn.commit()

        from research_harness.primitives.analysis_impls import reading_prioritize

        result = reading_prioritize(db=db, topic_id=1, limit=3)
        assert len(result.ranked) == 3
        assert result.total_papers == 5

    def test_custom_weights(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Old Cited", year=2015, citation_count=1000)
        _insert_paper(conn, 2, "New Uncited", year=2026, citation_count=0)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'medium')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'medium')"
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import reading_prioritize

        # Weight heavily toward recency
        result = reading_prioritize(
            db=db, topic_id=1, weights={"gap": 0, "citation": 0, "recency": 1}
        )
        assert result.ranked[0].paper_id == 2  # newer paper wins

        # Weight heavily toward citations
        result = reading_prioritize(
            db=db, topic_id=1, weights={"gap": 0, "citation": 1, "recency": 0}
        )
        assert result.ranked[0].paper_id == 1  # more cited paper wins

    def test_empty_topic(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'empty')")
        conn.commit()

        from research_harness.primitives.analysis_impls import reading_prioritize

        result = reading_prioritize(db=db, topic_id=1)
        assert result.total_papers == 0
        assert len(result.ranked) == 0

    def test_dismissed_papers_excluded(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Active Paper", year=2024, citation_count=10)
        _insert_paper(conn, 2, "Dismissed Paper", year=2024, citation_count=100)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO topic_paper_notes (paper_id, topic_id, note_type, content) VALUES (2, 1, 'user_dismissed', 'not relevant')"
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import reading_prioritize

        result = reading_prioritize(db=db, topic_id=1)
        assert result.total_papers == 1
        assert result.ranked[0].paper_id == 1


# ---------------------------------------------------------------------------
# experiment_design_checklist
# ---------------------------------------------------------------------------


class TestExperimentDesignChecklist:
    def test_returns_checklist(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        conn.commit()

        from research_harness.primitives.analysis_impls import (
            experiment_design_checklist,
        )

        result = experiment_design_checklist(db=db, topic_id=1)
        assert len(result.checklist) > 0
        # Check all expected categories present
        categories = {i.category for i in result.checklist}
        assert "baselines" in categories
        assert "metrics" in categories
        assert "datasets" in categories
        assert "ablations" in categories

    def test_fills_notes_from_compiled_summaries(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        compiled = json.dumps(
            {
                "overview": "...",
                "methods": ["DQN", "PPO"],
                "claims": [],
                "limitations": [],
                "metrics": [{"dataset": "MNIST", "metric": "accuracy", "value": "99%"}],
                "relations": [],
            }
        )
        _insert_paper(conn, 1, "RL Paper", compiled_summary=compiled)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import (
            experiment_design_checklist,
        )

        result = experiment_design_checklist(db=db, topic_id=1)

        # Should have notes with known methods/datasets
        baseline_items = [i for i in result.checklist if i.category == "baselines"]
        has_method_notes = any(
            "DQN" in i.notes or "PPO" in i.notes for i in baseline_items
        )
        assert has_method_notes

        dataset_items = [i for i in result.checklist if i.category == "datasets"]
        has_dataset_notes = any("MNIST" in i.notes for i in dataset_items)
        assert has_dataset_notes


# ---------------------------------------------------------------------------
# method_taxonomy (LLM-backed, requires mock)
# ---------------------------------------------------------------------------


class TestMethodTaxonomy:
    def test_builds_taxonomy(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        compiled = json.dumps(
            {
                "overview": "RL for bidding",
                "methods": ["DQN", "PPO"],
                "claims": [],
                "limitations": [],
                "metrics": [],
                "relations": [],
            }
        )
        _insert_paper(conn, 1, "DQN Paper", compiled_summary=compiled, year=2023)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()

        mock_response = json.dumps(
            {
                "nodes": [
                    {
                        "name": "Reinforcement Learning",
                        "parent": None,
                        "description": "RL category",
                        "aliases": ["RL"],
                        "paper_ids": [1],
                    },
                    {
                        "name": "DQN",
                        "parent": "Reinforcement Learning",
                        "description": "Deep Q-Network",
                        "aliases": ["Deep Q-Network"],
                        "paper_ids": [1],
                    },
                ]
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock()
            from research_harness.execution.llm_primitives import method_taxonomy

            result = method_taxonomy(db=db, topic_id=1)

        assert result.papers_processed == 1
        assert len(result.nodes) == 2
        # Check DB persistence
        conn2 = db.connect()
        nodes = conn2.execute(
            "SELECT * FROM taxonomy_nodes WHERE topic_id = 1"
        ).fetchall()
        conn2.close()
        assert len(nodes) == 2


# ---------------------------------------------------------------------------
# evidence_matrix (LLM-backed, requires mock)
# ---------------------------------------------------------------------------


class TestEvidenceMatrix:
    def test_normalizes_claims(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        compiled = json.dumps(
            {
                "overview": "Bidding methods comparison",
                "methods": ["DQN", "PPO"],
                "claims": [
                    {
                        "claim": "DQN outperforms PPO on CTR",
                        "evidence": "Table 3",
                        "strength": "strong",
                    }
                ],
                "limitations": [],
                "metrics": [
                    {
                        "dataset": "AdsData",
                        "metric": "CTR",
                        "value": "0.85",
                        "baseline": "0.80",
                    }
                ],
                "relations": [],
            }
        )
        _insert_paper(conn, 1, "Comparison Paper", compiled_summary=compiled, year=2024)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()

        mock_response = json.dumps(
            {
                "normalized_claims": [
                    {
                        "paper_id": 1,
                        "claim_text": "DQN outperforms PPO on CTR",
                        "method": "DQN",
                        "dataset": "AdsData",
                        "metric": "CTR",
                        "task": "ad bidding",
                        "value": "0.85",
                        "direction": "higher_better",
                        "confidence": 0.8,
                    },
                ]
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock()
            from research_harness.execution.llm_primitives import evidence_matrix

            result = evidence_matrix(db=db, topic_id=1)

        assert result.papers_processed == 1
        assert len(result.claims) == 1
        assert result.claims[0].method == "DQN"
        assert "DQN" in result.methods
        assert "AdsData" in result.datasets

        # Check DB persistence
        conn2 = db.connect()
        rows = conn2.execute(
            "SELECT * FROM normalized_claims WHERE topic_id = 1"
        ).fetchall()
        conn2.close()
        assert len(rows) == 1

    def test_empty_topic(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'empty')")
        conn.commit()

        from research_harness.execution.llm_primitives import evidence_matrix

        result = evidence_matrix(db=db, topic_id=1)
        assert result.papers_processed == 0
        assert len(result.claims) == 0


# ---------------------------------------------------------------------------
# contradiction_detect (LLM-backed, requires mock)
# ---------------------------------------------------------------------------


class TestContradictionDetect:
    def test_detects_contradictions(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Paper A")
        _insert_paper(conn, 2, "Paper B")
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'high')"
        )
        # Insert normalized claims
        conn.execute(
            "INSERT INTO normalized_claims (id, topic_id, paper_id, claim_text, method, dataset, metric, task, value, direction, confidence) "
            "VALUES (1, 1, 1, 'DQN > PPO', 'DQN', 'AdsData', 'CTR', 'bidding', '0.85', 'higher_better', 0.8)"
        )
        conn.execute(
            "INSERT INTO normalized_claims (id, topic_id, paper_id, claim_text, method, dataset, metric, task, value, direction, confidence) "
            "VALUES (2, 1, 2, 'PPO > DQN', 'PPO', 'AdsData', 'CTR', 'bidding', '0.88', 'higher_better', 0.7)"
        )
        conn.commit()

        mock_response = json.dumps(
            {
                "contradictions": [
                    {
                        "claim_a_id": 1,
                        "claim_b_id": 2,
                        "same_task": True,
                        "same_dataset": True,
                        "same_metric": True,
                        "confidence": 0.9,
                        "conflict_reason": "Paper A says DQN > PPO but Paper B says PPO > DQN on same dataset",
                    },
                ]
            }
        )

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_response,
            ),
        ):
            mock_client.return_value = MagicMock()
            from research_harness.execution.llm_primitives import contradiction_detect

            result = contradiction_detect(db=db, topic_id=1)

        assert result.claims_analyzed == 2
        assert len(result.contradictions) == 1
        c = result.contradictions[0]
        assert c.same_task is True
        assert c.same_dataset is True
        assert c.confidence == 0.9

        # Check DB persistence
        conn2 = db.connect()
        rows = conn2.execute(
            "SELECT * FROM contradictions WHERE topic_id = 1"
        ).fetchall()
        conn2.close()
        assert len(rows) == 1

    def test_too_few_claims(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        conn.commit()

        from research_harness.execution.llm_primitives import contradiction_detect

        result = contradiction_detect(db=db, topic_id=1)
        assert result.claims_analyzed == 0
        assert len(result.contradictions) == 0


# ---------------------------------------------------------------------------
# Migration 022: verify tables exist
# ---------------------------------------------------------------------------


class TestMigration022:
    def test_tables_exist(self, db, conn):
        for table in (
            "taxonomy_nodes",
            "taxonomy_assignments",
            "normalized_claims",
            "contradictions",
        ):
            conn.execute(f"SELECT COUNT(*) FROM {table}")  # should not raise

    def test_taxonomy_unique_constraint(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        conn.execute("INSERT INTO taxonomy_nodes (topic_id, name) VALUES (1, 'DQN')")
        conn.commit()

        # Duplicate should fail
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO taxonomy_nodes (topic_id, name) VALUES (1, 'DQN')"
            )


# ---------------------------------------------------------------------------
# Spec registration
# ---------------------------------------------------------------------------


class TestSpecRegistration:
    def test_all_phase2_specs_registered(self):
        from research_harness.primitives import PRIMITIVE_REGISTRY

        for name in (
            "reading_prioritize",
            "method_taxonomy",
            "experiment_design_checklist",
            "evidence_matrix",
            "contradiction_detect",
        ):
            assert name in PRIMITIVE_REGISTRY, f"{name} not in PRIMITIVE_REGISTRY"
