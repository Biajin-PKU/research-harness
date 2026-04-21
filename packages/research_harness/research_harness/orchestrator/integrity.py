"""Final integrity verification: 5-phase protocol and finalize logic.

Phases:
1. References — verify all citations are traceable to the paper pool
2. Citation context — check citations are used in proper context
3. Statistical data — flag unsubstantiated numerical claims
4. Originality — detect overclaiming or scope creep
5. Claims — verify every claim has linked evidence

Also handles finalize stage: produces final_bundle and process_summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..storage.db import Database
from .artifacts import ArtifactManager
from .review import ReviewManager


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTEGRITY_PHASES: tuple[str, ...] = (
    "references",
    "citation_context",
    "statistical_data",
    "originality",
    "claims",
)

PHASE_DESCRIPTIONS: dict[str, str] = {
    "references": "Verify all citations are traceable to ingested papers",
    "citation_context": "Check citations are used in proper context, not misrepresented",
    "statistical_data": "Flag numerical claims without source or methodology",
    "originality": "Detect overclaiming, scope creep, or unoriginal contribution framing",
    "claims": "Verify every claim has linked evidence in the evidence pack",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class IntegrityFinding:
    """A single finding from one integrity phase."""

    phase: str
    severity: str  # critical, high, medium, low
    category: str
    summary: str
    details: str = ""
    affected_artifact_type: str = ""
    affected_artifact_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "severity": self.severity,
            "category": self.category,
            "summary": self.summary,
            "details": self.details,
            "affected_artifact_type": self.affected_artifact_type,
            "affected_artifact_id": self.affected_artifact_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IntegrityFinding:
        return cls(
            phase=d.get("phase", ""),
            severity=d.get("severity", "medium"),
            category=d.get("category", ""),
            summary=d.get("summary", ""),
            details=d.get("details", ""),
            affected_artifact_type=d.get("affected_artifact_type", ""),
            affected_artifact_id=d.get("affected_artifact_id", ""),
        )


@dataclass
class IntegrityReport:
    """Result of the 5-phase integrity verification."""

    phases_completed: list[str] = field(default_factory=list)
    findings: list[IntegrityFinding] = field(default_factory=list)
    passed: bool = True
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "phases_completed": self.phases_completed,
            "findings": [f.to_dict() for f in self.findings],
            "passed": self.passed,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
        }

    @classmethod
    def from_payload(cls, p: dict[str, Any]) -> IntegrityReport:
        findings = [
            IntegrityFinding.from_dict(f)
            for f in p.get("findings", [])
        ]
        return cls(
            phases_completed=p.get("phases_completed", []),
            findings=findings,
            passed=p.get("passed", True),
            critical_count=p.get("critical_count", 0),
            high_count=p.get("high_count", 0),
            medium_count=p.get("medium_count", 0),
            low_count=p.get("low_count", 0),
        )


# ---------------------------------------------------------------------------
# IntegrityVerifier
# ---------------------------------------------------------------------------

class IntegrityVerifier:
    """Runs the 5-phase integrity verification protocol."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._artifact_manager = ArtifactManager(db)
        self._review_manager = ReviewManager(db)

    def run_check(
        self,
        project_id: int,
        topic_id: int,
        stage: str,
        findings: list[dict[str, Any]] | None = None,
    ) -> IntegrityReport:
        """Run integrity verification and persist as artifact.

        Findings can be supplied externally (e.g. from an LLM agent) or
        auto-checked against the database (references and claims phases).

        Returns the IntegrityReport.
        """
        report = IntegrityReport()
        external_findings = [
            IntegrityFinding.from_dict(f) for f in (findings or [])
        ]

        # Phase 1: References — check citation papers exist in pool
        phase1_findings = self._check_references(project_id, topic_id, stage)
        report.phases_completed.append("references")

        # Phase 2: Citation context — from external findings
        phase2_findings = [
            f for f in external_findings if f.phase == "citation_context"
        ]
        report.phases_completed.append("citation_context")

        # Phase 3: Statistical data — from external findings
        phase3_findings = [
            f for f in external_findings if f.phase == "statistical_data"
        ]
        report.phases_completed.append("statistical_data")

        # Phase 4: Originality — from external findings
        phase4_findings = [
            f for f in external_findings if f.phase == "originality"
        ]
        report.phases_completed.append("originality")

        # Phase 5: Claims — check evidence links exist
        phase5_findings = self._check_claims(project_id, topic_id, stage)
        report.phases_completed.append("claims")

        # Combine all findings
        all_findings = (
            phase1_findings
            + phase2_findings
            + phase3_findings
            + phase4_findings
            + phase5_findings
        )
        # Also include any external findings not matched to specific phases
        matched_phases = {"citation_context", "statistical_data", "originality"}
        for f in external_findings:
            if f.phase not in matched_phases:
                all_findings.append(f)

        report.findings = all_findings

        # Count by severity
        for f in all_findings:
            if f.severity == "critical":
                report.critical_count += 1
            elif f.severity == "high":
                report.high_count += 1
            elif f.severity == "medium":
                report.medium_count += 1
            else:
                report.low_count += 1

        report.passed = report.critical_count == 0

        # Persist as artifact
        self._artifact_manager.record(
            project_id=project_id,
            topic_id=topic_id,
            stage=stage,
            artifact_type="final_integrity_report",
            title="Final Integrity Report",
            payload=report.to_payload(),
            metadata={
                "phases": len(report.phases_completed),
                "total_findings": len(report.findings),
                "passed": report.passed,
            },
        )

        # Explode critical findings into review_issues
        for f in all_findings:
            if f.severity in ("critical", "high"):
                self._review_manager.add_issue(
                    project_id=project_id,
                    topic_id=topic_id,
                    stage=stage,
                    review_type="integrity",
                    severity=f.severity,
                    category=f.category or f.phase,
                    summary=f.summary,
                    details=f.details,
                    blocking=True,
                    affected_object_type=f.affected_artifact_type,
                    affected_object_id=f.affected_artifact_id,
                )

        return report

    def _check_references(
        self,
        project_id: int,
        topic_id: int,
        stage: str,
    ) -> list[IntegrityFinding]:
        """Phase 1: Check draft citations against paper pool."""
        findings: list[IntegrityFinding] = []
        conn = self._db.connect()
        try:
            # Get draft artifact for this project
            draft = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE project_id = ? AND artifact_type = 'draft_pack' AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            if draft is None:
                return findings

            import json
            payload = json.loads(draft["payload_json"] or "{}")
            cited_ids = payload.get("cited_paper_ids", [])
            if not cited_ids:
                return findings

            # Check each cited paper exists
            for paper_id in cited_ids:
                row = conn.execute(
                    "SELECT 1 FROM papers WHERE id = ?", (paper_id,)
                ).fetchone()
                if row is None:
                    findings.append(IntegrityFinding(
                        phase="references",
                        severity="critical",
                        category="citation",
                        summary=f"Cited paper ID {paper_id} not found in paper pool",
                        affected_artifact_type="paper",
                        affected_artifact_id=str(paper_id),
                    ))
        finally:
            conn.close()
        return findings

    def _check_claims(
        self,
        project_id: int,
        topic_id: int,
        stage: str,
    ) -> list[IntegrityFinding]:
        """Phase 5: Check claims have evidence links."""
        findings: list[IntegrityFinding] = []
        conn = self._db.connect()
        try:
            # Get evidence_pack artifact
            evidence = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE project_id = ? AND artifact_type = 'evidence_pack' AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()
            if evidence is None:
                return findings

            import json
            payload = json.loads(evidence["payload_json"] or "{}")
            claims = payload.get("claims", [])

            for claim in claims:
                if not isinstance(claim, dict):
                    continue
                claim_id = claim.get("claim_id", claim.get("content", "")[:50])
                evidence_links = claim.get("evidence_links", [])
                if not evidence_links:
                    findings.append(IntegrityFinding(
                        phase="claims",
                        severity="high",
                        category="evidence",
                        summary=f"Claim has no evidence links: {claim_id}",
                        affected_artifact_type="claim",
                        affected_artifact_id=str(claim_id),
                    ))
        finally:
            conn.close()
        return findings


# ---------------------------------------------------------------------------
# FinalizeManager
# ---------------------------------------------------------------------------

class FinalizeManager:
    """Produces the final bundle and process summary for the finalize stage."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._artifact_manager = ArtifactManager(db)

    def create_final_bundle(
        self,
        project_id: int,
        topic_id: int,
    ) -> Any:
        """Create the final submission bundle artifact.

        Collects references to all key artifacts produced during the workflow.
        """
        artifacts = self._artifact_manager.list_by_project(project_id)
        artifact_index = [
            {
                "id": a.id,
                "stage": a.stage,
                "type": a.artifact_type,
                "version": a.version,
                "title": a.title,
            }
            for a in artifacts
        ]

        payload = {
            "artifact_count": len(artifacts),
            "artifact_index": artifact_index,
            "status": "ready",
        }

        return self._artifact_manager.record(
            project_id=project_id,
            topic_id=topic_id,
            stage="finalize",
            artifact_type="final_bundle",
            title="Final Submission Bundle",
            payload=payload,
            metadata={"artifact_count": len(artifacts)},
        )

    def create_process_summary(
        self,
        project_id: int,
        topic_id: int,
    ) -> Any:
        """Create the process summary artifact.

        Documents the research workflow: stages traversed, review cycles,
        adversarial rounds, and key decisions.
        """
        conn = self._db.connect()
        try:
            # Stage events
            events = conn.execute(
                """
                SELECT from_stage, to_stage, event_type, actor, rationale, created_at
                FROM orchestrator_stage_events
                WHERE project_id = ?
                ORDER BY id
                """,
                (project_id,),
            ).fetchall()
            stage_history = [
                {
                    "from": e["from_stage"],
                    "to": e["to_stage"],
                    "type": e["event_type"],
                    "actor": e["actor"],
                    "rationale": e["rationale"],
                    "timestamp": e["created_at"],
                }
                for e in events
            ]

            # Review issue summary
            issue_row = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved,
                    SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical
                FROM review_issues WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()

            # Artifact count by stage
            artifact_counts = conn.execute(
                """
                SELECT stage, COUNT(*) as cnt
                FROM project_artifacts
                WHERE project_id = ?
                GROUP BY stage
                """,
                (project_id,),
            ).fetchall()

            # Provenance cost
            prov_row = conn.execute(
                """
                SELECT COUNT(*) as ops, COALESCE(SUM(cost_usd), 0) as cost
                FROM provenance_records
                WHERE topic_id = ?
                """,
                (topic_id,),
            ).fetchone()
        finally:
            conn.close()

        payload = {
            "stage_history": stage_history,
            "stages_traversed": len(stage_history),
            "review_issues": {
                "total": issue_row["total"] if issue_row else 0,
                "resolved": issue_row["resolved"] if issue_row else 0,
                "critical": issue_row["critical"] if issue_row else 0,
            },
            "artifacts_by_stage": {
                r["stage"]: r["cnt"] for r in artifact_counts
            },
            "provenance": {
                "total_operations": prov_row["ops"] if prov_row else 0,
                "total_cost_usd": float(prov_row["cost"]) if prov_row else 0.0,
            },
        }

        return self._artifact_manager.record(
            project_id=project_id,
            topic_id=topic_id,
            stage="finalize",
            artifact_type="process_summary",
            title="Research Process Summary",
            payload=payload,
            metadata={"stages_traversed": len(stage_history)},
        )
