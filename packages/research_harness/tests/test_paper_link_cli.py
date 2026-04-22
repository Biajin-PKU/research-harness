"""Tests for `hub paper link` CLI command."""

from __future__ import annotations

import json

from research_harness.cli import main


def test_paper_link_to_new_topic(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(main, ["topic", "init", "t2"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.60001",
            "--topic",
            "t1",
        ],
    )
    result = runner.invoke(
        main, ["--json", "paper", "link", "1", "--topic", "t2", "--relevance", "high"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["linked"] is True
    assert data["topic"] == "t2"
    assert data["relevance"] == "high"


def test_paper_link_updates_relevance(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.60002",
            "--topic",
            "t1",
            "--relevance",
            "low",
        ],
    )
    result = runner.invoke(
        main, ["--json", "paper", "link", "1", "--topic", "t1", "--relevance", "high"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["relevance"] == "high"


def test_paper_link_nonexistent_paper(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    result = runner.invoke(main, ["paper", "link", "999", "--topic", "t1"])
    assert result.exit_code != 0


def test_paper_link_nonexistent_topic(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.60003",
            "--topic",
            "t1",
        ],
    )
    result = runner.invoke(main, ["paper", "link", "1", "--topic", "nope"])
    assert result.exit_code != 0
