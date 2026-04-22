"""Lifecycle tests for topic, project, and search CLI commands."""

from __future__ import annotations

import json

from research_harness.cli import main


def test_topic_update_json(runner):
    runner.invoke(main, ["topic", "init", "t1", "-d", "Old desc", "--venue", "ICML"])
    result = runner.invoke(
        main,
        [
            "--json",
            "topic",
            "update",
            "t1",
            "--new-name",
            "t1-renamed",
            "--description",
            "New desc",
            "--venue",
            "NeurIPS",
            "--deadline",
            "2026-09-01",
            "--status",
            "paused",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["topic"] == "t1-renamed"
    show = runner.invoke(main, ["--json", "topic", "show", "t1-renamed"])
    data = json.loads(show.output)
    assert data["description"] == "New desc"
    assert data["target_venue"] == "NeurIPS"
    assert data["deadline"] == "2026-09-01"
    assert data["status"] == "paused"


def test_project_show_and_update_json(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(
        main,
        [
            "project",
            "add",
            "--topic",
            "t1",
            "--name",
            "paper1",
            "--venue",
            "KDD",
            "--description",
            "seed idea",
        ],
    )
    runner.invoke(
        main,
        [
            "task",
            "add",
            "--topic",
            "t1",
            "--project",
            "paper1",
            "--title",
            "Read paper",
        ],
    )
    runner.invoke(
        main,
        [
            "review",
            "add",
            "--topic",
            "t1",
            "--project",
            "paper1",
            "--gate",
            "novelty",
            "--reviewer",
            "codex",
            "--verdict",
            "pass",
        ],
    )

    show_before = runner.invoke(
        main, ["--json", "project", "show", "--topic", "t1", "paper1"]
    )
    assert show_before.exit_code == 0, show_before.output
    before = json.loads(show_before.output)
    assert before["task_count"] == 1
    assert before["review_count"] == 1
    assert before["status"] == "planning"

    update = runner.invoke(
        main,
        [
            "--json",
            "project",
            "update",
            "--topic",
            "t1",
            "paper1",
            "--new-name",
            "paper1-v2",
            "--description",
            "tightened scope",
            "--venue",
            "ICLR",
            "--deadline",
            "2026-10-15",
            "--status",
            "active",
        ],
    )
    assert update.exit_code == 0, update.output

    show_after = runner.invoke(
        main, ["--json", "project", "show", "--topic", "t1", "paper1-v2"]
    )
    after = json.loads(show_after.output)
    assert after["name"] == "paper1-v2"
    assert after["description"] == "tightened scope"
    assert after["target_venue"] == "ICLR"
    assert after["deadline"] == "2026-10-15"
    assert after["status"] == "active"
    assert after["task_count"] == 1
    assert after["review_count"] == 1


def test_search_list_filters_and_limit(runner):
    runner.invoke(main, ["topic", "init", "topic-a"])
    runner.invoke(main, ["topic", "init", "topic-b"])
    runner.invoke(
        main,
        [
            "search",
            "log",
            "--topic",
            "topic-a",
            "--query",
            "alpha",
            "--provider",
            "semantic-scholar",
            "--result-count",
            "10",
            "--ingested-count",
            "2",
        ],
    )
    runner.invoke(
        main,
        [
            "search",
            "log",
            "--topic",
            "topic-b",
            "--query",
            "beta",
            "--provider",
            "arxiv",
            "--result-count",
            "8",
            "--ingested-count",
            "1",
        ],
    )
    runner.invoke(
        main,
        [
            "search",
            "log",
            "--query",
            "gamma",
            "--provider",
            "semantic-scholar",
            "--result-count",
            "5",
            "--ingested-count",
            "0",
        ],
    )

    filtered = runner.invoke(
        main,
        [
            "--json",
            "search",
            "list",
            "--topic",
            "topic-a",
            "--provider",
            "semantic-scholar",
            "--limit",
            "5",
        ],
    )
    assert filtered.exit_code == 0, filtered.output
    filtered_payload = json.loads(filtered.output)
    assert len(filtered_payload) == 1
    assert filtered_payload[0]["query"] == "alpha"
    assert filtered_payload[0]["topic_name"] == "topic-a"

    limited = runner.invoke(main, ["--json", "search", "list", "--limit", "2"])
    assert limited.exit_code == 0, limited.output
    limited_payload = json.loads(limited.output)
    assert len(limited_payload) == 2
    assert [item["query"] for item in limited_payload] == ["gamma", "beta"]
