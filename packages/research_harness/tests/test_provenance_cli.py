import csv
import io
import json

from research_harness.cli import main


def test_provenance_list_and_show_json(runner):
    execute = runner.invoke(
        main,
        [
            "--json",
            "primitive",
            "exec",
            "paper_ingest",
            "--args",
            '{"source":"10.1000/prov-one"}',
        ],
    )
    assert execute.exit_code == 0

    listed = runner.invoke(main, ["--json", "provenance", "list"])
    assert listed.exit_code == 0
    records = json.loads(listed.output)
    assert len(records) == 1
    assert records[0]["primitive"] == "paper_ingest"

    shown = runner.invoke(main, ["--json", "provenance", "show", str(records[0]["id"])])
    assert shown.exit_code == 0
    payload = json.loads(shown.output)
    assert payload["id"] == records[0]["id"]
    assert payload["backend"] == "local"


def test_provenance_summary_json(runner):
    runner.invoke(
        main,
        [
            "--json",
            "primitive",
            "exec",
            "paper_ingest",
            "--args",
            '{"source":"10.1000/prov-a"}',
        ],
    )
    runner.invoke(
        main,
        [
            "--json",
            "primitive",
            "exec",
            "paper_ingest",
            "--args",
            '{"source":"10.1000/prov-b"}',
        ],
    )

    summary = runner.invoke(main, ["--json", "provenance", "summary"])
    assert summary.exit_code == 0
    payload = json.loads(summary.output)
    assert payload["total_operations"] == 2
    assert payload["operations_by_primitive"]["paper_ingest"] == 2


def test_provenance_export_json_and_csv(runner, tmp_path):
    runner.invoke(
        main,
        ["--json", "topic", "init", "prov-topic"],
    )
    topic = json.loads(
        runner.invoke(main, ["--json", "topic", "show", "prov-topic"]).output
    )
    runner.invoke(
        main,
        [
            "--json",
            "primitive",
            "exec",
            "--topic",
            str(topic["id"]),
            "paper_ingest",
            "--args",
            '{"source":"10.1000/prov-export"}',
        ],
    )

    exported = runner.invoke(main, ["provenance", "export", "--topic", "prov-topic"])
    assert exported.exit_code == 0
    payload = json.loads(exported.output)
    assert len(payload) == 1
    assert payload[0]["topic_id"] == topic["id"]

    csv_path = tmp_path / "provenance.csv"
    exported_csv = runner.invoke(
        main,
        [
            "provenance",
            "export",
            "--topic",
            "prov-topic",
            "--format",
            "csv",
            "--output",
            str(csv_path),
        ],
    )
    assert exported_csv.exit_code == 0
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text())))
    assert len(rows) == 1
    assert rows[0]["primitive_name"] == "paper_ingest"
    assert rows[0]["backend"] == "local"


def test_topic_export_json(runner, tmp_path):
    created = runner.invoke(
        main,
        [
            "--json",
            "topic",
            "init",
            "export-topic",
            "--description",
            "desc",
            "--venue",
            "ICLR",
        ],
    )
    assert created.exit_code == 0
    topic = json.loads(
        runner.invoke(main, ["--json", "topic", "show", "export-topic"]).output
    )

    paper = runner.invoke(
        main,
        [
            "--json",
            "paper",
            "ingest",
            "--title",
            "Exported Paper",
            "--authors",
            "Ada Lovelace,Grace Hopper",
            "--topic",
            "export-topic",
        ],
    )
    assert paper.exit_code == 0
    paper_payload = json.loads(paper.output)

    task = runner.invoke(
        main,
        [
            "--json",
            "task",
            "add",
            "--topic",
            "export-topic",
            "--title",
            "Do thing",
        ],
    )
    assert task.exit_code == 0

    review = runner.invoke(
        main,
        [
            "--json",
            "review",
            "add",
            "--topic",
            "export-topic",
            "--gate",
            "method",
            "--reviewer",
            "codex",
            "--verdict",
            "pass",
            "--findings",
            "ok",
        ],
    )
    assert review.exit_code == 0

    runner.invoke(
        main,
        [
            "--json",
            "primitive",
            "exec",
            "--topic",
            str(topic["id"]),
            "paper_search",
            "--args",
            '{"query":"Exported"}',
        ],
    )

    exported = runner.invoke(main, ["topic", "export", "export-topic"])
    assert exported.exit_code == 0
    payload = json.loads(exported.output)
    assert payload["topic"]["name"] == "export-topic"
    assert payload["claims"] == []
    assert len(payload["papers"]) == 1
    assert payload["papers"][0]["id"] == paper_payload["paper_id"]
    assert len(payload["tasks"]) == 1
    assert len(payload["provenance"]) == 1

    output_path = tmp_path / "topic-export.json"
    exported_file = runner.invoke(
        main, ["topic", "export", "export-topic", "--output", str(output_path)]
    )
    assert exported_file.exit_code == 0
    file_payload = json.loads(output_path.read_text())
    assert file_payload["topic"]["name"] == "export-topic"
