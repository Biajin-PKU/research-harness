"""Lightweight Python API — direct access to core functions without MCP.

Usage from Skills or scripts::

    from research_harness.api import ResearchAPI

    api = ResearchAPI()  # auto-resolves DB path
    api.record_artifact(project_id=1, topic_id=1, stage="init", artifact_type="topic_brief", payload={...})
    status = api.orchestrator_status(project_id=1)
    papers = api.paper_search(query="attention", topic_id=1)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import load_runtime_config
from .storage.db import Database

logger = logging.getLogger(__name__)


class ResearchAPI:
    """Direct Python API for research harness — no MCP required."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path:
            self._db = Database(Path(db_path))
        else:
            config = load_runtime_config()
            self._db = Database(config.db_path)
        self._db.migrate()

    @property
    def db(self) -> Database:
        return self._db

    @property
    def db_path(self) -> Path:
        return self._db.db_path

    def record_artifact(
        self,
        project_id: int,
        topic_id: int,
        stage: str,
        artifact_type: str,
        title: str = "",
        payload: dict[str, Any] | None = None,
        dependency_artifact_ids: list[int] | None = None,
        dependency_type: str = "consumed_by",
    ) -> dict[str, Any]:
        """Record a project artifact (equivalent to orchestrator_record_artifact MCP tool)."""
        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        artifact = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage=stage,
            artifact_type=artifact_type,
            title=title,
            payload=payload,
            dependency_artifact_ids=dependency_artifact_ids,
            dependency_type=dependency_type,
        )
        return {
            "success": True,
            "artifact_id": artifact.id,
            "version": artifact.version,
            "stage": artifact.stage,
            "type": artifact.artifact_type,
        }

    def add_artifact_dependency(
        self,
        from_artifact_id: int,
        to_artifact_id: int,
        dependency_type: str = "consumed_by",
    ) -> dict[str, Any]:
        """Declare a dependency edge between two artifacts."""
        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        return svc.add_artifact_dependency(
            from_artifact_id=from_artifact_id,
            to_artifact_id=to_artifact_id,
            dependency_type=dependency_type,
        )

    def mark_artifact_stale(
        self,
        artifact_id: int,
        reason: str = "",
        propagate: bool = True,
    ) -> dict[str, Any]:
        """Mark an artifact stale and optionally propagate downstream."""
        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        return svc.mark_artifact_stale(
            artifact_id=artifact_id,
            reason=reason,
            propagate=propagate,
        )

    def clear_artifact_stale(self, artifact_id: int) -> dict[str, Any]:
        """Clear stale state on an artifact."""
        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        return svc.clear_artifact_stale(artifact_id)

    def list_stale_artifacts(self, project_id: int) -> list[dict[str, Any]]:
        """List stale artifacts for a project."""
        from dataclasses import asdict

        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        return [asdict(item) for item in svc.list_stale_artifacts(project_id)]

    def orchestrator_status(self, project_id: int) -> dict[str, Any]:
        """Get orchestrator status for a project."""
        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        status = svc.get_status(project_id)
        status["db_path"] = str(self._db.db_path)
        return status

    def gate_check(self, project_id: int, stage: str | None = None) -> dict[str, Any]:
        """Check gate for current or specified stage."""
        from .orchestrator import OrchestratorService

        svc = OrchestratorService(self._db)
        return svc.check_gate(project_id, stage=stage)

    def paper_search(self, query: str, **kwargs: Any) -> Any:
        """Search papers (delegates to paper_search primitive)."""
        from .primitives import get_primitive_impl

        impl = get_primitive_impl("paper_search")
        if impl is None:
            raise RuntimeError("paper_search primitive not registered")
        return impl(db=self._db, query=query, **kwargs)

    def paper_ingest(self, source: str, **kwargs: Any) -> Any:
        """Ingest a paper (delegates to paper_ingest primitive)."""
        from .primitives import get_primitive_impl

        impl = get_primitive_impl("paper_ingest")
        if impl is None:
            raise RuntimeError("paper_ingest primitive not registered")
        return impl(db=self._db, source=source, **kwargs)

    def execute_primitive(self, name: str, **kwargs: Any) -> Any:
        """Execute any registered primitive by name."""
        from .primitives import get_primitive_impl

        impl = get_primitive_impl(name)
        if impl is None:
            raise ValueError(f"Unknown primitive: {name}")
        return impl(db=self._db, **kwargs)
