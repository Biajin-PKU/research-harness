"""Harness actions — compute next_actions, summary, and recovery hints.

Bridges primitive results and orchestrator state to produce agent-guiding
metadata for every MCP tool response (Agent Harness pattern).
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from ..primitives.types import PrimitiveResult

# ---------------------------------------------------------------------------
# Static next_actions defaults (fallback when dynamic derivation has no opinion)
# ---------------------------------------------------------------------------

STATIC_NEXT_ACTIONS: dict[str, list[str]] = {
    "paper_search": [
        "paper_ingest top results — add high-relevance papers to pool",
    ],
    "paper_ingest": [
        "paper_acquire — download PDF and annotate the ingested paper",
        "paper_summarize — generate structured summary of the ingested paper",
    ],
    "paper_acquire": [
        "paper_coverage_check — verify all high-priority papers are covered",
        "orchestrator_record_artifact — record acquisition_report",
    ],
    "paper_summarize": [
        "claim_extract — extract research claims from summarized paper",
    ],
    "claim_extract": [
        "evidence_link for each claim — link claims to supporting evidence",
        "gap_detect — identify research gaps across the literature",
    ],
    "evidence_link": [
        "gap_detect — check for remaining gaps in evidence coverage",
    ],
    "gap_detect": [
        "baseline_identify — identify comparison baselines",
        "section_draft — begin drafting paper sections",
    ],
    "query_refine": [
        "search_query_add for selected candidates — register promising new queries",
        "paper_search using one candidate query — expand the topic paper pool",
    ],
    "paper_coverage_check": [
        "paper_ingest high-necessity papers — download missing full texts",
        "paper_dismiss low-necessity — skip irrelevant papers to save cost",
    ],
    "baseline_identify": [
        "section_draft methodology — draft methods section with baselines",
    ],
    "section_draft": [
        "consistency_check — verify cross-section consistency",
    ],
    "consistency_check": [],
    "design_brief_expand": [
        "design_gap_probe — check knowledge gaps in the design brief",
    ],
    "design_gap_probe": [
        "algorithm_candidate_generate — generate algorithm candidates from brief + gaps",
    ],
    "algorithm_candidate_generate": [
        "originality_boundary_check — verify novelty of candidates against prior art",
    ],
    "originality_boundary_check": [
        "algorithm_design_refine — refine candidate based on novelty feedback",
    ],
    "algorithm_design_refine": [
        "orchestrator_record_artifact type=algorithm_proposal — record the final proposal",
    ],
    "algorithm_design_loop": [
        "orchestrator_record_artifact type=algorithm_proposal — record the converged design",
    ],
}

# ---------------------------------------------------------------------------
# Error recovery mapping
# ---------------------------------------------------------------------------

ERROR_PATTERNS: list[tuple[str, str]] = [
    (
        "no text available",
        "Run paper_coverage_check to find download sources, "
        "then paper_ingest with a direct URL or arxiv_id.",
    ),
    (
        "no api key",
        "Set KIMI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY in your environment.",
    ),
    (
        "api_key",
        "Set KIMI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY in your environment.",
    ),
    (
        "rate limit",
        "Provider rate-limited. Wait 30s and retry, or switch provider.",
    ),
    (
        "unknown primitive",
        "Check available primitives with topic_list or the primitive registry.",
    ),
    (
        "not implemented",
        "This primitive is planned but not yet available. "
        "Try an alternative approach or use a different primitive.",
    ),
    (
        "topic not found",
        "Run topic_list to see available topics, then use the correct topic name.",
    ),
    (
        "paper not found",
        "Run paper_list to see available papers, or paper_ingest to add a new one.",
    ),
    (
        "database disk image is malformed",
        "DB is corrupted. Restart the MCP server — it will auto-recover on startup. "
        "If the error persists on a specific paper, use paper_dismiss to skip it, "
        "then retry the operation.",
    ),
    (
        "disk image is malformed",
        "DB is corrupted. Restart the MCP server — it will auto-recover on startup. "
        "If the error persists on a specific paper, use paper_dismiss to skip it, "
        "then retry the operation.",
    ),
]


def classify_error(error: str) -> str:
    """Match an error string to a recovery hint."""
    if not error:
        return ""
    lower = error.lower()
    for pattern, hint in ERROR_PATTERNS:
        if pattern in lower:
            return hint
    return f"Unexpected error. Check the error message and retry: {error[:200]}"


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------

def compute_summary(primitive: str, result: PrimitiveResult) -> str:
    """Generate a one-line human-readable summary of a primitive result."""
    if not result.success:
        return f"{primitive} failed: {result.error[:200]}"

    output = result.output
    if output is None:
        return f"{primitive} completed with no output"

    # Convert dataclass to dict for uniform access
    data: dict[str, Any] = {}
    if is_dataclass(output) and not isinstance(output, type):
        data = asdict(output)
    elif isinstance(output, dict):
        data = output

    return _SUMMARY_GENERATORS.get(primitive, _default_summary)(primitive, data)


def _default_summary(primitive: str, data: dict[str, Any]) -> str:
    keys = list(data.keys())[:3]
    return f"{primitive} completed ({', '.join(keys)})"


def _paper_search_summary(_: str, data: dict[str, Any]) -> str:
    papers = data.get("papers", [])
    provider = data.get("provider", "")
    ingested = data.get("ingested_count", 0)
    total = data.get("total_before_filter", len(papers))
    parts = [f"Found {len(papers)} papers"]
    if total > len(papers):
        parts.append(f"from {total} candidates")
    if provider:
        parts.append(f"via {provider}")
    if ingested:
        parts.append(f"auto-ingested {ingested}")
    return " ".join(parts)


def _paper_ingest_summary(_: str, data: dict[str, Any]) -> str:
    title = data.get("title", "unknown")
    status = data.get("status", "")
    merged = data.get("merged_fields", [])
    enriched = data.get("enriched_fields", {})
    s = f"Ingested: {title} (status={status})"
    if merged:
        s += f", merged: {', '.join(merged)}"
    if enriched:
        s += f", enriched: {', '.join(enriched.keys())}"
    return s


def _paper_acquire_summary(_: str, data: dict[str, Any]) -> str:
    total = data.get("total", 0)
    downloaded = data.get("downloaded", 0)
    annotated = data.get("annotated", 0)
    enriched = data.get("enriched", 0)
    failed = data.get("failed", 0)
    needs_manual = data.get("needs_manual", 0)
    unable = data.get("unable_to_acquire", [])
    parts = [f"Acquired {downloaded}/{total} papers"]
    if annotated:
        parts.append(f"annotated={annotated}")
    if enriched:
        parts.append(f"enriched={enriched}")
    if failed:
        parts.append(f"failed={failed}")
    if needs_manual:
        parts.append(f"needs_manual={needs_manual}")
    if unable:
        high = sum(1 for u in unable if u.get("relevance") == "high")
        if high:
            parts.append(f"{high} high-priority papers still missing")
    return ", ".join(parts)


def _paper_summarize_summary(_: str, data: dict[str, Any]) -> str:
    summary = data.get("summary", "")
    conf = data.get("confidence", 0.0)
    preview = summary[:80] + "..." if len(summary) > 80 else summary
    return f"Summary (confidence={conf:.1f}): {preview}"


def _claim_extract_summary(_: str, data: dict[str, Any]) -> str:
    claims = data.get("claims", [])
    n_papers = data.get("papers_processed", 0)
    if not claims:
        return f"No claims extracted from {n_papers} papers"
    types: dict[str, int] = {}
    for c in claims:
        et = c.get("evidence_type", "unknown") if isinstance(c, dict) else "unknown"
        types[et] = types.get(et, 0) + 1
    type_str = ", ".join(f"{v} {k}" for k, v in types.items())
    return f"Extracted {len(claims)} claims from {n_papers} papers ({type_str})"


def _gap_detect_summary(_: str, data: dict[str, Any]) -> str:
    gaps = data.get("gaps", [])
    n_papers = data.get("papers_analyzed", 0)
    if not gaps:
        return f"No gaps found in {n_papers} papers — literature may be saturated"
    severities: dict[str, int] = {}
    for g in gaps:
        sev = g.get("severity", "medium") if isinstance(g, dict) else "medium"
        severities[sev] = severities.get(sev, 0) + 1
    sev_str = ", ".join(f"{v} {k}" for k, v in severities.items())
    return f"Found {len(gaps)} gaps in {n_papers} papers ({sev_str})"


def _baseline_identify_summary(_: str, data: dict[str, Any]) -> str:
    baselines = data.get("baselines", [])
    if not baselines:
        return "No baselines identified"
    names = [b.get("name", "?") if isinstance(b, dict) else "?" for b in baselines[:5]]
    return f"Identified {len(baselines)} baselines: {', '.join(names)}"


def _section_draft_summary(_: str, data: dict[str, Any]) -> str:
    draft = data.get("draft") or {}
    if isinstance(draft, dict):
        section = draft.get("section", "unknown")
        wc = draft.get("word_count", 0)
        cites = len(draft.get("citations_used", []))
        return f"Drafted '{section}' section — {wc} words, {cites} citations"
    return "Section draft completed"


def _consistency_check_summary(_: str, data: dict[str, Any]) -> str:
    issues = data.get("issues", [])
    checked = data.get("sections_checked", [])
    if not issues:
        return f"No inconsistencies found across {len(checked)} sections"
    severities: dict[str, int] = {}
    for i in issues:
        sev = i.get("severity", "medium") if isinstance(i, dict) else "medium"
        severities[sev] = severities.get(sev, 0) + 1
    sev_str = ", ".join(f"{v} {k}" for k, v in severities.items())
    return f"Found {len(issues)} inconsistencies ({sev_str})"


def _coverage_check_summary(_: str, data: dict[str, Any]) -> str:
    total = data.get("total_meta_only", 0)
    high = data.get("high_necessity_count", 0)
    if total == 0:
        return "All papers have full text — no coverage gaps"
    return f"{total} meta-only papers, {high} high-necessity needing download"


def _query_refine_summary(_: str, data: dict[str, Any]) -> str:
    candidates = data.get("candidates", [])
    keywords = data.get("top_keywords", [])
    if not candidates:
        return "No new query candidates generated"
    preview = ", ".join(c.get("query", "?") for c in candidates[:3] if isinstance(c, dict))
    return f"Generated {len(candidates)} query candidates from keywords: {', '.join(keywords[:4])} ({preview})"


_SUMMARY_GENERATORS: dict[str, Any] = {
    "paper_search": _paper_search_summary,
    "paper_ingest": _paper_ingest_summary,
    "paper_acquire": _paper_acquire_summary,
    "paper_summarize": _paper_summarize_summary,
    "claim_extract": _claim_extract_summary,
    "gap_detect": _gap_detect_summary,
    "query_refine": _query_refine_summary,
    "baseline_identify": _baseline_identify_summary,
    "section_draft": _section_draft_summary,
    "consistency_check": _consistency_check_summary,
    "paper_coverage_check": _coverage_check_summary,
}

# ---------------------------------------------------------------------------
# Dynamic next_actions derivation
# ---------------------------------------------------------------------------

def _derive_from_result(primitive: str, result: PrimitiveResult) -> list[str]:
    """Derive context-sensitive next_actions from the actual result data."""
    if not result.success:
        return []

    output = result.output
    if output is None:
        return []

    data: dict[str, Any] = {}
    if is_dataclass(output) and not isinstance(output, type):
        data = asdict(output)
    elif isinstance(output, dict):
        data = output

    deriver = _RESULT_DERIVERS.get(primitive)
    if deriver is None:
        return []
    return deriver(data)


def _derive_paper_search(data: dict[str, Any]) -> list[str]:
    papers = data.get("papers", [])
    ingested = data.get("ingested_count", 0)
    if not papers:
        return ["Retry paper_search with broader query or fewer filters"]
    if ingested > 0:
        return [
            "paper_summarize — summarize newly ingested papers",
            "paper_coverage_check — check which papers need full text",
        ]
    return [
        "paper_ingest top results — add high-relevance papers to pool",
    ]


def _derive_claim_extract(data: dict[str, Any]) -> list[str]:
    claims = data.get("claims", [])
    if len(claims) < 3:
        return [
            "claim_extract with more paper_ids — need at least 3 claims for robust analysis",
            "paper_search for additional papers — broaden the evidence base",
        ]
    return [
        "evidence_link for each claim — link claims to supporting evidence",
        "gap_detect — identify research gaps given extracted claims",
    ]


def _derive_gap_detect(data: dict[str, Any]) -> list[str]:
    gaps = data.get("gaps", [])
    if not gaps:
        return [
            "Literature appears well-covered. Proceed to section_draft",
        ]
    high_gaps = [g for g in gaps if isinstance(g, dict) and g.get("severity") == "high"]
    if high_gaps:
        return [
            "paper_search targeting high-severity gaps — fill critical gaps first",
            "baseline_identify — identify baselines before addressing gaps",
        ]
    return [
        "baseline_identify — identify comparison baselines",
        "section_draft — begin drafting with current evidence",
    ]


def _derive_query_refine(data: dict[str, Any]) -> list[str]:
    candidates = data.get("candidates", [])
    if not candidates:
        return ["paper_search with broader keywords — the current pool may be too narrow"]
    top = [c.get("query", "") for c in candidates[:3] if isinstance(c, dict) and c.get("query")]
    actions = [f"paper_search query='{query}' — test candidate coverage" for query in top]
    actions.append("search_query_add — persist chosen candidates in the query registry")
    return actions


def _derive_coverage_check(data: dict[str, Any]) -> list[str]:
    high = data.get("high_necessity_count", 0)
    items = data.get("items", [])
    if high == 0 and not items:
        return ["All papers have full text. Proceed to claim_extract or gap_detect"]
    actions = []
    if high > 0:
        actions.append(
            f"paper_ingest {high} high-necessity papers — download missing PDFs"
        )
    low = sum(1 for i in items if isinstance(i, dict) and i.get("necessity_level") == "low")
    if low > 0:
        actions.append(
            f"paper_dismiss {low} low-necessity papers — skip to save cost"
        )
    return actions


def _derive_consistency_check(data: dict[str, Any]) -> list[str]:
    issues = data.get("issues", [])
    if not issues:
        return ["No issues found. Ready for formal_review or finalize"]
    high = [i for i in issues if isinstance(i, dict) and i.get("severity") in ("high", "critical")]
    if high:
        return [
            f"Fix {len(high)} high-severity inconsistencies before proceeding",
            "section_draft — revise affected sections",
        ]
    return ["section_draft — address minor inconsistencies in next revision"]


_RESULT_DERIVERS: dict[str, Any] = {
    "paper_search": _derive_paper_search,
    "claim_extract": _derive_claim_extract,
    "gap_detect": _derive_gap_detect,
    "query_refine": _derive_query_refine,
    "paper_coverage_check": _derive_coverage_check,
    "consistency_check": _derive_consistency_check,
}


# ---------------------------------------------------------------------------
# Orchestrator state enrichment
# ---------------------------------------------------------------------------

def _enrich_from_orchestrator(
    actions: list[str],
    primitive: str,
    orch_state: dict[str, Any],
) -> list[str]:
    """Append orchestrator-aware hints to the actions list."""
    run = orch_state.get("run", {})
    stage_info = orch_state.get("stage", {})
    gate = orch_state.get("gate", {})

    current_stage = run.get("current_stage", "")
    missing = stage_info.get("missing_artifacts", [])
    can_advance = gate.get("can_advance", False)

    enriched = list(actions)

    if missing:
        enriched.append(
            f"Record missing artifacts for {current_stage}: {', '.join(missing)}"
        )

    if can_advance and current_stage:
        enriched.append(
            f"orchestrator_advance — gate passed, ready to move past {current_stage}"
        )

    blocking = run.get("blocking_issue_count", 0)
    if blocking > 0:
        enriched.append(
            f"review_issues — {blocking} blocking issue(s) must be resolved first"
        )

    return enriched


# ---------------------------------------------------------------------------
# Artifact extraction
# ---------------------------------------------------------------------------

def extract_artifacts(result: PrimitiveResult) -> list[str]:
    """Extract artifact identifiers from a primitive result."""
    if not result.success or result.output is None:
        return []

    data: dict[str, Any] = {}
    if is_dataclass(result.output) and not isinstance(result.output, type):
        data = asdict(result.output)
    elif isinstance(result.output, dict):
        data = result.output

    artifacts: list[str] = []

    # paper_ingest → paper_id
    if "paper_id" in data and result.primitive in ("paper_ingest", "paper_summarize"):
        artifacts.append(f"paper:{data['paper_id']}")

    # claim_extract → claim IDs
    for claim in data.get("claims", []):
        if isinstance(claim, dict) and claim.get("claim_id"):
            artifacts.append(f"claim:{claim['claim_id']}")

    # gap_detect → gap IDs
    for gap in data.get("gaps", []):
        if isinstance(gap, dict) and gap.get("gap_id"):
            artifacts.append(f"gap:{gap['gap_id']}")

    # evidence_link → link
    link = data.get("link")
    if isinstance(link, dict) and link.get("claim_id"):
        artifacts.append(f"evidence_link:{link['claim_id']}→{link.get('source_id', '?')}")

    # section_draft → section name
    draft = data.get("draft")
    if isinstance(draft, dict) and draft.get("section"):
        artifacts.append(f"draft:{draft['section']}")

    return artifacts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_next_actions(
    primitive: str,
    result: PrimitiveResult,
    orch_state: dict[str, Any] | None = None,
) -> list[str]:
    """Compute context-aware next_actions for a primitive result.

    Priority: dynamic derivation > orchestrator enrichment > static fallback.
    """
    # Dynamic first
    actions = _derive_from_result(primitive, result)

    # Orchestrator enrichment
    if orch_state:
        actions = _enrich_from_orchestrator(actions, primitive, orch_state)

    # Static fallback if nothing was derived
    if not actions:
        actions = list(STATIC_NEXT_ACTIONS.get(primitive, []))

    return actions
