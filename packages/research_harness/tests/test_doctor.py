import json

from research_harness.cli import main


def test_doctor_json(runner):
    result = runner.invoke(main, ["--json", "doctor"])
    assert result.exit_code == 0
    checks = json.loads(result.output)
    names = {item["check"] for item in checks}
    assert "python" in names
    assert "sqlite3" in names
    assert "database" in names
    assert "execution_backend" in names
    assert "primitives" in names
    assert "provenance" in names
