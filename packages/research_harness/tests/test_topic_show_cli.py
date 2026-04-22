"""Tests for `hub topic show` CLI command."""

from __future__ import annotations

import json

from research_harness.cli import main


def test_topic_show_json(runner):
    runner.invoke(
        main,
        [
            "topic",
            "init",
            "t1",
            "-d",
            "My topic",
            "--venue",
            "ICML",
            "--deadline",
            "2026-06-01",
        ],
    )
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.50001",
            "--topic",
            "t1",
        ],
    )
    result = runner.invoke(main, ["--json", "topic", "show", "t1"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["name"] == "t1"
    assert data["description"] == "My topic"
    assert data["target_venue"] == "ICML"
    assert data["deadline"] == "2026-06-01"
    assert data["paper_count"] == 1


def test_topic_show_text(runner):
    runner.invoke(main, ["topic", "init", "t1", "-d", "Test"])
    result = runner.invoke(main, ["topic", "show", "t1"])
    assert result.exit_code == 0
    assert "t1" in result.output


def test_topic_show_nonexistent(runner):
    result = runner.invoke(main, ["topic", "show", "nope"])
    assert result.exit_code != 0
