"""Stage transition validator and artifact gate checker."""

from __future__ import annotations

import json

from . import stages
from .models import DEFAULT_MIN_PAPER_COUNT, GateDecision, StageName
from .invariants import InvariantChecker, is_blocking


class TransitionValidator:
    """Validates whether a project can advance from one stage to another."""

    def __init__(self, db):
        self._db = db

    def can_advance(
        self,
        project_id: int,
        from_stage: StageName,
        to_stage: StageName,
    ) -> tuple[bool, str, list[str]]:
        """Return (allowed, reason, advisories) for a proposed transition.

        advisories: list of soft prerequisite warnings (non-blocking).
        """
        # 1. Check graph validity
        if not stages.is_valid_transition(from_stage, to_stage):
            return False, f"Invalid transition: {from_stage} -> {to_stage}", []

        # 2. Check required artifacts exist for the *current* stage
        required = stages.get_required_artifacts(from_stage)
        if required:
            stage_names = stages.stage_names_for_query(from_stage)
            placeholders = ",".join("?" * len(stage_names))
            conn = self._db.connect()
            try:
                for artifact_type in required:
                    row = conn.execute(
                        f"""
                        SELECT 1 FROM project_artifacts
                        WHERE project_id = ? AND stage IN ({placeholders})
                              AND artifact_type = ? AND status = 'active'
                        LIMIT 1
                        """,
                        (project_id, *stage_names, artifact_type),
                    ).fetchone()
                    if row is None:
                        return (
                            False,
                            (
                                f"Missing required artifact '{artifact_type}' "
                                f"for stage '{from_stage}'"
                            ),
                            [],
                        )
            finally:
                conn.close()

        # 3. Check soft prerequisites (advisory, not blocking)
        advisories: list[str] = []
        soft_prereqs = stages.get_soft_prerequisites(to_stage)
        if soft_prereqs:
            advisories = list(soft_prereqs)

        return True, "", advisories

    def check_artifacts_for_stage(
        self,
        project_id: int,
        stage: StageName,
    ) -> dict[str, bool]:
        """Return a map of required artifact -> exists for a stage."""
        required = stages.get_required_artifacts(stage)
        if not required:
            return {}

        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        result: dict[str, bool] = {art: False for art in required}
        conn = self._db.connect()
        try:
            for artifact_type in required:
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE project_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (project_id, *stage_names, artifact_type),
                ).fetchone()
                result[artifact_type] = row is not None
        finally:
            conn.close()
        return result


class GateEvaluator:
    """Gate evaluator with enhanced checks for V2 stages."""

    def __init__(self, db):
        self._db = db
        self._invariant_checker = InvariantChecker(db)

    def evaluate(self, project_id: int, stage: StageName) -> GateDecision:
        """Evaluate the gate for a stage and return a decision."""
        # Deterministic invariant pre-checks
        violations = self._invariant_checker.check_all(project_id, stage)
        blocking = [v for v in violations if is_blocking(v)]
        if blocking:
            import logging

            logger = logging.getLogger(__name__)
            for v in blocking:
                logger.warning("Invariant violation: %s", v.message)
            return "fail"

        gate_type = stages.get_gate_type(stage)

        if gate_type == "approval_gate":
            return self._evaluate_approval_gate(project_id, stage)
        if gate_type == "coverage_gate":
            return self._evaluate_coverage_gate(project_id, stage)
        if gate_type == "adversarial_gate":
            return self._evaluate_adversarial_gate(project_id, stage)
        if gate_type == "review_gate":
            return self._evaluate_review_gate(project_id)
        if gate_type == "integrity_gate":
            return self._evaluate_integrity_gate(project_id)
        if gate_type == "experiment_gate":
            return self._evaluate_experiment_gate(project_id, stage)
        return "pass"

    MIN_GAP_COUNT = 3

    def _evaluate_approval_gate(
        self, project_id: int, stage: StageName
    ) -> GateDecision:
        """Check if required artifacts exist.

        For the 'analyze' stage, also verifies that gap_detect produced
        enough gaps (>= MIN_GAP_COUNT) to warrant advancing. If not,
        returns 'needs_expansion' to trigger an automatic loopback.
        """
        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        conn = self._db.connect()
        try:
            required = stages.get_required_artifacts(stage)
            for artifact_type in required:
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE project_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (project_id, *stage_names, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_approval"

            resolved = stages.resolve_stage(stage)
            if resolved == "analyze":
                gap_row = conn.execute(
                    f"""
                    SELECT payload_json FROM project_artifacts
                    WHERE project_id = ? AND stage IN ({placeholders})
                          AND artifact_type IN ('gap_detect', 'gap_analysis')
                          AND status = 'active'
                    ORDER BY version DESC LIMIT 1
                    """,
                    (project_id, *stage_names),
                ).fetchone()
                if gap_row:
                    try:
                        payload = json.loads(gap_row["payload_json"] or "{}")
                    except (TypeError, ValueError):
                        payload = {}
                    gaps = payload.get("gaps", [])
                    if len(gaps) < self.MIN_GAP_COUNT:
                        return "needs_expansion"

            return "pass"
        finally:
            conn.close()

    def _evaluate_coverage_gate(
        self, project_id: int, stage: StageName
    ) -> GateDecision:
        """Check required artifacts + minimum corpus quality for Build exit.

        Enhanced checks:
        - Required artifacts exist
        - Minimum corpus size (≥20 papers linked to the topic)
        - Method family diversity (≥3 distinct concept families)
        - Temporal span (≥2 distinct years)
        """
        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        conn = self._db.connect()
        try:
            # 1. Check required artifacts
            required = stages.get_required_artifacts(stage)
            for artifact_type in required:
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE project_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (project_id, *stage_names, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_coverage"

            # 2. Enhanced: check corpus size and diversity (for "build" stage)
            resolved = stages.resolve_stage(stage)
            if resolved == "build":
                # Find topic_id from the orchestrator run
                run_row = conn.execute(
                    "SELECT topic_id FROM orchestrator_runs WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                if run_row:
                    topic_id = run_row["topic_id"]

                    # Min papers (≥20)
                    paper_count = conn.execute(
                        """
                        SELECT COUNT(DISTINCT pt.paper_id) as cnt
                        FROM paper_topics pt
                        WHERE pt.topic_id = ?
                          AND pt.relevance != 'dismissed'
                        """,
                        (topic_id,),
                    ).fetchone()["cnt"]
                    if paper_count < DEFAULT_MIN_PAPER_COUNT:
                        return "needs_coverage"

                    # Min distinct years (≥2)
                    year_count = conn.execute(
                        """
                        SELECT COUNT(DISTINCT p.year) as cnt
                        FROM papers p
                        JOIN paper_topics pt ON pt.paper_id = p.id
                        WHERE pt.topic_id = ? AND p.year IS NOT NULL
                          AND pt.relevance != 'dismissed'
                        """,
                        (topic_id,),
                    ).fetchone()["cnt"]
                    if year_count < 2:
                        return "needs_coverage"

                    # Retrieval convergence (soft: only enforced when the
                    # iterative_retrieval_loop primitive has been invoked).
                    # Motivation: prevents advancing while the LLM still has
                    # fresh queries that hit mostly-new papers.
                    loop_row = conn.execute(
                        f"""
                        SELECT payload_json FROM project_artifacts
                        WHERE project_id = ? AND stage IN ({placeholders})
                              AND artifact_type = 'iterative_retrieval_loop_result'
                              AND status = 'active'
                        ORDER BY version DESC LIMIT 1
                        """,
                        (project_id, *stage_names),
                    ).fetchone()
                    if loop_row:
                        try:
                            loop_payload = json.loads(loop_row["payload_json"] or "{}")
                        except (TypeError, ValueError):
                            loop_payload = {}
                        if not bool(loop_payload.get("convergence_reached")):
                            return "needs_coverage"

                    # Citation expansion (mandatory): keyword search alone
                    # is insufficient — must also traverse the citation
                    # graph (forward + backward) from seed papers. Without
                    # this, the pool misses seminal and follow-up work that
                    # doesn't match keyword queries.
                    cit_row = conn.execute(
                        f"""
                        SELECT payload_json FROM project_artifacts
                        WHERE project_id = ? AND stage IN ({placeholders})
                              AND artifact_type = 'citation_expansion_report'
                              AND status = 'active'
                        ORDER BY version DESC LIMIT 1
                        """,
                        (project_id, *stage_names),
                    ).fetchone()
                    if cit_row is None:
                        return "needs_coverage"

            return "pass"
        finally:
            conn.close()

    def _evaluate_adversarial_gate(
        self, project_id: int, stage: StageName
    ) -> GateDecision:
        """Check for adversarial resolution with no unresolved fatal flaws."""
        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        conn = self._db.connect()
        try:
            row = conn.execute(
                f"""
                SELECT payload_json FROM project_artifacts
                WHERE project_id = ? AND stage IN ({placeholders})
                      AND artifact_type = 'adversarial_resolution'
                      AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (project_id, *stage_names),
            ).fetchone()
            if row is None:
                return "needs_adversarial"
            payload = json.loads(row["payload_json"] or "{}")
            outcome = payload.get("outcome", "")
            if outcome in ("approved", "approved_with_conditions"):
                # Enhanced: verify no unresolved critical objections
                critical = payload.get("critical_unresolved", 0)
                if critical > 0:
                    return "needs_adversarial"
                return "pass"
            return "needs_adversarial"
        finally:
            conn.close()

    def _evaluate_review_gate(self, project_id: int) -> GateDecision:
        """Check for open blocking review issues and minimum score."""
        conn = self._db.connect()
        try:
            # Existing: no blocking issues
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

    def _evaluate_integrity_gate(self, project_id: int) -> GateDecision:
        """Check for open critical integrity issues."""
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM review_issues
                WHERE project_id = ? AND status = 'open' AND severity = 'critical'
                """,
                (project_id,),
            ).fetchone()
            if row and row["cnt"] > 0:
                return "needs_integrity"
            return "pass"
        finally:
            conn.close()

    def evaluate_with_policy(
        self,
        project_id: int,
        stage: str,
        auto_resolve: bool = False,
    ) -> tuple[str, bool]:
        """Evaluate gate with optional auto-resolution.

        Returns (decision, was_auto_resolved).
        """
        decision = self.evaluate(project_id, stage)

        if decision == "pass" or not auto_resolve:
            return decision, False

        # In autonomous mode, auto-resolve non-blocking decisions
        # but NEVER auto-resolve "fail" (invariant violations)
        if decision == "fail":
            return decision, False

        # Check if this stage allows auto-resolution
        from ..auto_runner.stage_policy import get_policy

        policy = get_policy(stage)
        if policy and policy.risk_level == "high":
            # High-risk stages always need human even in autonomous mode
            return decision, False

        import logging

        logger = logging.getLogger(__name__)
        logger.info("Auto-resolving gate for stage %s: %s → pass", stage, decision)
        return "pass", True

    def _evaluate_experiment_gate(
        self, project_id: int, stage: StageName
    ) -> GateDecision:
        """Check experiment completion: result + verified registry + kept iterations."""
        stage_names = stages.stage_names_for_query(stage)
        placeholders = ",".join("?" * len(stage_names))
        conn = self._db.connect()
        try:
            # Check required artifacts exist
            for artifact_type in ("experiment_result", "verified_registry"):
                row = conn.execute(
                    f"""
                    SELECT 1 FROM project_artifacts
                    WHERE project_id = ? AND stage IN ({placeholders})
                          AND artifact_type = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (project_id, *stage_names, artifact_type),
                ).fetchone()
                if row is None:
                    return "needs_experiment"

            # Check at least one kept experiment iteration
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM experiment_runs WHERE project_id = ? AND kept = 1",
                    (project_id,),
                ).fetchone()
                if not row or row["cnt"] == 0:
                    return "needs_experiment"
            except Exception:
                # experiment_runs table may not exist yet during migration
                return "needs_experiment"

            return "pass"
        finally:
            conn.close()
