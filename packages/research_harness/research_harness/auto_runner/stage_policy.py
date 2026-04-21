"""Stage policy — defines what each stage does, when to call codex, and error handling.

V2: 6-stage policies (Init, Build, Analyze, Propose, Experiment, Write).
Legacy 13-stage policies preserved for reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..orchestrator.stages import STAGE_ORDER, STAGE_REGISTRY


CodexPolicy = Literal["required", "recommended", "optional", "none"]
HumanPolicy = Literal["always", "conditional", "never"]
RetryPolicy = Literal["retry_twice", "retry_once", "no_retry"]


@dataclass(frozen=True)
class StagePolicy:
    """Execution policy for one orchestrator stage."""

    name: str
    tools: tuple[str, ...]  # MCP tools to call (in order)
    codex: CodexPolicy  # When to invoke codex review
    codex_focus: str  # Focus text for codex review prompt
    human_checkpoint: HumanPolicy  # When to pause for human
    retry: RetryPolicy  # How to handle tool failures
    max_codex_rounds: int = 3  # Max adversarial rounds
    description: str = ""  # One-line stage objective for prompt
    autonomous_allowed: bool = True
    risk_level: str = "low"  # low|medium|high — high-risk stages require human even in autonomous mode
    approval_policy: str = "auto"  # auto|human_required|budget_dependent
    expansion_paper_budget: int = 0  # Max papers to add during loopback (0 = unlimited)


# ---------------------------------------------------------------------------
# V2: 6-stage policies
# ---------------------------------------------------------------------------

STAGE_POLICIES: dict[str, StagePolicy] = {
    "init": StagePolicy(
        name="init",
        tools=(
            "orchestrator_status",
            "orchestrator_record_artifact",
            "paper_search",
            "paper_ingest",
            "orchestrator_gate_check",
        ),
        codex="none",
        codex_focus="",
        human_checkpoint="always",
        retry="no_retry",
        description=(
            "Environment sensing, guided interaction, query generation, "
            "exclusion criteria, seed paper ingestion, parameter confirmation."
        ),
        autonomous_allowed=True,
        risk_level="low",
        approval_policy="auto",
    ),
    "build": StagePolicy(
        name="build",
        tools=(
            "paper_search",
            "paper_ingest",
            "select_seeds",
            "expand_citations",
            "paper_acquire",
            "paper_list",
            "paper_coverage_check",
            "paper_dismiss",
            "orchestrator_record_artifact",
            "orchestrator_gate_check",
        ),
        codex="optional",
        codex_focus=(
            "Evaluate search coverage: are key baselines and seminal works included? "
            "Check method family diversity and temporal span."
        ),
        human_checkpoint="conditional",
        retry="retry_twice",
        description=(
            "Multi-source retrieval, citation expansion, relevance filtering, "
            "metadata completion, PDF cascade, structured extraction."
        ),
        autonomous_allowed=True,
        risk_level="low",
        approval_policy="auto",
    ),
    "analyze": StagePolicy(
        name="analyze",
        tools=(
            "paper_list",
            "paper_search",
            "paper_ingest",
            "claim_extract",
            "evidence_link",
            "baseline_identify",
            "gap_detect",
            "orchestrator_record_artifact",
            "orchestrator_gate_check",
        ),
        codex="optional",
        codex_focus=(
            "Evaluate claim graph completeness, gap significance, "
            "and research direction novelty/feasibility."
        ),
        human_checkpoint="always",
        retry="retry_twice",
        description=(
            "Method taxonomy, claim extraction, claim graph, baseline identification, "
            "gap detection, research direction ranking."
        ),
        autonomous_allowed=True,
        risk_level="medium",
        approval_policy="budget_dependent",
        expansion_paper_budget=30,
    ),
    "propose": StagePolicy(
        name="propose",
        tools=(
            "paper_search",
            "paper_ingest",
            "paper_acquire",
            "orchestrator_record_artifact",
            "adversarial_run",
            "adversarial_resolve",
            "adversarial_status",
            "orchestrator_gate_check",
        ),
        codex="required",
        codex_focus=(
            "Challenge the research direction for novelty, evidence coverage, "
            "method validity, baseline completeness, scope discipline, "
            "falsifiability, and clarity. Verify method-layer papers "
            "adequately support the proposed approach."
        ),
        human_checkpoint="always",
        retry="retry_once",
        max_codex_rounds=5,
        description=(
            "Proposal draft, method-layer paper expansion (cross-domain), "
            "adversarial optimization, experiment design."
        ),
        autonomous_allowed=True,
        risk_level="high",
        approval_policy="human_required",
        expansion_paper_budget=10,
    ),
    "experiment": StagePolicy(
        name="experiment",
        tools=(
            "code_generate",
            "code_validate",
            "experiment_run",
            "verified_registry_build",
            "verified_registry_check",
            "orchestrator_record_artifact",
            "orchestrator_gate_check",
        ),
        codex="recommended",
        codex_focus=(
            "Review experiment code for correctness, security, and statistical "
            "validity. Check metric computation, baseline fairness, and "
            "reproducibility."
        ),
        human_checkpoint="conditional",
        retry="retry_twice",
        description=(
            "Code generation from study spec, AST validation, sandbox execution, "
            "metric evaluation, iterative improvement, verified registry construction."
        ),
        autonomous_allowed=True,
        risk_level="medium",
        approval_policy="auto",
    ),
    "write": StagePolicy(
        name="write",
        tools=(
            "outline_generate",
            "section_draft",
            "section_review",
            "section_revise",
            "consistency_check",
            "verified_registry_check",
            "paper_verify_numbers",
            "citation_verify",
            "evidence_trace",
            "latex_compile",
            "integrity_check",
            "review_add_issue",
            "review_bundle_create",
            "review_issues",
            "review_respond",
            "review_resolve",
            "review_status",
            "finalize_project",
            "orchestrator_record_artifact",
            "orchestrator_gate_check",
        ),
        codex="recommended",
        codex_focus=(
            "Conduct scholarly review: methodology rigor, statistical validity, "
            "writing clarity, citation completeness, citation density. "
            "Verify comparison table accuracy and BibTeX integrity."
        ),
        human_checkpoint="always",
        retry="retry_once",
        description=(
            "Competitive paper learning, writing architecture discussion, "
            "section drafting, review loop, assembly, submission prep."
        ),
        autonomous_allowed=True,
        risk_level="high",
        approval_policy="human_required",
    ),
}


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------


def get_policy(stage: str) -> StagePolicy | None:
    """Get the execution policy for a stage."""
    return STAGE_POLICIES.get(stage)


def should_invoke_codex(stage: str, mode: str = "standard") -> bool:
    """Determine if codex should be invoked for a stage given the workflow mode."""
    policy = get_policy(stage)
    if policy is None:
        return False
    if policy.codex == "required":
        return True
    if policy.codex == "recommended" and mode in ("standard", "strict"):
        return True
    if policy.codex == "optional" and mode == "strict":
        return True
    return False


def should_pause_human(stage: str, mode: str = "standard", autonomy: str = "supervised") -> bool:
    """Determine if the runner should pause for human approval."""
    policy = get_policy(stage)
    if policy is None:
        return True
    if autonomy == "autonomous":
        if policy.autonomous_allowed:
            return False
        return True
    if policy.human_checkpoint == "always":
        return mode != "demo"
    if policy.human_checkpoint == "conditional":
        return mode in ("standard", "strict")
    return False


def max_retries(stage: str) -> int:
    """Return the max retry count for a stage."""
    policy = get_policy(stage)
    if policy is None:
        return 0
    return {"retry_twice": 2, "retry_once": 1, "no_retry": 0}[policy.retry]


def decide_recovery(
    stage: str,
    error_kind: str,
    retry_count: int,
) -> Literal["retry", "pause_human", "fallback_stage"]:
    """Decide recovery action based on stage policy and error state."""
    limit = max_retries(stage)

    if retry_count < limit:
        return "retry"

    # Exhausted retries — check if fallback is available
    meta = STAGE_REGISTRY.get(stage)
    if meta and meta.fallback_stage:
        return "fallback_stage"

    return "pause_human"
