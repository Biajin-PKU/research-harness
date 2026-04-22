"""Advisory data model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..storage.db import Database


@dataclass
class Advisory:
    """A single advisory about research quality or process."""

    id: int = 0
    topic_id: int = 0
    project_id: int | None = None
    level: str = "info"  # "info" | "warning"
    category: str = (
        ""  # coverage | recency | bias | dependency | contradiction | missing_stage
    )
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    acknowledged: bool = False
    acknowledged_at: str | None = None
    auto_resolved: bool = False


class AdvisoryStore:
    """Persistence layer for advisories."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, advisory: Advisory) -> Advisory:
        """Insert an advisory and return it with its ID."""
        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO advisories
                (topic_id, project_id, level, category, message, details_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    advisory.topic_id,
                    advisory.project_id,
                    advisory.level,
                    advisory.category,
                    advisory.message,
                    json.dumps(advisory.details, ensure_ascii=False),
                ),
            )
            conn.commit()
            advisory_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM advisories WHERE id = ?", (advisory_id,)
            ).fetchone()
            return self._row_to_advisory(row)
        finally:
            conn.close()

    def acknowledge(self, advisory_id: int) -> Advisory | None:
        """Mark an advisory as acknowledged."""
        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE advisories
                SET acknowledged = 1, acknowledged_at = datetime('now')
                WHERE id = ?
                """,
                (advisory_id,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM advisories WHERE id = ?", (advisory_id,)
            ).fetchone()
            return self._row_to_advisory(row) if row else None
        finally:
            conn.close()

    def list_advisories(
        self,
        topic_id: int,
        level: str | None = None,
        include_acknowledged: bool = False,
    ) -> list[Advisory]:
        """List advisories for a topic."""
        clauses = ["topic_id = ?"]
        params: list[Any] = [topic_id]
        if level:
            clauses.append("level = ?")
            params.append(level)
        if not include_acknowledged:
            clauses.append("acknowledged = 0")

        where = " AND ".join(clauses)
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM advisories WHERE {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
            return [self._row_to_advisory(r) for r in rows]
        finally:
            conn.close()

    def has_active_advisory(self, topic_id: int, category: str, message: str) -> bool:
        """Check if an identical unacknowledged advisory already exists."""
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT 1 FROM advisories
                WHERE topic_id = ? AND category = ? AND message = ?
                  AND acknowledged = 0 AND auto_resolved = 0
                LIMIT 1
                """,
                (topic_id, category, message),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def _row_to_advisory(row: Any) -> Advisory:
        details = {}
        raw = row["details_json"]
        if raw:
            try:
                details = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return Advisory(
            id=row["id"],
            topic_id=row["topic_id"],
            project_id=row["project_id"],
            level=row["level"],
            category=row["category"],
            message=row["message"],
            details=details,
            created_at=row["created_at"] or "",
            acknowledged=bool(row["acknowledged"]),
            acknowledged_at=row["acknowledged_at"],
            auto_resolved=bool(row["auto_resolved"]),
        )
