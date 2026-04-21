import json

from research_harness.cli import main


def test_cli_end_to_end_json_contracts(runner):
    topic = runner.invoke(main, ["--json", "topic", "init", "auto-bidding", "--venue", "KDD 2027"])
    assert topic.exit_code == 0
    assert json.loads(topic.output)["id"] == 1

    project = runner.invoke(main, ["--json", "project", "add", "--topic", "auto-bidding", "--name", "paper1", "--venue", "KDD"])
    assert project.exit_code == 0
    assert json.loads(project.output)["id"] == 1

    ingest = runner.invoke(
        main,
        [
            "--json", "paper", "ingest", "--arxiv-id", "1706.03762", "--title", "Attention Is All You Need",
            "--authors", "Vaswani,Shazeer", "--year", "2017", "--venue", "NeurIPS", "--topic", "auto-bidding", "--relevance", "high",
        ],
    )
    assert ingest.exit_code == 0
    assert json.loads(ingest.output)["paper_id"] == 1

    task = runner.invoke(main, ["--json", "task", "add", "--topic", "auto-bidding", "--project", "paper1", "--title", "Read paper", "--priority", "high"])
    assert task.exit_code == 0
    assert json.loads(task.output)["project_id"] == 1

    update = runner.invoke(main, ["--json", "task", "update", "1", "--status", "in_progress"])
    assert update.exit_code == 0
    assert json.loads(update.output)["updated"] is True

    search = runner.invoke(main, ["--json", "search", "log", "--topic", "auto-bidding", "--query", "budget pacing", "--provider", "semantic-scholar", "--result-count", "15", "--ingested-count", "3"])
    assert search.exit_code == 0
    assert json.loads(search.output)["id"] == 1

    review = runner.invoke(main, ["--json", "review", "add", "--topic", "auto-bidding", "--project", "paper1", "--gate", "novelty", "--reviewer", "codex", "--verdict", "pass"])
    assert review.exit_code == 0
    assert json.loads(review.output)["id"] == 1

    paper_show = runner.invoke(main, ["--json", "paper", "show", "1"])
    assert paper_show.exit_code == 0
    payload = json.loads(paper_show.output)
    assert payload["paper"]["title"] == "Attention Is All You Need"


def test_review_scoped_by_topic(runner):
    runner.invoke(main, ["topic", "init", "t1"])
    runner.invoke(main, ["topic", "init", "t2"])
    runner.invoke(main, ["project", "add", "--topic", "t1", "--name", "paper1"])
    runner.invoke(main, ["project", "add", "--topic", "t2", "--name", "paper1"])
    result = runner.invoke(main, ["review", "add", "--topic", "t2", "--project", "paper1", "--gate", "method", "--reviewer", "codex", "--verdict", "pass"])
    assert result.exit_code == 0
