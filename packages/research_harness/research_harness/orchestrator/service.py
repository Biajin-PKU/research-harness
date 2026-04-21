"""OrchestratorService: high-level orchestration API.

Used by CLI, MCP, and dashboard.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from ..config import load_runtime_config
from ..storage.db import Database
from .artifacts import ArtifactManager
from .models import (
    GateDecision,
    GateStatus,
    OrchestratorRun,
    ProjectArtifact,
    StageEvent,
    StageName,
    StageStatus,
    WorkflowMode,
)
from .models import STAGE_GRAPH, SUBSTEP_TO_STAGE
from .stages import (
    ARTIFACT_STAGE_ALIASES,
    STAGE_ORDER,
    get_required_artifacts,
    next_stage,
    resolve_stage,
)
from .adversarial import AdversarialLoop, Objection
from .integrity import FinalizeManager, IntegrityVerifier
from .review import ReviewManager
from .transitions import GateEvaluator, TransitionValidator


class OrchestratorService:
    """Service layer for orchestrator state management."""

    def __init__(self, db: Database | None = None):
        self._db = db or Database(load_runtime_config().db_path)
        self._validator = TransitionValidator(self._db)
        self._gate_evaluator = GateEvaluator(self._db)
        self._artifact_manager = ArtifactManager(self._db)
        self._adversarial = AdversarialLoop(self._db)
        self._review = ReviewManager(self._db)
        self._integrity = IntegrityVerifier(self._db)
        self._finalize = FinalizeManager(self._db)

    # -----------------------------------------------------------------------
    # Run lifecycle
    # -----------------------------------------------------------------------

    def init_run(
        self,
        project_id: int,
        topic_id: int,
        mode: WorkflowMode = "standard",
    ) -> OrchestratorRun:
        """Create a new orchestrator run for a project."""
        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO orchestrator_runs
                (project_id, topic_id, mode, current_stage, stage_status)
                VALUES (?, ?, ?, 'init', 'in_progress')
                """,
                (project_id, topic_id, mode),
            )
            run_id = int(cur.lastrowid)

            # Record initial stage event (single transaction with run insert)
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, project_id, topic_id, from_stage, to_stage, event_type, status, actor, rationale)
                VALUES (?, ?, ?, '', 'init', 'init', 'in_progress', 'system', 'Orchestrator run initialized')
                """,
                (run_id, project_id, topic_id),
            )
            conn.commit()

            return self.get_run(project_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def infer_stage_from_artifacts(self, project_id: int) -> str:
        """Return the furthest V2 stage that has at least one artifact covering it.

        Handles artifacts stored under both V2 stage names and legacy substep
        names.  Falls back to ``init`` if no matching artifacts exist.
        """
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT stage, artifact_type FROM project_artifacts WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        finally:
            conn.close()

        covered_stages: set[str] = set()
        for row in rows:
            stage = row["stage"]
            artifact_type = row["artifact_type"]
            # Resolve stage column (may be V2 name or legacy substep)
            resolved = resolve_stage(stage)
            if resolved in STAGE_ORDER:
                covered_stages.add(resolved)
            # Also resolve via legacy substep mapping
            substep_mapped = SUBSTEP_TO_STAGE.get(stage)
            if substep_mapped:
                covered_stages.add(substep_mapped)
            # Alias lookup by artifact_type
            alias_mapped = ARTIFACT_STAGE_ALIASES.get(artifact_type)
            if alias_mapped:
                covered_stages.add(alias_mapped)

        if not covered_stages:
            return "init"

        # Return the last (furthest) stage in canonical V2 order that is covered
        for stage in reversed(STAGE_ORDER):
            if stage in covered_stages:
                return stage
        return "init"

    def resume_run(
        self,
        project_id: int,
        topic_id: int,
        mode: WorkflowMode = "standard",
        force_stage: str | None = None,
        stop_before: str | None = None,
    ) -> OrchestratorRun:
        """Resume (or create) an orchestrator run, inferring the current stage
        from existing artifacts instead of always starting at ``topic_framing``.

        If a run already exists for ``project_id``, returns it unchanged unless
        ``force_stage`` is given, in which case the stage is overwritten.

        If no run exists, creates one at the inferred stage (or ``force_stage``).
        """
        if force_stage:
            force_stage = resolve_stage(force_stage)
        if stop_before:
            stop_before = resolve_stage(stop_before)
        existing = self.get_run(project_id)
        if existing is not None:
            # Update stop_before if provided
            if stop_before is not None:
                conn = self._db.connect()
                try:
                    conn.execute(
                        "UPDATE orchestrator_runs SET stop_before = ? WHERE project_id = ?",
                        (stop_before, project_id),
                    )
                    conn.commit()
                except Exception:
                    logger.warning(
                        "Failed to persist stop_before for project %s",
                        project_id, exc_info=True,
                    )
                finally:
                    conn.close()
            if force_stage and force_stage != existing.current_stage:
                conn = self._db.connect()
                try:
                    conn.execute(
                        """
                        UPDATE orchestrator_runs
                        SET current_stage = ?, stage_status = 'in_progress',
                            updated_at = datetime('now')
                        WHERE project_id = ?
                        """,
                        (force_stage, project_id),
                    )
                    conn.execute(
                        """
                        INSERT INTO orchestrator_stage_events
                        (run_id, project_id, topic_id, from_stage, to_stage,
                         event_type, status, actor, rationale)
                        VALUES (?, ?, ?, ?, ?, 'resume', 'in_progress', 'system', ?)
                        """,
                        (
                            existing.id,
                            project_id,
                            topic_id,
                            existing.current_stage,
                            force_stage,
                            f"Stage overridden to {force_stage} via resume_run(force_stage=...)",
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                return self.get_run(project_id)
            return existing

        inferred = force_stage or self.infer_stage_from_artifacts(project_id)
        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO orchestrator_runs
                (project_id, topic_id, mode, current_stage, stage_status, stop_before)
                VALUES (?, ?, ?, ?, 'in_progress', ?)
                """,
                (project_id, topic_id, mode, inferred, stop_before or ""),
            )
            run_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, project_id, topic_id, from_stage, to_stage,
                 event_type, status, actor, rationale)
                VALUES (?, ?, ?, '', ?, 'init', 'in_progress', 'system', ?)
                """,
                (
                    run_id,
                    project_id,
                    topic_id,
                    inferred,
                    f"Run resumed at inferred stage: {inferred}",
                ),
            )
            conn.commit()
            return self.get_run(project_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_run(self, project_id: int) -> OrchestratorRun | None:
        """Fetch the current orchestrator run for a project."""
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM orchestrator_runs WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_run(row)
        finally:
            conn.close()

    def get_status(self, project_id: int) -> dict[str, Any]:
        """Return a rich status dict for a project."""
        run = self.get_run(project_id)
        if run is None:
            return {"error": "No orchestrator run found for this project"}

        # Check required artifacts for current stage
        artifacts_check = self._validator.check_artifacts_for_stage(
            project_id, run.current_stage
        )

        # Evaluate gate
        gate_decision = self._gate_evaluator.evaluate(project_id, run.current_stage)

        # Count active artifacts
        conn = self._db.connect()
        try:
            artifact_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM project_artifacts WHERE project_id = ? AND status = 'active'",
                (project_id,),
            ).fetchone()["cnt"]

            issue_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM review_issues WHERE project_id = ? AND status = 'open'",
                (project_id,),
            ).fetchone()["cnt"]
        finally:
            conn.close()

        missing_artifacts = [
            art for art, exists in artifacts_check.items() if not exists
        ]

        return {
            "run": {
                "id": run.id,
                "project_id": run.project_id,
                "topic_id": run.topic_id,
                "mode": run.mode,
                "current_stage": run.current_stage,
                "stage_status": run.stage_status,
                "gate_status": gate_decision,
                "blocking_issue_count": run.blocking_issue_count,
                "unresolved_issue_count": run.unresolved_issue_count,
            },
            "stage": {
                "required_artifacts": list(get_required_artifacts(run.current_stage)),
                "artifacts_present": artifacts_check,
                "missing_artifacts": missing_artifacts,
            },
            "gate": {
                "decision": gate_decision,
                "can_advance": gate_decision == "pass" and not missing_artifacts,
            },
            "summary": {
                "total_artifacts": artifact_count,
                "open_issues": issue_count,
            },
        }

    # -----------------------------------------------------------------------
    # Artifact management
    # -----------------------------------------------------------------------

    def record_artifact(
        self,
        project_id: int,
        topic_id: int,
        stage: StageName,
        artifact_type: str,
        title: str = "",
        path: str = "",
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_artifact_id: int | None = None,
        provenance_record_id: int | None = None,
        dependency_artifact_ids: list[int] | None = None,
        dependency_type: str = "consumed_by",
        propagate_stale_from_previous: bool = True,
    ) -> ProjectArtifact:
        """Record a new artifact for a stage."""
        previous = self._artifact_manager.get_latest(project_id, stage, artifact_type)
        artifact = self._artifact_manager.record(
            project_id=project_id,
            topic_id=topic_id,
            stage=stage,
            artifact_type=artifact_type,
            title=title,
            path=path,
            payload=payload,
            metadata=metadata,
            parent_artifact_id=parent_artifact_id,
            provenance_record_id=provenance_record_id,
        )
        for upstream_id in dependency_artifact_ids or []:
            self._artifact_manager.add_dependency(
                from_artifact_id=upstream_id,
                to_artifact_id=artifact.id,
                dependency_type=dependency_type,
            )
        if (
            previous is not None
            and previous.id != artifact.id
            and propagate_stale_from_previous
        ):
            self._artifact_manager.mark_stale(
                previous.id,
                reason=(
                    f"artifact superseded by newer {artifact_type} "
                    f"version {artifact.version} (artifact #{artifact.id})"
                ),
                propagate=True,
            )
        return artifact

    def list_artifacts(
        self,
        project_id: int,
        stage: StageName | None = None,
        artifact_type: str | None = None,
    ) -> list[ProjectArtifact]:
        """List artifacts for a project."""
        return self._artifact_manager.list_by_project(
            project_id=project_id,
            stage=stage,
            artifact_type=artifact_type,
        )

    def get_latest_artifact(
        self,
        project_id: int,
        stage: StageName,
        artifact_type: str,
    ) -> ProjectArtifact | None:
        """Get the latest artifact of a given type."""
        return self._artifact_manager.get_latest(project_id, stage, artifact_type)

    def add_artifact_dependency(
        self,
        from_artifact_id: int,
        to_artifact_id: int,
        dependency_type: str = "consumed_by",
    ) -> dict[str, Any]:
        """Declare that one artifact depends on another."""
        upstream = self._artifact_manager.get(from_artifact_id)
        downstream = self._artifact_manager.get(to_artifact_id)
        if upstream is None:
            return {"success": False, "error": f"Artifact not found: {from_artifact_id}"}
        if downstream is None:
            return {"success": False, "error": f"Artifact not found: {to_artifact_id}"}
        self._artifact_manager.add_dependency(
            from_artifact_id=from_artifact_id,
            to_artifact_id=to_artifact_id,
            dependency_type=dependency_type,
        )
        return {
            "success": True,
            "from_artifact_id": from_artifact_id,
            "to_artifact_id": to_artifact_id,
            "dependency_type": dependency_type,
        }

    def mark_artifact_stale(
        self,
        artifact_id: int,
        reason: str = "",
        propagate: bool = True,
    ) -> dict[str, Any]:
        """Mark an artifact stale and optionally propagate to dependents."""
        artifact = self._artifact_manager.get(artifact_id)
        if artifact is None:
            return {"success": False, "error": f"Artifact not found: {artifact_id}"}
        stale_ids = self._artifact_manager.mark_stale(
            artifact_id=artifact_id,
            reason=reason,
            propagate=propagate,
        )
        return {
            "success": True,
            "artifact_id": artifact_id,
            "propagate": propagate,
            "stale_ids": stale_ids,
        }

    def clear_artifact_stale(self, artifact_id: int) -> dict[str, Any]:
        """Clear stale state for an artifact."""
        artifact = self._artifact_manager.get(artifact_id)
        if artifact is None:
            return {"success": False, "error": f"Artifact not found: {artifact_id}"}
        self._artifact_manager.clear_stale(artifact_id)
        return {"success": True, "artifact_id": artifact_id}

    def list_stale_artifacts(self, project_id: int) -> list[ProjectArtifact]:
        """List active stale artifacts for a project."""
        return self._artifact_manager.list_stale(project_id)

    # -----------------------------------------------------------------------
    # Stage advancement
    # -----------------------------------------------------------------------

    def advance(
        self,
        project_id: int,
        actor: str = "system",
        auto_run_gates: bool = True,
    ) -> dict[str, Any]:
        """Attempt to advance the project to the next stage."""
        run = self.get_run(project_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}

        current = run.current_stage

        # 1. Check if there's a next stage
        nxt = next_stage(current)
        if nxt is None:
            return {
                "success": False,
                "error": "No next stage (already at finalize)",
                "stage": current,
            }

        # 1b. Check stop_before gate
        if run.stop_before and nxt == run.stop_before:
            return {
                "success": False,
                "error": (
                    f"Hard stop: stop_before='{run.stop_before}' is set. "
                    f"Stage '{current}' is complete but advance to '{nxt}' is blocked. "
                    f"Use orchestrator_resume with stop_before='' to clear, "
                    f"or review the output of '{current}' before proceeding."
                ),
                "stage": current,
                "stop_before": run.stop_before,
                "completed_stage": current,
            }

        # 2. Check required artifacts exist
        allowed, reason, advisories = self._validator.can_advance(project_id, current, nxt)
        if not allowed:
            return {
                "success": False,
                "error": reason,
                "stage": current,
            }

        # 3. Check gate
        if auto_run_gates:
            gate_decision = self._gate_evaluator.evaluate(project_id, current)
            if gate_decision == "needs_expansion" and current == "analyze":
                loopback_result = self._try_gap_loopback(run, actor)
                if loopback_result is not None:
                    return loopback_result
            if gate_decision != "pass":
                return {
                    "success": False,
                    "error": f"Gate check failed: {gate_decision}",
                    "gate_decision": gate_decision,
                    "stage": current,
                }

        # Perform transition
        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE orchestrator_runs
                SET current_stage = ?, stage_status = 'in_progress', updated_at = datetime('now')
                WHERE project_id = ?
                """,
                (nxt, project_id),
            )
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, project_id, topic_id, from_stage, to_stage, event_type, status, actor, rationale)
                VALUES (?, ?, ?, ?, ?, 'advance', 'in_progress', ?, ?)
                """,
                (
                    run.id,
                    project_id,
                    run.topic_id,
                    current,
                    nxt,
                    actor,
                    f"Advanced from {current} to {nxt}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # Auto-extract lessons from the completed stage
        self._auto_extract_lessons(current, project_id, run.topic_id)

        # Auto-housekeeping: promote draft strategies, check stale, patch
        self._auto_housekeeping()

        result: dict[str, Any] = {
            "success": True,
            "from_stage": current,
            "to_stage": nxt,
            "gate_decision": "pass" if auto_run_gates else "skipped",
        }
        if advisories:
            result["advisories"] = advisories
        return result

    MAX_GAP_LOOPBACKS = 2

    def _try_gap_loopback(
        self, run: OrchestratorRun, actor: str,
    ) -> dict[str, Any] | None:
        """Attempt an automatic analyze→build loopback when gaps are insufficient.

        Returns a result dict if the loopback was performed (or exhausted),
        or None to fall through to the normal gate-failure path.
        """
        conn = self._db.connect()
        try:
            loopback_count = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM orchestrator_stage_events
                WHERE project_id = ? AND from_stage = 'analyze' AND to_stage = 'build'
                      AND event_type = 'transition'
                """,
                (run.project_id,),
            ).fetchone()["cnt"]
        finally:
            conn.close()

        if loopback_count >= self.MAX_GAP_LOOPBACKS:
            return None

        rationale = (
            f"Gap-triggered loopback (round {loopback_count + 1}/{self.MAX_GAP_LOOPBACKS}): "
            f"insufficient research gaps detected — expanding paper pool"
        )
        result = self.transition_to(
            run.project_id, "build", rationale=rationale, actor=actor,
        )
        if not result.get("success"):
            return None

        self.record_decision(
            project_id=run.project_id,
            topic_id=run.topic_id,
            stage="analyze",
            checkpoint="gap_expansion_loopback",
            choice=f"loopback_round_{loopback_count + 1}",
            reasoning=rationale,
        )

        logger.info(
            "Auto loopback analyze→build for project %d (round %d)",
            run.project_id, loopback_count + 1,
        )
        return {
            "success": True,
            "loopback": True,
            "from_stage": "analyze",
            "to_stage": "build",
            "round": loopback_count + 1,
            "max_rounds": self.MAX_GAP_LOOPBACKS,
            "gate_decision": "needs_expansion",
        }

    def _auto_housekeeping(self) -> None:
        """Run housekeeping: promote draft strategies, check/patch stale ones."""
        try:
            from ..evolution.patcher import StrategyPatcher

            patcher = StrategyPatcher(self._db)

            # 1. Promote draft strategies that passed probation
            promoted = patcher.check_promotions()
            if promoted:
                logger.info("Auto-promoted %d strategies from draft to active", len(promoted))

            # 2. Check stale strategies and auto-patch
            conn = self._db.connect()
            try:
                active_rows = conn.execute(
                    "SELECT id FROM strategies WHERE status = 'active'"
                ).fetchall()
            finally:
                conn.close()

            for row in active_rows:
                stale = patcher.check_stale(row["id"])
                if stale.is_stale:
                    logger.info(
                        "Strategy %d is stale (%s), attempting patch",
                        row["id"], stale.reason,
                    )
                    # Patch is LLM-powered — only attempt if stale
                    # (actual patching deferred to explicit strategy_patch call
                    #  to avoid surprise LLM costs during advance)
                    pass  # Log only; explicit patch via MCP tool

        except Exception:
            logger.debug("Auto-housekeeping failed", exc_info=True)

    def _auto_extract_lessons(
        self, stage: str, project_id: int, topic_id: int | None,
    ) -> None:
        """Auto-extract lessons from a completed stage (best-effort, non-blocking)."""
        try:
            from ..evolution.store import DBLessonStore, Lesson

            # Build a minimal summary from recent provenance
            conn = self._db.connect()
            try:
                rows = conn.execute(
                    """SELECT primitive, success, COUNT(*) as cnt,
                              SUM(cost_usd) as cost
                       FROM provenance_records
                       WHERE stage = ? AND topic_id = ?
                       GROUP BY primitive, success
                       ORDER BY cnt DESC LIMIT 10""",
                    (stage, topic_id),
                ).fetchall()
            finally:
                conn.close()

            if not rows:
                return

            # Build issues from failed primitives
            issues: list[str] = []
            summary_parts: list[str] = []
            for r in rows:
                if r["success"]:
                    summary_parts.append(f"{r['primitive']}: {r['cnt']} calls, ${r['cost'] or 0:.4f}")
                else:
                    issues.append(f"{r['primitive']} failed {r['cnt']} times")

            stage_summary = f"Stage {stage} completed. " + "; ".join(summary_parts[:5])

            # Store lessons directly (stub-level, no LLM call to avoid blocking)
            store = DBLessonStore(self._db)
            for issue in issues:
                store.append(
                    Lesson(stage=stage, content=issue, lesson_type="failure", tags=[stage]),
                    source="auto_extracted",
                    source_project_id=project_id,
                    topic_id=topic_id,
                )
            if stage_summary:
                store.append(
                    Lesson(stage=stage, content=stage_summary, lesson_type="observation", tags=[stage]),
                    source="auto_extracted",
                    source_project_id=project_id,
                    topic_id=topic_id,
                )

            logger.info("Auto-extracted %d lessons from stage %s", len(issues) + 1, stage)
        except Exception:
            logger.debug("Auto lesson extraction failed for stage %s", stage, exc_info=True)

    def transition_to(
        self,
        project_id: int,
        target_stage: StageName,
        *,
        rationale: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Transition to any stage allowed by STAGE_GRAPH (including loopbacks).

        Unlike advance() which only moves linearly, this allows jumps
        defined in STAGE_GRAPH — e.g. propose → build, write → experiment.
        """
        run = self.get_run(project_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}

        current = run.current_stage
        valid_targets = STAGE_GRAPH.get(current, frozenset())
        if target_stage not in valid_targets:
            return {
                "success": False,
                "error": (
                    f"Invalid transition: {current} → {target_stage}. "
                    f"Valid targets: {sorted(valid_targets)}"
                ),
                "stage": current,
            }

        conn = self._db.connect()
        try:
            conn.execute(
                """
                UPDATE orchestrator_runs
                SET current_stage = ?, stage_status = 'in_progress', updated_at = datetime('now')
                WHERE project_id = ?
                """,
                (target_stage, project_id),
            )
            conn.execute(
                """
                INSERT INTO orchestrator_stage_events
                (run_id, project_id, topic_id, from_stage, to_stage, event_type, status, actor, rationale)
                VALUES (?, ?, ?, ?, ?, 'transition', 'in_progress', ?, ?)
                """,
                (
                    run.id,
                    project_id,
                    run.topic_id,
                    current,
                    target_stage,
                    actor,
                    rationale or f"Transition from {current} to {target_stage}",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "success": True,
            "from_stage": current,
            "to_stage": target_stage,
            "transition_type": "loopback" if target_stage != next_stage(current) else "linear",
        }

    def check_gate(self, project_id: int, stage: StageName | None = None) -> GateDecision:
        """Evaluate the gate for a stage (defaults to current stage)."""
        if stage is None:
            run = self.get_run(project_id)
            if run is None:
                return "fail"
            stage = run.current_stage
        return self._gate_evaluator.evaluate(project_id, stage)

    # -----------------------------------------------------------------------
    # Adversarial optimization
    # -----------------------------------------------------------------------

    def run_adversarial_round(
        self,
        project_id: int,
        target_artifact_id: int,
        proposal_snapshot: dict[str, Any],
        objections: list[dict[str, Any]],
        proposer_responses: list[dict[str, Any]] | None = None,
        resolver_notes: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Run one adversarial round and record it as an artifact."""
        run = self.get_run(project_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}

        # Convert dict objections to Objection objects
        objection_objs = [
            Objection(
                category=o.get("category", ""),
                severity=o.get("severity", "minor"),
                target=o.get("target", ""),
                reasoning=o.get("reasoning", ""),
                suggested_fix=o.get("suggested_fix", ""),
            )
            for o in objections
        ]

        # Count existing rounds
        round_count = self._adversarial._count_rounds(project_id, run.current_stage)
        round_number = round_count + 1

        result = self._adversarial.run_round(
            project_id=project_id,
            topic_id=run.topic_id,
            target_artifact_id=target_artifact_id,
            target_stage=run.current_stage,
            round_number=round_number,
            proposal_snapshot=proposal_snapshot,
            objections=objection_objs,
            proposer_responses=proposer_responses or [],
            resolver_notes=resolver_notes,
        )

        return {
            "success": True,
            "artifact_id": result["artifact_id"],
            "round_number": round_number,
            "stage": run.current_stage,
        }

    def resolve_adversarial_round(
        self,
        project_id: int,
        round_artifact_id: int,
        scores: dict[str, float] | None = None,
        notes: str = "",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Resolve an adversarial round and determine outcome."""
        run = self.get_run(project_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}

        # Get round number from artifact
        round_artifact = self._artifact_manager.get(round_artifact_id)
        if round_artifact is None:
            return {"success": False, "error": f"Round artifact {round_artifact_id} not found"}

        round_number = round_artifact.metadata.get("round_number", 1)

        result = self._adversarial.resolve_round(
            project_id=project_id,
            topic_id=run.topic_id,
            target_stage=run.current_stage,
            round_number=round_number,
            round_artifact_id=round_artifact_id,
            scores=scores or {},
            notes=notes,
        )

        resolution = result["resolution"]

        return {
            "success": True,
            "artifact_id": result["artifact_id"],
            "outcome": resolution["outcome"],
            "mean_score": resolution["mean_score"],
            "critical_unresolved": resolution["critical_unresolved"],
            "major_unresolved": resolution["major_unresolved"],
            "should_repeat": resolution["outcome"] == "revise_and_repeat",
            "stage": run.current_stage,
        }

    def check_adversarial_status(self, project_id: int) -> dict[str, Any]:
        """Check current adversarial status for the project."""
        run = self.get_run(project_id)
        if run is None:
            return {"error": "No orchestrator run found"}

        # Get latest resolution
        resolution_artifact = self._adversarial._artifact_manager.get_latest(
            project_id, run.current_stage, "adversarial_resolution"
        )

        if resolution_artifact is None:
            # Check if there are any rounds
            round_count = self._adversarial._count_rounds(project_id, run.current_stage)
            return {
                "has_resolution": False,
                "round_count": round_count,
                "stage": run.current_stage,
                "status": "no_resolution_yet",
            }

        from .adversarial import AdversarialResolution
        resolution = AdversarialResolution.from_payload(resolution_artifact.payload)

        should_repeat, reason = self._adversarial.should_repeat(
            project_id, run.current_stage, run.mode
        )

        return {
            "has_resolution": True,
            "outcome": resolution.outcome,
            "mean_score": resolution.mean_score,
            "critical_unresolved": resolution.critical_unresolved,
            "major_unresolved": resolution.major_unresolved,
            "round_number": resolution.round_number,
            "should_repeat": should_repeat,
            "reason": reason,
            "stage": run.current_stage,
        }

    # -----------------------------------------------------------------------
    # Review management
    # -----------------------------------------------------------------------

    def create_review_bundle(
        self,
        project_id: int,
        integrity_artifact_id: int | None = None,
        scholarly_artifact_id: int | None = None,
    ) -> dict[str, Any]:
        """Create a review bundle linking review report artifacts."""
        run = self.get_run(project_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}
        bundle = self._review.create_bundle(
            project_id,
            run.topic_id,
            run.current_stage,
            integrity_artifact_id,
            scholarly_artifact_id,
        )
        return {
            "success": True,
            "artifact_id": bundle.id,
            "stage": run.current_stage,
            "cycle_number": bundle.metadata.get("cycle_number", 1),
        }

    def add_review_issue(
        self,
        project_id: int,
        review_type: str,
        severity: str,
        category: str,
        summary: str,
        details: str = "",
        blocking: bool = False,
        recommended_action: str = "",
        review_artifact_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a review finding as an issue."""
        run = self.get_run(project_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}
        issue = self._review.add_issue(
            project_id=project_id,
            topic_id=run.topic_id,
            stage=run.current_stage,
            review_type=review_type,
            severity=severity,
            category=category,
            summary=summary,
            details=details,
            blocking=blocking,
            recommended_action=recommended_action,
            review_artifact_id=review_artifact_id,
        )
        return {
            "success": True,
            "issue_id": issue.id,
            "severity": issue.severity,
            "blocking": issue.blocking,
            "stage": run.current_stage,
        }

    def respond_to_issue(
        self,
        issue_id: int,
        project_id: int,
        response_type: str,
        response_text: str,
        artifact_id: int | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a response to a review issue."""
        response = self._review.add_response(
            issue_id=issue_id,
            project_id=project_id,
            response_type=response_type,
            response_text=response_text,
            artifact_id=artifact_id,
            evidence=evidence,
        )
        return {
            "success": True,
            "response_id": response.id,
            "response_type": response.response_type,
        }

    def resolve_review_issue(
        self,
        issue_id: int,
        resolution_status: str = "resolved",
    ) -> dict[str, Any]:
        """Mark a review issue as resolved or wontfix."""
        issue = self._review.resolve_issue(issue_id, resolution_status)
        return {
            "success": True,
            "issue_id": issue.id,
            "status": issue.status,
        }

    def list_review_issues(
        self,
        project_id: int,
        stage: str | None = None,
        status: str | None = None,
        blocking_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List review issues with optional filters."""
        issues = self._review.list_issues(
            project_id=project_id,
            stage=stage,
            status=status,
            blocking_only=blocking_only,
        )
        return [
            {
                "id": i.id,
                "severity": i.severity,
                "category": i.category,
                "summary": i.summary,
                "status": i.status,
                "blocking": i.blocking,
                "review_type": i.review_type,
                "stage": i.stage,
            }
            for i in issues
        ]

    def get_review_status(self, project_id: int) -> dict[str, Any]:
        """Get review summary for a project."""
        run = self.get_run(project_id)
        if run is None:
            return {"error": "No orchestrator run found"}
        return self._review.get_review_summary(project_id, run.current_stage)

    # -----------------------------------------------------------------------
    # Integrity verification & finalize
    # -----------------------------------------------------------------------

    def run_integrity_check(
        self,
        project_id: int,
        findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run 5-phase integrity verification and persist report."""
        run = self.get_run(project_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}
        report = self._integrity.run_check(
            project_id=project_id,
            topic_id=run.topic_id,
            stage=run.current_stage,
            findings=findings,
        )
        return {
            "success": True,
            "passed": report.passed,
            "phases_completed": report.phases_completed,
            "critical_count": report.critical_count,
            "high_count": report.high_count,
            "medium_count": report.medium_count,
            "low_count": report.low_count,
            "total_findings": len(report.findings),
            "stage": run.current_stage,
        }

    def finalize_project(
        self,
        project_id: int,
    ) -> dict[str, Any]:
        """Create final_bundle and process_summary artifacts."""
        run = self.get_run(project_id)
        if run is None:
            return {"success": False, "error": "No orchestrator run found"}
        bundle = self._finalize.create_final_bundle(project_id, run.topic_id)
        summary = self._finalize.create_process_summary(project_id, run.topic_id)
        return {
            "success": True,
            "bundle_artifact_id": bundle.id,
            "summary_artifact_id": summary.id,
            "artifact_count": bundle.payload.get("artifact_count", 0),
            "stages_traversed": summary.payload.get("stages_traversed", 0),
            "stage": run.current_stage,
        }

    def record_experiment_run(
        self,
        project_id: int,
        *,
        iteration: int = 1,
        code_hash: str = "",
        primary_metric_name: str = "",
        primary_metric_value: float = 0.0,
        metrics: dict | None = None,
        kept: bool = True,
    ) -> None:
        """Insert an experiment_runs row (public API for auto_runner)."""
        import json as _json

        conn = self._db.connect()
        try:
            conn.execute(
                """INSERT INTO experiment_runs
                   (project_id, iteration, code_hash, primary_metric_name,
                    primary_metric_value, all_metrics_json, kept)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, iteration, code_hash, primary_metric_name,
                 primary_metric_value, _json.dumps(metrics or {}),
                 1 if kept else 0),
            )
            conn.commit()
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Decision log
    # -----------------------------------------------------------------------

    def record_decision(
        self,
        project_id: int,
        topic_id: int,
        stage: str,
        checkpoint: str,
        choice: str,
        reasoning: str = "",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a human (or auto) decision at a checkpoint."""
        import json as _json

        conn = self._db.connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO decision_log
                (project_id, topic_id, stage, checkpoint, choice, reasoning, params_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    topic_id,
                    resolve_stage(stage),
                    checkpoint,
                    choice,
                    reasoning,
                    _json.dumps(params or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            return {
                "success": True,
                "decision_id": cur.lastrowid,
                "stage": resolve_stage(stage),
                "checkpoint": checkpoint,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_decisions(
        self,
        project_id: int,
        stage: str | None = None,
    ) -> list[dict[str, Any]]:
        """List decision log entries for a project."""
        conn = self._db.connect()
        try:
            if stage:
                rows = conn.execute(
                    "SELECT * FROM decision_log WHERE project_id = ? AND stage = ? ORDER BY created_at",
                    (project_id, resolve_stage(stage)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM decision_log WHERE project_id = ? ORDER BY created_at",
                    (project_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _row_to_run(row: Any) -> OrchestratorRun:
        # stop_before may not exist in older DBs before migration 027
        try:
            stop_before = row["stop_before"] or ""
        except (IndexError, KeyError):
            stop_before = ""
        return OrchestratorRun(
            id=row["id"],
            project_id=row["project_id"],
            topic_id=row["topic_id"],
            mode=row["mode"],
            current_stage=row["current_stage"],
            stage_status=row["stage_status"],
            gate_status=row["gate_status"],
            blocking_issue_count=row["blocking_issue_count"],
            unresolved_issue_count=row["unresolved_issue_count"],
            latest_plan_artifact_id=row["latest_plan_artifact_id"],
            latest_draft_artifact_id=row["latest_draft_artifact_id"],
            stop_before=stop_before,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )
