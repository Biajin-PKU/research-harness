"""Runner — top-level supervisor for autonomous research workflow.

The runner is a deterministic controller that:
1. Loads/creates checkpoint
2. Iterates through orchestrator stages
3. Delegates LLM work to claude-kimi sessions (via MCP)
4. Invokes codex at quality gates
5. Pauses at human checkpoints
6. Persists state after every stage
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..config import find_workspace_root, load_runtime_config
from ..orchestrator.service import OrchestratorService
from ..orchestrator.stages import STAGE_ORDER, next_stage
from ..storage.db import Database
from . import checkpoint as ckpt
from .budget import BudgetLimits, BudgetMonitor
from .stage_executor import execute_stage
from .stage_policy import max_retries, should_pause_human

logger = logging.getLogger(__name__)


def run_project(
    project_id: int,
    *,
    topic_id: int | None = None,
    direction: str = "",
    mode: str = "standard",
    session_command: list[str] | None = None,
    auto_approve: bool = False,
    base_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the full research workflow for a project.

    This is the main entrypoint called by CLI (`rhub auto-runner start`)
    or by the /research-harness skill.

    Returns a dict with:
        status: "completed" | "paused" | "error" | "aborted"
        current_stage: where execution stopped
        stages_completed: list of completed stage names
        summary: human-readable summary
    """
    config = load_runtime_config()
    db = Database(config.db_path)
    db.migrate()
    svc = OrchestratorService(db)

    if base_dir is None:
        ws = find_workspace_root()
        base_dir = ws / ".research-harness" if ws else Path.home() / ".research-harness"

    cmd = session_command or ["claude-kimi"]
    ckpt_path = ckpt.checkpoint_path(base_dir, project_id)

    # Load or create checkpoint
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)
    if checkpoint_data is None:
        # Resolve topic_id and current stage from orchestrator if not provided
        run = svc.get_run(project_id)
        if topic_id is None:
            if run is None:
                return {
                    "status": "error",
                    "current_stage": "",
                    "stages_completed": [],
                    "summary": f"No orchestrator run found for project {project_id}. "
                    "Initialize with: rhub auto-runner start --init",
                }
            topic_id = run.topic_id
        checkpoint_data = ckpt.new_checkpoint(
            project_id,
            topic_id,
            mode=mode,
            session_command=cmd,
        )
        # Sync initial stage from orchestrator run if it exists
        if run is not None and run.current_stage and run.current_stage != "init":
            checkpoint_data["current_stage"] = run.current_stage
            logger.info(
                "Resuming from orchestrator stage '%s' for project %d",
                run.current_stage,
                project_id,
            )
        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
        logger.info("Created new checkpoint for project %d", project_id)

    # Initialize budget monitor
    budget_data = checkpoint_data.get("budget", {})
    policy_json = checkpoint_data.get("policy_json", "{}")
    budget_limits = BudgetLimits.from_policy_json(policy_json)
    budget_monitor = BudgetMonitor.from_checkpoint(budget_data, budget_limits)

    # Store direction in context if provided
    if direction:
        ctx = checkpoint_data.setdefault("stage_context", {})
        ctx["direction"] = direction

    stages_completed: list[str] = []
    current_stage = checkpoint_data.get("current_stage", "init")

    if dry_run:
        return _dry_run(current_stage, mode)

    # Main loop: iterate through stages
    while current_stage is not None:
        logger.info("━━━ Stage: %s ━━━", current_stage)
        ckpt.update_stage(checkpoint_data, stage=current_stage, state="running")
        ckpt.save_checkpoint(ckpt_path, checkpoint_data)

        # Execute stage
        result = execute_stage(
            db=db,
            svc=svc,
            project_id=project_id,
            topic_id=checkpoint_data.get("topic_id", 0),
            stage=current_stage,
            mode=mode,
            checkpoint_data=checkpoint_data,
            base_dir=base_dir,
            budget_monitor=budget_monitor,
        )

        status = result.get("status", "error")

        # Budget check after each stage
        budget_result = budget_monitor.check()
        checkpoint_data["budget"] = budget_monitor.to_dict()
        if budget_result.action == "halt":
            ckpt.record_event(
                checkpoint_data,
                stage=current_stage,
                event="budget_halt",
                detail=budget_result.message,
            )
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
            return {
                "status": "paused",
                "current_stage": current_stage,
                "stages_completed": stages_completed,
                "summary": f"Budget exhausted: {budget_result.message}",
                "budget": budget_monitor.to_dict(),
            }

        if status == "complete":
            stages_completed.append(current_stage)
            ckpt.record_event(
                checkpoint_data,
                stage=current_stage,
                event="advance",
                detail="gate passed",
            )

            # Terminal stage: write is the last stage, no advance needed.
            # But still verify the gate passes (review issues, artifacts).
            if current_stage == "write":
                gate_decision = svc.check_gate(project_id, stage="write")
                if gate_decision not in ("pass", None):
                    logger.warning("Write gate not passed: %s", gate_decision)
                    ckpt.update_stage(
                        checkpoint_data,
                        stage="write",
                        state="needs_human",
                        summary_md=f"Write gate: {gate_decision}",
                    )
                    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                    if auto_approve:
                        logger.info("Auto-approving write gate (%s)", gate_decision)
                    else:
                        return {
                            "status": "paused",
                            "current_stage": "write",
                            "stages_completed": stages_completed,
                            "summary": f"Write stage complete but gate returned: {gate_decision}",
                            "gate_decision": gate_decision,
                            "checkpoint_path": str(ckpt_path),
                        }

                ckpt.update_stage(checkpoint_data, stage="write", state="complete")
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                return {
                    "status": "completed",
                    "current_stage": "write",
                    "stages_completed": stages_completed,
                    "summary": f"Workflow completed. {len(stages_completed)} stages passed.",
                    "checkpoint_path": str(ckpt_path),
                }

            # Advance orchestrator — only move checkpoint if advance succeeds
            try:
                advance_result = svc.advance(project_id, actor="auto_runner")
                if not advance_result.get("success"):
                    error_msg = advance_result.get("error", "advance failed")
                    logger.warning("orchestrator_advance blocked: %s", error_msg)

                    # Loopback support: advance() may have triggered a loopback
                    if advance_result.get("loopback"):
                        loopback_to = advance_result.get("to_stage", "build")
                        ckpt.record_event(
                            checkpoint_data,
                            stage=current_stage,
                            event="loopback",
                            detail=f"→ {loopback_to} (gap-triggered)",
                        )
                        current_stage = loopback_to
                        ckpt.update_stage(
                            checkpoint_data, stage=current_stage, state="pending"
                        )
                        checkpoint_data["current_stage_attempt"] = 1
                        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                        continue

                    # Stop-before or gate failure — pause for human
                    if advance_result.get("stop_before"):
                        ckpt.update_stage(
                            checkpoint_data,
                            stage=current_stage,
                            state="needs_human",
                            summary_md=f"Stop-before: {error_msg}",
                        )
                        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                        return {
                            "status": "paused",
                            "current_stage": current_stage,
                            "stages_completed": stages_completed,
                            "summary": error_msg,
                        }

                    # Other advance failure — don't move checkpoint, pause
                    ckpt.update_stage(
                        checkpoint_data,
                        stage=current_stage,
                        state="error",
                        summary_md=f"Advance blocked: {error_msg}",
                    )
                    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                    return {
                        "status": "error",
                        "current_stage": current_stage,
                        "stages_completed": stages_completed,
                        "summary": f"Orchestrator advance blocked: {error_msg}",
                    }
            except Exception as exc:
                logger.warning("orchestrator_advance failed: %s", exc)
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                return {
                    "status": "error",
                    "current_stage": current_stage,
                    "stages_completed": stages_completed,
                    "summary": f"Orchestrator advance exception: {exc}",
                }

            # Move to next stage
            current_stage = next_stage(current_stage)
            if current_stage:
                ckpt.update_stage(checkpoint_data, stage=current_stage, state="pending")
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
            continue

        if status == "needs_human":
            ckpt.update_stage(
                checkpoint_data,
                stage=current_stage,
                state="needs_human",
                summary_md=result.get("summary", ""),
            )
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)

            if auto_approve:
                # Auto-approve in demo mode — but still respect advance() result
                try:
                    advance_result = svc.advance(project_id, actor="auto_runner")
                    if not advance_result.get("success"):
                        error_msg = advance_result.get("error", "advance failed")
                        logger.warning("Auto-approve advance blocked: %s", error_msg)
                        # Don't advance checkpoint — return error to prevent divergence
                        ckpt.update_stage(
                            checkpoint_data,
                            stage=current_stage,
                            state="error",
                            summary_md=f"Auto-approve blocked: {error_msg}",
                        )
                        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                        return {
                            "status": "error",
                            "current_stage": current_stage,
                            "stages_completed": stages_completed,
                            "summary": f"Auto-approve advance blocked: {error_msg}",
                        }
                except Exception as exc:
                    logger.warning("Auto-approve advance failed: %s", exc)
                    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                    return {
                        "status": "error",
                        "current_stage": current_stage,
                        "stages_completed": stages_completed,
                        "summary": f"Auto-approve advance exception: {exc}",
                    }
                stages_completed.append(current_stage)
                current_stage = next_stage(current_stage)
                if current_stage:
                    ckpt.update_stage(
                        checkpoint_data, stage=current_stage, state="pending"
                    )
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                continue

            return {
                "status": "paused",
                "current_stage": current_stage,
                "stages_completed": stages_completed,
                "summary": result.get("summary", ""),
                "gate_decision": result.get("gate_decision", ""),
                "checkpoint_path": str(ckpt_path),
            }

        if status == "fallback_stage":
            from ..orchestrator.stages import STAGE_REGISTRY

            stage_meta = STAGE_REGISTRY.get(current_stage)
            if stage_meta and stage_meta.fallback_stage:
                fallback = stage_meta.fallback_stage
                logger.warning("Falling back from %s to %s", current_stage, fallback)
                ckpt.record_event(
                    checkpoint_data,
                    stage=current_stage,
                    event="fallback",
                    detail=f"→ {fallback}",
                )
                current_stage = fallback
                ckpt.update_stage(checkpoint_data, stage=current_stage, state="pending")
                checkpoint_data["current_stage_attempt"] = 1
                ckpt.clear_error(checkpoint_data)
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                continue

        if status in ("pause_human", "error"):
            ckpt.update_stage(
                checkpoint_data,
                stage=current_stage,
                state="error",
                summary_md=result.get("summary", ""),
            )
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
            return {
                "status": "paused" if status == "pause_human" else "error",
                "current_stage": current_stage,
                "stages_completed": stages_completed,
                "summary": result.get("summary", ""),
                "error": result.get("error", ""),
                "checkpoint_path": str(ckpt_path),
            }

        # Retry
        if status == "retry":
            budget_monitor.record_iteration()
            attempt = checkpoint_data.get("current_stage_attempt", 1) + 1
            checkpoint_data["current_stage_attempt"] = attempt
            limit = max_retries(current_stage)
            if attempt > limit + 1:
                logger.error(
                    "Retry limit exhausted for stage %s (attempt %d > %d)",
                    current_stage,
                    attempt,
                    limit + 1,
                )
                ckpt.update_stage(
                    checkpoint_data,
                    stage=current_stage,
                    state="error",
                    summary_md=f"Retry limit exhausted after {attempt - 1} attempts",
                )
                ckpt.save_checkpoint(ckpt_path, checkpoint_data)
                return {
                    "status": "error",
                    "current_stage": current_stage,
                    "stages_completed": stages_completed,
                    "summary": f"Retry limit exhausted for {current_stage}",
                    "checkpoint_path": str(ckpt_path),
                }
            ckpt.record_event(
                checkpoint_data,
                stage=current_stage,
                event="retry",
                detail=f"attempt {attempt}",
            )
            ckpt.save_checkpoint(ckpt_path, checkpoint_data)
            continue

        # Unknown status
        logger.error("Unknown stage result status: %s", status)
        ckpt.save_checkpoint(ckpt_path, checkpoint_data)
        return {
            "status": "error",
            "current_stage": current_stage,
            "stages_completed": stages_completed,
            "summary": f"Unknown status: {status}",
        }

    # Unreachable under current 6-stage model: write stage exits via terminal
    # branch above.  Guard defensively in case stage ordering changes.
    last = stages_completed[-1] if stages_completed else "unknown"
    ckpt.update_stage(checkpoint_data, stage=last, state="complete")
    ckpt.save_checkpoint(ckpt_path, checkpoint_data)
    return {
        "status": "completed",
        "current_stage": last,
        "stages_completed": stages_completed,
        "summary": f"Workflow completed. {len(stages_completed)} stages passed.",
        "checkpoint_path": str(ckpt_path),
    }


def resume_project(
    project_id: int,
    *,
    base_dir: Path | None = None,
    auto_approve: bool = False,
) -> dict[str, Any]:
    """Resume a paused workflow from checkpoint."""
    if base_dir is None:
        ws = find_workspace_root()
        base_dir = ws / ".research-harness" if ws else Path.home() / ".research-harness"

    ckpt_path = ckpt.checkpoint_path(base_dir, project_id)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)
    if checkpoint_data is None:
        return {
            "status": "error",
            "current_stage": "",
            "stages_completed": [],
            "summary": f"No checkpoint found for project {project_id}",
        }

    return run_project(
        project_id,
        topic_id=checkpoint_data.get("topic_id"),
        mode=checkpoint_data.get("mode", "standard"),
        session_command=checkpoint_data.get("session_command"),
        auto_approve=auto_approve,
        base_dir=base_dir,
    )


def get_status(
    project_id: int,
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Get current workflow status without executing."""
    if base_dir is None:
        ws = find_workspace_root()
        base_dir = ws / ".research-harness" if ws else Path.home() / ".research-harness"

    ckpt_path = ckpt.checkpoint_path(base_dir, project_id)
    checkpoint_data = ckpt.load_checkpoint(ckpt_path)
    if checkpoint_data is None:
        return {"status": "not_started", "project_id": project_id}

    current = checkpoint_data.get("current_stage", "?")
    state = checkpoint_data.get("stage_state", "?")
    idx = STAGE_ORDER.index(current) + 1 if current in STAGE_ORDER else 0

    return {
        "status": state,
        "project_id": project_id,
        "current_stage": f"{idx}/{len(STAGE_ORDER)}: {current}",
        "stage_state": state,
        "mode": checkpoint_data.get("mode", "?"),
        "artifacts_recorded": sum(
            len(arts) for arts in checkpoint_data.get("artifacts", {}).values()
        ),
        "history_events": len(checkpoint_data.get("history", [])),
        "last_error": checkpoint_data.get("last_error", {}).get("message", ""),
        "checkpoint_path": str(ckpt_path),
    }


def _dry_run(current_stage: str, mode: str) -> dict[str, Any]:
    """Show what would happen without executing."""
    from .stage_policy import STAGE_POLICIES, should_invoke_codex

    plan = []
    stage = current_stage
    while stage:
        policy = STAGE_POLICIES.get(stage)
        if policy is None:
            break
        plan.append(
            {
                "stage": stage,
                "tools": list(policy.tools),
                "codex": should_invoke_codex(stage, mode),
                "human_pause": should_pause_human(stage, mode),
            }
        )
        stage = next_stage(stage)

    return {
        "status": "dry_run",
        "current_stage": current_stage,
        "stages_completed": [],
        "plan": plan,
        "summary": f"Dry run: {len(plan)} stages from {current_stage}",
    }
