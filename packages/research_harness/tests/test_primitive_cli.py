import json

from research_harness.cli import main


def test_primitive_list_json(runner):
    result = runner.invoke(main, ["--json", "primitive", "list"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    names = {item["name"] for item in payload}
    assert len(payload) >= 30
    assert "paper_search" in names
    assert "claim_extract" in names


def test_primitive_exec_json_records_provenance(runner):
    result = runner.invoke(
        main,
        [
            "--json",
            "primitive",
            "exec",
            "paper_ingest",
            "--args",
            '{"source":"10.1000/primitive"}',
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["primitive"] == "paper_ingest"
    assert payload["success"] is True
    assert payload["backend"] == "local"

    provenance = runner.invoke(main, ["--json", "provenance", "list"])
    assert provenance.exit_code == 0
    records = json.loads(provenance.output)
    assert records[0]["primitive"] == "paper_ingest"
