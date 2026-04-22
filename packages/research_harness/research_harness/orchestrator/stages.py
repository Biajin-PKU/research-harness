"""5-stage registry with predecessor/artifact/gate rules.

V2 redesign: Init → Build → Analyze → Propose → Write.
Legacy 13-stage definitions preserved for artifact compatibility.
"""

from __future__ import annotations

from .models import (
    DEFAULT_MIN_PAPER_COUNT,
    STAGE_GRAPH,
    STAGE_SUBSTEP_MAP,
    SUBSTEP_TO_STAGE,
    StageMetadata,
)


# ---------------------------------------------------------------------------
# Legacy 13-stage registry (preserved for artifact alias resolution)
# ---------------------------------------------------------------------------

LEGACY_STAGE_REGISTRY: dict[str, StageMetadata] = {
    "topic_framing": StageMetadata(
        name="topic_framing",
        display_name="Topic Framing",
        description="Define topic, venue, goals, constraints, and scope boundaries.",
        predecessor=None,
        required_artifacts=("topic_brief",),
        fallback_stage=None,
        gate_type="approval_gate",
    ),
    "literature_mapping": StageMetadata(
        name="literature_mapping",
        display_name="Literature Mapping",
        description="Build a credible literature base with clusters, baselines, and gaps.",
        predecessor="topic_framing",
        required_artifacts=("literature_map", "paper_pool_snapshot"),
        fallback_stage="topic_framing",
        gate_type="coverage_gate",
    ),
    "paper_acquisition": StageMetadata(
        name="paper_acquisition",
        display_name="Paper Acquisition",
        description="Download PDFs, build paperindex annotations, triage manual downloads.",
        predecessor="literature_mapping",
        required_artifacts=("acquisition_report",),
        fallback_stage="literature_mapping",
        gate_type="coverage_gate",
    ),
    "evidence_structuring": StageMetadata(
        name="evidence_structuring",
        display_name="Evidence Structuring",
        description="Transform papers into claims, baselines, and support links.",
        predecessor="paper_acquisition",
        required_artifacts=("evidence_pack", "baseline_matrix", "claim_candidate_set"),
        fallback_stage="literature_mapping",
        gate_type="coverage_gate",
    ),
    "research_direction": StageMetadata(
        name="research_direction",
        display_name="Research Direction",
        description="Propose candidate research direction and contributions.",
        predecessor="evidence_structuring",
        required_artifacts=("direction_proposal",),
        fallback_stage="evidence_structuring",
        gate_type="approval_gate",
    ),
    "adversarial_optimization": StageMetadata(
        name="adversarial_optimization",
        display_name="Adversarial Optimization",
        description="Challenge and resolve the proposed direction via structured debate.",
        predecessor="research_direction",
        required_artifacts=("adversarial_round", "adversarial_resolution"),
        fallback_stage="research_direction",
        gate_type="adversarial_gate",
    ),
    "study_design": StageMetadata(
        name="study_design",
        display_name="Study Design",
        description="Define experiment or study plan with baselines, metrics, and risks.",
        predecessor="adversarial_optimization",
        required_artifacts=("study_spec",),
        fallback_stage="adversarial_optimization",
        gate_type="adversarial_gate",
    ),
    "draft_preparation": StageMetadata(
        name="draft_preparation",
        display_name="Draft Preparation",
        description="Prepare outline, citations, and claim-to-evidence mapping.",
        predecessor="study_design",
        required_artifacts=("draft_pack",),
        fallback_stage="study_design",
        gate_type="approval_gate",
    ),
    "formal_review": StageMetadata(
        name="formal_review",
        display_name="Formal Review",
        description="Run integrity + scholarly review on the draft package.",
        predecessor="draft_preparation",
        required_artifacts=(
            "integrity_review_report",
            "scholarly_review_report",
            "review_bundle",
        ),
        fallback_stage="draft_preparation",
        gate_type="review_gate",
    ),
    "revision": StageMetadata(
        name="revision",
        display_name="Revision",
        description="Address review findings and produce response log.",
        predecessor="formal_review",
        required_artifacts=("revision_package", "response_to_review"),
        fallback_stage="formal_review",
        gate_type="review_gate",
    ),
    "re_review": StageMetadata(
        name="re_review",
        display_name="Re-Review",
        description="Verify revisions solved problems without regressions.",
        predecessor="revision",
        required_artifacts=("re_review_report",),
        fallback_stage="revision",
        gate_type="review_gate",
    ),
    "final_integrity": StageMetadata(
        name="final_integrity",
        display_name="Final Integrity",
        description="Last verification pass before export.",
        predecessor="re_review",
        required_artifacts=("final_integrity_report",),
        fallback_stage="revision",
        gate_type="integrity_gate",
    ),
    "finalize": StageMetadata(
        name="finalize",
        display_name="Finalize",
        description="Produce submission-ready bundle and project summary.",
        predecessor="final_integrity",
        required_artifacts=("final_bundle", "process_summary"),
        fallback_stage="final_integrity",
        gate_type="approval_gate",
    ),
}

LEGACY_STAGE_ORDER: tuple[str, ...] = tuple(LEGACY_STAGE_REGISTRY.keys())


# ---------------------------------------------------------------------------
# V2: 5-stage registry
# ---------------------------------------------------------------------------

STAGE_REGISTRY: dict[str, StageMetadata] = {
    "init": StageMetadata(
        name="init",
        display_name="Init",
        description="Environment sensing, guided interaction, query generation, seed papers.",
        predecessor=None,
        required_artifacts=("topic_brief",),
        fallback_stage=None,
        gate_type="approval_gate",
    ),
    "build": StageMetadata(
        name="build",
        display_name="Build",
        description="Multi-source retrieval, citation expansion, relevance filtering, "
        "metadata completion, PDF cascade, structured extraction.",
        predecessor="init",
        required_artifacts=(
            "literature_map",
            "paper_pool_snapshot",
            "citation_expansion_report",
            "acquisition_report",
        ),
        fallback_stage="init",
        gate_type="coverage_gate",
    ),
    "analyze": StageMetadata(
        name="analyze",
        display_name="Analyze",
        description="Claim extraction, claim graph, gap detection, research direction ranking.",
        predecessor="build",
        required_artifacts=(
            "evidence_pack",
            "claim_candidate_set",
            "direction_proposal",
        ),
        fallback_stage="build",
        gate_type="approval_gate",
        soft_prerequisites=(
            f"Paper pool contains >= {DEFAULT_MIN_PAPER_COUNT} papers",
            "At least one gap detection run completed",
            "Claims extracted from >= 5 papers",
        ),
    ),
    "propose": StageMetadata(
        name="propose",
        display_name="Propose",
        description="Proposal draft, method-layer expansion, adversarial optimization, "
        "experiment design.",
        predecessor="analyze",
        required_artifacts=("adversarial_resolution", "study_spec"),
        fallback_stage="analyze",
        gate_type="adversarial_gate",
        soft_prerequisites=(
            "At least one gap detection run completed",
            f"Paper pool contains >= {DEFAULT_MIN_PAPER_COUNT} papers",
            "Claims extracted from >= 10 papers",
            "Algorithm design loop completed or algorithm_proposal artifact recorded",
        ),
    ),
    "experiment": StageMetadata(
        name="experiment",
        display_name="Experiment",
        description="Code generation, sandbox execution, metric evaluation, "
        "iterative improvement, verified registry construction.",
        predecessor="propose",
        required_artifacts=(
            "experiment_code",
            "experiment_result",
            "verified_registry",
        ),
        fallback_stage="propose",
        gate_type="experiment_gate",
        soft_prerequisites=(
            "Study spec approved through adversarial review",
            "Baseline methods identified",
        ),
    ),
    "write": StageMetadata(
        name="write",
        display_name="Write",
        description="Competitive learning, section drafting, review loop, assembly, "
        "submission prep.",
        predecessor="experiment",
        required_artifacts=("draft_pack", "final_bundle", "process_summary"),
        fallback_stage="experiment",
        gate_type="review_gate",
        soft_prerequisites=(
            "At least one successful experiment run",
            "Verified number registry built",
            "Paper outline generated",
        ),
    ),
}

STAGE_ORDER: tuple[str, ...] = tuple(STAGE_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Artifact-to-stage aliases (covers both legacy and V2 names)
# ---------------------------------------------------------------------------

ARTIFACT_STAGE_ALIASES: dict[str, str] = {
    # --- legacy stage names map to V2 stages ---
    "topic_framing": "init",
    "literature_mapping": "build",
    "paper_acquisition": "build",
    "evidence_structuring": "analyze",
    "research_direction": "analyze",
    "adversarial_optimization": "propose",
    "study_design": "propose",
    "draft_preparation": "write",
    "formal_review": "write",
    "revision": "write",
    "re_review": "write",
    "final_integrity": "write",
    "finalize": "write",
    # --- legacy artifact type aliases → V2 stages ---
    # init
    "topic_overview": "init",
    "topic_scope": "init",
    # build
    "literature_review": "build",
    "paper_pool": "build",
    "paper_pool_summary": "build",
    "citation_expansion_report": "build",
    "citation_expansion": "build",
    "pdf_acquisition_report": "build",
    "acquisition_summary": "build",
    # analyze
    "gap_analysis": "analyze",
    "gap_detect": "analyze",
    "claim_set": "analyze",
    "claims": "analyze",
    "baseline_matrix_draft": "analyze",
    "baselines": "analyze",
    "baseline_matrix": "analyze",
    "research_proposal": "analyze",
    "direction_candidate": "analyze",
    "modeling_proposal": "analyze",
    "research_direction_proposal": "analyze",
    # propose
    "adversarial_review": "propose",
    "adversarial_round": "propose",
    "algorithm_proposal": "propose",
    "experiment_plan": "propose",
    "study_plan": "propose",
    # experiment
    "experiment_execution": "experiment",
    "experiment_code": "experiment",
    "experiment_result": "experiment",
    "experiment_metrics": "experiment",
    "verified_registry": "experiment",
    "verified_numbers": "experiment",
    # write
    "outline": "write",
    "draft_outline": "write",
    "review_report": "write",
    "integrity_report": "write",
    "integrity_review_report": "write",
    "scholarly_review_report": "write",
    "review_bundle": "write",
    "revision_package": "write",
    "response_to_review": "write",
    "re_review_report": "write",
    "final_integrity_report": "write",
    "final_bundle": "write",
    "process_summary": "write",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_stage(name: str) -> str:
    """Given a V2 stage name, legacy substep name, or artifact alias, return V2 stage name.

    Returns *name* unchanged if already a valid V2 stage.
    """
    if name in STAGE_REGISTRY:
        return name
    mapped = SUBSTEP_TO_STAGE.get(name)
    if mapped:
        return mapped
    alias = ARTIFACT_STAGE_ALIASES.get(name)
    if alias:
        return alias
    return name  # Unknown — return as-is for backward compat


def get_stage_metadata(name: str) -> StageMetadata | None:
    """Return metadata for a stage by name (resolves legacy names)."""
    resolved = resolve_stage(name)
    return STAGE_REGISTRY.get(resolved)


def stage_index(name: str) -> int:
    """Return the canonical index of a stage (0-based). Resolves legacy names."""
    resolved = resolve_stage(name)
    try:
        return STAGE_ORDER.index(resolved)
    except ValueError:
        return -1


def is_valid_transition(from_stage: str, to_stage: str) -> bool:
    """Check if a transition is valid using the stage graph.

    A transition is valid if and only if to_stage is in
    STAGE_GRAPH[from_stage]. This covers forward advances,
    self-loops (staying at same stage), and all loopbacks.
    """
    from_resolved = resolve_stage(from_stage)
    to_resolved = resolve_stage(to_stage)
    allowed = STAGE_GRAPH.get(from_resolved)
    if allowed is None:
        return False
    return to_resolved in allowed


def next_stage(current: str) -> str | None:
    """Return the next canonical stage, or None if at write."""
    resolved = resolve_stage(current)
    idx = stage_index(resolved)
    if idx < 0 or idx >= len(STAGE_ORDER) - 1:
        return None
    return STAGE_ORDER[idx + 1]


def get_required_artifacts(stage: str) -> tuple[str, ...]:
    """Return required artifact types for a stage."""
    meta = get_stage_metadata(stage)
    return meta.required_artifacts if meta else ()


def get_gate_type(stage: str) -> str:
    """Return the gate type for a stage."""
    meta = get_stage_metadata(stage)
    return meta.gate_type if meta else "approval_gate"


def get_soft_prerequisites(stage: str) -> tuple[str, ...]:
    """Return soft prerequisites for a stage (advisory, not blocking)."""
    meta = get_stage_metadata(stage)
    return meta.soft_prerequisites if meta else ()


def stage_names_for_query(stage: str) -> list[str]:
    """Return the V2 stage name plus all its legacy substep names.

    Useful for SQL queries that need to match artifacts stored under either
    the new or legacy stage names.
    """
    resolved = resolve_stage(stage)
    substeps = list(STAGE_SUBSTEP_MAP.get(resolved, ()))
    return [resolved] + substeps
