"""Primitive registry — maps primitive names to specs and implementations."""

from __future__ import annotations

from typing import Any, Callable

from .types import PrimitiveCategory, PrimitiveSpec

PrimitiveImplementation = Callable[..., Any]


PRIMITIVE_REGISTRY: dict[str, PrimitiveSpec] = {}
_IMPLEMENTATIONS: dict[str, PrimitiveImplementation] = {}


def register_primitive(
    spec: PrimitiveSpec,
) -> Callable[[PrimitiveImplementation], PrimitiveImplementation]:
    """Register a primitive spec and the decorated implementation."""

    PRIMITIVE_REGISTRY[spec.name] = spec

    def decorator(fn: PrimitiveImplementation) -> PrimitiveImplementation:
        _IMPLEMENTATIONS[spec.name] = fn
        return fn

    return decorator


def get_primitive_spec(name: str) -> PrimitiveSpec | None:
    return PRIMITIVE_REGISTRY.get(name)


def get_primitive_impl(name: str) -> PrimitiveImplementation | None:
    return _IMPLEMENTATIONS.get(name)


def list_primitives() -> list[PrimitiveSpec]:
    return list(PRIMITIVE_REGISTRY.values())


def list_by_category(category: PrimitiveCategory) -> list[PrimitiveSpec]:
    return [spec for spec in PRIMITIVE_REGISTRY.values() if spec.category == category]


PAPER_SEARCH_SPEC = PrimitiveSpec(
    name="paper_search",
    category=PrimitiveCategory.RETRIEVAL,
    description="Search for papers by query across configured providers",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "topic_id": {"type": "integer"},
            "max_results": {
                "type": "integer",
                "default": 50,
                "description": "Max results. Use ≥50 for Build stage coverage.",
            },
            "year_from": {"type": "integer"},
            "year_to": {"type": "integer"},
            "venue_filter": {"type": "string"},
            "tier_filter": {
                "type": "string",
                "description": "Minimum venue tier filter: ccf_a_star, ccf_a, ccf_b, ccf_c, cas_q1, cas_q2",
            },
            "auto_ingest": {
                "type": "boolean",
                "default": False,
                "description": "When true, auto-ingest top results into the local paper pool",
            },
        },
        "required": ["query"],
    },
    output_type="PaperSearchOutput",
    requires_llm=False,
    idempotent=True,
)

PAPER_INGEST_SPEC = PrimitiveSpec(
    name="paper_ingest",
    category=PrimitiveCategory.RETRIEVAL,
    description="Ingest a paper into the pool by arxiv_id, doi, or pdf_path",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "topic_id": {"type": "integer"},
            "relevance": {"type": "string", "enum": ["high", "medium", "low"]},
            "url": {"type": "string"},
        },
        "required": ["source"],
    },
    output_type="PaperIngestOutput",
    requires_llm=False,
    idempotent=True,
)

PAPER_ACQUIRE_SPEC = PrimitiveSpec(
    name="paper_acquire",
    category=PrimitiveCategory.RETRIEVAL,
    description="Download PDFs, enrich metadata, and build paperindex annotations for all meta_only papers in a topic",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {
                "type": "integer",
                "description": "Topic ID to acquire papers for",
            },
        },
        "required": ["topic_id"],
    },
    output_type="PaperAcquireOutput",
    requires_llm=False,
    idempotent=True,
)

PAPER_SUMMARIZE_SPEC = PrimitiveSpec(
    name="paper_summarize",
    category=PrimitiveCategory.COMPREHENSION,
    description="Generate a focused summary of a paper",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["paper_id"],
    },
    output_type="SummaryOutput",
    requires_llm=True,
)

CLAIM_EXTRACT_SPEC = PrimitiveSpec(
    name="claim_extract",
    category=PrimitiveCategory.EXTRACTION,
    description="Extract research claims from papers within a topic",
    input_schema={
        "type": "object",
        "properties": {
            "paper_ids": {"type": "array", "items": {"type": "integer"}},
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["paper_ids", "topic_id"],
    },
    output_type="ClaimExtractOutput",
    requires_llm=True,
)

EVIDENCE_LINK_SPEC = PrimitiveSpec(
    name="evidence_link",
    category=PrimitiveCategory.EXTRACTION,
    description="Link a claim to supporting evidence",
    input_schema={
        "type": "object",
        "properties": {
            "claim_id": {"type": "string"},
            "source_type": {"type": "string"},
            "source_id": {"type": "string"},
            "strength": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["claim_id", "source_type", "source_id"],
    },
    output_type="EvidenceLinkOutput",
    requires_llm=False,
    idempotent=True,
)

GAP_DETECT_SPEC = PrimitiveSpec(
    name="gap_detect",
    category=PrimitiveCategory.ANALYSIS,
    description="Detect research gaps in a topic's literature",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["topic_id"],
    },
    output_type="GapDetectOutput",
    requires_llm=True,
)

QUERY_REFINE_SPEC = PrimitiveSpec(
    name="query_refine",
    category=PrimitiveCategory.ANALYSIS,
    description="Generate candidate search queries from the current topic paper pool and known gaps",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "max_candidates": {"type": "integer", "default": 8},
        },
        "required": ["topic_id"],
    },
    output_type="QueryRefineOutput",
    requires_llm=True,
)

ITERATIVE_RETRIEVAL_LOOP_SPEC = PrimitiveSpec(
    name="iterative_retrieval_loop",
    category=PrimitiveCategory.RETRIEVAL,
    description=(
        "Run multi-round paper retrieval until the topic's paper pool converges. "
        "Each round calls query_refine to propose fresh queries, executes paper_search "
        "without auto-ingest, computes the overlap ratio between hits and the existing "
        "pool, ingests only the new papers, and stops when overlap ≥ threshold AND new "
        "papers added < new_paper_floor for `window` consecutive rounds (or when the "
        "per-new-paper cost exceeds budget_per_new_paper_usd, if set)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "max_rounds": {
                "type": "integer",
                "default": 5,
                "description": "Hard cap on retrieval rounds.",
            },
            "convergence_threshold": {
                "type": "number",
                "default": 0.8,
                "description": "Mean round overlap ratio above which a round counts as 'mostly duplicates'.",
            },
            "window": {
                "type": "integer",
                "default": 2,
                "description": "Number of consecutive converged rounds required to stop.",
            },
            "new_paper_floor": {
                "type": "integer",
                "default": 5,
                "description": "A round also counts as converged when fewer than this many new papers are ingested.",
            },
            "queries_per_round": {
                "type": "integer",
                "default": 4,
                "description": "Max fresh queries per round (from query_refine candidates).",
            },
            "max_results_per_query": {
                "type": "integer",
                "default": 30,
                "description": "Paper search max_results per query inside the loop.",
            },
            "budget_per_new_paper_usd": {
                "type": "number",
                "description": "Optional cost-aware stop: abort if cost_per_new_paper exceeds this.",
            },
            "ingest_relevance": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "default": "medium",
                "description": "Relevance tag to apply when ingesting new papers discovered by the loop.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="IterativeRetrievalLoopOutput",
    requires_llm=True,
)

PAPER_COVERAGE_CHECK_SPEC = PrimitiveSpec(
    name="paper_coverage_check",
    category=PrimitiveCategory.ANALYSIS,
    description=(
        "Identify meta_only papers at risk of being unread. "
        "Checks whether abstracts exist, scores full-text necessity via LLM, "
        "and surfaces download hints for high-necessity papers."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {
                "type": "string",
                "description": "Optional research focus to guide necessity scoring",
            },
        },
        "required": ["topic_id"],
    },
    output_type="CoverageCheckOutput",
    requires_llm=True,
)

BASELINE_IDENTIFY_SPEC = PrimitiveSpec(
    name="baseline_identify",
    category=PrimitiveCategory.EXTRACTION,
    description="Identify baseline methods for comparison in a topic",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["topic_id"],
    },
    output_type="BaselineIdentifyOutput",
    requires_llm=True,
)

COMPETITIVE_LEARNING_SPEC = PrimitiveSpec(
    name="competitive_learning",
    category=PrimitiveCategory.ANALYSIS,
    description="Analyze exemplar papers from target venue to extract writing patterns "
    "(structure, narrative arc, section lengths, transition techniques). "
    "Run before section_draft to learn from top papers.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {
                "type": "integer",
                "description": "Topic to source exemplar papers from",
            },
            "venue": {
                "type": "string",
                "description": "Target venue name (e.g. 'KDD', 'NeurIPS', 'WWW')",
            },
            "paper_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional: specific paper IDs to use as exemplars. "
                "If omitted, auto-selects high-cited recent papers from the topic matching the venue.",
            },
            "contributions": {
                "type": "string",
                "description": "Optional: your paper's key contributions, to tailor pattern recommendations.",
            },
        },
        "required": ["topic_id", "venue"],
    },
    output_type="CompetitiveLearningOutput",
    requires_llm=True,
)

SECTION_DRAFT_SPEC = PrimitiveSpec(
    name="section_draft",
    category=PrimitiveCategory.GENERATION,
    description="Draft a paper section using linked evidence. "
    "Uses section-specific prompts for intro/related_work/experiments with citation quota. "
    "Optionally accepts writing_patterns from competitive_learning for venue-aware drafting.",
    input_schema={
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "topic_id": {"type": "integer"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "outline": {"type": "string"},
            "writing_patterns": {
                "type": "string",
                "description": "Writing patterns from competitive_learning output. "
                "When provided, drafting follows venue-specific conventions.",
            },
            "max_words": {
                "type": "integer",
                "default": 0,
                "description": "Target word count; 0 uses section-appropriate default "
                "(intro 1500, related_work 2500, method 3000, experiments 3500).",
            },
            "citation_quota": {
                "type": "integer",
                "default": -1,
                "description": "Minimum distinct citations required; -1 uses section-appropriate "
                "default (intro 15, related_work 30, experiments 8).",
            },
        },
        "required": ["section", "topic_id"],
    },
    output_type="SectionDraftOutput",
    requires_llm=True,
)

CONSISTENCY_CHECK_SPEC = PrimitiveSpec(
    name="consistency_check",
    category=PrimitiveCategory.VERIFICATION,
    description="Check consistency across drafted sections",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "sections": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["topic_id"],
    },
    output_type="ConsistencyCheckOutput",
    requires_llm=True,
)


SELECT_SEEDS_SPEC = PrimitiveSpec(
    name="select_seeds",
    category=PrimitiveCategory.RETRIEVAL,
    description=(
        "Select top citation-expansion seeds from the paper pool. "
        "Ranks by composite score: venue tier (0.4) + citation count (0.3) + relevance (0.3). "
        "Returns papers with s2_id or arxiv_id ready for S2 citation/reference expansion."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "top_n": {
                "type": "integer",
                "default": 10,
                "description": "Number of seed papers to return",
            },
            "min_relevance": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "default": "medium",
                "description": "Minimum relevance level to consider",
            },
        },
        "required": ["topic_id"],
    },
    output_type="SelectSeedsOutput",
    requires_llm=False,
    idempotent=True,
)


EXPAND_CITATIONS_SPEC = PrimitiveSpec(
    name="expand_citations",
    category=PrimitiveCategory.RETRIEVAL,
    description=(
        "Expand the paper pool via citation graph traversal on selected seed papers. "
        "Fetches both forward (papers citing the seed) and backward (papers cited by the seed) "
        "directions from Semantic Scholar. Returns rich candidate metadata — venue tier, "
        "citation count, year, abstract — plus decision_guidance to help the model "
        "choose which papers to ingest and how many expansion rounds to run."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "seed_paper_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Local DB paper IDs to use as seeds (from select_seeds output). "
                "If omitted, select_seeds is called automatically with top_n=5.",
            },
            "forward_limit": {
                "type": "integer",
                "default": 50,
                "description": "Max forward candidates per seed (papers that CITE the seed).",
            },
            "backward_limit": {
                "type": "integer",
                "default": 50,
                "description": "Max backward candidates per seed (papers CITED BY the seed).",
            },
        },
        "required": ["topic_id"],
    },
    output_type="ExpandCitationsOutput",
    requires_llm=False,
    idempotent=False,
)


# ---------------------------------------------------------------------------
# Experiment primitives (Sprint 2)
# ---------------------------------------------------------------------------

CODE_GENERATE_SPEC = PrimitiveSpec(
    name="code_generate",
    category=PrimitiveCategory.GENERATION,
    description="Generate experiment code from study spec and topic context.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "study_spec": {
                "type": "string",
                "description": "Study design specification.",
            },
            "iteration": {"type": "integer", "default": 0},
            "previous_code": {"type": "string", "default": ""},
            "previous_metrics": {"type": "object", "default": {}},
            "feedback": {"type": "string", "default": ""},
        },
        "required": ["topic_id", "study_spec"],
    },
    output_type="CodeGenerationOutput",
    requires_llm=True,
)

CODE_VALIDATE_SPEC = PrimitiveSpec(
    name="code_validate",
    category=PrimitiveCategory.VERIFICATION,
    description="Validate experiment code: syntax, security, imports. Auto-fix common issues.",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to validate."},
            "auto_fix": {"type": "boolean", "default": True},
        },
        "required": ["code"],
    },
    output_type="CodeValidationOutput",
    requires_llm=False,
)

EXPERIMENT_RUN_SPEC = PrimitiveSpec(
    name="experiment_run",
    category=PrimitiveCategory.VERIFICATION,
    description="Run experiment in local sandbox with timeout and metric parsing.",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python experiment code."},
            "timeout_sec": {"type": "number", "default": 300.0},
            "primary_metric": {"type": "string", "default": ""},
        },
        "required": ["code"],
    },
    output_type="ExperimentRunOutput",
    requires_llm=False,
)

VERIFIED_REGISTRY_BUILD_SPEC = PrimitiveSpec(
    name="verified_registry_build",
    category=PrimitiveCategory.VERIFICATION,
    description="Build verified number registry from experiment metrics.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "metrics": {"type": "object", "description": "Experiment metrics dict."},
            "primary_metric_name": {"type": "string", "default": ""},
        },
        "required": ["project_id", "metrics"],
    },
    output_type="VerifiedRegistryOutput",
    requires_llm=False,
)

VERIFIED_REGISTRY_CHECK_SPEC = PrimitiveSpec(
    name="verified_registry_check",
    category=PrimitiveCategory.VERIFICATION,
    description="Check numbers against the verified registry whitelist.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "numbers": {"type": "array", "items": {"type": "number"}},
            "tolerance": {"type": "number", "default": 0.01},
        },
        "required": ["project_id", "numbers"],
    },
    output_type="VerifiedRegistryCheckOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Verification primitives (Sprint 3)
# ---------------------------------------------------------------------------

PAPER_VERIFY_NUMBERS_SPEC = PrimitiveSpec(
    name="paper_verify_numbers",
    category=PrimitiveCategory.VERIFICATION,
    description="Verify numbers in paper text against the verified registry whitelist.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "text": {"type": "string", "description": "Paper text (LaTeX or plain)."},
            "section": {
                "type": "string",
                "default": "",
                "description": "Section name for strict/lenient classification.",
            },
            "tolerance": {"type": "number", "default": 0.01},
        },
        "required": ["project_id", "text"],
    },
    output_type="PaperVerifyOutput",
    requires_llm=False,
)

CITATION_VERIFY_SPEC = PrimitiveSpec(
    name="citation_verify",
    category=PrimitiveCategory.VERIFICATION,
    description="Verify citations against external databases (CrossRef, OpenAlex, S2).",
    input_schema={
        "type": "object",
        "properties": {
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "authors": {"type": "array", "items": {"type": "string"}},
                        "year": {"type": "integer"},
                        "venue": {"type": "string"},
                        "doi": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["citations"],
    },
    output_type="CitationVerifyOutput",
    requires_llm=False,
)

EVIDENCE_TRACE_SPEC = PrimitiveSpec(
    name="evidence_trace",
    category=PrimitiveCategory.VERIFICATION,
    description="Trace claims through evidence links to papers and verified numbers.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "topic_id": {"type": "integer"},
        },
        "required": ["project_id", "topic_id"],
    },
    output_type="EvidenceTraceOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Writing pipeline primitives (Sprint 4)
# ---------------------------------------------------------------------------

OUTLINE_GENERATE_SPEC = PrimitiveSpec(
    name="outline_generate",
    category=PrimitiveCategory.GENERATION,
    description="Generate paper outline from contributions, evidence pack, and experiment results. "
    "Contribution fallback chain: explicit argument → projects.contributions → writing_architecture artifact. "
    "Set contributions once per project via project_set_contributions — then every writing primitive reuses it automatically.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "project_id": {"type": "integer"},
            "template": {
                "type": "string",
                "default": "neurips",
                "description": "Conference template.",
            },
            "contributions": {
                "type": "string",
                "default": "",
                "description": "Optional override. Fallback order: this argument → "
                "projects.contributions for this project → latest writing_architecture "
                "artifact. Declare once via project_set_contributions to avoid repetition.",
            },
        },
        "required": ["topic_id", "project_id"],
    },
    output_type="OutlineGenerateOutput",
    requires_llm=True,
)

SECTION_REVIEW_SPEC = PrimitiveSpec(
    name="section_review",
    category=PrimitiveCategory.VERIFICATION,
    description="Review a paper section: 10-dim LLM scoring + deterministic checks (AI phrases, weasel words, word count).",
    input_schema={
        "type": "object",
        "properties": {
            "section": {"type": "string", "description": "Section name."},
            "content": {"type": "string", "description": "Section text to review."},
            "target_words": {"type": "integer", "default": 0},
        },
        "required": ["section", "content"],
    },
    output_type="SectionReviewOutput",
    requires_llm=True,
)

SECTION_REVISE_SPEC = PrimitiveSpec(
    name="section_revise",
    category=PrimitiveCategory.GENERATION,
    description="Revise a paper section based on review feedback.",
    input_schema={
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "content": {"type": "string", "description": "Current section text."},
            "review_feedback": {
                "type": "string",
                "description": "Review issues to address.",
            },
            "target_words": {"type": "integer", "default": 0},
        },
        "required": ["section", "content", "review_feedback"],
    },
    output_type="SectionReviseOutput",
    requires_llm=True,
)

LATEX_COMPILE_SPEC = PrimitiveSpec(
    name="latex_compile",
    category=PrimitiveCategory.GENERATION,
    description="Assemble and compile LaTeX paper with conference template and BibTeX.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "output_dir": {
                "type": "string",
                "description": "Directory for output files.",
            },
            "template": {"type": "string", "default": "neurips"},
            "sections": {
                "type": "object",
                "description": "Section name → content mapping.",
            },
            "title": {"type": "string", "default": ""},
            "authors": {"type": "array", "items": {"type": "string"}, "default": []},
            "abstract": {"type": "string", "default": ""},
            "bibliography_entries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "BibTeX entries.",
            },
        },
        "required": ["project_id", "output_dir"],
    },
    output_type="LatexCompileOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Evolution primitives (Sprint 5)
# ---------------------------------------------------------------------------

EXPERIENCE_INGEST_SPEC = PrimitiveSpec(
    name="experience_ingest",
    category=PrimitiveCategory.EXTRACTION,
    description=(
        "V2 unified experience ingestion. Records human edits, review findings, "
        "gold-standard comparisons, or auto-extracted observations into the "
        "experience pipeline. Bridges to V1 lesson store automatically."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "source_kind": {
                "type": "string",
                "enum": [
                    "human_edit",
                    "self_review",
                    "gold_comparison",
                    "auto_extracted",
                ],
            },
            "stage": {"type": "string"},
            "section": {"type": "string"},
            "before_text": {"type": "string"},
            "after_text": {"type": "string"},
            "diff_summary": {"type": "string"},
            "quality_delta": {"type": "number"},
            "topic_id": {"type": "integer"},
            "project_id": {"type": "integer"},
            "paper_id": {"type": "integer"},
        },
        "required": ["source_kind", "stage"],
    },
    output_type="ExperienceIngestOutput",
    requires_llm=False,
)

LESSON_EXTRACT_SPEC = PrimitiveSpec(
    name="lesson_extract",
    category=PrimitiveCategory.EXTRACTION,
    description="Extract lessons learned from a completed stage execution.",
    input_schema={
        "type": "object",
        "properties": {
            "stage": {"type": "string", "description": "Stage that just completed."},
            "stage_summary": {
                "type": "string",
                "description": "Summary of what happened.",
            },
            "issues_encountered": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["stage", "stage_summary"],
    },
    output_type="LessonExtractOutput",
    requires_llm=True,
)

LESSON_OVERLAY_SPEC = PrimitiveSpec(
    name="lesson_overlay",
    category=PrimitiveCategory.SYNTHESIS,
    description="Build prompt overlay from stored lessons for a stage.",
    input_schema={
        "type": "object",
        "properties": {
            "stage": {"type": "string"},
            "store_path": {
                "type": "string",
                "description": "Path to lessons JSONL file.",
            },
            "top_k": {"type": "integer", "default": 5},
        },
        "required": ["stage", "store_path"],
    },
    output_type="LessonOverlayOutput",
    requires_llm=False,
)

STRATEGY_DISTILL_SPEC = PrimitiveSpec(
    name="strategy_distill",
    category=PrimitiveCategory.SYNTHESIS,
    description=(
        "Distill lessons and trajectories into reusable strategies for a stage. "
        "5-phase pipeline: collect, aggregate, distill, quality-gate, persist."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stage": {
                "type": "string",
                "description": "Stage to distill (e.g. build, analyze)",
            },
            "min_lessons": {"type": "integer", "default": 3},
            "topic_id": {"type": "integer"},
            "force": {"type": "boolean", "default": False},
        },
        "required": ["stage"],
    },
    output_type="StrategyDistillOutput",
    requires_llm=False,  # manages its own LLM calls internally
)

STRATEGY_INJECT_SPEC = PrimitiveSpec(
    name="strategy_inject",
    category=PrimitiveCategory.SYNTHESIS,
    description="Get active strategy overlay text for a stage (for prompt injection).",
    input_schema={
        "type": "object",
        "properties": {
            "stage": {"type": "string"},
            "topic_id": {"type": "integer"},
            "max_strategies": {"type": "integer", "default": 3},
        },
        "required": ["stage"],
    },
    output_type="StrategyInjectOutput",
    requires_llm=False,
)

EXPERIMENT_LOG_SPEC = PrimitiveSpec(
    name="experiment_log",
    category=PrimitiveCategory.EXTRACTION,
    description="Log an experiment result for dual-loop tracking.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "topic_id": {"type": "integer"},
            "hypothesis": {"type": "string"},
            "primary_metric_name": {"type": "string"},
            "primary_metric_value": {"type": "number"},
            "outcome": {
                "type": "string",
                "enum": ["pending", "success", "partial", "failure"],
            },
            "notes": {"type": "string"},
        },
        "required": ["project_id", "topic_id", "hypothesis"],
    },
    output_type="ExperimentLogOutput",
    requires_llm=False,
)

META_REFLECT_SPEC = PrimitiveSpec(
    name="meta_reflect",
    category=PrimitiveCategory.ANALYSIS,
    description=(
        "Cross-experiment meta-reflection: analyze patterns and decide "
        "DEEPEN / BROADEN / PIVOT / CONCLUDE."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "topic_id": {"type": "integer"},
            "force": {"type": "boolean", "default": False},
        },
        "required": ["project_id", "topic_id"],
    },
    output_type="MetaReflectOutput",
    requires_llm=False,  # manages its own LLM calls internally
)


# ---------------------------------------------------------------------------
# Deep reading primitives
# ---------------------------------------------------------------------------

DEEP_READ_SPEC = PrimitiveSpec(
    name="deep_read",
    category=PrimitiveCategory.COMPREHENSION,
    description=(
        "Critical deep reading of a high-priority paper. "
        "Two-pass analysis: Pass 1 extracts algorithm walkthrough, limitations, "
        "and reproducibility. Pass 2 provides critical assessment, industrial "
        "feasibility, research implications, and cross-paper links. "
        "Stores result in paper_annotations."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer", "description": "Paper ID to deep-read"},
            "topic_id": {
                "type": "integer",
                "description": "Topic ID for cross-paper context",
            },
            "focus": {
                "type": "string",
                "description": "Optional focus area for the reading",
            },
        },
        "required": ["paper_id", "topic_id"],
    },
    output_type="DeepReadingOutput",
    requires_llm=True,
)

GET_DEEP_READING_SPEC = PrimitiveSpec(
    name="get_deep_reading",
    category=PrimitiveCategory.COMPREHENSION,
    description="Retrieve a previously stored deep reading note for a paper.",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer", "description": "Paper ID"},
        },
        "required": ["paper_id"],
    },
    output_type="GetDeepReadingOutput",
    requires_llm=False,
    idempotent=True,
)

ENRICH_AFFILIATIONS_SPEC = PrimitiveSpec(
    name="enrich_affiliations",
    category=PrimitiveCategory.EXTRACTION,
    description=(
        "Extract author affiliations from PDF email domains on the first page "
        "and merge with existing paper affiliations. Updates papers.affiliations."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer", "description": "Paper ID"},
        },
        "required": ["paper_id"],
    },
    output_type="AffiliationOutput",
    requires_llm=False,
    idempotent=True,
)


# ---------------------------------------------------------------------------
# Phase 2: Cross-paper analysis specs
# ---------------------------------------------------------------------------

READING_PRIORITIZE_SPEC = PrimitiveSpec(
    name="reading_prioritize",
    category=PrimitiveCategory.ANALYSIS,
    description="Rank unread papers by priority score (gap relevance, citations, recency)",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {
                "type": "string",
                "description": "Research focus for gap relevance scoring",
            },
            "limit": {
                "type": "integer",
                "description": "Max papers to return (default 20)",
            },
            "weights": {
                "type": "object",
                "description": "Score weights: gap, citation, recency (default 0.4/0.3/0.3)",
                "properties": {
                    "gap": {"type": "number"},
                    "citation": {"type": "number"},
                    "recency": {"type": "number"},
                },
            },
        },
        "required": ["topic_id"],
    },
    output_type="ReadingPrioritizeOutput",
    requires_llm=False,
)

METHOD_TAXONOMY_SPEC = PrimitiveSpec(
    name="method_taxonomy",
    category=PrimitiveCategory.ANALYSIS,
    description="Build a method taxonomy from compiled summaries, with alias detection",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["topic_id"],
    },
    output_type="MethodTaxonomyOutput",
    requires_llm=True,
)

EXPERIMENT_DESIGN_CHECKLIST_SPEC = PrimitiveSpec(
    name="experiment_design_checklist",
    category=PrimitiveCategory.ANALYSIS,
    description="Generate a template-based experiment design checklist (no LLM)",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "method_name": {"type": "string", "description": "Method being evaluated"},
        },
        "required": ["topic_id"],
    },
    output_type="ExperimentDesignChecklistOutput",
    requires_llm=False,
)

EVIDENCE_MATRIX_SPEC = PrimitiveSpec(
    name="evidence_matrix",
    category=PrimitiveCategory.ANALYSIS,
    description="Build evidence matrix: normalize claims into structured dimensions",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["topic_id"],
    },
    output_type="EvidenceMatrixOutput",
    requires_llm=True,
)

CONTRADICTION_DETECT_SPEC = PrimitiveSpec(
    name="contradiction_detect",
    category=PrimitiveCategory.ANALYSIS,
    description="Detect contradictions between normalized claims in evidence matrix",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="ContradictionDetectOutput",
    requires_llm=True,
)


# ---------------------------------------------------------------------------
# Phase 3: Quantitative extraction specs
# ---------------------------------------------------------------------------

TABLE_EXTRACT_SPEC = PrimitiveSpec(
    name="table_extract",
    category=PrimitiveCategory.EXTRACTION,
    description="Extract structured tables from paper PDF using vision model",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer"},
        },
        "required": ["paper_id"],
    },
    output_type="TableExtractOutput",
    requires_llm=True,
)

FIGURE_INTERPRET_SPEC = PrimitiveSpec(
    name="figure_interpret",
    category=PrimitiveCategory.EXTRACTION,
    description="Interpret figures from paper PDF using vision model",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer"},
        },
        "required": ["paper_id"],
    },
    output_type="FigureInterpretOutput",
    requires_llm=True,
)

METRICS_AGGREGATE_SPEC = PrimitiveSpec(
    name="metrics_aggregate",
    category=PrimitiveCategory.ANALYSIS,
    description="Aggregate metrics from tables and compiled summaries with provenance",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="MetricsAggregateOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Phase 4: Workflow and export specs
# ---------------------------------------------------------------------------

REBUTTAL_FORMAT_SPEC = PrimitiveSpec(
    name="rebuttal_format",
    category=PrimitiveCategory.GENERATION,
    description="Format a rebuttal letter from review issues and responses",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
        },
        "required": ["project_id"],
    },
    output_type="RebuttalFormatOutput",
    requires_llm=True,
)

TOPIC_EXPORT_SPEC = PrimitiveSpec(
    name="topic_export",
    category=PrimitiveCategory.SYNTHESIS,
    description="Export topic overview as structured markdown report",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="TopicExportOutput",
    requires_llm=False,
)

VISUALIZE_TOPIC_SPEC = PrimitiveSpec(
    name="visualize_topic",
    category=PrimitiveCategory.SYNTHESIS,
    description="Generate Mermaid visualizations: paper graph, taxonomy tree, timeline",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "viz_type": {
                "type": "string",
                "enum": ["paper_graph", "taxonomy_tree", "timeline"],
                "description": "Type of visualization to generate",
            },
        },
        "required": ["topic_id", "viz_type"],
    },
    output_type="VisualizationOutput",
    requires_llm=False,
)


DATASET_INDEX_SPEC = PrimitiveSpec(
    name="dataset_index",
    category=PrimitiveCategory.ANALYSIS,
    description="Extract dataset index from compiled summaries (no LLM)",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="DatasetIndexOutput",
    requires_llm=False,
)

AUTHOR_COVERAGE_SPEC = PrimitiveSpec(
    name="author_coverage",
    category=PrimitiveCategory.ANALYSIS,
    description="Check author coverage in the paper pool (no LLM)",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "author_name": {
                "type": "string",
                "description": "Filter by specific author",
            },
        },
        "required": ["topic_id"],
    },
    output_type="AuthorCoverageOutput",
    requires_llm=False,
)


TOPIC_FRAMING_SPEC = PrimitiveSpec(
    name="topic_framing",
    category=PrimitiveCategory.SYNTHESIS,
    description="Analyze project context (README, docs, papers) to generate a structured "
    "topic definition with search queries, scope boundaries, and seed papers.",
    input_schema={
        "type": "object",
        "properties": {
            "context": {
                "type": "string",
                "description": "Concatenated text from project files (README, docs, notes) "
                "for the LLM to analyze.",
            },
        },
        "required": ["context"],
    },
    output_type="TopicFramingOutput",
    requires_llm=True,
)

DIRECTION_RANKING_SPEC = PrimitiveSpec(
    name="direction_ranking",
    category=PrimitiveCategory.ANALYSIS,
    description="Rank candidate research directions by novelty × feasibility × impact "
    "based on detected gaps and extracted claims.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string", "description": "Optional focus area"},
        },
        "required": ["topic_id"],
    },
    output_type="DirectionRankingOutput",
    requires_llm=True,
)

METHOD_LAYER_EXPANSION_SPEC = PrimitiveSpec(
    name="method_layer_expansion",
    category=PrimitiveCategory.RETRIEVAL,
    description="Extract method keywords from a research proposal and generate "
    "cross-domain search queries for method-layer literature.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "proposal": {
                "type": "string",
                "description": "The research proposal text to extract methods from.",
            },
        },
        "required": ["topic_id", "proposal"],
    },
    output_type="MethodLayerExpansionOutput",
    requires_llm=True,
)

WRITING_ARCHITECTURE_SPEC = PrimitiveSpec(
    name="writing_architecture",
    category=PrimitiveCategory.SYNTHESIS,
    description="Design optimal paper structure based on contributions and venue conventions. "
    "Produces section plan with argument strategy, word targets, and evidence mapping.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "contributions": {
                "type": "string",
                "default": "",
                "description": "Description of the paper's key contributions. "
                "Optional: if omitted, falls back to projects.contributions for "
                "the most recently updated project of this topic. Set once via "
                "project_set_contributions and all writing primitives reuse it.",
            },
            "writing_patterns": {
                "type": "string",
                "description": "Optional: writing patterns from competitive_learning output.",
            },
            "outline": {
                "type": "string",
                "description": "Optional: existing outline draft to refine.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="WritingArchitectureOutput",
    requires_llm=True,
)


PAPER_FINALIZE_SPEC = PrimitiveSpec(
    name="paper_finalize",
    category=PrimitiveCategory.GENERATION,
    description="One-shot paper assembly + PDF compilation. Takes section drafts and "
    "produces .tex, references.bib, and .pdf in one call. Prefers pdflatex, falls back "
    "to tectonic. Default template is 'arxiv' (single-column, self-contained).",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "output_dir": {
                "type": "string",
                "description": "Directory to write paper.tex, references.bib, paper.pdf.",
            },
            "title": {"type": "string"},
            "authors": {"type": "array", "items": {"type": "string"}},
            "abstract": {"type": "string"},
            "sections": {
                "type": "object",
                "description": "Map of section_id → LaTeX content (e.g. "
                "{'introduction': '...', 'method': '...'}).",
            },
            "bibliography_entries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional BibTeX entries.",
            },
            "template": {
                "type": "string",
                "default": "arxiv",
                "description": "Template: arxiv (default, recommended for drafts), neurips, icml, iclr, acl, generic.",
            },
        },
        "required": ["project_id", "output_dir"],
    },
    output_type="PaperFinalizeOutput",
    requires_llm=False,
)


FIGURE_PLAN_SPEC = PrimitiveSpec(
    name="figure_plan",
    category=PrimitiveCategory.SYNTHESIS,
    description="Plan figures and tables for a paper based on contributions and outline. "
    "Produces 3-5 figures + 5-8 tables with captions, layouts, and placement hints.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "contributions": {
                "type": "string",
                "default": "",
                "description": "Description of the paper's key contributions. "
                "Optional: if omitted, falls back to projects.contributions for "
                "the most recently updated project of this topic.",
            },
            "outline": {
                "type": "string",
                "description": "Optional paper outline to inform placement.",
            },
            "target_venue": {
                "type": "string",
                "description": "Target venue (NeurIPS/ICML/KDD/etc.) for styling conventions.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="FigurePlanOutput",
    requires_llm=True,
)


FIGURE_GENERATE_SPEC = PrimitiveSpec(
    name="figure_generate",
    category=PrimitiveCategory.GENERATION,
    description="Generate academic paper figures from figure_plan output using fal.ai image generation. "
    "Converts figure metadata into optimized prompts and produces PNG images in output_dir "
    "for LaTeX \\includegraphics integration. Skips tables, only processes kind='figure' items.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "items": {
                "type": "array",
                "items": {"type": "object"},
                "description": "FigurePlanItem objects (dicts with figure_id, kind, title, caption, "
                "purpose, data_source, suggested_layout). Only kind='figure' items are processed.",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to save generated figure PNGs. Must match paper_finalize output_dir.",
            },
            "model": {
                "type": "string",
                "default": "recraft",
                "description": "Image generation model: 'recraft' (default, best for diagrams) or 'flux' (FLUX Pro).",
            },
        },
        "required": ["topic_id", "items", "output_dir"],
    },
    output_type="FigureGenerateOutput",
    requires_llm=True,
)


WRITING_PATTERN_EXTRACT_SPEC = PrimitiveSpec(
    name="writing_pattern_extract",
    category=PrimitiveCategory.EXTRACTION,
    description="Extract structural writing patterns from a deeply-read paper. "
    "Analyzes 12 dimensions (abstract hook type, experiment analysis style, etc.) "
    "to build the Universal Writing Skill. Results persist in writing_observations table.",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "integer",
                "description": "Paper ID to extract writing patterns from. "
                "Paper should have full text available (PDF downloaded).",
            },
        },
        "required": ["paper_id"],
    },
    output_type="WritingPatternExtractOutput",
    requires_llm=True,
)

PROJECT_SET_CONTRIBUTIONS_SPEC = PrimitiveSpec(
    name="project_set_contributions",
    category=PrimitiveCategory.ANALYSIS,
    description="Set the authoritative paper contributions on a project. "
    "Writing primitives (writing_architecture, outline_generate, figure_plan, "
    "competitive_learning) read this as a fallback when their contributions "
    "argument is empty, so you only need to declare contributions ONCE per project.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
            "contributions": {
                "type": "string",
                "description": "Full contributions text: paper title, method name, "
                "claim bullets, etc. This is the 'source of truth' for downstream "
                "writing primitives.",
            },
        },
        "required": ["project_id", "contributions"],
    },
    output_type="ProjectSetContributionsOutput",
    requires_llm=False,
)


PROJECT_GET_CONTRIBUTIONS_SPEC = PrimitiveSpec(
    name="project_get_contributions",
    category=PrimitiveCategory.ANALYSIS,
    description="Read the authoritative paper contributions from a project.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "integer"},
        },
        "required": ["project_id"],
    },
    output_type="ProjectSetContributionsOutput",
    requires_llm=False,
)


WRITING_SKILL_AGGREGATE_SPEC = PrimitiveSpec(
    name="writing_skill_aggregate",
    category=PrimitiveCategory.SYNTHESIS,
    description="Aggregate writing observations into the Universal Writing Skill. "
    "Reads all writing_observations, computes pattern distributions per dimension, "
    "and persists as strategies for automatic injection into section_draft. "
    "Run after extracting patterns from >=10 papers.",
    input_schema={
        "type": "object",
        "properties": {
            "min_papers": {
                "type": "integer",
                "default": 10,
                "description": "Minimum number of papers with observations required to aggregate.",
            },
        },
        "required": [],
    },
    output_type="WritingSkillAggregateOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Algorithm design subsystem specs
# ---------------------------------------------------------------------------

DESIGN_BRIEF_EXPAND_SPEC = PrimitiveSpec(
    name="design_brief_expand",
    category=PrimitiveCategory.SYNTHESIS,
    description="Expand a research direction into a formal design brief with "
    "problem definition, constraints, method slots, and blocking questions.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "direction": {
                "type": "string",
                "description": "Research direction from direction_ranking",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional design constraints",
            },
        },
        "required": ["topic_id", "direction"],
    },
    output_type="DesignBriefOutput",
)

DESIGN_GAP_PROBE_SPEC = PrimitiveSpec(
    name="design_gap_probe",
    category=PrimitiveCategory.ANALYSIS,
    description="Probe a design brief for knowledge gaps that require "
    "targeted literature search or deep reading.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "brief": {
                "type": "object",
                "description": "Design brief from design_brief_expand",
            },
            "method_inventory": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional method inventory from method_taxonomy",
            },
        },
        "required": ["topic_id", "brief"],
    },
    output_type="DesignGapProbeOutput",
)

ALGORITHM_CANDIDATE_GENERATE_SPEC = PrimitiveSpec(
    name="algorithm_candidate_generate",
    category=PrimitiveCategory.GENERATION,
    description="Generate 2-3 concrete algorithm candidates with provenance-tagged "
    "components from a design brief and method inventory.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "brief": {
                "type": "object",
                "description": "Design brief from design_brief_expand",
            },
            "gap_probe": {"type": "object", "description": "Gap probe results"},
            "deep_read_notes": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Deep reading notes for relevant papers",
            },
        },
        "required": ["topic_id", "brief"],
    },
    output_type="AlgorithmCandidateGenerateOutput",
)

ORIGINALITY_BOUNDARY_CHECK_SPEC = PrimitiveSpec(
    name="originality_boundary_check",
    category=PrimitiveCategory.VERIFICATION,
    description="Check a candidate algorithm against prior art to determine "
    "novelty boundary: novel, incremental, or too_similar.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "candidate": {
                "type": "object",
                "description": "Algorithm candidate to check",
            },
        },
        "required": ["topic_id", "candidate"],
    },
    output_type="OriginalityBoundaryCheckOutput",
)

ALGORITHM_DESIGN_REFINE_SPEC = PrimitiveSpec(
    name="algorithm_design_refine",
    category=PrimitiveCategory.SYNTHESIS,
    description="Refine the best algorithm candidate with originality feedback "
    "into a final research proposal document.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "candidate": {"type": "object", "description": "Best algorithm candidate"},
            "originality_result": {
                "type": "object",
                "description": "Originality check result",
            },
            "feedback": {
                "type": "string",
                "description": "Additional refinement feedback",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Design constraints",
            },
        },
        "required": ["topic_id", "candidate"],
    },
    output_type="AlgorithmDesignRefineOutput",
)

ALGORITHM_DESIGN_LOOP_SPEC = PrimitiveSpec(
    name="algorithm_design_loop",
    category=PrimitiveCategory.SYNTHESIS,
    description="Iterative algorithm design loop: brief → gap probe → candidates → "
    "originality check → refine, max 3 rounds until convergence.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "project_id": {"type": "integer"},
            "direction": {
                "type": "string",
                "description": "Research direction from direction_ranking",
            },
            "max_rounds": {"type": "integer", "default": 3},
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional design constraints",
            },
        },
        "required": ["topic_id", "project_id", "direction"],
    },
    output_type="AlgorithmDesignLoopOutput",
)

COLD_START_RUN_SPEC = PrimitiveSpec(
    name="cold_start_run",
    category=PrimitiveCategory.SYNTHESIS,
    description=(
        "Check cold-start readiness for a topic. Returns phase progress for "
        "Seed (paper count), Index (cards, deep reads, writing obs), and "
        "Calibrate (gaps, writing dimensions)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "gold_papers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional seed arXiv IDs or DOIs to bootstrap the topic",
            },
        },
        "required": ["topic_id"],
    },
    output_type="ColdStartProtocolOutput",
    requires_llm=False,
)


for spec in (
    PROJECT_SET_CONTRIBUTIONS_SPEC,
    PROJECT_GET_CONTRIBUTIONS_SPEC,
    SELECT_SEEDS_SPEC,
    EXPAND_CITATIONS_SPEC,
    PAPER_SEARCH_SPEC,
    PAPER_INGEST_SPEC,
    PAPER_ACQUIRE_SPEC,
    PAPER_SUMMARIZE_SPEC,
    CLAIM_EXTRACT_SPEC,
    EVIDENCE_LINK_SPEC,
    GAP_DETECT_SPEC,
    PAPER_COVERAGE_CHECK_SPEC,
    BASELINE_IDENTIFY_SPEC,
    COMPETITIVE_LEARNING_SPEC,
    SECTION_DRAFT_SPEC,
    CONSISTENCY_CHECK_SPEC,
    CODE_GENERATE_SPEC,
    CODE_VALIDATE_SPEC,
    EXPERIMENT_RUN_SPEC,
    VERIFIED_REGISTRY_BUILD_SPEC,
    VERIFIED_REGISTRY_CHECK_SPEC,
    PAPER_VERIFY_NUMBERS_SPEC,
    CITATION_VERIFY_SPEC,
    EVIDENCE_TRACE_SPEC,
    OUTLINE_GENERATE_SPEC,
    SECTION_REVIEW_SPEC,
    SECTION_REVISE_SPEC,
    LATEX_COMPILE_SPEC,
    LESSON_EXTRACT_SPEC,
    EXPERIENCE_INGEST_SPEC,
    LESSON_OVERLAY_SPEC,
    STRATEGY_DISTILL_SPEC,
    STRATEGY_INJECT_SPEC,
    EXPERIMENT_LOG_SPEC,
    META_REFLECT_SPEC,
    DEEP_READ_SPEC,
    GET_DEEP_READING_SPEC,
    ENRICH_AFFILIATIONS_SPEC,
    READING_PRIORITIZE_SPEC,
    METHOD_TAXONOMY_SPEC,
    EXPERIMENT_DESIGN_CHECKLIST_SPEC,
    EVIDENCE_MATRIX_SPEC,
    CONTRADICTION_DETECT_SPEC,
    DATASET_INDEX_SPEC,
    AUTHOR_COVERAGE_SPEC,
    TABLE_EXTRACT_SPEC,
    FIGURE_INTERPRET_SPEC,
    METRICS_AGGREGATE_SPEC,
    REBUTTAL_FORMAT_SPEC,
    TOPIC_EXPORT_SPEC,
    VISUALIZE_TOPIC_SPEC,
    ITERATIVE_RETRIEVAL_LOOP_SPEC,
    TOPIC_FRAMING_SPEC,
    DIRECTION_RANKING_SPEC,
    METHOD_LAYER_EXPANSION_SPEC,
    WRITING_ARCHITECTURE_SPEC,
    WRITING_PATTERN_EXTRACT_SPEC,
    WRITING_SKILL_AGGREGATE_SPEC,
    FIGURE_PLAN_SPEC,
    FIGURE_GENERATE_SPEC,
    PAPER_FINALIZE_SPEC,
    DESIGN_BRIEF_EXPAND_SPEC,
    DESIGN_GAP_PROBE_SPEC,
    ALGORITHM_CANDIDATE_GENERATE_SPEC,
    ORIGINALITY_BOUNDARY_CHECK_SPEC,
    ALGORITHM_DESIGN_REFINE_SPEC,
    ALGORITHM_DESIGN_LOOP_SPEC,
    COLD_START_RUN_SPEC,
):
    PRIMITIVE_REGISTRY[spec.name] = spec
