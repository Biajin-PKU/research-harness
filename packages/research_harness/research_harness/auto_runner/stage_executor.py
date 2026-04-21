"""Stage executor — runs one orchestrator stage through MCP tools.

The executor is called by the supervisor (runner.py) for each stage.
It uses OrchestratorService for DB operations and the MCP tools layer
for research primitives.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..orchestrator.service import OrchestratorService
from ..storage.db import Database
from . import checkpoint as ckpt
from .codex_bridge import (
    codex_issues_to_objections,
    load_handoff_response,
    run_codex_review,
    save_handoff_request,
    save_handoff_response,
)
from .stage_policy import (
    decide_recovery,
    get_policy,
    should_invoke_codex,
    should_pause_human,
)

logger = logging.getLogger(__name__)

# Tools that require LLM-constructed arguments and always return success=False
# from tool_dispatch. These are excluded from "all tools failed" detection.
_DEFERRED_TOOLS = frozenset({
    "adversarial_run", "adversarial_resolve", "adversarial_review",
    "integrity_check", "review_add_issue", "review_respond",
})


def execute_stage(
    *,
    db: Database,
    svc: OrchestratorService,
    project_id: int,
    topic_id: int,
    stage: str,
    mode: str,
    checkpoint_data: dict[str, Any],
    base_dir: Path,
    budget_monitor: "BudgetMonitor | None" = None,
) -> dict[str, Any]:
    """Execute one stage's tools and return the outcome.

    The executor runs tools and (optionally) codex review. It does NOT
    check the orchestrator gate — that responsibility belongs to runner.py
    via advance(), which is the single source of truth for stage transitions.

    Returns a dict with:
        status: "complete" | "needs_human" | "error" | "retry" | "fallback_stage" | "pause_human"
        stage: current stage name
        summary: one-line result
        error: error details if failed
    """
    policy = get_policy(stage)
    if policy is None:
        return {"status": "error", "stage": stage, "summary": f"Unknown stage: {stage}"}

    ckpt.update_stage(checkpoint_data, stage=stage, state="running")
    ckpt.record_event(checkpoint_data, stage=stage, event="stage_start",
                      detail=policy.description)

    # Reset stage_context to prevent stale key leakage between stages.
    # Preserve only cross-stage keys that are explicitly carried forward.
    prev_ctx = checkpoint_data.get("stage_context", {})
    fresh_ctx: dict[str, Any] = {}
    for keep_key in ("direction", "project_id"):
        if keep_key in prev_ctx:
            fresh_ctx[keep_key] = prev_ctx[keep_key]
    checkpoint_data["stage_context"] = fresh_ctx

    # LLM Planner: enrich stage_context before tool execution
    from .llm_planner import plan_stage

    try:
        planned = plan_stage(
            db=db, svc=svc,
            project_id=project_id, topic_id=topic_id,
            stage=stage, checkpoint_data=checkpoint_data,
        )
        if planned:
            checkpoint_data["stage_context"].update(planned)
            ckpt.record_event(checkpoint_data, stage=stage, event="planner_ok",
                              detail=f"keys={sorted(planned.keys())[:8]}")
    except Exception as exc:
        logger.warning("LLM planner failed for stage %s: %s", stage, exc, exc_info=True)
        ckpt.record_event(checkpoint_data, stage=stage, event="planner_error",
                          detail=str(exc)[:200])

    # Execute stage tools via orchestrator service
    try:
        result = _execute_stage_tools(
            db=db,
            svc=svc,
            project_id=project_id,
            topic_id=topic_id,
            stage=stage,
            checkpoint_data=checkpoint_data,
            budget_monitor=budget_monitor,
        )
    except Exception as exc:
        error_msg = str(exc)
        ckpt.record_error(checkpoint_data, kind="exception", message=error_msg)
        ckpt.record_event(checkpoint_data, stage=stage, event="tool_error",
                          detail=error_msg[:200])

        retry_count = checkpoint_data.get("last_error", {}).get("retry_count", 0)
        recovery = decide_recovery(stage, "exception", retry_count)
        return {
            "status": recovery,
            "stage": stage,
            "summary": f"Stage failed: {error_msg[:200]}",
            "error": error_msg,
        }

    # Record tool errors in checkpoint for visibility
    tool_errors = result.get("errors", [])
    if tool_errors:
        ckpt.record_event(checkpoint_data, stage=stage, event="tool_errors",
                          detail=f"{len(tool_errors)} tool(s) failed: {'; '.join(tool_errors[:3])}"[:200])

    # Track artifact IDs from orchestrator_record_artifact results
    for tr in result.get("tool_results", []):
        if tr.get("success") and tr.get("tool") == "orchestrator_record_artifact":
            output = tr.get("output", {})
            art_type = output.get("artifact_type", "")
            art_id = output.get("artifact_id", 0)
            if art_type and art_id:
                ckpt.record_artifact(checkpoint_data, stage=stage,
                                     artifact_type=art_type, artifact_id=art_id)

    # Track auto-recorded artifacts (gate-required artifacts from _record_auto_artifacts)
    for art_type, art_id in result.get("auto_artifacts", []):
        if art_type and art_id:
            ckpt.record_artifact(checkpoint_data, stage=stage,
                                 artifact_type=art_type, artifact_id=art_id)

    # If ALL tools failed, trigger recovery
    tool_results = result.get("tool_results", [])
    all_failed = tool_results and all(not tr.get("success") for tr in tool_results)
    # Exclude deferred tools (LLM-constructed args) from "all failed" detection
    non_deferred = [tr for tr in tool_results if tr.get("tool") not in _DEFERRED_TOOLS]
    all_real_failed = non_deferred and all(not tr.get("success") for tr in non_deferred)

    if all_real_failed:
        error_msg = f"All {len(non_deferred)} tools failed: {'; '.join(tool_errors[:3])}"
        ckpt.record_error(checkpoint_data, kind="all_tools_failed", message=error_msg)
        retry_count = checkpoint_data.get("last_error", {}).get("retry_count", 0)
        recovery = decide_recovery(stage, "all_tools_failed", retry_count)
        return {
            "status": recovery,
            "stage": stage,
            "summary": error_msg[:200],
            "error": error_msg,
        }

    # Run codex review AFTER tools (so it reviews current stage output)
    if should_invoke_codex(stage, mode):
        codex_result = _maybe_run_codex(
            stage=stage,
            mode=mode,
            project_id=project_id,
            topic_id=topic_id,
            svc=svc,
            checkpoint_data=checkpoint_data,
            base_dir=base_dir,
            policy=policy,
        )
        if codex_result is not None:
            return codex_result

    # Tools executed successfully — check human checkpoint, then report complete.
    # Gate checking is handled by runner.py via advance().
    autonomy = "autonomous" if mode in ("demo", "autonomous") else "supervised"
    if should_pause_human(stage, mode, autonomy=autonomy):
        ckpt.update_stage(checkpoint_data, stage=stage, state="needs_human",
                          summary_md=result.get("summary", ""))
        return {
            "status": "needs_human",
            "stage": stage,
            "summary": result.get("summary", f"Stage {stage} complete, awaiting approval"),
        }

    ckpt.update_stage(checkpoint_data, stage=stage, state="complete",
                      summary_md=result.get("summary", ""))
    ckpt.clear_error(checkpoint_data)
    ckpt.record_event(checkpoint_data, stage=stage, event="stage_complete")
    return {
        "status": "complete",
        "stage": stage,
        "summary": result.get("summary", f"Stage {stage} complete"),
    }


def _execute_stage_tools(
    *,
    db: Database,
    svc: OrchestratorService,
    project_id: int,
    topic_id: int,
    stage: str,
    checkpoint_data: dict[str, Any],
    budget_monitor: "BudgetMonitor | None" = None,
) -> dict[str, Any]:
    """Execute the tools for a stage via tool_dispatch.

    Iterates through the stage policy's tool list, dispatching each
    through the appropriate backend (primitive, orchestrator, or service).
    Each tool call is recorded in provenance via the execution backend.
    """
    from .tool_dispatch import dispatch_stage_tools

    policy = get_policy(stage)
    if policy is None:
        return {"summary": f"Stage {stage}: no policy found", "errors": []}

    context = checkpoint_data.get("stage_context", {})
    return dispatch_stage_tools(
        db=db,
        svc=svc,
        project_id=project_id,
        topic_id=topic_id,
        stage=stage,
        tools=policy.tools,
        context=context,
        budget_monitor=budget_monitor,
    )


def _maybe_run_codex(
    *,
    stage: str,
    mode: str,
    project_id: int,
    topic_id: int,
    svc: OrchestratorService,
    checkpoint_data: dict[str, Any],
    base_dir: Path,
    policy: Any,
) -> dict[str, Any] | None:
    """Run codex review if needed. Returns outcome dict or None to continue."""
    handoff = checkpoint_data.get("codex_handoff", {})

    # Already have a verdict for THIS stage from a previous run
    if handoff.get("verdict") and handoff.get("stage") == stage:
        return None  # Continue with existing verdict

    h_dir = ckpt.handoff_dir(base_dir, project_id, stage)

    # Check for existing response from a previous interrupted run
    existing = load_handoff_response(h_dir)
    if existing and existing.get("success"):
        ckpt.clear_codex_handoff(checkpoint_data, verdict=existing.get("verdict", ""))
        ckpt.record_event(checkpoint_data, stage=stage, event="codex_complete",
                          detail=f"verdict={existing.get('verdict', '?')}")
        return None  # Continue

    # Find the artifact to review — handles both V2 and legacy stage names
    stage_artifacts = checkpoint_data.get("artifacts", {}).get(stage, {})
    artifact_path = ""

    # V2 propose = legacy adversarial_optimization + study_design
    if stage in ("adversarial_optimization", "propose"):
        # Look for direction_proposal in propose or research_direction stages
        for search_stage in (stage, "research_direction", "analyze"):
            proposal = checkpoint_data.get("artifacts", {}).get(search_stage, {})
            artifact_id = proposal.get("direction_proposal", {}).get("artifact_id")
            if artifact_id:
                artifact_path = f"artifact:{artifact_id}"
                break

    elif stage == "study_design":
        spec = stage_artifacts.get("study_spec", {})
        artifact_id = spec.get("artifact_id")
        if artifact_id:
            artifact_path = f"artifact:{artifact_id}"

    elif stage == "write":
        # For write stage, review draft_pack if available
        draft = stage_artifacts.get("draft_pack", {})
        artifact_id = draft.get("artifact_id")
        if artifact_id:
            artifact_path = f"artifact:{artifact_id}"

    elif stage == "experiment":
        # For experiment stage, review experiment_result if available
        expr = stage_artifacts.get("experiment_result", {})
        artifact_id = expr.get("artifact_id")
        if artifact_id:
            artifact_path = f"artifact:{artifact_id}"

    if not artifact_path:
        # No artifact to review yet — let the stage continue
        return None

    # Save handoff request
    evidence = checkpoint_data.get("stage_context", {}).get("summary_md", "")
    save_handoff_request(
        h_dir,
        stage=stage,
        artifact_path=artifact_path,
        focus=policy.codex_focus,
        evidence_summary=evidence,
    )

    # Run codex
    ckpt.record_event(checkpoint_data, stage=stage, event="codex_start")
    review = run_codex_review(
        artifact_path=Path(artifact_path),
        stage=stage,
        focus=policy.codex_focus,
        evidence_summary=evidence,
        cwd=base_dir.parent if base_dir.exists() else None,
    )
    save_handoff_response(h_dir, review)

    if not review.get("success"):
        # Codex failed — policy says required stages must pause
        if policy.codex == "required":
            ckpt.record_event(checkpoint_data, stage=stage, event="codex_error",
                              detail=review.get("error", "unknown"))
            return {
                "status": "pause_human",
                "stage": stage,
                "summary": f"Codex review failed: {review.get('error', 'unknown')[:200]}",
                "error": review.get("error", ""),
            }
        # Optional/recommended — continue without codex
        ckpt.record_event(checkpoint_data, stage=stage, event="codex_skipped",
                          detail="codex failed, continuing without review")
        return None

    verdict = review.get("verdict", "")
    ckpt.clear_codex_handoff(checkpoint_data, verdict=verdict)
    ckpt.record_event(checkpoint_data, stage=stage, event="codex_complete",
                      detail=f"verdict={verdict}, issues={len(review.get('issues', []))}")

    # "revise" verdict from a required codex gate should block advancement
    if verdict == "revise" and policy.codex == "required":
        issues = review.get("issues", [])
        return {
            "status": "needs_human",
            "stage": stage,
            "summary": f"Codex requires revision: {len(issues)} issue(s) flagged",
            "codex_issues": issues,
        }

    # "reject" verdict always blocks
    if verdict == "reject":
        return {
            "status": "pause_human",
            "stage": stage,
            "summary": f"Codex rejected: {len(review.get('issues', []))} issue(s)",
            "codex_issues": review.get("issues", []),
        }

    return None
