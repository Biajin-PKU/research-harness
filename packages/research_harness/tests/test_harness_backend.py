from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from research_harness.execution.harness import ResearchHarnessBackend


@pytest.fixture
def harness(db):
    with patch("research_harness.execution.harness.resolve_llm_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(
            provider="kimi",
            model="kimi-test",
            api_key="fake-key",
        )
        backend = ResearchHarnessBackend(db=db)
    return backend


def _insert_paper(conn, title: str, summary: str, suffix: str) -> int:
    conn.execute(
        "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
        (title, f"10.1000/{suffix}", f"arxiv-{suffix}", f"s2-{suffix}"),
    )
    paper_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO paper_annotations (paper_id, section, content) VALUES (?, ?, ?)",
        (paper_id, "summary", summary),
    )
    conn.commit()
    return paper_id


class TestHarnessInfo:
    def test_info_name(self, harness):
        info = harness.get_info()
        assert info.name == "research_harness"

    def test_supports_llm_primitives(self, harness):
        assert harness.supports("paper_summarize")
        assert harness.supports("claim_extract")
        assert harness.supports("gap_detect")
        assert harness.supports("baseline_identify")
        assert harness.supports("section_draft")
        assert harness.supports("consistency_check")

    def test_supports_local_primitives(self, harness):
        assert harness.supports("paper_search")
        assert harness.supports("paper_ingest")
        assert harness.supports("evidence_link")

    def test_cost_estimate(self, harness):
        assert harness.estimate_cost("paper_summarize") > 0
        assert harness.estimate_cost("paper_search") == 0.0


class TestHarnessLocalExecution:
    def test_paper_search_via_harness(self, harness, db):
        conn = db.connect()
        try:
            _insert_paper(conn, "Test Search Paper", "Searchable paper content.", "search-paper")
        finally:
            conn.close()

        result = harness.execute("paper_search", query="search")
        assert result.success
        assert result.backend == "research_harness"
        assert result.output.papers[0].title == "Test Search Paper"

    def test_unknown_primitive(self, harness):
        result = harness.execute("nonexistent_primitive")
        assert not result.success
        assert "Unknown primitive" in result.error


class TestHarnessLLMExecution:
    @patch("research_harness.execution.llm_primitives._get_client")
    def test_paper_summarize(self, mock_get_client, harness, db):
        conn = db.connect()
        try:
            paper_id = _insert_paper(
                conn,
                "Test Paper",
                "This paper studies attention mechanisms in transformers.",
                "summary-paper",
            )
        finally:
            conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps(
            {"summary": "This paper studies attention.", "confidence": 0.85}
        )
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute("paper_summarize", paper_id=paper_id)
        assert result.success
        assert result.backend == "research_harness"
        assert "attention" in result.output.summary.lower()
        assert result.output.confidence == 0.85

    @patch("research_harness.execution.llm_primitives._get_client")
    def test_claim_extract(self, mock_get_client, harness, db):
        conn = db.connect()
        try:
            paper_id = _insert_paper(
                conn,
                "Paper A",
                "We show that method X outperforms Y by 10%.",
                "claim-paper",
            )
            conn.execute("INSERT INTO topics (name) VALUES (?)", ("test-topic",))
            topic_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
                (paper_id, topic_id),
            )
            conn.commit()
        finally:
            conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps(
            {
                "claims": [
                    {
                        "content": "Method X outperforms Y by 10%",
                        "evidence_type": "empirical",
                        "confidence": 0.9,
                    }
                ]
            }
        )
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute("claim_extract", paper_ids=[paper_id], topic_id=topic_id)
        assert result.success
        assert len(result.output.claims) == 1
        assert "outperforms" in result.output.claims[0].content

    @patch("research_harness.execution.llm_primitives._get_client")
    def test_gap_detect(self, mock_get_client, harness, db):
        conn = db.connect()
        try:
            paper_id = _insert_paper(
                conn,
                "Gap Paper",
                "Existing work evaluates method A but not domain X.",
                "gap-paper",
            )
            conn.execute("INSERT INTO topics (name) VALUES (?)", ("gaps-topic",))
            topic_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
                (paper_id, topic_id),
            )
            conn.commit()
        finally:
            conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps(
            {
                "gaps": [
                    {
                        "description": "No study on domain X",
                        "gap_type": "empirical",
                        "severity": "high",
                    }
                ]
            }
        )
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute("gap_detect", topic_id=topic_id)
        assert result.success
        assert len(result.output.gaps) == 1
        assert result.output.gaps[0].related_paper_ids == [paper_id]

    def test_no_api_key_error(self, db):
        with patch("research_harness.execution.harness.resolve_llm_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                provider="openai",
                model="test-model",
                api_key="",
            )
            backend = ResearchHarnessBackend(db=db)

        result = backend.execute("paper_summarize", paper_id=1)
        assert not result.success
        assert "provider" in result.error.lower()

    @patch("research_harness.execution.llm_primitives._get_client")
    def test_llm_error_handled(self, mock_get_client, harness, db):
        conn = db.connect()
        try:
            paper_id = _insert_paper(conn, "Err Paper", "Some text.", "err-paper")
        finally:
            conn.close()

        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("API timeout")
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute("paper_summarize", paper_id=paper_id)
        assert not result.success
        assert "timeout" in result.error.lower()

    @patch("research_harness.execution.llm_primitives._get_client")
    def test_malformed_json_handled(self, mock_get_client, harness, db):
        conn = db.connect()
        try:
            paper_id = _insert_paper(
                conn,
                "Bad JSON Paper",
                "Abstract text here.",
                "bad-json-paper",
            )
        finally:
            conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = "This is not JSON, just a plain summary."
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute("paper_summarize", paper_id=paper_id)
        assert result.success
        assert "plain summary" in result.output.summary


class TestHarnessWithTracked:
    @patch("research_harness.execution.llm_primitives._get_client")
    def test_provenance_recorded(self, mock_get_client, harness, db):
        from research_harness.execution.tracked import TrackedBackend
        from research_harness.provenance.recorder import ProvenanceRecorder

        conn = db.connect()
        try:
            paper_id = _insert_paper(
                conn,
                "Tracked Paper",
                "Some abstract.",
                "tracked-paper",
            )
        finally:
            conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps(
            {"summary": "Tracked summary.", "confidence": 0.7}
        )
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        tracked = TrackedBackend(harness, ProvenanceRecorder(db))
        result = tracked.execute("paper_summarize", paper_id=paper_id)
        assert result.success

        records = ProvenanceRecorder(db).list_records(backend="research_harness")
        assert len(records) == 1
        assert records[0].primitive == "paper_summarize"
