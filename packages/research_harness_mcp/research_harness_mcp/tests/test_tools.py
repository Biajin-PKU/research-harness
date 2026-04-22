"""Tests for MCP tool definitions and execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.storage.db import Database


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    database.migrate()
    return database


@pytest.fixture()
def _env_db(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db.db_path))
    monkeypatch.setenv("RESEARCH_HUB_BACKEND", "local")


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


def test_list_tool_definitions() -> None:
    from research_harness_mcp.tools import list_tool_definitions

    tools = list_tool_definitions()
    names = {t.name for t in tools}

    # Primitives
    assert "paper_search" in names
    assert "claim_extract" in names
    assert "gap_detect" in names

    # Convenience
    assert "topic_list" in names
    assert "provenance_summary" in names
    assert "provenance_export" in names
    assert "advisory_check" in names

    # Paperindex
    assert "paperindex_search" in names


def test_tool_definitions_have_schemas() -> None:
    from research_harness_mcp.tools import list_tool_definitions

    for tool in list_tool_definitions():
        assert tool.name
        assert tool.description
        assert tool.inputSchema is not None


# ---------------------------------------------------------------------------
# HarnessResponse envelope — all tool results now have these keys
# ---------------------------------------------------------------------------

ENVELOPE_KEYS = {
    "status",
    "summary",
    "output",
    "next_actions",
    "artifacts",
    "recovery_hint",
    "primitive",
    "backend",
    "model_used",
    "cost_usd",
    "session_advisory",
}


def _assert_envelope(result: dict) -> None:
    """Assert result conforms to HarnessResponse envelope."""
    assert ENVELOPE_KEYS.issubset(result.keys()), (
        f"Missing keys: {ENVELOPE_KEYS - result.keys()}"
    )
    assert result["status"] in ("success", "error", "warning")
    assert isinstance(result["summary"], str)
    assert isinstance(result["next_actions"], list)
    assert isinstance(result["artifacts"], list)


# ---------------------------------------------------------------------------
# Primitive tool execution
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_env_db")
def test_execute_paper_search(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
            ("Attention Is All You Need", "10.1000/attn", "1706.03762", "s2-attn"),
        )
        conn.commit()
    finally:
        conn.close()

    result = execute_tool("paper_search", {"query": "attention"})
    _assert_envelope(result)
    assert result["status"] == "success"
    assert result["output"]["papers"]


@pytest.mark.usefixtures("_env_db")
def test_execute_unknown_tool() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("nonexistent_tool", {})
    _assert_envelope(result)
    assert result["status"] == "error"
    assert "Unknown tool" in result["output"]["error"]


# ---------------------------------------------------------------------------
# Convenience tool execution
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_env_db")
def test_topic_list_empty(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("topic_list", {})
    _assert_envelope(result)
    assert result["status"] == "success"
    assert result["output"]["topics"] == []


@pytest.mark.usefixtures("_env_db")
def test_topic_list_with_data(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, status) VALUES (?, ?, ?)",
            ("auto-bidding", "Auction bidding strategies", "active"),
        )
        conn.commit()
    finally:
        conn.close()

    result = execute_tool("topic_list", {})
    _assert_envelope(result)
    assert len(result["output"]["topics"]) == 1
    assert result["output"]["topics"][0]["name"] == "auto-bidding"


@pytest.mark.usefixtures("_env_db")
def test_topic_show_not_found() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("topic_show", {"name": "nonexistent"})
    _assert_envelope(result)
    assert result["status"] == "error"


@pytest.mark.usefixtures("_env_db")
def test_provenance_summary(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("provenance_summary", {})
    _assert_envelope(result)
    assert result["status"] == "success"
    assert result["output"]["total_operations"] == 0


@pytest.mark.usefixtures("_env_db")
def test_provenance_export(db: Database) -> None:
    from research_harness.primitives.types import PrimitiveResult
    from research_harness.provenance.recorder import ProvenanceRecorder
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, status) VALUES (?, ?, ?)",
            ("prov-topic", "topic for provenance export", "active"),
        )
        conn.commit()
        topic_id = conn.execute(
            "SELECT id FROM topics WHERE name = ?", ("prov-topic",)
        ).fetchone()[0]
    finally:
        conn.close()

    recorder = ProvenanceRecorder(db)
    recorder.record(
        PrimitiveResult(
            primitive="paper_ingest",
            success=True,
            output={"paper_id": 1},
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:01+00:00",
            backend="local",
            model_used="",
            cost_usd=0.0,
        ),
        input_kwargs={"source": "10.1000/test"},
        topic_id=topic_id,
    )

    result = execute_tool("provenance_export", {"topic_id": topic_id, "format": "json"})
    _assert_envelope(result)
    assert result["output"]["format"] == "json"
    assert len(result["output"]["records"]) == 1
    assert result["output"]["records"][0]["primitive"] == "paper_ingest"
    assert result["output"]["records"][0]["topic_id"] == topic_id


@pytest.mark.usefixtures("_env_db")
def test_paper_list_empty() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("paper_list", {})
    _assert_envelope(result)
    assert result["output"]["papers"] == []


@pytest.mark.usefixtures("_env_db")
def test_task_list_empty() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("task_list", {})
    _assert_envelope(result)
    assert result["output"]["tasks"] == []


@pytest.mark.usefixtures("_env_db")
def test_advisory_check_list_and_acknowledge(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, ?, ?, ?)",
            ("sparse-topic", "topic with low coverage", "active"),
        )
        conn.execute(
            "INSERT INTO papers (title, year, authors, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "Classic Bidding Paper",
                2021,
                '["Alice", "Alice", "Bob"]',
                "10.1000/sparse-1",
                "2401.00001",
                "s2-sparse-1",
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()
    finally:
        conn.close()

    checked = execute_tool("advisory_check", {"topic_id": 1})
    _assert_envelope(checked)
    assert checked["status"] == "success"
    assert checked["output"]["count"] >= 1

    listed = execute_tool("advisory_list", {"topic_id": 1})
    _assert_envelope(listed)
    advisories = listed["output"]["advisories"]
    assert advisories
    advisory_id = advisories[0]["id"]

    acked = execute_tool("advisory_acknowledge", {"advisory_id": advisory_id})
    _assert_envelope(acked)
    assert acked["output"]["advisory"]["acknowledged"] is True


@pytest.mark.usefixtures("_env_db")
def test_orchestrator_stale_artifact_tools(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, ?, ?, ?)",
            ("orch-topic", "topic for orchestrator", "active"),
        )
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, ?, ?)",
            ("orch-project", "project for orchestrator"),
        )
        conn.commit()
    finally:
        conn.close()

    recorded = execute_tool(
        "orchestrator_record_artifact",
        {
            "topic_id": 1,
            "stage": "build",
            "artifact_type": "literature_map",
            "payload": {"v": 1},
        },
    )
    _assert_envelope(recorded)
    artifact_id = recorded["output"]["artifact_id"]

    marked = execute_tool(
        "orchestrator_mark_artifact_stale",
        {"artifact_id": artifact_id, "reason": "source changed"},
    )
    _assert_envelope(marked)
    assert artifact_id in marked["output"]["stale_ids"]

    listed = execute_tool("orchestrator_list_stale_artifacts", {"topic_id": 1})
    _assert_envelope(listed)
    assert listed["output"]["count"] == 1
    assert listed["output"]["artifacts"][0]["id"] == artifact_id

    cleared = execute_tool(
        "orchestrator_clear_artifact_stale", {"artifact_id": artifact_id}
    )
    _assert_envelope(cleared)
    assert cleared["output"]["success"] is True


# ---------------------------------------------------------------------------
# Harness features — next_actions and recovery_hint
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_env_db")
def test_paper_search_has_next_actions(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
            ("Test Paper", "10.1000/test", "0000.00000", "s2-test"),
        )
        conn.commit()
    finally:
        conn.close()

    result = execute_tool("paper_search", {"query": "test"})
    assert result["status"] == "success"
    assert len(result["next_actions"]) > 0
    assert result["summary"]  # non-empty summary


@pytest.mark.usefixtures("_env_db")
def test_session_advisory_after_consecutive_topic_ops(db: Database) -> None:
    from research_harness_mcp import tools as tools_module
    from research_harness_mcp.tools import execute_tool

    tools_module._SESSION_ACTIVITY["last_topic_id"] = None
    tools_module._SESSION_ACTIVITY["streak"] = 0

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, ?, ?, ?)",
            ("advisory-topic", "topic for session advisory", "active"),
        )
        conn.commit()
    finally:
        conn.close()

    for query in ("query one", "query two", "query three"):
        result = execute_tool("search_query_add", {"topic_id": 1, "query": query})
        _assert_envelope(result)

    assert "Detected 3 consecutive operations on topic 1" in result["session_advisory"]


@pytest.mark.usefixtures("_env_db")
def test_error_has_recovery_hint() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("nonexistent_tool", {})
    assert result["status"] == "error"
    assert result["recovery_hint"]  # non-empty recovery hint
