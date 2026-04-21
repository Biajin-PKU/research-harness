"""Tests for `hub topic overview` CLI command."""
from __future__ import annotations

import json

from click.testing import CliRunner

from research_harness.cli import main


def _setup_topic_with_mixed_papers(runner: CliRunner, topic: str = "dl-opt") -> None:
    runner.invoke(main, ["topic", "init", topic])
    # Paper with PDF (needs annotation)
    runner.invoke(main, [
        "paper", "ingest", "--title", "Paper A", "--arxiv-id", "2401.10001",
        "--pdf-path", "/tmp/a.pdf", "--topic", topic,
    ])
    # Paper without PDF
    runner.invoke(main, [
        "paper", "ingest", "--title", "Paper B", "--arxiv-id", "2401.10002",
        "--topic", topic,
    ])
    # Add a task
    runner.invoke(main, [
        "task", "add", "--topic", topic, "--title", "Read paper A",
    ])


def test_topic_overview_json(runner):
    _setup_topic_with_mixed_papers(runner)
    result = runner.invoke(main, ["--json", "topic", "overview", "dl-opt"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["topic"] == "dl-opt"
    assert data["paper_count"] == 2
    assert "queue_summary" in data
    assert "task_summary" in data
    assert data["task_summary"]["total"] >= 1


def test_topic_overview_text(runner):
    _setup_topic_with_mixed_papers(runner)
    result = runner.invoke(main, ["topic", "overview", "dl-opt"])
    assert result.exit_code == 0
    assert "dl-opt" in result.output
    assert "papers" in result.output.lower() or "paper" in result.output.lower()


def test_topic_overview_nonexistent(runner):
    result = runner.invoke(main, ["topic", "overview", "nope"])
    assert result.exit_code != 0
