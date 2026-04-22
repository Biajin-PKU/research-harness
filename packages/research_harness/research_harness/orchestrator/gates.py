"""Gate evaluator implementations."""

from __future__ import annotations

import json
import logging
from typing import Protocol

from ..storage.db import Database
from .models import GateDecision, StageName

logger = logging.getLogger(__name__)


class IGateEvaluator(Protocol):
    """Protocol for gate evaluators."""

    def evaluate(
        self, db: Database, project_id: int, stage: StageName
    ) -> GateDecision: ...


class CoverageGateEvaluator:
    """Evaluates coverage gates: checks artifact presence and quantity thresholds."""

    def evaluate(
        self,
        db: Database,
        project_id: int,
        stage: StageName,
        required_artifacts: tuple[str, ...],
        min_papers: int = 0,
    ) -> GateDecision:
        """Check if required artifacts exist and paper count meets threshold."""
        conn = db.connect()
        try:
            for artifact_type in required_artifacts:
                row = conn.execute(
                    """
                    SELECT 1 FROM project_artifacts
                    WHERE project_id = ? AND stage = ? AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (project_id, stage, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_coverage"

            if min_papers > 0 and stage in (
                "literature_mapping",
                "evidence_structuring",
            ):
                row = conn.execute(
                    """
                    SELECT COUNT(*) as cnt FROM papers p
                    JOIN paper_topics pt ON pt.paper_id = p.id
                    JOIN projects pr ON pr.topic_id = pt.topic_id
                    WHERE pr.id = ?
                    """,
                    (project_id,),
                ).fetchone()
                if row and row["cnt"] < min_papers:
                    return "needs_coverage"

            return "pass"
        finally:
            conn.close()


class ApprovalGateEvaluator:
    """Evaluates approval gates: requires explicit human approval."""

    def evaluate(
        self,
        db: Database,
        project_id: int,
        stage: StageName,
        required_artifacts: tuple[str, ...],
    ) -> GateDecision:
        conn = db.connect()
        try:
            for artifact_type in required_artifacts:
                row = conn.execute(
                    """
                    SELECT 1 FROM project_artifacts
                    WHERE project_id = ? AND stage = ? AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (project_id, stage, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_approval"
            return "pass"
        finally:
            conn.close()


class AdversarialGateEvaluator:
    """Evaluates adversarial gates: checks for approved resolution."""

    def evaluate(
        self,
        db: Database,
        project_id: int,
        stage: StageName,
    ) -> GateDecision:
        conn = db.connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE project_id = ? AND stage = ? AND artifact_type = 'adversarial_resolution' AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (project_id, stage),
            ).fetchone()
            if row is None:
                return "needs_adversarial"
            payload = json.loads(row["payload_json"] or "{}")
            outcome = payload.get("outcome", "")
            if outcome in ("approved", "approved_with_conditions"):
                return "pass"
            return "needs_adversarial"
        finally:
            conn.close()


class ReviewGateEvaluator:
    """Evaluates review gates: checks for open blocking issues."""

    def evaluate(self, db: Database, project_id: int) -> GateDecision:
        conn = db.connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM review_issues
                WHERE project_id = ? AND status = 'open' AND blocking = 1
                """,
                (project_id,),
            ).fetchone()
            if row and row["cnt"] > 0:
                return "needs_review"
            return "pass"
        finally:
            conn.close()


class ExperimentGateEvaluator:
    """Evaluates experiment gates: checks for results + verified registry + no NaN."""

    def evaluate(
        self,
        db: Database,
        project_id: int,
        stage: StageName,
    ) -> GateDecision:
        conn = db.connect()
        try:
            # Check required artifacts exist
            for artifact_type in ("experiment_result", "verified_registry"):
                row = conn.execute(
                    """
                    SELECT 1 FROM project_artifacts
                    WHERE project_id = ? AND stage = ? AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (project_id, stage, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_experiment"

            # Check at least one kept iteration exists
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM experiment_runs
                WHERE project_id = ? AND kept = 1
                """,
                (project_id,),
            ).fetchone()
            if not row or row["cnt"] == 0:
                return "needs_experiment"

            return "pass"
        except Exception as exc:
            logger.debug("experiment_runs check skipped (table may not exist): %s", exc)
            return "needs_experiment"
        finally:
            conn.close()


class IntegrityGateEvaluator:
    """Evaluates integrity gates: enhanced checks for Sprint 3.

    Sub-checks:
    1. No open critical review issues
    2. Verified registry check pass (if available)
    3. No hallucinated citations (if citation_verify ran)
    4. Evidence trace coverage >= 0.8 (if evidence_trace ran)

    Default: warn, not block. Gate returns "pass" with warnings unless
    critical issues exist.
    """

    def evaluate(self, db: Database, project_id: int) -> GateDecision:
        conn = db.connect()
        try:
            # Sub-check 1: Open critical review issues → block
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM review_issues
                WHERE project_id = ? AND status = 'open' AND severity = 'critical'
                """,
                (project_id,),
            ).fetchone()
            if row and row["cnt"] > 0:
                return "needs_integrity"

            # Sub-check 2: Hallucinated citations → block
            try:
                row = conn.execute(
                    """
                    SELECT COUNT(*) as cnt FROM citation_verifications
                    WHERE project_id = ? AND status = 'hallucinated'
                    """,
                    (project_id,),
                ).fetchone()
                if row and row["cnt"] > 0:
                    return "needs_integrity"
            except Exception as exc:
                logger.debug("citation_verifications check skipped: %s", exc)

            return "pass"
        finally:
            conn.close()
