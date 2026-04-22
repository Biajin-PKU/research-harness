"""Tests for Phase 4: workflow, export, and visualization primitives."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _insert_paper(conn, pid, title, **extra):
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
# rebuttal_format
# ---------------------------------------------------------------------------


class TestRebuttalFormat:
    def test_formats_rebuttal(self, db, conn):
        # Set up topic with review issues
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        conn.execute(
            "INSERT INTO review_issues (id, project_id, topic_id, stage, review_type, severity, category, summary, details, recommended_action, status) "
            "VALUES (1, NULL, 1, 'writing', 'scholarly', 'high', 'methodology', 'Missing ablation study', 'Need ablation of key components', 'Add ablation table', 'open')"
        )
        conn.execute(
            "INSERT INTO review_responses (id, issue_id, topic_id, response_type, response_text, status) "
            "VALUES (1, 1, 1, 'change', 'Added ablation study in Table 5', 'active')"
        )
        conn.commit()

        mock_rebuttal = "Dear Reviewers,\n\nThank you for the thoughtful review.\n\nRe: Missing ablation study\nWe have added an ablation study in Table 5.\n\nBest regards"

        with (
            patch(
                "research_harness.execution.llm_primitives._get_client"
            ) as mock_client,
            patch(
                "research_harness.execution.llm_primitives._client_chat",
                return_value=mock_rebuttal,
            ),
        ):
            mock_client.return_value = MagicMock()
            from research_harness.execution.llm_primitives import rebuttal_format

            result = rebuttal_format(db=db, topic_id=1)

        assert result.issues_addressed == 1
        assert "ablation" in result.rebuttal_text.lower()
        assert result.topic_id == 1

    def test_no_issues(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'empty')")
        conn.commit()

        from research_harness.execution.llm_primitives import rebuttal_format

        result = rebuttal_format(db=db, topic_id=1)
        assert result.issues_addressed == 0
        assert "No review issues" in result.rebuttal_text


# ---------------------------------------------------------------------------
# topic_export
# ---------------------------------------------------------------------------


class TestTopicExport:
    def test_generates_markdown_report(self, db, conn):
        conn.execute(
            "INSERT INTO topics (id, name, description) VALUES (1, 'auto-bidding', 'Research on auto bidding')"
        )
        _insert_paper(
            conn, 1, "DQN Bidding", year=2023, venue="NeurIPS", citation_count=50
        )
        _insert_paper(
            conn, 2, "PPO Bidding", year=2024, venue="ICML", citation_count=20
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'high')"
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import topic_export

        result = topic_export(db=db, topic_id=1)

        assert result.topic_name == "auto-bidding"
        assert result.paper_count == 2
        assert "auto-bidding" in result.markdown
        assert "DQN Bidding" in result.markdown
        assert "statistics" in result.sections
        assert "top_papers" in result.sections
        assert "timeline" in result.sections

    def test_with_taxonomy_and_contradictions(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Paper A", year=2024)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO taxonomy_nodes (id, topic_id, name, description) VALUES (1, 1, 'DQN', 'Deep Q-Network')"
        )
        conn.execute(
            "INSERT INTO normalized_claims (id, topic_id, paper_id, claim_text, method) VALUES (1, 1, 1, 'DQN is best', 'DQN')"
        )
        conn.execute(
            "INSERT INTO normalized_claims (id, topic_id, paper_id, claim_text, method) VALUES (2, 1, 1, 'PPO is best', 'PPO')"
        )
        conn.execute(
            "INSERT INTO contradictions (topic_id, claim_a_id, claim_b_id, conflict_reason, status) "
            "VALUES (1, 1, 2, 'Conflicting best method claims', 'candidate')"
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import topic_export

        result = topic_export(db=db, topic_id=1)

        assert "method_taxonomy" in result.sections
        assert "contradictions" in result.sections
        assert "DQN" in result.markdown
        assert "Conflicting" in result.markdown

    def test_nonexistent_topic(self, db, conn):
        from research_harness.primitives.analysis_impls import topic_export

        result = topic_export(db=db, topic_id=999)
        assert "not found" in result.markdown.lower()


# ---------------------------------------------------------------------------
# visualize_topic
# ---------------------------------------------------------------------------


class TestVisualizeTopic:
    def test_taxonomy_tree(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        conn.execute(
            "INSERT INTO taxonomy_nodes (id, topic_id, name) VALUES (1, 1, 'RL')"
        )
        conn.execute(
            "INSERT INTO taxonomy_nodes (id, topic_id, name, parent_id) VALUES (2, 1, 'DQN', 1)"
        )
        conn.execute(
            "INSERT INTO taxonomy_nodes (id, topic_id, name, parent_id) VALUES (3, 1, 'PPO', 1)"
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import visualize_topic

        result = visualize_topic(db=db, topic_id=1, viz_type="taxonomy_tree")

        assert result.viz_type == "taxonomy_tree"
        assert "graph TD" in result.mermaid_code
        assert "N1" in result.mermaid_code
        assert "N2" in result.mermaid_code
        assert result.node_count == 3

    def test_timeline(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Paper 2023", year=2023)
        _insert_paper(conn, 2, "Paper 2024", year=2024)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'high')"
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import visualize_topic

        result = visualize_topic(db=db, topic_id=1, viz_type="timeline")

        assert result.viz_type == "timeline"
        assert "gantt" in result.mermaid_code
        assert "2023" in result.mermaid_code
        assert "2024" in result.mermaid_code

    def test_paper_graph(self, db, conn):
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        _insert_paper(conn, 1, "Paper A")
        _insert_paper(conn, 2, "Paper B")
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'high')"
        )
        conn.execute(
            "INSERT INTO normalized_claims (id, topic_id, paper_id, claim_text, method) VALUES (1, 1, 1, 'A is good', 'DQN')"
        )
        conn.execute(
            "INSERT INTO normalized_claims (id, topic_id, paper_id, claim_text, method) VALUES (2, 1, 2, 'B is good', 'DQN')"
        )
        conn.commit()

        from research_harness.primitives.analysis_impls import visualize_topic

        result = visualize_topic(db=db, topic_id=1, viz_type="paper_graph")

        assert result.viz_type == "paper_graph"
        assert "graph LR" in result.mermaid_code
        assert result.node_count == 2

    def test_unknown_type(self, db, conn):
        from research_harness.primitives.analysis_impls import visualize_topic

        result = visualize_topic(db=db, topic_id=1, viz_type="unknown")
        assert result.mermaid_code == ""


# ---------------------------------------------------------------------------
# Spec registration
# ---------------------------------------------------------------------------


class TestPhase4SpecRegistration:
    def test_all_specs_registered(self):
        from research_harness.primitives import PRIMITIVE_REGISTRY

        for name in ("rebuttal_format", "topic_export", "visualize_topic"):
            assert name in PRIMITIVE_REGISTRY
