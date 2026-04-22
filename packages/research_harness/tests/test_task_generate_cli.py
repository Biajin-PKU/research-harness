"""Tests for `hub task generate` CLI command."""

from __future__ import annotations

import json

from click.testing import CliRunner

from research_harness.cli import main


def _setup_topic_with_papers(runner: CliRunner, topic: str = "llm-safety") -> dict:
    """Create a topic with papers in various states for task generation testing."""
    runner.invoke(main, ["topic", "init", topic])

    # Paper 1: has PDF + all annotations + card + note → ready (no task needed)
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "Fully Ready Paper",
            "--arxiv-id",
            "2401.00001",
            "--pdf-path",
            "/tmp/ready.pdf",
            "--topic",
            topic,
        ],
    )

    # Paper 2: has PDF but missing annotations → needs annotate task
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "Needs Annotation Paper",
            "--arxiv-id",
            "2401.00002",
            "--pdf-path",
            "/tmp/needs_annotate.pdf",
            "--topic",
            topic,
        ],
    )

    # Paper 3: no PDF → needs attach_pdf task
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "No PDF Paper",
            "--arxiv-id",
            "2401.00003",
            "--topic",
            topic,
        ],
    )

    return {"topic": topic}


def test_task_generate_creates_tasks_for_actionable_papers(runner):
    """task generate should create tasks for papers that need work."""
    _setup_topic_with_papers(runner)
    result = runner.invoke(
        main, ["--json", "task", "generate", "--topic", "llm-safety"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["created_count"] >= 2  # at least annotate + attach_pdf
    assert data["skipped_count"] >= 0
    # Verify tasks exist
    tasks_result = runner.invoke(
        main, ["--json", "task", "list", "--topic", "llm-safety"]
    )
    tasks = json.loads(tasks_result.output)
    assert len(tasks) >= 2
    titles = [t["title"] for t in tasks]
    assert any("Needs Annotation" in t for t in titles)
    assert any("No PDF" in t for t in titles)


def test_task_generate_skips_duplicates(runner):
    """Running task generate twice should not create duplicate tasks."""
    _setup_topic_with_papers(runner)
    result1 = runner.invoke(
        main, ["--json", "task", "generate", "--topic", "llm-safety"]
    )
    assert result1.exit_code == 0
    data1 = json.loads(result1.output)
    created_first = data1["created_count"]

    result2 = runner.invoke(
        main, ["--json", "task", "generate", "--topic", "llm-safety"]
    )
    assert result2.exit_code == 0
    data2 = json.loads(result2.output)
    assert data2["created_count"] == 0
    assert data2["skipped_count"] == created_first


def test_task_generate_respects_dry_run(runner):
    """--dry-run should show what would be created without writing."""
    _setup_topic_with_papers(runner)
    result = runner.invoke(
        main, ["--json", "task", "generate", "--topic", "llm-safety", "--dry-run"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["dry_run"] is True
    assert len(data["proposed_tasks"]) >= 2
    # Verify no actual tasks created
    tasks_result = runner.invoke(
        main, ["--json", "task", "list", "--topic", "llm-safety"]
    )
    tasks = json.loads(tasks_result.output)
    assert len(tasks) == 0


def test_task_generate_missing_topic(runner):
    """task generate with nonexistent topic should fail."""
    result = runner.invoke(main, ["task", "generate", "--topic", "nonexistent"])
    assert result.exit_code != 0


def test_task_generate_text_output(runner):
    """Non-JSON output should be human-readable."""
    _setup_topic_with_papers(runner)
    result = runner.invoke(main, ["task", "generate", "--topic", "llm-safety"])
    assert result.exit_code == 0
    assert "generated" in result.output.lower() or "created" in result.output.lower()
