"""Review manager."""

from __future__ import annotations

import sqlite3

from ..storage.models import Review


class ReviewManager:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def add_review(
        self,
        project_id: int,
        gate: str,
        reviewer: str,
        verdict: str,
        score: float | None = None,
        findings: str = "",
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO reviews (project_id, gate, reviewer, verdict, score, findings)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, gate, reviewer, verdict, score, findings),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_reviews(self, project_id: int) -> list[Review]:
        rows = self._conn.execute(
            "SELECT * FROM reviews WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        return [self._row_to_review(row) for row in rows]

    @staticmethod
    def _row_to_review(row: sqlite3.Row) -> Review:
        return Review(
            id=row["id"],
            project_id=row["project_id"],
            gate=row["gate"],
            reviewer=row["reviewer"],
            verdict=row["verdict"],
            score=row["score"],
            findings=row["findings"],
            created_at=row["created_at"],
        )
