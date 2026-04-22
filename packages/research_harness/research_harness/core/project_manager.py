"""Project manager."""

from __future__ import annotations

import sqlite3

from ..storage.models import Project


class ProjectManager:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(
        self,
        topic_id: int,
        name: str,
        description: str = "",
        target_venue: str = "",
        deadline: str = "",
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO projects (topic_id, name, description, target_venue, deadline)
            VALUES (?, ?, ?, ?, ?)
            """,
            (topic_id, name, description, target_venue, deadline),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_projects(self, topic_id: int | None = None) -> list[Project]:
        query = "SELECT * FROM projects"
        params: list[object] = []
        if topic_id is not None:
            query += " WHERE topic_id = ?"
            params.append(topic_id)
        query += " ORDER BY created_at"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_project(row) for row in rows]

    def get_project(self, topic_id: int, name: str) -> Project | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE topic_id = ? AND name = ?",
            (topic_id, name),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    def update_project(
        self,
        project_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        target_venue: str | None = None,
        deadline: str | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[object] = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if target_venue is not None:
            updates.append("target_venue = ?")
            params.append(target_venue)
        if deadline is not None:
            updates.append("deadline = ?")
            params.append(deadline)
        if not updates:
            return
        updates.append("updated_at = datetime('now')")
        params.append(project_id)
        self._conn.execute(
            f"UPDATE projects SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        self._conn.commit()

    def update_status(self, project_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE projects SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, project_id),
        )
        self._conn.commit()

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            topic_id=row["topic_id"],
            name=row["name"],
            description=row["description"],
            status=row["status"],
            target_venue=row["target_venue"],
            deadline=row["deadline"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
