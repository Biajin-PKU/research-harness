from pathlib import Path

from research_harness.config import init_project_config, load_runtime_config


def test_project_default_db_path(tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / "packages" / "research_harness").mkdir(parents=True)
    (workspace / "packages" / "research_harness" / "pyproject.toml").write_text("")
    runtime = load_runtime_config(cwd=workspace)
    assert runtime.source == "project-default"
    assert runtime.db_path == (workspace / ".research-harness" / "pool.db").resolve()
    assert runtime.execution_backend == "local"


def test_project_config_override(tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / "packages" / "research_harness").mkdir(parents=True)
    (workspace / "packages" / "research_harness" / "pyproject.toml").write_text("")
    init_project_config(
        workspace, db_path="data/custom.db", execution_backend="research_harness"
    )
    runtime = load_runtime_config(cwd=workspace)
    assert runtime.source == "project-config"
    assert runtime.db_path == (workspace / "data" / "custom.db").resolve()
    assert runtime.execution_backend == "research_harness"


def test_explicit_backend_overrides_project_config(tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / "packages" / "research_harness").mkdir(parents=True)
    (workspace / "packages" / "research_harness" / "pyproject.toml").write_text("")
    init_project_config(workspace, execution_backend="research_harness")
    runtime = load_runtime_config(cwd=workspace, explicit_backend="claude_code")
    assert runtime.execution_backend == "claude_code"
