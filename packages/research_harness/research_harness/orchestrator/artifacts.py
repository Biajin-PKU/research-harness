"""Artifact persistence helpers with versioning."""

from __future__ import annotations

import json
from typing import Any

from ..storage.db import Database
from .models import ProjectArtifact


class ArtifactManager:
    """CRUD for project artifacts with versioning support."""

    def __init__(self, db: Database):
        self._db = db

    def record(
        self,
        project_id: int,
        topic_id: int,
        stage: str,
        artifact_type: str,
        title: str = "",
        path: str = "",
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_artifact_id: int | None = None,
        provenance_record_id: int | None = None,
    ) -> ProjectArtifact:
        """Record a new artifact, auto-incrementing version if one exists."""
        conn = self._db.connect()
        try:
            # Find latest version
            row = conn.execute(
                """
                SELECT version FROM project_artifacts
                WHERE project_id = ? AND stage = ? AND artifact_type = ?
                ORDER BY version DESC LIMIT 1
                """,
                (project_id, stage, artifact_type),
            ).fetchone()
            version = 1 if row is None else int(row["version"]) + 1

            # Deprecate old version
            conn.execute(
                """
                UPDATE project_artifacts
                SET status = 'superseded', updated_at = datetime('now')
                WHERE project_id = ? AND stage = ? AND artifact_type = ? AND status = 'active'
                """,
                (project_id, stage, artifact_type),
            )

            # Insert new version
            cur = conn.execute(
                """
                INSERT INTO project_artifacts
                (project_id, topic_id, stage, artifact_type, status, version, title, path,
                 payload_json, metadata_json, parent_artifact_id, provenance_record_id)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    topic_id,
                    stage,
                    artifact_type,
                    version,
                    title,
                    path,
                    json.dumps(payload or {}, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    parent_artifact_id,
                    provenance_record_id,
                ),
            )
            conn.commit()
            artifact_id = int(cur.lastrowid)
            return self.get(artifact_id)
        finally:
            conn.close()

    def get(self, artifact_id: int) -> ProjectArtifact | None:
        """Fetch a single artifact by id."""
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM project_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_artifact(row)
        finally:
            conn.close()

    def list_by_project(
        self,
        project_id: int,
        stage: str | None = None,
        artifact_type: str | None = None,
        status: str = "active",
    ) -> list[ProjectArtifact]:
        """List artifacts for a project, optionally filtered."""
        conn = self._db.connect()
        try:
            clauses = ["project_id = ?"]
            params: list[Any] = [project_id]
            if stage:
                clauses.append("stage = ?")
                params.append(stage)
            if artifact_type:
                clauses.append("artifact_type = ?")
                params.append(artifact_type)
            if status:
                clauses.append("status = ?")
                params.append(status)

            where = " AND ".join(clauses)
            rows = conn.execute(
                f"SELECT * FROM project_artifacts WHERE {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
            return [self._row_to_artifact(row) for row in rows]
        finally:
            conn.close()

    def get_latest(
        self,
        project_id: int,
        stage: str,
        artifact_type: str,
    ) -> ProjectArtifact | None:
        """Get the latest active artifact of a given type for a stage."""
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM project_artifacts
                WHERE project_id = ? AND stage = ? AND artifact_type = ? AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (project_id, stage, artifact_type),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_artifact(row)
        finally:
            conn.close()

    # -- Dependency tracking ----------------------------------------------------

    def add_dependency(
        self,
        from_artifact_id: int,
        to_artifact_id: int,
        dependency_type: str = "consumed_by",
    ) -> None:
        """Record that to_artifact depends on from_artifact.

        dependency_type:
          - consumed_by: to_artifact consumes from_artifact's output
          - derived_from: to_artifact is derived from from_artifact
        """
        conn = self._db.connect()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO artifact_dependencies
                (from_artifact_id, to_artifact_id, dependency_type)
                VALUES (?, ?, ?)
                """,
                (from_artifact_id, to_artifact_id, dependency_type),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_stale(
        self,
        artifact_id: int,
        reason: str = "",
        propagate: bool = True,
    ) -> list[int]:
        """Mark an artifact as stale and optionally propagate to dependents.

        Returns list of all artifact IDs that were marked stale (including
        the original).
        """
        stale_ids: list[int] = []
        self._propagate_stale(artifact_id, reason, stale_ids, propagate)
        return stale_ids

    def _propagate_stale(
        self,
        artifact_id: int,
        reason: str,
        stale_ids: list[int],
        propagate: bool,
    ) -> None:
        """Recursively mark stale through dependency graph."""
        if artifact_id in stale_ids:
            return  # Avoid cycles
        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE project_artifacts
                SET stale = 1, stale_reason = ?, updated_at = datetime('now')
                WHERE id = ? AND stale = 0
                """,
                (reason, artifact_id),
            )
            conn.commit()
        finally:
            conn.close()
        stale_ids.append(artifact_id)

        if not propagate:
            return

        # Find downstream dependents
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT to_artifact_id FROM artifact_dependencies
                WHERE from_artifact_id = ? AND dependency_type = 'consumed_by'
                """,
                (artifact_id,),
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            downstream_id = row["to_artifact_id"]
            cascade_reason = f"upstream artifact #{artifact_id} stale: {reason}"
            self._propagate_stale(
                downstream_id, cascade_reason, stale_ids, propagate=True
            )

    def clear_stale(self, artifact_id: int) -> None:
        """Acknowledge and clear stale flag on an artifact."""
        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE project_artifacts
                SET stale = 0, stale_reason = NULL, updated_at = datetime('now')
                WHERE id = ?
                """,
                (artifact_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def list_stale(self, project_id: int) -> list[ProjectArtifact]:
        """List all stale artifacts for a project."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM project_artifacts
                WHERE project_id = ? AND stale = 1 AND status = 'active'
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
            return [self._row_to_artifact(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def _row_to_artifact(row: Any) -> ProjectArtifact:
        return ProjectArtifact(
            id=row["id"],
            project_id=row["project_id"],
            topic_id=row["topic_id"],
            stage=row["stage"],
            artifact_type=row["artifact_type"],
            status=row["status"],
            version=row["version"],
            title=row["title"] or "",
            path=row["path"] or "",
            payload=json.loads(row["payload_json"] or "{}"),
            metadata=json.loads(row["metadata_json"] or "{}"),
            parent_artifact_id=row["parent_artifact_id"],
            provenance_record_id=row["provenance_record_id"],
            stale=bool(row["stale"]) if "stale" in row.keys() else False,
            stale_reason=row["stale_reason"] if "stale_reason" in row.keys() else None,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )
