"""Runtime config resolution for research-harness."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


GLOBAL_DB_PATH = Path.home() / ".research-harness" / "pool.db"
CONFIG_DIRNAME = ".research-harness"
CONFIG_FILENAME = "config.json"
DEFAULT_BACKEND = "local"


@dataclass
class RuntimeConfig:
    db_path: Path
    source: str
    workspace_root: Path | None = None
    config_path: Path | None = None
    execution_backend: str = DEFAULT_BACKEND


def find_workspace_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / 'packages' / 'research_harness' / 'pyproject.toml').exists():
            return candidate
    return None


def default_project_db_path(workspace_root: Path) -> Path:
    return workspace_root / CONFIG_DIRNAME / 'pool.db'


def _resolve_execution_backend(
    explicit_backend: str | None,
    config_data: dict[str, object] | None = None,
) -> str:
    if explicit_backend:
        return explicit_backend
    env_backend = os.environ.get('RESEARCH_HARNESS_BACKEND') or os.environ.get('RESEARCH_HUB_BACKEND')
    if env_backend:
        return env_backend
    if config_data:
        configured = config_data.get('execution_backend')
        if isinstance(configured, str) and configured:
            return configured
    return DEFAULT_BACKEND


def load_runtime_config(
    explicit_db_path: str | Path | None = None,
    explicit_backend: str | None = None,
    cwd: Path | None = None,
) -> RuntimeConfig:
    workspace_root = find_workspace_root(cwd)
    config_path = workspace_root / CONFIG_DIRNAME / CONFIG_FILENAME if workspace_root else None

    config_data: dict[str, object] | None = None
    if config_path and config_path.exists():
        config_data = json.loads(config_path.read_text())

    execution_backend = _resolve_execution_backend(explicit_backend, config_data)

    if explicit_db_path:
        return RuntimeConfig(
            db_path=Path(explicit_db_path).expanduser().resolve(),
            source='explicit',
            workspace_root=workspace_root,
            config_path=config_path,
            execution_backend=execution_backend,
        )

    env_db_path = os.environ.get('RESEARCH_HARNESS_DB_PATH') or os.environ.get('RESEARCH_HUB_DB_PATH')
    if env_db_path:
        return RuntimeConfig(
            db_path=Path(env_db_path).expanduser().resolve(),
            source='env',
            workspace_root=workspace_root,
            config_path=config_path,
            execution_backend=execution_backend,
        )

    if workspace_root:
        if config_data:
            configured = config_data.get('db_path')
            if configured:
                candidate = Path(str(configured))
                if not candidate.is_absolute():
                    candidate = workspace_root / candidate
                return RuntimeConfig(
                    db_path=candidate.resolve(),
                    source='project-config',
                    workspace_root=workspace_root,
                    config_path=config_path,
                    execution_backend=execution_backend,
                )
        return RuntimeConfig(
            db_path=default_project_db_path(workspace_root).resolve(),
            source='project-default',
            workspace_root=workspace_root,
            config_path=config_path,
            execution_backend=execution_backend,
        )

    return RuntimeConfig(
        db_path=GLOBAL_DB_PATH,
        source='global-default',
        workspace_root=None,
        config_path=None,
        execution_backend=execution_backend,
    )


def init_project_config(
    workspace_root: Path,
    db_path: str | Path | None = None,
    execution_backend: str = DEFAULT_BACKEND,
) -> Path:
    config_dir = workspace_root / CONFIG_DIRNAME
    config_dir.mkdir(parents=True, exist_ok=True)
    target = Path(db_path) if db_path else Path(CONFIG_DIRNAME) / 'pool.db'
    payload = {
        'db_path': str(target),
        'execution_backend': execution_backend,
    }
    config_path = config_dir / CONFIG_FILENAME
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return config_path
