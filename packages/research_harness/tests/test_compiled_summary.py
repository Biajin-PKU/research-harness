"""Tests for compiled summary cache infrastructure."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from research_harness.execution.compiled_summary import (
    _compute_source_hash,
    ensure_compiled_summary,
    format_compiled_as_text,
    format_compiled_for_context,
    get_topic_summary_cached,
)


SAMPLE_COMPILED = {
    "overview": "This paper proposes method X for budget pacing.",
    "methods": ["dual decomposition", "online learning"],
    "claims": [
        {
            "claim": "Method X outperforms baseline by 15%",
            "evidence": "Table 3",
            "strength": "strong",
        }
    ],
    "limitations": ["Assumes stationary distributions"],
    "metrics": [
        {"dataset": "iPinYou", "metric": "CTR", "value": "0.85", "baseline": "0.74"}
    ],
    "relations": ["extends Paper #10", "contradicts Paper #20 on convergence"],
}

# The LLM functions are imported lazily inside ensure_compiled_summary and
# get_topic_summary_cached from llm_primitives, so we must patch at the
# llm_primitives module level.
_P_CLIENT = "research_harness.execution.llm_primitives._get_client"
_P_CHAT = "research_harness.execution.llm_primitives._client_chat"
_P_JSON = "research_harness.execution.llm_primitives._parse_json"


@pytest.fixture(autouse=True)
def _disable_fk(conn):
    """Disable FK checks so test helpers can insert without full topic/paper chains."""
    conn.execute("PRAGMA foreign_keys = OFF")
    yield
    conn.execute("PRAGMA foreign_keys = ON")


def _insert_paper(conn, paper_id=1, title="Test Paper", abstract="A" * 200):
    conn.execute(
        "INSERT OR IGNORE INTO papers (id, title, abstract, status, doi, arxiv_id, s2_id) "
        "VALUES (?, ?, ?, 'meta_only', ?, ?, ?)",
        (
            paper_id,
            title,
            abstract,
            f"doi_{paper_id}",
            f"arxiv_{paper_id}",
            f"s2_{paper_id}",
        ),
    )
    conn.commit()


def _insert_topic(conn, topic_id=1, name="test-topic"):
    conn.execute(
        "INSERT OR IGNORE INTO topics (id, name) VALUES (?, ?)",
        (topic_id, name),
    )
    conn.commit()


def _link_paper_topic(conn, paper_id, topic_id, relevance="high"):
    conn.execute(
        "INSERT OR IGNORE INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
        (paper_id, topic_id, relevance),
    )
    conn.commit()


def _insert_annotation(conn, paper_id, section, content):
    conn.execute(
        "INSERT OR REPLACE INTO paper_annotations (paper_id, section, content, source) "
        "VALUES (?, ?, ?, 'test')",
        (paper_id, section, content),
    )
    conn.commit()


# --- Hash tests ---


class TestSourceHash:
    def test_deterministic(self, db, conn):
        _insert_paper(conn)
        _insert_annotation(conn, 1, "summary", "This is a test summary.")
        h1 = _compute_source_hash(conn, 1)
        h2 = _compute_source_hash(conn, 1)
        assert h1 == h2
        assert len(h1) == 64

    def test_changes_on_annotation_update(self, db, conn):
        _insert_paper(conn)
        _insert_annotation(conn, 1, "summary", "Version 1")
        h1 = _compute_source_hash(conn, 1)
        _insert_annotation(conn, 1, "summary", "Version 2")
        h2 = _compute_source_hash(conn, 1)
        assert h1 != h2

    def test_empty_for_nonexistent(self, db, conn):
        h = _compute_source_hash(conn, 9999)
        assert h


# --- ensure_compiled_summary tests ---


class TestEnsureCompiledSummary:
    def test_cache_hit(self, db, conn):
        _insert_paper(conn)
        _insert_annotation(
            conn,
            1,
            "summary",
            "Test summary content about budget pacing methods for online advertising platforms with dual decomposition and reinforcement learning approaches.",
        )
        source_hash = _compute_source_hash(conn, 1)
        conn.execute(
            "UPDATE papers SET compiled_summary = ?, compiled_from_hash = ? WHERE id = 1",
            (json.dumps(SAMPLE_COMPILED), source_hash),
        )
        conn.commit()

        # Should return cached without calling LLM
        with patch(_P_CLIENT) as mock:
            result = ensure_compiled_summary(db, 1)
            mock.assert_not_called()
        assert result["overview"] == SAMPLE_COMPILED["overview"]

    def test_cache_miss_calls_llm(self, db, conn):
        _insert_paper(conn)
        _insert_annotation(
            conn,
            1,
            "summary",
            "Test summary about budget pacing methods for online advertising platforms with dual decomposition and reinforcement learning approaches for constrained optimization.",
        )

        with patch(_P_CLIENT, return_value=MagicMock()):
            with patch(_P_CHAT, return_value=json.dumps(SAMPLE_COMPILED)):
                with patch(_P_JSON, return_value=SAMPLE_COMPILED):
                    result = ensure_compiled_summary(db, 1)

        assert result["overview"] == SAMPLE_COMPILED["overview"]
        row = conn.execute(
            "SELECT compiled_summary FROM papers WHERE id = 1"
        ).fetchone()
        assert row["compiled_summary"]
        stored = json.loads(row["compiled_summary"])
        assert stored["overview"] == SAMPLE_COMPILED["overview"]

    def test_invalidation_on_hash_change(self, db, conn):
        _insert_paper(conn)
        _insert_annotation(
            conn,
            1,
            "summary",
            "Original summary about budget pacing methods for online advertising platforms with dual decomposition approaches.",
        )
        old_hash = _compute_source_hash(conn, 1)
        conn.execute(
            "UPDATE papers SET compiled_summary = ?, compiled_from_hash = ? WHERE id = 1",
            (json.dumps(SAMPLE_COMPILED), old_hash),
        )
        conn.commit()

        _insert_annotation(
            conn,
            1,
            "summary",
            "Updated summary with new content about reinforcement learning approaches for constrained budget optimization in real-time bidding systems.",
        )

        new_compiled = {**SAMPLE_COMPILED, "overview": "Updated overview"}
        with patch(_P_CLIENT, return_value=MagicMock()):
            with patch(_P_CHAT, return_value=json.dumps(new_compiled)):
                with patch(_P_JSON, return_value=new_compiled):
                    result = ensure_compiled_summary(db, 1)

        assert result["overview"] == "Updated overview"

    def test_no_source_data_returns_empty(self, db, conn):
        _insert_paper(conn, abstract="Short")
        result = ensure_compiled_summary(db, 1)
        assert result == {}

    def test_abstract_only_compiles(self, db, conn):
        _insert_paper(conn, abstract="A" * 200)

        with patch(_P_CLIENT, return_value=MagicMock()):
            with patch(_P_CHAT, return_value=json.dumps(SAMPLE_COMPILED)):
                with patch(_P_JSON, return_value=SAMPLE_COMPILED):
                    result = ensure_compiled_summary(db, 1)
        assert result.get("overview")

    def test_llm_failure_returns_empty(self, db, conn):
        _insert_paper(conn)
        _insert_annotation(
            conn,
            1,
            "summary",
            "Test summary content about budget pacing methods for online advertising platforms with dual decomposition and reinforcement learning approaches.",
        )

        with patch(_P_CLIENT, return_value=MagicMock()):
            with patch(_P_CHAT, side_effect=RuntimeError("LLM down")):
                result = ensure_compiled_summary(db, 1)
        assert result == {}
        row = conn.execute(
            "SELECT compiled_summary FROM papers WHERE id = 1"
        ).fetchone()
        assert row["compiled_summary"] == ""

    def test_nonexistent_paper(self, db):
        result = ensure_compiled_summary(db, 9999)
        assert result == {}


# --- Format tests ---


class TestFormatCompiled:
    def test_full_format(self):
        text = format_compiled_as_text(SAMPLE_COMPILED)
        assert "[Overview]" in text
        assert "[Methods]" in text
        assert "[Claims]" in text
        assert "[Limitations]" in text
        assert "[Metrics]" in text
        assert "[Relations]" in text
        assert "dual decomposition" in text
        assert "iPinYou" in text

    def test_empty_returns_empty(self):
        assert format_compiled_as_text({}) == ""

    def test_partial_fields(self):
        text = format_compiled_as_text({"overview": "Just an overview"})
        assert "[Overview]" in text
        assert "[Methods]" not in text

    def test_context_format_short(self):
        ctx = format_compiled_for_context(SAMPLE_COMPILED)
        assert len(ctx) < 500
        assert "budget pacing" in ctx


# --- Topic summary tests ---


class TestTopicSummaryCached:
    def _setup_topic_with_papers(self, conn, n=5):
        _insert_topic(conn)
        for i in range(1, n + 1):
            _insert_paper(conn, paper_id=i, title=f"Paper {i}", abstract="A" * 200)
            _link_paper_topic(conn, i, 1)
            conn.execute(
                "UPDATE papers SET citation_count = ?, year = ? WHERE id = ?",
                (100 - i, 2020 + i, i),
            )
        conn.commit()

    def test_cache_hit(self, db, conn):
        self._setup_topic_with_papers(conn, 3)
        conn.execute(
            "INSERT INTO topic_summaries (topic_id, summary, paper_count, paper_ids_json) "
            "VALUES (1, 'Cached overview', 3, '[1,2,3]')",
        )
        conn.commit()

        summary, ids = get_topic_summary_cached(db, 1)
        assert summary == "Cached overview"
        assert ids == [1, 2, 3]

    def test_staleness_triggers_recompile(self, db, conn):
        self._setup_topic_with_papers(conn, 3)
        conn.execute(
            "INSERT INTO topic_summaries (topic_id, summary, paper_count, paper_ids_json) "
            "VALUES (1, 'Old overview', 2, '[1,2]')",
        )
        conn.commit()

        with patch(
            "research_harness.execution.compiled_summary.ensure_compiled_summary",
            return_value=SAMPLE_COMPILED,
        ):
            with patch(_P_CLIENT, return_value=MagicMock()):
                with patch(
                    _P_CHAT, return_value=json.dumps({"overview": "New overview"})
                ):
                    with patch(_P_JSON, return_value={"overview": "New overview"}):
                        summary, ids = get_topic_summary_cached(db, 1)

        assert summary == "New overview"
        assert len(ids) == 3

    def test_empty_topic(self, db, conn):
        _insert_topic(conn)
        summary, ids = get_topic_summary_cached(db, 1)
        assert "no papers" in summary
        assert ids == []

    def test_contradiction_sampling(self, db, conn):
        _insert_topic(conn)
        for i in range(1, 26):
            _insert_paper(conn, paper_id=i, title=f"Paper {i}", abstract="A" * 200)
            _link_paper_topic(conn, i, 1)
            conn.execute(
                "UPDATE papers SET citation_count = ?, year = ? WHERE id = ?",
                (100 - i, 2020, i),
            )
        _insert_paper(
            conn,
            paper_id=30,
            title="Revisiting budget pacing: failures and pitfalls",
            abstract="A" * 200,
        )
        _link_paper_topic(conn, 30, 1)
        conn.execute("UPDATE papers SET citation_count = 0, year = 2025 WHERE id = 30")
        conn.commit()

        with patch(
            "research_harness.execution.compiled_summary.ensure_compiled_summary",
            return_value=SAMPLE_COMPILED,
        ):
            with patch(_P_CLIENT, return_value=MagicMock()):
                with patch(_P_CHAT, return_value=json.dumps({"overview": "Overview"})):
                    with patch(_P_JSON, return_value={"overview": "Overview"}):
                        summary, ids = get_topic_summary_cached(db, 1)

        assert 30 in ids


# --- Integration with _get_paper_text ---


class TestGetPaperTextIntegration:
    def test_uses_compiled_summary(self, db, conn):
        _insert_paper(conn)
        conn.execute(
            "UPDATE papers SET compiled_summary = ? WHERE id = 1",
            (json.dumps(SAMPLE_COMPILED),),
        )
        conn.commit()

        from research_harness.execution.llm_primitives import _get_paper_text

        title, text = _get_paper_text(db, 1)
        assert "[Overview]" in text
        assert "budget pacing" in text

    def test_fallback_to_annotations(self, db, conn):
        _insert_paper(conn)
        _insert_annotation(conn, 1, "summary", "Annotation-based summary.")

        from research_harness.execution.llm_primitives import _get_paper_text

        title, text = _get_paper_text(db, 1)
        assert "Annotation-based summary" in text
