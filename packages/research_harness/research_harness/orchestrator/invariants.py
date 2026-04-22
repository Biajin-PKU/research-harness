"""Deterministic invariant checks for stage gates.

These checks run BEFORE LLM-based gate evaluation and are:
- Fast (no LLM calls)
- Deterministic (same input = same output)
- Non-bypassable (even in autonomous mode)

Inspired by OpenAI's "enforce invariants mechanically, not through documentation."
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..storage.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Artifact schema definitions (per artifact_type)
# ---------------------------------------------------------------------------

ARTIFACT_SCHEMAS: dict[str, dict[str, Any]] = {
    "topic_brief": {
        "required_fields": ["scope", "venue_target"],
        "description": "Topic framing output with scope and venue target",
    },
    "literature_map": {
        "required_fields": ["clusters"],
        "description": "Clustered literature mapping",
    },
    "paper_pool_snapshot": {
        "required_fields": ["paper_count"],
        "description": "Snapshot of paper pool state",
    },
    "evidence_pack": {
        "required_fields": ["claims"],
        "description": "Extracted claims and evidence links",
    },
    "direction_proposal": {
        "required_fields": ["research_question"],
        "description": "Proposed research direction with question and hypothesis",
    },
    "adversarial_resolution": {
        "required_fields": ["outcome"],
        "description": "Result of adversarial review round",
    },
    "study_spec": {
        "required_fields": ["methodology"],
        "description": "Experiment study design specification",
    },
    "experiment_result": {
        "required_fields": ["metrics"],
        "description": "Experiment execution results with metrics",
    },
    "verified_registry": {
        "required_fields": ["whitelist_size"],
        "description": "Verified number registry from experiment",
    },
    "draft_pack": {
        "required_fields": ["sections"],
        "description": "Drafted paper sections",
    },
}


class InvariantChecker:
    """Runs deterministic pre-checks before gate evaluation."""

    def __init__(self, db: Database):
        self._db = db

    def check_all(self, topic_id: int, stage: str) -> list[InvariantViolation]:
        """Run all invariant checks for a stage. Returns list of violations."""
        violations: list[InvariantViolation] = []
        violations.extend(self.check_artifact_schemas(topic_id, stage))
        violations.extend(self.check_no_stale_artifacts(topic_id, stage))
        violations.extend(self.check_provenance_linkage(topic_id, stage))
        violations.extend(self.check_section_citations(topic_id, stage))
        return violations

    def check_artifact_schemas(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Validate that artifact payloads match their type schemas."""
        violations: list[InvariantViolation] = []
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, payload_json, title
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                """,
                (topic_id,),
            ).fetchall()

            for row in rows:
                artifact_type = row["artifact_type"]
                schema = ARTIFACT_SCHEMAS.get(artifact_type)
                if schema is None:
                    continue  # No schema defined = no validation

                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    violations.append(
                        InvariantViolation(
                            check="artifact_schema",
                            severity="critical",
                            message=f"Artifact {row['id']} ({artifact_type}) has invalid JSON payload",
                            artifact_id=row["id"],
                        )
                    )
                    continue

                for field in schema.get("required_fields", []):
                    if field not in payload or not payload[field]:
                        violations.append(
                            InvariantViolation(
                                check="artifact_schema",
                                severity="medium",
                                message=(
                                    f"Artifact {row['id']} ({artifact_type}) missing "
                                    f"required field '{field}'"
                                ),
                                artifact_id=row["id"],
                            )
                        )
        finally:
            conn.close()

        return violations

    def check_no_stale_artifacts(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Verify no stale artifacts are being counted for gate evaluation."""
        violations: list[InvariantViolation] = []
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, stale, stale_reason
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active' AND stale = 1
                """,
                (topic_id,),
            ).fetchall()

            for row in rows:
                violations.append(
                    InvariantViolation(
                        check="stale_artifact",
                        severity="high",
                        message=(
                            f"Artifact {row['id']} ({row['artifact_type']}) is stale: "
                            f"{row['stale_reason'] or 'no reason given'}"
                        ),
                        artifact_id=row["id"],
                    )
                )
        finally:
            conn.close()

        return violations

    def check_provenance_linkage(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Check that critical artifacts have provenance records."""
        violations: list[InvariantViolation] = []
        # Critical artifact types that MUST have provenance
        critical_types = frozenset(
            {
                "evidence_pack",
                "direction_proposal",
                "experiment_result",
                "draft_pack",
                "adversarial_resolution",
            }
        )

        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, provenance_record_id
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                  AND artifact_type IN ({})
                """.format(",".join("?" * len(critical_types))),
                (topic_id, *critical_types),
            ).fetchall()

            for row in rows:
                if not row["provenance_record_id"]:
                    violations.append(
                        InvariantViolation(
                            check="provenance_linkage",
                            severity="medium",
                            message=(
                                f"Critical artifact {row['id']} ({row['artifact_type']}) "
                                "has no provenance record"
                            ),
                            artifact_id=row["id"],
                        )
                    )
        finally:
            conn.close()

        return violations

    def check_section_citations(
        self, topic_id: int, stage: str
    ) -> list[InvariantViolation]:
        """Check that draft sections contain citation markers."""
        violations: list[InvariantViolation] = []
        if stage not in ("write", "draft_preparation", "formal_review"):
            return violations

        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT id, artifact_type, payload_json
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active'
                  AND artifact_type = 'draft_pack'
                ORDER BY version DESC LIMIT 1
                """,
                (topic_id,),
            ).fetchall()

            for row in rows:
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    continue

                sections = payload.get("sections", {})
                for section_name, content in sections.items():
                    if section_name in ("abstract", "conclusion", "acknowledgments"):
                        continue  # These sections may not need citations
                    if isinstance(content, str) and len(content) > 200:
                        # Check for citation markers: \cite{}, [N], (Author, Year)
                        import re

                        has_cite = bool(
                            re.search(
                                r"\\cite\{|[\[\(]\d+[\]\)]|\(\w+,\s*\d{4}\)", content
                            )
                        )
                        if not has_cite:
                            violations.append(
                                InvariantViolation(
                                    check="section_citations",
                                    severity="medium",
                                    message=(
                                        f"Section '{section_name}' in draft_pack "
                                        f"({len(content)} chars) has no citation markers"
                                    ),
                                    artifact_id=row["id"],
                                )
                            )
        finally:
            conn.close()

        return violations


class InvariantViolation:
    """A single invariant check failure."""

    __slots__ = ("check", "severity", "message", "artifact_id")

    def __init__(
        self,
        check: str,
        severity: str,
        message: str,
        artifact_id: int | None = None,
    ):
        self.check = check
        self.severity = severity  # critical|high|medium|low
        self.message = message
        self.artifact_id = artifact_id

    def __repr__(self) -> str:
        return f"InvariantViolation({self.severity}: {self.message})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "artifact_id": self.artifact_id,
        }


def is_blocking(violation: InvariantViolation) -> bool:
    """Check if a violation should block gate progression."""
    return violation.severity in ("critical", "high")
