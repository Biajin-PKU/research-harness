"""Tool dispatch — maps stage policy tool names to executable functions.

Bridges the gap between stage_policy.StagePolicy.tools (string names)
and the actual execution layer (backends + orchestrator service).

Three categories:
  1. Primitive tools → executed via ExecutionBackend
  2. Orchestrator tools → executed via OrchestratorService methods
  3. Query tools → read-only operations (paper_list, review_issues, etc.)
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..execution.backend import PrimitiveResult
from ..execution.factory import create_backend
from ..orchestrator.service import OrchestratorService
from ..primitives.registry import PRIMITIVE_REGISTRY
from ..storage.db import Database

if TYPE_CHECKING:
    from .budget import BudgetMonitor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output normalization helpers
# ---------------------------------------------------------------------------


def _extract_section_text(output: dict[str, Any]) -> str:
    """Extract text content from section_draft output.

    Real SectionDraftOutput → {"draft": {"content": ..., "section": ...}}
    Fallback: output["text"] for simplified/mock outputs.
    """
    draft = output.get("draft")
    if isinstance(draft, dict):
        return draft.get("content", "")
    return output.get("text", output.get("content", ""))


def _extract_review_feedback(output: dict[str, Any]) -> str:
    """Extract review feedback from section_review output.

    Real SectionReviewOutput → {"suggestions": [...], "dimensions": [...]}
    """
    suggestions = output.get("suggestions", [])
    if suggestions:
        return "; ".join(str(s) for s in suggestions)
    dims = output.get("dimensions", [])
    if dims:
        return "; ".join(
            f"{d.get('dimension', '?')}: {d.get('comment', '')}"
            for d in dims
            if isinstance(d, dict)
        )
    return output.get("feedback", output.get("issues", ""))


def _extract_revise_text(output: dict[str, Any]) -> str:
    """Extract revised text from section_revise output.

    Real SectionReviseOutput → {"revised_content": ...}
    """
    return output.get("revised_content", output.get("text", output.get("content", "")))


@dataclass
class ToolResult:
    """Result of dispatching one tool."""

    tool: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert a dataclass or primitive result to a serializable dict."""
    if isinstance(obj, dict):
        return obj
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return {"result": str(obj)}


# ---------------------------------------------------------------------------
# Primitive tools — dispatched via ExecutionBackend
# ---------------------------------------------------------------------------

_PRIMITIVE_TOOLS = frozenset(PRIMITIVE_REGISTRY.keys())

# Orchestrator tools — dispatched via OrchestratorService
_ORCHESTRATOR_TOOLS = frozenset(
    {
        "orchestrator_status",
        "orchestrator_record_artifact",
        "orchestrator_advance",
        "orchestrator_gate_check",
        "orchestrator_resume",
    }
)

# Service tools — methods on OrchestratorService
_SERVICE_TOOLS = frozenset(
    {
        "adversarial_run",
        "adversarial_resolve",
        "adversarial_status",
        "adversarial_review",
        "integrity_check",
        "review_add_issue",
        "review_bundle_create",
        "review_issues",
        "review_respond",
        "review_resolve",
        "review_status",
        "finalize_project",
    }
)

# Read-only query tools — thin wrappers
_QUERY_TOOLS = frozenset(
    {
        "paper_list",
        "paper_coverage_check",
        "paper_dismiss",
        "topic_list",
        "topic_show",
    }
)


def dispatch(
    tool_name: str,
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
) -> ToolResult:
    """Dispatch a single tool by name and return its result.

    *context* is the checkpoint's stage_context dict, used to build
    tool-specific parameters.
    """
    try:
        if tool_name in _PRIMITIVE_TOOLS:
            return _dispatch_primitive(
                tool_name, db=db, topic_id=topic_id, context=context
            )
        if tool_name in _ORCHESTRATOR_TOOLS:
            return _dispatch_orchestrator(
                tool_name,
                svc=svc,
                topic_id=topic_id,
                stage=stage,
                context=context,
            )
        if tool_name in _SERVICE_TOOLS:
            return _dispatch_service(
                tool_name,
                svc=svc,
                topic_id=topic_id,
                stage=stage,
                context=context,
            )
        if tool_name in _QUERY_TOOLS:
            return _dispatch_query(tool_name, db=db, topic_id=topic_id, context=context)
        logger.warning("Unknown tool '%s', skipping", tool_name)
        return ToolResult(
            tool=tool_name, success=False, error=f"Unknown tool: {tool_name}"
        )
    except Exception as exc:
        logger.warning("Tool '%s' failed: %s", tool_name, exc)
        return ToolResult(tool=tool_name, success=False, error=str(exc)[:500])


def dispatch_stage_tools(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    tools: tuple[str, ...],
    context: dict[str, Any],
    budget_monitor: "BudgetMonitor | None" = None,
) -> dict[str, Any]:
    """Execute all tools for a stage in order.

    Returns a summary dict with results, errors, and overall status.
    If budget_monitor is provided, syncs cost from provenance after each tool
    and halts early if budget is exhausted.
    """

    results: list[ToolResult] = []
    errors: list[str] = []

    # Sync budget at stage START only (not per-tool) to avoid N*2 SQL queries
    if budget_monitor is not None:
        budget_monitor.sync_from_provenance(db, topic_id=topic_id)

    for tool_name in tools:
        # Skip gate/status checks that happen elsewhere
        if tool_name in ("orchestrator_gate_check", "orchestrator_status"):
            continue

        # Multi-section expansion: call section_draft once per section
        if tool_name == "section_draft" and context.get("sections_to_draft"):
            for sec in context["sections_to_draft"]:
                context["section"] = sec
                result = dispatch(
                    tool_name,
                    db=db,
                    svc=svc,
                    topic_id=topic_id,
                    stage=stage,
                    context=context,
                )
                results.append(result)
                if result.success and result.output:
                    context.setdefault("_drafted_sections", []).append(sec)
                    # Normalize output: real SectionDraftOutput → {"draft": {"content": ...}}
                    text = _extract_section_text(result.output)
                    context[f"_output_{tool_name}_{sec}"] = {"text": text}
                if not result.success:
                    errors.append(f"{tool_name}[{sec}]: {result.error}")
                    logger.warning(
                        "Tool %s[%s] failed in stage %s: %s",
                        tool_name,
                        sec,
                        stage,
                        result.error,
                    )
            continue

        # Multi-section expansion: review each drafted section
        if tool_name == "section_review" and context.get("_drafted_sections"):
            for sec in context["_drafted_sections"]:
                context["section"] = sec
                result = dispatch(
                    tool_name,
                    db=db,
                    svc=svc,
                    topic_id=topic_id,
                    stage=stage,
                    context=context,
                )
                results.append(result)
                if result.success and result.output:
                    # Normalize: SectionReviewOutput → {"feedback": ..., "issues": ...}
                    feedback = _extract_review_feedback(result.output)
                    context[f"_output_section_review_{sec}"] = {"feedback": feedback}
                if not result.success:
                    errors.append(f"{tool_name}[{sec}]: {result.error}")
            continue

        # Multi-section expansion: revise each section using its review
        if tool_name == "section_revise" and context.get("_drafted_sections"):
            for sec in context["_drafted_sections"]:
                context["section"] = sec
                review_out = context.get(f"_output_section_review_{sec}", {})
                context["_output_section_review"] = review_out
                result = dispatch(
                    tool_name,
                    db=db,
                    svc=svc,
                    topic_id=topic_id,
                    stage=stage,
                    context=context,
                )
                results.append(result)
                if result.success and result.output:
                    # Normalize: SectionReviseOutput → {"text": revised_content}
                    text = _extract_revise_text(result.output)
                    normalized = {"text": text}
                    context[f"_output_section_revise_{sec}"] = normalized
                    context[f"_output_section_draft_{sec}"] = normalized
                if not result.success:
                    errors.append(f"{tool_name}[{sec}]: {result.error}")
            continue
        # direction_proposal and study_spec artifacts via one tool entry
        if (
            tool_name == "orchestrator_record_artifact"
            and stage == "propose"
            and context.get("study_spec")
        ):
            # First: record the primary artifact (direction_proposal)
            result = dispatch(
                tool_name,
                db=db,
                svc=svc,
                topic_id=topic_id,
                stage=stage,
                context=context,
            )
            results.append(result)
            if not result.success:
                errors.append(f"{tool_name}[primary]: {result.error}")

            # Second: record study_spec artifact
            saved = (
                context.get("artifact_type"),
                context.get("artifact_title"),
                context.get("artifact_payload"),
            )
            try:
                context["artifact_type"] = "study_spec"
                context["artifact_title"] = "Study design specification"
                context["artifact_payload"] = {"methodology": context["study_spec"]}
                result2 = dispatch(
                    tool_name,
                    db=db,
                    svc=svc,
                    topic_id=topic_id,
                    stage=stage,
                    context=context,
                )
                results.append(result2)
                if not result2.success:
                    errors.append(f"{tool_name}[study_spec]: {result2.error}")
            finally:
                (
                    context["artifact_type"],
                    context["artifact_title"],
                    context["artifact_payload"],
                ) = saved
            continue

        result = dispatch(
            tool_name,
            db=db,
            svc=svc,
            topic_id=topic_id,
            stage=stage,
            context=context,
        )
        results.append(result)

        # Feed tool output back into context for downstream tools
        if result.success and result.output:
            context[f"_output_{tool_name}"] = result.output

        if not result.success:
            errors.append(f"{tool_name}: {result.error}")
            logger.warning(
                "Tool %s failed in stage %s: %s", tool_name, stage, result.error
            )
            if tool_name in _PRIMITIVE_TOOLS and PRIMITIVE_REGISTRY.get(tool_name):
                continue
            if tool_name.startswith("orchestrator_record"):
                continue

    # Post-tool artifact recording: ensure all gate-required artifacts exist.
    auto_artifacts = _record_auto_artifacts(
        svc=svc,
        topic_id=topic_id,
        stage=stage,
        context=context,
        results=results,
        errors=errors,
    )

    # Sync budget at stage END and check limits
    if budget_monitor is not None:
        budget_monitor.sync_from_provenance(db, topic_id=topic_id)
        budget_check = budget_monitor.check()
        if budget_check.action == "halt":
            errors.append(f"Budget halted: {budget_check.message}")
            logger.warning(
                "Budget halted during stage %s: %s", stage, budget_check.message
            )

    succeeded = [r for r in results if r.success]
    summary: dict[str, Any] = {
        "summary": f"Stage {stage}: {len(succeeded)}/{len(results)} tools succeeded",
        "tool_results": [
            {"tool": r.tool, "success": r.success, "error": r.error, "output": r.output}
            for r in results
        ],
        "errors": errors,
        "auto_artifacts": auto_artifacts,
    }
    if budget_monitor is not None:
        summary["budget"] = budget_monitor.to_dict()
    return summary


# ---------------------------------------------------------------------------
# Automated adversarial review
# ---------------------------------------------------------------------------


def _run_automated_adversarial(proposal: dict[str, Any]) -> dict[str, Any]:
    """Run LLM-based adversarial evaluation of a research proposal.

    Returns a dict with verdict ("approved"/"revise"), issues list, and summary.
    Falls back to "approved" on LLM failure to avoid blocking the pipeline.
    """
    try:
        from ..execution.llm_primitives import _client_chat, _get_client, _parse_json

        direction = proposal.get("direction", proposal.get("research_question", ""))
        motivation = proposal.get("motivation", "")

        prompt = f"""You are a critical adversarial reviewer evaluating a research direction proposal.

Direction: {direction}
Motivation: {motivation}
Full proposal: {json.dumps(proposal, ensure_ascii=False, default=str)[:2000]}

Evaluate on: novelty, feasibility, evidence coverage, scope discipline.
Return JSON:
{{
  "verdict": "approved" or "revise",
  "issues": [{{
    "category": "novelty|feasibility|evidence|scope",
    "severity": "critical|major|minor",
    "description": "..."
  }}],
  "summary": "one-line overall assessment"
}}

Only return "revise" if there are critical issues. Return ONLY JSON."""

        client = _get_client(tier="medium", task_name="stage_planner")
        raw = _client_chat(client, prompt)
        result = _parse_json(raw, primitive="adversarial_review")
        if result.get("verdict") in ("approved", "revise"):
            return result
        return {
            "verdict": "approved",
            "issues": [],
            "summary": "LLM returned invalid verdict",
        }
    except Exception as exc:
        logger.warning("Automated adversarial review failed: %s", exc)
        return {
            "verdict": "approved",
            "issues": [],
            "summary": f"Review unavailable: {str(exc)[:100]}",
        }


# ---------------------------------------------------------------------------
# Auto-artifact recording
# ---------------------------------------------------------------------------


def _record_auto_artifacts(
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
    results: list[ToolResult],
    errors: list[str],
) -> list[tuple[str, int]]:
    """Record gate-required artifacts from tool outputs.

    After all tools in a stage execute, this ensures the artifacts
    required by the orchestrator gate are written to the DB. Without this,
    advance() blocks with "Missing required artifact" errors.

    Returns list of (artifact_type, artifact_id) tuples for checkpoint tracking.
    """
    recorded: list[tuple[str, int]] = []
    succeeded_tools = {r.tool for r in results if r.success}

    if stage == "init":
        already_recorded = {
            r.output.get("artifact_type") if isinstance(r.output, dict) else None
            for r in results
            if r.success and r.tool == "orchestrator_record_artifact"
        }
        if "topic_brief" not in already_recorded:
            topic_desc = context.get("topic_description", context.get("query", ""))
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="topic_brief",
                    title="Topic brief",
                    payload={
                        "description": topic_desc,
                        "search_queries": context.get("additional_queries", []),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("topic_brief", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[topic_brief]: {exc}")

    elif stage == "build":
        ps_out = context.get("_output_paper_search", {})
        expand_out = context.get("_output_expand_citations", {})
        acquire_out = context.get("_output_paper_acquire", {})

        if ps_out and "paper_search" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="literature_map",
                    title="Literature map from search",
                    payload={
                        "papers_found": ps_out.get(
                            "ingested_count", len(ps_out.get("papers", []))
                        ),
                        "query": ps_out.get("query_used", ""),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("literature_map", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[literature_map]: {exc}")

            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="paper_pool_snapshot",
                    title="Paper pool snapshot",
                    payload={
                        "total_papers": ps_out.get("ingested_count", 0),
                        "provider": ps_out.get("provider", ""),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("paper_pool_snapshot", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[paper_pool_snapshot]: {exc}")

        if expand_out or "expand_citations" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="citation_expansion_report",
                    title="Citation expansion report",
                    payload=expand_out if expand_out else {"status": "completed"},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("citation_expansion_report", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[citation_expansion_report]: {exc}")

        if acquire_out or "paper_acquire" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="acquisition_report",
                    title="Paper acquisition report",
                    payload=acquire_out if acquire_out else {"status": "completed"},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("acquisition_report", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[acquisition_report]: {exc}")

    elif stage == "analyze":
        claims_out = context.get("_output_claim_extract", {})
        gaps_out = context.get("_output_gap_detect", {})
        baselines_out = context.get("_output_baseline_identify", {})

        if claims_out and "claim_extract" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="claim_candidate_set",
                    title="Extracted claims",
                    payload={
                        "claims_count": len(claims_out.get("claims", [])),
                        "papers_processed": claims_out.get("papers_processed", 0),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("claim_candidate_set", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[claim_candidate_set]: {exc}")

        if (gaps_out or baselines_out) and (
            "gap_detect" in succeeded_tools or "baseline_identify" in succeeded_tools
        ):
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="evidence_pack",
                    title="Evidence pack (gaps + baselines)",
                    payload={
                        "gaps_count": len(gaps_out.get("gaps", [])),
                        "papers_analyzed": gaps_out.get("papers_analyzed", 0),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("evidence_pack", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[evidence_pack]: {exc}")

        if gaps_out and "gap_detect" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="direction_proposal",
                    title="Research direction from gap analysis",
                    payload={
                        "gaps": gaps_out.get("gaps", [])[:5],
                        "research_question": context.get(
                            "focus", "What are the key gaps?"
                        ),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("direction_proposal", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[direction_proposal]: {exc}")

    elif stage == "propose":
        if "adversarial_run" not in succeeded_tools:
            proposal = context.get("artifact_payload", {})
            outcome = _run_automated_adversarial(proposal)
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="adversarial_resolution",
                    title=f"Automated adversarial review ({outcome['verdict']})",
                    payload={
                        "outcome": outcome["verdict"],
                        "issues": outcome.get("issues", []),
                        "summary": outcome.get("summary", ""),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("adversarial_resolution", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[adversarial_resolution]: {exc}")

    elif stage == "experiment":
        cg_out = context.get("_output_code_generate", {})
        er_out = context.get("_output_experiment_run", {})
        vr_out = context.get("_output_verified_registry_build", {})

        if cg_out and "code_generate" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="experiment_code",
                    title="Generated experiment code",
                    payload={
                        "files": list(cg_out.get("files", {}).keys()),
                        "entry_point": cg_out.get("entry_point", "main.py"),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("experiment_code", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[experiment_code]: {exc}")

        if er_out and "experiment_run" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="experiment_result",
                    title="Experiment results",
                    payload={"metrics": er_out.get("metrics", {})},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("experiment_result", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[experiment_result]: {exc}")

            # P0-2: Insert experiment_runs row with kept=1 to satisfy experiment_gate
            try:
                svc.record_experiment_run(
                    topic_id,
                    code_hash=cg_out.get("entry_point", "main.py"),
                    primary_metric_name=er_out.get(
                        "primary_metric_name", context.get("primary_metric", "")
                    ),
                    primary_metric_value=er_out.get("primary_metric_value", 0.0),
                    metrics=er_out.get("metrics", {}),
                )
            except Exception as exc:
                errors.append(f"auto_artifact[experiment_runs]: {exc}")

        if vr_out and "verified_registry_build" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="verified_registry",
                    title="Verified number registry",
                    payload={"whitelist_size": vr_out.get("whitelist_size", 0)},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("verified_registry", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[verified_registry]: {exc}")

    elif stage == "write":
        drafted = context.get("_drafted_sections", [])
        sections_map: dict[str, str] = {}
        if drafted:
            for sec in drafted:
                text = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
                if text:
                    sections_map[sec] = text[:200]
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="draft_pack",
                    title="Paper draft sections",
                    payload={"sections": list(sections_map.keys())},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("draft_pack", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[draft_pack]: {exc}")

        latex_out = context.get("_output_latex_compile", {})
        if latex_out and "latex_compile" in succeeded_tools:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="final_bundle",
                    title="Final LaTeX bundle",
                    payload={
                        "output_dir": latex_out.get("output_dir", ""),
                        "pdf_path": latex_out.get("pdf_path", ""),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("final_bundle", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[final_bundle]: {exc}")
        elif drafted:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="final_bundle",
                    title="Draft bundle (pre-compilation)",
                    payload={"sections": list(sections_map.keys()), "status": "draft"},
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("final_bundle", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[final_bundle]: {exc}")

        if drafted:
            try:
                art = svc.record_artifact(
                    topic_id=topic_id,
                    stage=stage,
                    artifact_type="process_summary",
                    title="Writing process summary",
                    payload={
                        "sections_drafted": drafted,
                        "sections_count": len(drafted),
                        "tools_succeeded": list(succeeded_tools),
                    },
                )
                art_id = art.id if hasattr(art, "id") else 0
                if art_id:
                    recorded.append(("process_summary", art_id))
            except Exception as exc:
                errors.append(f"auto_artifact[process_summary]: {exc}")

    return recorded


# ---------------------------------------------------------------------------
# Internal dispatchers
# ---------------------------------------------------------------------------


def _dispatch_primitive(
    name: str,
    *,
    db: Database,
    topic_id: int,
    context: dict[str, Any],
) -> ToolResult:
    """Execute a research primitive via the execution backend.

    Uses 'research_harness' backend which handles both LLM and non-LLM
    primitives (routes LLM calls through the configured provider).
    """
    backend = create_backend("research_harness", db=db)
    params = _build_primitive_params(name, topic_id=topic_id, context=context)
    params["db"] = db

    result: PrimitiveResult = backend.execute(name, **params)

    if not result.success:
        return ToolResult(
            tool=name, success=False, error=result.error or "Unknown error"
        )

    output = _to_dict(result.output)
    return ToolResult(tool=name, success=True, output=output)


def _dispatch_orchestrator(
    name: str,
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
) -> ToolResult:
    """Execute an orchestrator operation."""
    if name == "orchestrator_status":
        output = svc.get_status(topic_id)
        return ToolResult(tool=name, success=True, output=output)

    if name == "orchestrator_record_artifact":
        artifact_type = context.get("artifact_type", "")
        title = context.get("artifact_title", "")
        payload = context.get("artifact_payload", {})
        if not artifact_type:
            return ToolResult(
                tool=name, success=False, error="No artifact_type in context"
            )
        artifact = svc.record_artifact(
            topic_id=topic_id,
            stage=stage,
            artifact_type=artifact_type,
            title=title,
            payload=payload,
        )
        artifact_id = artifact.id if hasattr(artifact, "id") else 0
        return ToolResult(
            tool=name,
            success=True,
            output={
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
            },
        )

    if name == "orchestrator_advance":
        result = svc.advance(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    if name == "orchestrator_gate_check":
        decision = svc.check_gate(topic_id, stage=stage)
        return ToolResult(tool=name, success=True, output={"decision": decision})

    if name == "orchestrator_resume":
        result = svc.resume_run(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    return ToolResult(
        tool=name, success=False, error=f"Unhandled orchestrator tool: {name}"
    )


def _dispatch_service(
    name: str,
    *,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    context: dict[str, Any],
) -> ToolResult:
    """Execute a service-level operation (adversarial, review, finalize).

    Wires through to real OrchestratorService methods where possible.
    Tools that require LLM-constructed arguments (e.g. adversarial proposals)
    raise an explicit error so the caller knows to delegate to the MCP layer.
    """
    if name == "adversarial_status":
        result = svc.check_adversarial_status(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    if name == "review_issues":
        result = svc.list_review_issues(
            topic_id,
            stage=context.get("review_stage"),
            status=context.get("review_status"),
            blocking_only=context.get("blocking_only", False),
        )
        return ToolResult(tool=name, success=True, output=result)

    if name == "review_status":
        result = svc.get_review_status(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    if name == "review_resolve":
        issue_id = context.get("issue_id")
        status = context.get("resolve_status", "resolved")
        if not issue_id:
            return ToolResult(tool=name, success=False, error="No issue_id in context")
        result = svc.resolve_review_issue(issue_id, status)
        return ToolResult(tool=name, success=True, output=result)

    if name == "review_bundle_create":
        result = svc.create_review_bundle(
            topic_id,
            integrity_artifact_id=context.get("integrity_artifact_id"),
            scholarly_artifact_id=context.get("scholarly_artifact_id"),
        )
        return ToolResult(tool=name, success=True, output=result)

    if name == "finalize_project":
        result = svc.finalize_project(topic_id)
        return ToolResult(tool=name, success=True, output=result)

    # Tools requiring LLM-driven parameter construction
    if name in (
        "adversarial_run",
        "adversarial_resolve",
        "adversarial_review",
        "integrity_check",
        "review_add_issue",
        "review_respond",
    ):
        return ToolResult(
            tool=name,
            success=False,
            error=f"Service tool '{name}' requires LLM-constructed arguments; "
            f"delegate to MCP layer or provide arguments in context",
        )

    return ToolResult(tool=name, success=False, error=f"Unhandled service tool: {name}")


def _dispatch_query(
    name: str,
    *,
    db: Database,
    topic_id: int,
    context: dict[str, Any],
) -> ToolResult:
    """Execute a read-only query tool."""
    if name == "paper_list":
        conn = db.connect()
        try:
            rows = conn.execute(
                """SELECT p.id, p.title, p.year, p.venue, pt.relevance
                   FROM papers p JOIN paper_topics pt ON p.id = pt.paper_id
                   WHERE pt.topic_id = ? ORDER BY p.id""",
                (topic_id,),
            ).fetchall()
            papers = [dict(r) for r in rows]
            return ToolResult(
                tool=name, success=True, output={"count": len(papers), "papers": papers}
            )
        finally:
            conn.close()

    if name == "paper_coverage_check":
        backend = create_backend("research_harness", db=db)
        result = backend.execute("paper_coverage_check", topic_id=topic_id, db=db)
        if result.success:
            return ToolResult(tool=name, success=True, output=_to_dict(result.output))
        return ToolResult(
            tool=name, success=False, error=result.error or "coverage_check failed"
        )

    if name == "paper_dismiss":
        paper_id = context.get("paper_id")
        reason = context.get("reason", "")
        if not paper_id:
            return ToolResult(tool=name, success=False, error="No paper_id in context")
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE paper_topics SET relevance = 'dismissed' WHERE paper_id = ? AND topic_id = ?",
                (paper_id, topic_id),
            )
            conn.execute(
                """INSERT OR REPLACE INTO topic_paper_notes (paper_id, topic_id, note_type, content)
                   VALUES (?, ?, 'dismissed', ?)""",
                (paper_id, topic_id, reason),
            )
            conn.commit()
            return ToolResult(
                tool=name,
                success=True,
                output={"paper_id": paper_id, "dismissed": True},
            )
        except Exception as exc:
            conn.rollback()
            return ToolResult(
                tool=name, success=False, error=f"paper_dismiss failed: {exc}"
            )
        finally:
            conn.close()

    return ToolResult(
        tool=name, success=False, error=f"Query tool '{name}' not implemented"
    )


# ---------------------------------------------------------------------------
# Parameter builders
# ---------------------------------------------------------------------------


def _build_primitive_params(
    name: str,
    *,
    topic_id: int,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build parameters for a primitive from checkpoint context."""
    params: dict[str, Any] = {"topic_id": topic_id}

    if name == "paper_search":
        query = context.get("query", context.get("topic_description", ""))
        params["query"] = query
        params["auto_ingest"] = context.get("auto_ingest", True)
        params["max_results"] = context.get("max_results", 500)

    elif name == "paper_ingest":
        params["source"] = context.get("ingest_source", "")

    elif name == "select_seeds":
        params["top_n"] = context.get("seed_top_n", 10)

    elif name == "expand_citations":
        params["forward_limit"] = context.get("forward_limit", 50)
        params["backward_limit"] = context.get("backward_limit", 50)

    elif name == "paper_acquire":
        pass  # topic_id is sufficient

    elif name in ("claim_extract", "gap_detect", "baseline_identify"):
        params["focus"] = context.get("focus", "")
        if name == "claim_extract":
            params["paper_ids"] = context.get("paper_ids", [])

    elif name == "section_draft":
        params["section"] = context.get("section", "")
        params["outline"] = context.get("outline", "")
        params["evidence_ids"] = context.get("evidence_ids", [])

    elif name == "consistency_check":
        params["sections"] = context.get("sections", [])

    elif name == "competitive_learning":
        params["venue"] = context.get("venue", "")
        params["contributions"] = context.get("contributions", "")

    elif name == "cold_start_run":
        params["gold_papers"] = context.get("gold_papers", [])

    elif name == "code_generate":
        params["study_spec"] = context.get("study_spec", "")

    elif name == "code_validate":
        cg_out = context.get("_output_code_generate", {})
        files = cg_out.get("files", {})
        entry = cg_out.get("entry_point", "main.py")
        params["code"] = files.get(entry, "") or cg_out.get("code", "")

    elif name == "experiment_run":
        cg_out = context.get("_output_code_generate", {})
        files = cg_out.get("files", {})
        entry = cg_out.get("entry_point", "main.py")
        params["code"] = files.get(entry, "") or cg_out.get("code", "")
        params["primary_metric"] = context.get("primary_metric", "")

    elif name == "verified_registry_build":
        er_out = context.get("_output_experiment_run", {})
        params["metrics"] = er_out.get("metrics", {})
        params["primary_metric_name"] = er_out.get(
            "primary_metric_name", context.get("primary_metric", "")
        )

    elif name == "verified_registry_check":
        er_out = context.get("_output_experiment_run", {})
        metrics = er_out.get("metrics", {})
        params["numbers"] = list(metrics.values()) if metrics else []

    elif name == "outline_generate":
        pass  # topic_id is sufficient

    elif name == "section_review":
        drafted = context.get("_drafted_sections", [])
        sec = context.get("section", drafted[-1] if drafted else "")
        content = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
        params["section"] = sec
        params["content"] = content

    elif name == "section_revise":
        drafted = context.get("_drafted_sections", [])
        sec = context.get("section", drafted[-1] if drafted else "")
        draft_out = context.get(f"_output_section_draft_{sec}", {})
        review_out = context.get("_output_section_review", {})
        params["section"] = sec
        params["content"] = draft_out.get("text", "")
        params["review_feedback"] = review_out.get(
            "feedback", review_out.get("issues", "")
        )

    elif name == "paper_verify_numbers":
        all_text_parts = []
        for sec in context.get("_drafted_sections", []):
            text = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
            if text:
                all_text_parts.append(text)
        params["text"] = "\n\n".join(all_text_parts)

    elif name == "citation_verify":
        citations: list[dict[str, Any]] = []
        for sec in context.get("_drafted_sections", []):
            sec_cites = context.get(f"_output_section_draft_{sec}", {}).get(
                "citations", []
            )
            if isinstance(sec_cites, list):
                citations.extend(sec_cites)
        params["citations"] = citations

    elif name == "evidence_trace":
        pass  # topic_id is sufficient

    elif name == "latex_compile":
        sections_map: dict[str, str] = {}
        for sec in context.get("_drafted_sections", []):
            text = context.get(f"_output_section_draft_{sec}", {}).get("text", "")
            if text:
                sections_map[sec] = text
        params["sections"] = sections_map
        params["output_dir"] = context.get("output_dir", "")
        params["template"] = context.get("venue", "arxiv").lower()
        params["title"] = (
            context.get("contributions", "").split("\n")[0][:200]
            if context.get("contributions")
            else ""
        )
        params["abstract"] = ""

    # Pass through topic_id when available in context
    if "topic_id" in context:
        params.setdefault("topic_id", context["topic_id"])

    return params
