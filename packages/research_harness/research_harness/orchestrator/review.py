"""Review system: formal review loop with issue tracking and response management.

Implements the review lifecycle for stages 8 (formal_review), 9 (revision),
and 10 (re_review). Review bundles are persisted as project_artifacts;
issues and responses use dedicated tables from migration 006.
"""

from __future__ import annotations

import json
from typing import Any

from ..primitives.types import SCHOLARLY_REVIEW_DIMENSIONS
from ..storage.db import Database
from .artifacts import ArtifactManager
from .models import ReviewIssue, ReviewResponse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_REVIEW_CYCLES = 2

# Unified scholarly-review dimensions (7 weighted axes). Re-exported here so
# orchestrator code and tests can import from a stable location.
REVIEW_DIMENSIONS = SCHOLARLY_REVIEW_DIMENSIONS


REVIEW_CATEGORIES: tuple[str, ...] = (
    "methodology",
    "evidence",
    "writing",
    "structure",
    "citation",
    "ethics",
    "reproducibility",
    "statistics",
    "novelty_claim",
    "scope",
)

SEVERITY_DECISION_MAP: dict[str, str] = {
    "critical": "reject",
    "high": "major_revision",
    "medium": "minor_revision",
    "low": "accept_with_notes",
}


# ---------------------------------------------------------------------------
# ReviewManager
# ---------------------------------------------------------------------------


class ReviewManager:
    """Manages the formal review lifecycle: bundles, issues, responses."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._artifact_manager = ArtifactManager(db)

    # -- Bundle management ---------------------------------------------------

    def create_bundle(
        self,
        topic_id: int,
        stage: str,
        integrity_report_id: int | None = None,
        scholarly_report_id: int | None = None,
    ) -> Any:
        """Create a review bundle artifact linking review reports.

        Returns the persisted ProjectArtifact.
        """
        # Validate report artifacts exist
        if integrity_report_id is not None:
            if self._artifact_manager.get(integrity_report_id) is None:
                raise ValueError(
                    f"Integrity report artifact {integrity_report_id} not found"
                )
        if scholarly_report_id is not None:
            if self._artifact_manager.get(scholarly_report_id) is None:
                raise ValueError(
                    f"Scholarly report artifact {scholarly_report_id} not found"
                )

        # Count existing bundles for cycle tracking
        cycle_number = self._count_bundles(topic_id) + 1
        if cycle_number > MAX_REVIEW_CYCLES:
            raise ValueError(f"Maximum review cycles ({MAX_REVIEW_CYCLES}) exceeded")

        payload = {
            "integrity_report_artifact_id": integrity_report_id,
            "scholarly_report_artifact_id": scholarly_report_id,
            "cycle_number": cycle_number,
            "status": "open",
        }

        return self._artifact_manager.record(
            topic_id=topic_id,
            stage=stage,
            artifact_type="review_bundle",
            title=f"Review Bundle (cycle {cycle_number})",
            payload=payload,
            metadata={"cycle_number": cycle_number},
        )

    # -- Issue management ----------------------------------------------------

    def add_issue(
        self,
        topic_id: int,
        stage: str,
        review_type: str,
        severity: str,
        category: str,
        summary: str,
        details: str = "",
        blocking: bool = False,
        recommended_action: str = "",
        review_artifact_id: int | None = None,
        affected_object_type: str = "",
        affected_object_id: str = "",
    ) -> ReviewIssue:
        """Insert a review issue. Critical/high severity auto-sets blocking."""
        if severity not in ("critical", "high", "medium", "low"):
            raise ValueError(f"Invalid severity: {severity}")

        # Auto-block critical and high
        if severity in ("critical", "high"):
            blocking = True

        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO review_issues
                (project_id, topic_id, stage, review_type, severity, category,
                 summary, details, blocking, recommended_action,
                 review_artifact_id, affected_object_type, affected_object_id,
                 status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    topic_id,
                    topic_id,
                    stage,
                    review_type,
                    severity,
                    category,
                    summary,
                    details,
                    1 if blocking else 0,
                    recommended_action,
                    review_artifact_id,
                    affected_object_type,
                    affected_object_id,
                ),
            )
            conn.commit()
            issue_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM review_issues WHERE id = ?", (issue_id,)
            ).fetchone()
            return self._row_to_issue(row)
        finally:
            conn.close()

    def list_issues(
        self,
        topic_id: int,
        stage: str | None = None,
        status: str | None = None,
        blocking_only: bool = False,
    ) -> list[ReviewIssue]:
        """Query review issues with optional filters."""
        clauses = ["topic_id = ?"]
        params: list[Any] = [topic_id]
        if stage is not None:
            clauses.append("stage = ?")
            params.append(stage)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if blocking_only:
            clauses.append("blocking = 1")

        where = " AND ".join(clauses)
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM review_issues WHERE {where} ORDER BY id",
                params,
            ).fetchall()
            return [self._row_to_issue(r) for r in rows]
        finally:
            conn.close()

    def resolve_issue(
        self,
        issue_id: int,
        resolution_status: str = "resolved",
    ) -> ReviewIssue:
        """Mark an issue as resolved or wontfix."""
        if resolution_status not in ("resolved", "wontfix"):
            raise ValueError(f"Invalid resolution status: {resolution_status}")
        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE review_issues
                SET status = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (resolution_status, issue_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM review_issues WHERE id = ?", (issue_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Issue {issue_id} not found")
            return self._row_to_issue(row)
        finally:
            conn.close()

    # -- Response management -------------------------------------------------

    def add_response(
        self,
        issue_id: int,
        topic_id: int,
        response_type: str,
        response_text: str,
        artifact_id: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> ReviewResponse:
        """Record a response to a review issue."""
        if response_type not in ("change", "clarify", "dispute", "acknowledge"):
            raise ValueError(f"Invalid response type: {response_type}")

        evidence_json = json.dumps(evidence or {})
        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO review_responses
                (issue_id, project_id, response_type, status,
                 response_text, artifact_id, evidence_json)
                VALUES (?, ?, ?, 'proposed', ?, ?, ?)
                """,
                (
                    issue_id,
                    topic_id,
                    response_type,
                    response_text,
                    artifact_id,
                    evidence_json,
                ),
            )
            # If response is a change, move issue to in_progress
            if response_type == "change":
                conn.execute(
                    """
                    UPDATE review_issues
                    SET status = 'in_progress', updated_at = datetime('now')
                    WHERE id = ? AND status = 'open'
                    """,
                    (issue_id,),
                )
            conn.commit()
            response_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM review_responses WHERE id = ?", (response_id,)
            ).fetchone()
            return self._row_to_response(row)
        finally:
            conn.close()

    def list_responses(self, issue_id: int) -> list[ReviewResponse]:
        """List all responses for an issue."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM review_responses WHERE issue_id = ? ORDER BY created_at",
                (issue_id,),
            ).fetchall()
            return [self._row_to_response(r) for r in rows]
        finally:
            conn.close()

    # -- Summary & decision --------------------------------------------------

    def get_review_summary(
        self,
        topic_id: int,
        stage: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate review status: counts, decision, cycle info."""
        conn = self._db.connect()
        try:
            clauses = ["topic_id = ?"]
            params: list[Any] = [topic_id]
            if stage is not None:
                clauses.append("stage = ?")
                params.append(stage)
            where = " AND ".join(clauses)

            rows = conn.execute(
                f"""
                SELECT severity, status,
                       COUNT(*) as cnt,
                       SUM(CASE WHEN blocking = 1 THEN 1 ELSE 0 END) as blocking_cnt
                FROM review_issues
                WHERE {where}
                GROUP BY severity, status
                """,
                params,
            ).fetchall()

            by_severity: dict[str, dict[str, int]] = {}
            by_status: dict[str, int] = {}
            blocking_open = 0
            total = 0

            for row in rows:
                sev = row["severity"]
                st = row["status"]
                cnt = row["cnt"]
                total += cnt

                by_severity.setdefault(sev, {})
                by_severity[sev][st] = cnt

                by_status[st] = by_status.get(st, 0) + cnt

                if st == "open":
                    blocking_open += row["blocking_cnt"]

            # Decision from worst open severity
            decision = "accept"
            for sev in ("critical", "high", "medium", "low"):
                open_count = by_severity.get(sev, {}).get("open", 0)
                if open_count > 0:
                    decision = SEVERITY_DECISION_MAP[sev]
                    break

            cycle_number = self._count_bundles(topic_id)

            return {
                "topic_id": topic_id,
                "stage": stage,
                "cycle_number": cycle_number,
                "max_cycles": MAX_REVIEW_CYCLES,
                "by_severity": by_severity,
                "by_status": by_status,
                "blocking_open": blocking_open,
                "total_issues": total,
                "decision": decision,
                "can_pass_gate": blocking_open == 0,
            }
        finally:
            conn.close()

    # -- Internal helpers ----------------------------------------------------

    def _count_bundles(self, topic_id: int) -> int:
        """Count all review_bundle artifacts (any status) for cycle tracking."""
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM project_artifacts
                WHERE topic_id = ? AND artifact_type = 'review_bundle'
                """,
                (topic_id,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    @staticmethod
    def _row_to_issue(row: Any) -> ReviewIssue:
        return ReviewIssue(
            id=row["id"],
            topic_id=row["topic_id"],
            review_artifact_id=row["review_artifact_id"],
            stage=row["stage"],
            review_type=row["review_type"],
            severity=row["severity"],
            category=row["category"],
            affected_object_type=row["affected_object_type"],
            affected_object_id=row["affected_object_id"],
            blocking=bool(row["blocking"]),
            status=row["status"],
            summary=row["summary"],
            details=row["details"],
            recommended_action=row["recommended_action"],
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    @staticmethod
    def _row_to_response(row: Any) -> ReviewResponse:
        evidence = {}
        raw = row["evidence_json"]
        if raw:
            try:
                evidence = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return ReviewResponse(
            id=row["id"],
            issue_id=row["issue_id"],
            topic_id=row["project_id"],
            response_type=row["response_type"],
            status=row["status"],
            artifact_id=row["artifact_id"],
            response_text=row["response_text"],
            evidence=evidence,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )
