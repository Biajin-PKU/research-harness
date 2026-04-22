import json

from research_harness.cli import main


def test_backend_list_json(runner):
    result = runner.invoke(main, ["--json", "backend", "list"])
    assert result.exit_code == 0
    assert json.loads(result.output) == ["claude_code", "local", "research_harness"]


def test_backend_info_json_default_local(runner):
    result = runner.invoke(main, ["--json", "backend", "info"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["name"] == "local"
    assert "paper_search" in payload["supported_primitives"]


def test_backend_info_json_with_backend_override(runner):
    result = runner.invoke(
        main, ["--backend", "claude_code", "--json", "backend", "info"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["name"] == "claude_code"
    assert payload["requires_api_key"] is True


def test_backend_primitives_json(runner):
    result = runner.invoke(main, ["--json", "backend", "primitives"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "paper_search" in payload
    assert "paper_ingest" in payload
