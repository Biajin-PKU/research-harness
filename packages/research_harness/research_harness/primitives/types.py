"""Research primitive types — input/output contracts for research operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class PrimitiveCategory(str, Enum):
    """Task taxonomy for research primitives."""

    RETRIEVAL = "retrieval"
    COMPREHENSION = "comprehension"
    EXTRACTION = "extraction"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"
    GENERATION = "generation"
    VERIFICATION = "verification"


@dataclass(frozen=True)
class PrimitiveSpec:
    """Metadata for a registered research primitive."""

    name: str
    category: PrimitiveCategory
    description: str
    input_schema: dict[str, Any]
    output_type: str
    requires_llm: bool = True
    idempotent: bool = False


@dataclass(frozen=True)
class PaperRef:
    """Lightweight paper reference returned by search."""

    title: str
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    arxiv_id: str = ""
    s2_id: str = ""
    url: str = ""
    relevance_score: float = 0.0
    snippet: str = ""
    venue_tier: str = ""
    citation_count: int | None = None


@dataclass(frozen=True)
class PaperSearchInput:
    query: str
    topic_id: int | None = None
    max_results: int = 20
    year_from: int | None = None
    year_to: int | None = None
    venue_filter: str = ""


@dataclass(frozen=True)
class PaperSearchOutput:
    papers: list[PaperRef] = field(default_factory=list)
    provider: str = ""
    query_used: str = ""
    providers_queried: list[str] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    total_before_filter: int = 0
    ingested_count: int = 0


@dataclass(frozen=True)
class PaperIngestInput:
    source: str
    topic_id: int | None = None
    relevance: str = "medium"
    url: str = ""


@dataclass(frozen=True)
class PaperIngestOutput:
    paper_id: int
    title: str
    status: str
    merged_fields: list[str] = field(default_factory=list)
    enriched_fields: dict[str, str] = field(default_factory=dict)
    duplicate_candidates: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectSetContributionsOutput:
    """Result of reading/writing project-level contributions config."""

    project_id: int
    contributions: str
    updated: bool = False  # True for setter, False for getter


@dataclass(frozen=True)
class SummaryOutput:
    paper_id: int
    summary: str
    focus: str = ""
    confidence: float = 0.0
    model_used: str = ""


@dataclass(frozen=True)
class Claim:
    """An extracted research claim with evidence linkage."""

    claim_id: str
    content: str
    paper_ids: list[int] = field(default_factory=list)
    evidence_type: str = ""
    confidence: float = 0.0
    source_section: str = ""

    def __post_init__(self) -> None:
        if not self.claim_id:
            digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:12]
            object.__setattr__(self, "claim_id", f"claim_{digest}")


@dataclass(frozen=True)
class ClaimExtractInput:
    paper_ids: list[int]
    topic_id: int
    focus: str = ""


@dataclass(frozen=True)
class ClaimExtractOutput:
    claims: list[Claim] = field(default_factory=list)
    papers_processed: int = 0


@dataclass(frozen=True)
class EvidenceLink:
    """Link between a claim and its supporting evidence."""

    claim_id: str
    source_type: str
    source_id: str
    strength: str = "moderate"
    notes: str = ""


@dataclass(frozen=True)
class EvidenceLinkInput:
    claim_id: str
    source_type: str
    source_id: str
    strength: str = "moderate"
    notes: str = ""


@dataclass(frozen=True)
class EvidenceLinkOutput:
    link: EvidenceLink
    created: bool = True


@dataclass(frozen=True)
class Gap:
    """A detected research gap."""

    gap_id: str
    description: str
    gap_type: str = ""
    severity: str = "medium"
    related_paper_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class GapDetectInput:
    topic_id: int
    focus: str = ""


@dataclass(frozen=True)
class GapDetectOutput:
    gaps: list[Gap] = field(default_factory=list)
    papers_analyzed: int = 0


@dataclass(frozen=True)
class QueryCandidate:
    """A suggested search query derived from the current paper pool."""

    query: str
    rationale: str = ""
    coverage_direction: str = ""
    priority: str = "medium"


@dataclass(frozen=True)
class QueryRefineOutput:
    """Output of query_refine primitive."""

    topic_id: int = 0
    candidates: list[QueryCandidate] = field(default_factory=list)
    top_keywords: list[str] = field(default_factory=list)
    frequent_authors: list[str] = field(default_factory=list)
    venue_distribution: list[str] = field(default_factory=list)
    known_queries: list[str] = field(default_factory=list)
    gaps_considered: list[str] = field(default_factory=list)
    model_used: str = ""


@dataclass(frozen=True)
class RetrievalRoundRecord:
    """One query's result inside a single iterative_retrieval_loop round."""

    round_index: int
    query: str
    total_hits: int = 0
    dedup_hits: int = 0
    existing_hits: int = 0
    new_papers_added: int = 0
    overlap_ratio: float = 0.0
    seed_gap: str = ""
    ingest_errors: list[str] = field(default_factory=list)
    providers_queried: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IterativeRetrievalLoopOutput:
    """Output of iterative_retrieval_loop primitive.

    Records per-round metrics and the stop reason so downstream consumers
    (build-stage gate, dashboard, cost-aware stopper) can decide whether the
    paper pool has truly converged.
    """

    topic_id: int = 0
    rounds_run: int = 0
    total_new_papers: int = 0
    total_fresh_queries: int = 0
    final_mean_overlap: float = 0.0
    convergence_reached: bool = False
    stop_reason: str = ""
    rounds: list[RetrievalRoundRecord] = field(default_factory=list)
    per_round_mean_overlap: list[float] = field(default_factory=list)
    per_round_new_papers: list[int] = field(default_factory=list)
    total_prompt_tokens: int | None = None
    total_completion_tokens: int | None = None
    total_cost_usd: float = 0.0
    cost_per_new_paper: float | None = None
    model_used: str = ""


@dataclass(frozen=True)
class Baseline:
    """An identified baseline method/system for comparison."""

    name: str
    paper_ids: list[int] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class BaselineIdentifyInput:
    topic_id: int
    focus: str = ""


@dataclass(frozen=True)
class BaselineIdentifyOutput:
    baselines: list[Baseline] = field(default_factory=list)


@dataclass(frozen=True)
class DraftText:
    """A drafted section of text with citation tracking."""

    section: str
    content: str
    citations_used: list[int] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    word_count: int = 0


@dataclass(frozen=True)
class SectionDraftInput:
    section: str
    topic_id: int
    evidence_ids: list[str] = field(default_factory=list)
    outline: str = ""
    max_words: int = 2000


@dataclass(frozen=True)
class SectionDraftOutput:
    draft: DraftText | None = None


@dataclass(frozen=True)
class ConsistencyIssue:
    """An issue found during consistency checking."""

    issue_type: str
    severity: str
    location: str
    description: str
    suggestion: str = ""


@dataclass(frozen=True)
class ConsistencyCheckInput:
    topic_id: int
    sections: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConsistencyCheckOutput:
    issues: list[ConsistencyIssue] = field(default_factory=list)
    sections_checked: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CoverageItem:
    """A meta-only paper assessed for full-text necessity."""

    paper_id: int
    title: str
    has_abstract: bool
    has_pdf: bool
    necessity_level: str  # "high" | "medium" | "low"
    reason: str
    download_hint: str  # e.g. arxiv URL or DOI resolver URL
    arxiv_id: str = ""
    doi: str = ""


@dataclass(frozen=True)
class CoverageCheckInput:
    topic_id: int
    focus: str = ""


@dataclass(frozen=True)
class CoverageCheckOutput:
    items: list[CoverageItem] = field(default_factory=list)
    total_meta_only: int = 0
    high_necessity_count: int = 0


@dataclass(frozen=True)
class SeedPaper:
    """A paper selected as a citation-expansion seed."""

    paper_id: int
    title: str
    venue: str = ""
    venue_tier: str = ""
    year: int | None = None
    citation_count: int | None = None
    relevance: str = ""  # high / medium / low (from paper_topics)
    seed_score: float = 0.0  # composite score used for ranking
    s2_id: str = ""
    arxiv_id: str = ""
    doi: str = ""


@dataclass(frozen=True)
class SelectSeedsOutput:
    seeds: list[SeedPaper] = field(default_factory=list)
    topic_id: int = 0
    total_pool: int = 0  # number of papers considered


@dataclass(frozen=True)
class ExpandCandidatePaper:
    """A paper discovered via citation/reference expansion."""

    title: str
    doi: str = ""
    arxiv_id: str = ""
    s2_id: str = ""
    year: int | None = None
    venue: str = ""
    venue_tier: str = ""
    citation_count: int | None = None
    abstract: str = ""
    direction: str = ""  # "forward" (cites seed) | "backward" (cited by seed)
    seed_paper_id: int = 0  # local DB id of the seed that produced this candidate


@dataclass(frozen=True)
class ExpandCitationsOutput:
    """Result of one citation-expansion run against a set of seeds."""

    topic_id: int
    seeds_used: int = 0
    forward_count: int = 0  # how many citing-paper candidates found
    backward_count: int = 0  # how many reference candidates found
    candidates: list[ExpandCandidatePaper] = field(default_factory=list)
    # Guidance for the model to decide next steps
    decision_guidance: str = ""


@dataclass(frozen=True)
class UnableToAcquireItem:
    """A paper that could not be automatically downloaded."""

    paper_id: int
    title: str
    relevance: str = "medium"
    doi: str = ""
    arxiv_id: str = ""
    failure_reason: str = ""
    download_hint: str = ""


@dataclass(frozen=True)
class PaperAcquireOutput:
    """Result of batch PDF acquisition + annotation for a topic."""

    topic_id: int
    total: int = 0
    downloaded: int = 0
    annotated: int = 0
    enriched: int = 0
    failed: int = 0
    needs_manual: int = 0
    unable_to_acquire: list[UnableToAcquireItem] = field(default_factory=list)


@dataclass(frozen=True)
class HarnessResponse:
    """Unified MCP response envelope following Agent Harness design.

    Every MCP tool response is wrapped in this envelope so Claude receives
    structured guidance (next_actions, recovery_hint) alongside the data.
    """

    status: str  # "success" | "warning" | "error"
    summary: str  # one-line human-readable result
    output: Any  # the actual data payload
    next_actions: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    recovery_hint: str = ""
    # metadata
    primitive: str = ""
    backend: str = ""
    model_used: str = ""
    cost_usd: float = 0.0


@dataclass(frozen=True)
class PrimitiveResult:
    """Standard envelope wrapping every primitive execution result."""

    primitive: str
    success: bool
    output: Any
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    backend: str = ""
    model_used: str = ""
    cost_usd: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def duration_seconds(self) -> float:
        if not self.started_at or not self.finished_at:
            return 0.0
        return (
            datetime.fromisoformat(self.finished_at)
            - datetime.fromisoformat(self.started_at)
        ).total_seconds()

    def input_hash(self, input_data: Any) -> str:
        raw = json.dumps(_to_jsonable(input_data), sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def output_hash(self) -> str:
        raw = json.dumps(_to_jsonable(self.output), sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Experiment types (Sprint 2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeGenerationOutput:
    """Output of code_generate primitive."""

    files: dict[str, str] = field(default_factory=dict)  # filename → content
    entry_point: str = "main.py"
    description: str = ""
    model_used: str = ""


@dataclass(frozen=True)
class CodeValidationIssue:
    """Single issue found during code validation."""

    severity: str = ""  # "error" | "warning"
    category: str = ""  # "syntax" | "security" | "import" | "quality"
    message: str = ""
    line: int | None = None


@dataclass(frozen=True)
class CodeValidationOutput:
    """Output of code_validate primitive."""

    ok: bool = True
    issues: list[CodeValidationIssue] = field(default_factory=list)
    summary: str = ""
    auto_fixed: int = 0  # number of auto-fixes applied


@dataclass(frozen=True)
class ExperimentRunOutput:
    """Output of experiment_run primitive."""

    metrics: dict[str, float] = field(default_factory=dict)
    primary_metric_value: float | None = None
    primary_metric_name: str = ""
    elapsed_sec: float = 0.0
    returncode: int = 0
    timed_out: bool = False
    divergence: str = ""
    code_hash: str = ""
    stdout_tail: str = ""  # last N chars of stdout
    stderr_tail: str = ""


@dataclass(frozen=True)
class VerifiedRegistryOutput:
    """Output of verified_registry_build primitive."""

    whitelist_size: int = 0
    condition_names: list[str] = field(default_factory=list)
    primary_metric: float | None = None
    primary_metric_name: str = ""


@dataclass(frozen=True)
class VerifiedRegistryCheckOutput:
    """Output of verified_registry_check primitive."""

    verified: list[float] = field(default_factory=list)
    unverified: list[float] = field(default_factory=list)
    always_allowed: list[float] = field(default_factory=list)
    pass_rate: float = 0.0
    total_checked: int = 0


# ---------------------------------------------------------------------------
# Verification types (Sprint 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaperVerifyIssue:
    """Single issue found during paper number verification."""

    severity: str = ""  # "error" | "warning"
    number: float = 0.0
    raw_text: str = ""
    section: str = ""
    message: str = ""
    line_number: int = 0


@dataclass(frozen=True)
class PaperVerifyOutput:
    """Output of paper_verify_numbers primitive."""

    total_numbers: int = 0
    verified_count: int = 0
    always_allowed_count: int = 0
    unverified_count: int = 0
    pass_rate: float = 1.0
    ok: bool = True
    issues: list[PaperVerifyIssue] = field(default_factory=list)


@dataclass(frozen=True)
class CitationVerifyItem:
    """Result of verifying a single citation."""

    title: str
    status: str = ""  # "verified" | "partial_match" | "not_found" | "hallucinated"
    confidence: float = 0.0
    matched_title: str = ""
    matched_doi: str = ""
    source: str = ""  # which API confirmed it


@dataclass(frozen=True)
class CitationVerifyOutput:
    """Output of citation_verify primitive."""

    total: int = 0
    verified: int = 0
    partial: int = 0
    not_found: int = 0
    hallucinated: int = 0
    items: list[CitationVerifyItem] = field(default_factory=list)
    pass_rate: float = 1.0


@dataclass(frozen=True)
class EvidenceTraceLink:
    """A single link in the evidence trace chain."""

    claim_id: str = ""
    evidence_link_id: str = ""
    paper_id: int = 0
    paper_title: str = ""
    has_verified_numbers: bool = False
    chain_complete: bool = False


@dataclass(frozen=True)
class EvidenceTraceOutput:
    """Output of evidence_trace primitive."""

    total_claims: int = 0
    traced_claims: int = 0
    fully_traced: int = 0  # claim → evidence → paper → verified numbers
    coverage_ratio: float = 0.0
    traces: list[EvidenceTraceLink] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Writing pipeline types (Sprint 4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutlineSectionItem:
    """A section in the generated outline."""

    section: str
    title: str = ""
    target_words: int = 0
    key_points: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OutlineGenerateOutput:
    """Output of outline_generate primitive."""

    title: str = ""
    abstract_draft: str = ""
    sections: list[OutlineSectionItem] = field(default_factory=list)
    total_target_words: int = 0
    model_used: str = ""


# ---------------------------------------------------------------------------
# Unified review dimension definitions (authoritative source)
# ---------------------------------------------------------------------------

# Section-level writing review: 10 dimensions for evaluating individual sections
SECTION_REVIEW_DIMENSIONS: list[str] = [
    "clarity",
    "novelty",
    "correctness",
    "significance",
    "reproducibility",
    "writing_quality",
    "evidence_support",
    "logical_flow",
    "completeness",
    "conciseness",
]

# Paper-level scholarly review: 7 weighted dimensions for whole-paper evaluation
SCHOLARLY_REVIEW_DIMENSIONS: dict[str, dict[str, float]] = {
    "originality": {"weight": 0.15},
    "methodology": {"weight": 0.25},
    "evidence": {"weight": 0.20},
    "significance": {"weight": 0.15},
    "clarity": {"weight": 0.10},
    "reproducibility": {"weight": 0.10},
    "ethics": {"weight": 0.05},
}


@dataclass(frozen=True)
class ReviewDimension:
    """A single review dimension score."""

    dimension: str  # e.g. "clarity", "novelty", "correctness"
    score: float = 0.0  # 0-1 scale
    comment: str = ""


@dataclass(frozen=True)
class DeterministicCheck:
    """Result of a deterministic (non-LLM) writing check."""

    check_name: str
    passed: bool = True
    details: str = ""
    items_found: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SectionReviewOutput:
    """Output of section_review primitive."""

    section: str = ""
    overall_score: float = 0.0  # 0-1, average of dimensions
    dimensions: list[ReviewDimension] = field(default_factory=list)
    deterministic_checks: list[DeterministicCheck] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    needs_revision: bool = False
    model_used: str = ""


@dataclass(frozen=True)
class SectionReviseOutput:
    """Output of section_revise primitive."""

    section: str = ""
    revised_content: str = ""
    changes_made: list[str] = field(default_factory=list)
    word_count: int = 0
    model_used: str = ""


@dataclass(frozen=True)
class LatexCompileOutput:
    """Output of latex_compile primitive."""

    success: bool = False
    pdf_path: str = ""
    log_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pages: int = 0
    auto_fixes_applied: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaperFinalizeOutput:
    """Output of paper_finalize primitive: one-shot assemble + compile."""

    success: bool = False
    tex_path: str = ""
    bib_path: str = ""
    pdf_path: str = ""
    pages: int = 0
    word_count: int = 0
    sections_assembled: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    auto_fixes_applied: list[str] = field(default_factory=list)
    template_used: str = ""
    validation_errors: int = 0
    validation_warnings: int = 0


# ---------------------------------------------------------------------------
# Evolution types (Sprint 5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExperienceIngestOutput:
    """Output of experience_ingest primitive (V2 unified pipeline)."""

    record_id: int = 0
    source_kind: str = ""
    lesson_id: int | None = None
    gate_verdict: str = "pending"


@dataclass(frozen=True)
class LessonItem:
    """A single extracted lesson."""

    stage: str = ""
    content: str = ""
    lesson_type: str = "observation"  # observation | success | failure | tip
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LessonExtractOutput:
    """Output of lesson_extract primitive."""

    lessons: list[LessonItem] = field(default_factory=list)
    stage: str = ""
    model_used: str = ""


@dataclass(frozen=True)
class LessonOverlayOutput:
    """Output of lesson_overlay primitive."""

    overlay_text: str = ""
    lesson_count: int = 0
    stage: str = ""


@dataclass(frozen=True)
class StrategyDistillOutput:
    """Output of strategy_distill primitive."""

    stage: str = ""
    strategies_created: int = 0
    strategies_updated: int = 0
    strategies_skipped: int = 0
    quality_scores: list[float] = field(default_factory=list)
    model_used: str = ""


@dataclass(frozen=True)
class StrategyInjectOutput:
    """Output of strategy_inject primitive."""

    overlay_text: str = ""
    strategy_count: int = 0
    stage: str = ""


@dataclass(frozen=True)
class ExperimentLogOutput:
    """Output of experiment_log primitive."""

    experiment_id: int = 0
    experiment_number: int = 0
    project_id: int = 0


@dataclass(frozen=True)
class MetaReflectOutput:
    """Output of meta_reflect primitive."""

    decision: str = ""  # DEEPEN | BROADEN | PIVOT | CONCLUDE
    reasoning: str = ""
    next_hypothesis: str = ""
    patterns_observed: str = ""
    confidence: float = 0.5
    reflection_number: int = 0
    model_used: str = ""
    should_transition: bool = False  # True if PIVOT or CONCLUDE
    transition_target: str = ""  # propose (PIVOT) or write (CONCLUDE)


# ---------------------------------------------------------------------------
# Deep reading types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndustrialFeasibility:
    """Structured industrial deployment feasibility assessment."""

    viability: str = ""  # high | medium | low
    latency_constraints: str = ""
    data_requirements: str = ""
    engineering_challenges: list[str] = field(default_factory=list)
    deployment_prerequisites: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CrossPaperLink:
    """Relationship between two papers in the pool."""

    target_paper_id: int = 0
    relation_type: str = ""  # extends | contradicts | applies | improves | competes
    evidence: str = ""


@dataclass(frozen=True)
class DeepReadingNote:
    """Two-pass deep reading output: extraction + critical analysis."""

    # Pass 1 (medium tier): deep extraction
    algorithm_walkthrough: str = ""
    limitation_analysis: str = ""
    reproducibility_assessment: str = ""
    # Pass 2 (heavy tier): critical analysis
    critical_assessment: str = ""
    industrial_feasibility: IndustrialFeasibility = field(
        default_factory=IndustrialFeasibility
    )
    research_implications: list[str] = field(default_factory=list)
    cross_paper_links: list[CrossPaperLink] = field(default_factory=list)


@dataclass(frozen=True)
class DeepReadingOutput:
    """Output of deep_read primitive."""

    paper_id: int = 0
    note: DeepReadingNote = field(default_factory=DeepReadingNote)
    model_used: str = ""
    pass1_model: str = ""
    pass2_model: str = ""
    confidence: float = 0.0


@dataclass(frozen=True)
class GetDeepReadingOutput:
    """Output of get_deep_reading primitive."""

    paper_id: int = 0
    note: DeepReadingNote | None = None
    found: bool = False


@dataclass(frozen=True)
class AffiliationOutput:
    """Output of enrich_affiliations primitive."""

    paper_id: int = 0
    affiliations: list[str] = field(default_factory=list)
    new_affiliations: list[str] = field(default_factory=list)
    source: str = ""


# ---------------------------------------------------------------------------
# Phase 2: Cross-paper analysis types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrioritizedPaper:
    paper_id: int
    title: str = ""
    score: float = 0.0
    gap_relevance: float = 0.0
    citation_score: float = 0.0
    recency_score: float = 0.0


@dataclass(frozen=True)
class ReadingPrioritizeOutput:
    ranked: list[PrioritizedPaper] = field(default_factory=list)
    total_papers: int = 0


@dataclass(frozen=True)
class TaxonomyNode:
    node_id: int = 0
    name: str = ""
    parent_id: int | None = None
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    paper_count: int = 0


@dataclass(frozen=True)
class MethodTaxonomyOutput:
    nodes: list[TaxonomyNode] = field(default_factory=list)
    assignments_count: int = 0
    papers_processed: int = 0


@dataclass(frozen=True)
class ChecklistItem:
    category: str = ""
    item: str = ""
    status: str = "pending"
    notes: str = ""


@dataclass(frozen=True)
class ExperimentDesignChecklistOutput:
    checklist: list[ChecklistItem] = field(default_factory=list)
    completeness_score: float = 0.0


@dataclass(frozen=True)
class NormalizedClaim:
    claim_id: int = 0
    paper_id: int = 0
    claim_text: str = ""
    method: str = ""
    dataset: str = ""
    metric: str = ""
    task: str = ""
    value: str = ""
    direction: str = ""
    confidence: float = 0.5


@dataclass(frozen=True)
class EvidenceMatrixOutput:
    claims: list[NormalizedClaim] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    papers_processed: int = 0


@dataclass(frozen=True)
class ContradictionCandidate:
    contradiction_id: int = 0
    claim_a: NormalizedClaim | None = None
    claim_b: NormalizedClaim | None = None
    same_task: bool = False
    same_dataset: bool = False
    same_metric: bool = False
    confidence: float = 0.5
    conflict_reason: str = ""


@dataclass(frozen=True)
class ContradictionDetectOutput:
    contradictions: list[ContradictionCandidate] = field(default_factory=list)
    claims_analyzed: int = 0


# ---------------------------------------------------------------------------
# Phase 3: Quantitative extraction types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractedTable:
    table_id: int = 0
    paper_id: int = 0
    table_number: int = 0
    caption: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    source_page: int | None = None
    confidence: float = 0.5


@dataclass(frozen=True)
class TableExtractOutput:
    tables: list[ExtractedTable] = field(default_factory=list)
    paper_id: int = 0


@dataclass(frozen=True)
class ExtractedFigure:
    figure_id: int = 0
    paper_id: int = 0
    figure_number: int = 0
    caption: str = ""
    interpretation: str = ""
    key_data_points: list[str] = field(default_factory=list)
    figure_type: str = ""
    source_page: int | None = None


@dataclass(frozen=True)
class FigureInterpretOutput:
    figures: list[ExtractedFigure] = field(default_factory=list)
    paper_id: int = 0


@dataclass(frozen=True)
class AggregatedMetric:
    metric_id: int = 0
    paper_id: int = 0
    method: str = ""
    dataset: str = ""
    metric: str = ""
    value: str = ""
    source_type: str = "text"
    source_ref: str = ""
    confidence: float = 0.5


@dataclass(frozen=True)
class MetricsAggregateOutput:
    metrics: list[AggregatedMetric] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    papers_processed: int = 0


@dataclass(frozen=True)
class DatasetEntry:
    dataset: str = ""
    paper_ids: list[int] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    count: int = 0


@dataclass(frozen=True)
class DatasetIndexOutput:
    datasets: list[DatasetEntry] = field(default_factory=list)
    total_papers: int = 0


@dataclass(frozen=True)
class AuthorEntry:
    name: str = ""
    paper_ids: list[int] = field(default_factory=list)
    paper_count: int = 0


@dataclass(frozen=True)
class AuthorCoverageOutput:
    authors: list[AuthorEntry] = field(default_factory=list)
    total_papers: int = 0


# ---------------------------------------------------------------------------
# Phase 4: Workflow and export types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RebuttalFormatOutput:
    rebuttal_text: str = ""
    issues_addressed: int = 0
    project_id: int = 0


@dataclass(frozen=True)
class TopicExportOutput:
    markdown: str = ""
    topic_name: str = ""
    paper_count: int = 0
    sections: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisualizationOutput:
    mermaid_code: str = ""
    viz_type: str = ""
    title: str = ""
    node_count: int = 0


# ---------------------------------------------------------------------------
# Figure planning (write stage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FigurePlanItem:
    """A planned figure or table for a paper section."""

    figure_id: str = ""  # e.g. "fig:arch", "tab:main"
    kind: str = "figure"  # "figure" | "table"
    title: str = ""  # short descriptive title
    caption: str = ""  # full LaTeX caption text
    section: str = ""  # target section (introduction/method/experiments)
    purpose: str = ""  # what this figure/table communicates
    data_source: str = ""  # where the data/source material comes from
    suggested_layout: str = (
        ""  # e.g. "2-column multirow table with cellcolor for Ours row"
    )
    placement_hint: str = ""  # e.g. "after main results paragraph in Section 4.2"


@dataclass(frozen=True)
class FigurePlanOutput:
    """Output of figure_plan primitive."""

    items: list[FigurePlanItem] = field(default_factory=list)
    total_items: int = 0
    figures_count: int = 0
    tables_count: int = 0
    model_used: str = ""


@dataclass(frozen=True)
class FigureGenerateItem:
    """Result of generating a single figure image."""

    figure_id: str = ""
    filename: str = ""
    path: str = ""
    success: bool = False
    error: str = ""
    prompt_used: str = ""
    model_used: str = ""
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class FigureGenerateOutput:
    """Output of figure_generate primitive."""

    items: list[FigureGenerateItem] = field(default_factory=list)
    total_requested: int = 0
    total_generated: int = 0
    total_failed: int = 0
    output_dir: str = ""
    model_used: str = ""


# ---------------------------------------------------------------------------
# Universal Writing Skill (write stage)
# ---------------------------------------------------------------------------

# 12 extraction dimensions grouped by section
WRITING_SKILL_DIMENSIONS: dict[str, list[str]] = {
    "abstract": ["abstract_hook_type", "abstract_structure"],
    "introduction": ["intro_tension_building", "intro_contribution_style"],
    "related_work": ["rw_taxonomy_type", "rw_positioning"],
    "method": ["method_motivation_ratio", "method_design_justification"],
    "experiments": ["exp_post_table_analysis", "exp_result_narrative"],
    "conclusion": ["conclusion_structure"],
    "overall": ["claim_calibration"],
}

ALL_WRITING_DIMENSIONS: list[str] = [
    d for dims in WRITING_SKILL_DIMENSIONS.values() for d in dims
]


@dataclass(frozen=True)
class WritingObservation:
    """A structural writing observation from a single paper."""

    paper_id: int = 0
    dimension: str = ""  # e.g. 'abstract_hook_type'
    section: str = ""  # e.g. 'abstract'
    observation: str = ""  # structured observation (JSON string)
    example_text: str = ""  # verbatim excerpt from the paper
    paper_venue: str = ""
    paper_venue_tier: str = ""
    paper_year: int = 0


@dataclass(frozen=True)
class WritingPatternExtractOutput:
    """Output of writing_pattern_extract: observations from one paper."""

    paper_id: int = 0
    observations: list[WritingObservation] = field(default_factory=list)
    dimensions_extracted: int = 0
    model_used: str = ""


@dataclass(frozen=True)
class DimensionGuidance:
    """Aggregated writing guidance for a single dimension."""

    dimension: str = ""  # e.g. 'abstract_hook_type'
    section: str = ""  # e.g. 'abstract'
    pattern_distribution: dict[str, float] = field(default_factory=dict)
    recommended_approach: str = ""  # 2-3 sentence guidance
    examples: list[str] = field(default_factory=list)  # 2-3 good examples
    anti_patterns: list[str] = field(default_factory=list)
    source_paper_count: int = 0
    confidence: float = 0.0  # based on sample size


@dataclass(frozen=True)
class WritingSkillAggregateOutput:
    """Output of writing skill aggregation across papers."""

    dimensions: list[DimensionGuidance] = field(default_factory=list)
    total_papers_analyzed: int = 0
    strategies_created: int = 0
    strategies_updated: int = 0
    model_used: str = ""


# ---------------------------------------------------------------------------
# Competitive learning (write stage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WritingPattern:
    """A writing pattern extracted from an exemplar paper."""

    dimension: str  # e.g. "intro_narrative", "method_exposition", "section_lengths"
    pattern: str  # description of the pattern
    example: str = ""  # concrete example from the exemplar
    source_paper: str = ""  # title of the exemplar paper


@dataclass(frozen=True)
class CompetitiveLearningOutput:
    """Output of competitive learning: writing patterns from exemplar papers."""

    venue: str = ""
    exemplar_count: int = 0
    patterns: list[WritingPattern] = field(default_factory=list)
    section_length_norms: dict[str, int] = field(default_factory=dict)
    narrative_guidance: str = ""
    model_used: str = ""


# ---------------------------------------------------------------------------
# Topic framing (init stage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopicFramingOutput:
    """Output of topic framing: structured topic definition from context analysis."""

    topic_name: str = ""
    description: str = ""
    search_queries: list[str] = field(default_factory=list)
    scope_keywords: list[str] = field(default_factory=list)
    target_venue: str = ""
    year_from: int = 0
    exclusions: list[str] = field(default_factory=list)
    seed_papers: list[str] = field(default_factory=list)
    model_used: str = ""


# ---------------------------------------------------------------------------
# Research direction ranking (analyze stage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankedDirection:
    """A candidate research direction with scores."""

    direction: str
    description: str = ""
    novelty: float = 0.0
    feasibility: float = 0.0
    impact: float = 0.0
    composite_score: float = 0.0
    supporting_gaps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DirectionRankingOutput:
    """Output of research direction ranking."""

    directions: list[RankedDirection] = field(default_factory=list)
    recommendation: str = ""
    model_used: str = ""


# ---------------------------------------------------------------------------
# Method layer expansion (propose stage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MethodQuery:
    """A search query for method-layer literature."""

    query: str
    category: str = ""  # method_foundation / technique_reference / evaluation_reference
    rationale: str = ""


@dataclass(frozen=True)
class MethodLayerExpansionOutput:
    """Output of method layer keyword extraction from a proposal."""

    method_keywords: list[str] = field(default_factory=list)
    queries: list[MethodQuery] = field(default_factory=list)
    cross_domain_venues: list[str] = field(default_factory=list)
    model_used: str = ""


# ---------------------------------------------------------------------------
# Writing architecture (write stage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionPlan:
    """Plan for a single paper section."""

    section: str
    title: str = ""
    target_words: int = 0
    argument_strategy: str = ""
    key_evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WritingArchitectureOutput:
    """Output of writing architecture design."""

    paper_title: str = ""
    narrative_strategy: str = ""
    sections: list[SectionPlan] = field(default_factory=list)
    total_words: int = 0
    strengths: list[str] = field(default_factory=list)
    model_used: str = ""


# ---------------------------------------------------------------------------
# Algorithm design subsystem types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DesignBriefOutput:
    """Output of design_brief_expand — formalizes a direction into a design brief."""

    problem_definition: str = ""
    constraints: list[str] = field(default_factory=list)
    method_slots: list[dict[str, Any]] = field(default_factory=list)
    blocking_questions: list[str] = field(default_factory=list)
    model_used: str = ""


@dataclass(frozen=True)
class DesignGapProbeOutput:
    """Output of design_gap_probe — identifies knowledge blanks in a design brief."""

    knowledge_gaps: list[dict[str, Any]] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    deep_read_targets: list[int] = field(default_factory=list)
    model_used: str = ""


@dataclass(frozen=True)
class AlgorithmCandidate:
    """A single algorithm candidate with provenance-tagged components."""

    name: str = ""
    architecture_description: str = ""
    components: list[dict[str, Any]] = field(default_factory=list)
    novelty_statement: str = ""
    feasibility_notes: str = ""
    provenance_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AlgorithmCandidateGenerateOutput:
    """Output of algorithm_candidate_generate — 2-3 concrete algorithm blueprints."""

    candidates: list[AlgorithmCandidate] = field(default_factory=list)
    method_inventory_used: int = 0
    model_used: str = ""


@dataclass(frozen=True)
class OriginalityBoundaryCheckOutput:
    """Output of originality_boundary_check — novelty verdict against prior art."""

    candidate_name: str = ""
    near_matches: list[dict[str, Any]] = field(default_factory=list)
    novelty_verdict: str = ""
    novelty_score: float = 0.0
    recommended_modifications: list[str] = field(default_factory=list)
    model_used: str = ""


@dataclass(frozen=True)
class AlgorithmDesignRefineOutput:
    """Output of algorithm_design_refine — final research proposal document."""

    proposal_title: str = ""
    problem_formulation: str = ""
    algorithm_description: str = ""
    components: list[dict[str, Any]] = field(default_factory=list)
    novelty_statement: str = ""
    experiment_hooks: list[str] = field(default_factory=list)
    provenance_summary: list[dict[str, Any]] = field(default_factory=list)
    model_used: str = ""


@dataclass(frozen=True)
class AlgorithmDesignLoopOutput:
    """Output of algorithm_design_loop — full iterative design process trace."""

    final_proposal: AlgorithmDesignRefineOutput | None = None
    rounds_completed: int = 0
    convergence_reason: str = ""
    briefs: list[DesignBriefOutput] = field(default_factory=list)
    gap_probes: list[DesignGapProbeOutput] = field(default_factory=list)
    candidates_history: list[AlgorithmCandidateGenerateOutput] = field(
        default_factory=list
    )
    originality_checks: list[OriginalityBoundaryCheckOutput] = field(
        default_factory=list
    )
    papers_read_during_loop: int = 0
    model_used: str = ""


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value
