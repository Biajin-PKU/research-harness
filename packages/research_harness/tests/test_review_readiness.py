"""Tests for review readiness detection in topic overview and task generate."""
from __future__ import annotations

import json

from research_harness.cli import main


def _setup_topic_all_done(runner, topic: str = "t1") -> None:
    """Create a topic where all papers are actionable but tasks are all done."""
    runner.invoke(main, ["topic", "init", topic])
    # Paper without PDF → generates task
    runner.invoke(main, ["paper", "ingest", "--title", "P1", "--arxiv-id", "2401.80001", "--topic", topic])
    runner.invoke(main, ["task", "generate", "--topic", topic])
    # Mark all tasks as done
    tasks_result = runner.invoke(main, ["--json", "task", "list", "--topic", topic])
    for t in json.loads(tasks_result.output):
        runner.invoke(main, ["task", "update", str(t["id"]), "--status", "done"])


def _setup_topic_with_pending(runner, topic: str = "t2") -> None:
    runner.invoke(main, ["topic", "init", topic])
    runner.invoke(main, ["paper", "ingest", "--title", "P2", "--arxiv-id", "2401.80002", "--topic", topic])
    runner.invoke(main, ["task", "generate", "--topic", topic])


def test_topic_overview_shows_review_ready_when_all_tasks_done(runner):
    _setup_topic_all_done(runner)
    result = runner.invoke(main, ["--json", "topic", "overview", "t1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["review_ready"] is True


def test_topic_overview_shows_review_not_ready_with_pending_tasks(runner):
    _setup_topic_with_pending(runner)
    result = runner.invoke(main, ["--json", "topic", "overview", "t2"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["review_ready"] is False


def test_task_generate_signals_review_ready_when_no_actionable_papers(runner):
    """When task generate creates 0 tasks and all existing tasks are done, review_ready=True."""
    runner.invoke(main, ["topic", "init", "t3"])
    # Manually add a task and mark it done (no actionable papers)
    runner.invoke(main, ["task", "add", "--topic", "t3", "--title", "Manual task"])
    tasks = json.loads(runner.invoke(main, ["--json", "task", "list", "--topic", "t3"]).output)
    runner.invoke(main, ["task", "update", str(tasks[0]["id"]), "--status", "done"])
    result = runner.invoke(main, ["--json", "task", "generate", "--topic", "t3"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["created_count"] == 0
    assert data["review_ready"] is True


def test_task_generate_not_review_ready_with_pending_tasks(runner):
    _setup_topic_with_pending(runner, "t4")
    # tasks are pending from generate
    result = runner.invoke(main, ["--json", "task", "generate", "--topic", "t4"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["review_ready"] is False


def test_topic_overview_text_includes_review_hint(runner):
    _setup_topic_all_done(runner)
    result = runner.invoke(main, ["topic", "overview", "t1"])
    assert result.exit_code == 0
    assert "review" in result.output.lower()
