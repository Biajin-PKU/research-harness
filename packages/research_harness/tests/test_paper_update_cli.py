"""Tests for `hub paper update` CLI command."""

from __future__ import annotations

import json

from research_harness.cli import main


def test_paper_update_pdf_path(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.70001",
            "--topic",
            "t1",
        ],
    )
    result = runner.invoke(
        main, ["--json", "paper", "update", "1", "--pdf-path", "/tmp/new.pdf"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["updated"] is True
    # Verify
    show = json.loads(runner.invoke(main, ["--json", "paper", "show", "1"]).output)
    assert show["paper"]["pdf_path"] == "/tmp/new.pdf"


def test_paper_update_status(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.70002",
            "--topic",
            "t1",
        ],
    )
    result = runner.invoke(
        main, ["--json", "paper", "update", "1", "--status", "annotated"]
    )
    assert result.exit_code == 0
    show = json.loads(runner.invoke(main, ["--json", "paper", "show", "1"]).output)
    assert show["paper"]["status"] == "annotated"


def test_paper_update_title_and_year(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "Old Title",
            "--arxiv-id",
            "2401.70003",
            "--topic",
            "t1",
        ],
    )
    result = runner.invoke(
        main,
        ["--json", "paper", "update", "1", "--title", "New Title", "--year", "2025"],
    )
    assert result.exit_code == 0
    show = json.loads(runner.invoke(main, ["--json", "paper", "show", "1"]).output)
    assert show["paper"]["title"] == "New Title"
    assert show["paper"]["year"] == 2025


def test_paper_update_nothing(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "paper",
            "ingest",
            "--title",
            "P1",
            "--arxiv-id",
            "2401.70004",
            "--topic",
            "t1",
        ],
    )
    result = runner.invoke(main, ["paper", "update", "1"])
    assert result.exit_code != 0  # nothing to update


def test_paper_update_nonexistent(runner):
    result = runner.invoke(main, ["paper", "update", "999", "--title", "X"])
    assert result.exit_code != 0
