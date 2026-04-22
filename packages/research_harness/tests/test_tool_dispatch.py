"""Tests for auto_runner.tool_dispatch — tool name → execution mapping."""

from __future__ import annotations

import pytest

from research_harness.auto_runner.tool_dispatch import (
    dispatch,
    dispatch_stage_tools,
    _PRIMITIVE_TOOLS,
)
from research_harness.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.migrate()
    return d


@pytest.fixture()
def svc(db):
    from research_harness.orchestrator.service import OrchestratorService

    return OrchestratorService(db)


def test_primitive_tools_are_populated():
    assert "paper_search" in _PRIMITIVE_TOOLS
    assert "select_seeds" in _PRIMITIVE_TOOLS
    assert "expand_citations" in _PRIMITIVE_TOOLS
    assert len(_PRIMITIVE_TOOLS) >= 13


def test_unknown_tool_returns_error(db, svc):
    result = dispatch(
        "nonexistent_tool",
        db=db,
        svc=svc,
        topic_id=1,
        stage="init",
        context={},
    )
    assert not result.success
    assert "Unknown tool" in result.error


def test_orchestrator_status_dispatches(db, svc):
    # Create a topic first
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test-topic')")
        conn.commit()
    finally:
        conn.close()
    svc.resume_run(1)

    result = dispatch(
        "orchestrator_status",
        db=db,
        svc=svc,
        topic_id=1,
        stage="init",
        context={},
    )
    assert result.success
    assert "run" in result.output or "stage" in result.output


def test_paper_list_query(db, svc):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        conn.execute(
            "INSERT INTO papers (id, title, year) VALUES (1, 'Test Paper', 2024)"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()
    finally:
        conn.close()

    result = dispatch(
        "paper_list",
        db=db,
        svc=svc,
        topic_id=1,
        stage="build",
        context={},
    )
    assert result.success
    assert result.output["count"] == 1


def test_dispatch_stage_tools_runs_multiple(db, svc):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test-topic')")
        conn.commit()
    finally:
        conn.close()
    svc.resume_run(1)

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="init",
        tools=("orchestrator_status", "orchestrator_gate_check"),
        context={},
    )
    assert "summary" in result
    assert "Stage init" in result["summary"]
