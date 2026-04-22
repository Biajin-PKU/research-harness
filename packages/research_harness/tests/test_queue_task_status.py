"""Tests for paper queue showing task status per paper."""

from __future__ import annotations

import json

from research_harness.cli import main


def test_queue_shows_has_pending_task_false_when_no_tasks(runner):
    """Papers without tasks should show has_pending_task=False."""
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.90001",
            "--topic",
            "t1",
        ],
    )
    result = runner.invoke(main, ["--json", "paper", "queue", "--topic", "t1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["papers"][0]["has_pending_task"] is False


def test_queue_shows_has_pending_task_true_after_task_generate(runner):
    """After task generate, actionable papers should show has_pending_task=True."""
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.90002",
            "--topic",
            "t1",
        ],
    )
    runner.invoke(main, ["task", "generate", "--topic", "t1"])
    result = runner.invoke(main, ["--json", "paper", "queue", "--topic", "t1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["papers"][0]["has_pending_task"] is True


def test_queue_shows_has_pending_task_false_after_task_done(runner):
    """Once a task is marked done, has_pending_task should revert to False."""
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.90003",
            "--topic",
            "t1",
        ],
    )
    runner.invoke(main, ["task", "generate", "--topic", "t1"])
    # find task id
    tasks_result = runner.invoke(main, ["--json", "task", "list", "--topic", "t1"])
    tasks = json.loads(tasks_result.output)
    task_id = tasks[0]["id"]
    runner.invoke(main, ["task", "update", str(task_id), "--status", "done"])

    result = runner.invoke(main, ["--json", "paper", "queue", "--topic", "t1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["papers"][0]["has_pending_task"] is False
