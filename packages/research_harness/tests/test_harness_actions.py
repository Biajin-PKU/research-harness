"""Tests for harness_actions — next_actions, summary, recovery, artifacts."""

from __future__ import annotations

from research_harness.execution.harness_actions import (
    STATIC_NEXT_ACTIONS,
    classify_error,
    compute_next_actions,
    compute_summary,
    extract_artifacts,
)
from research_harness.primitives.types import (
    Claim,
    ClaimExtractOutput,
    CoverageCheckOutput,
    DraftText,
    EvidenceLink,
    EvidenceLinkOutput,
    Gap,
    GapDetectOutput,
    HarnessResponse,
    PaperSearchOutput,
    PrimitiveResult,
    SectionDraftOutput,
)


# ---------------------------------------------------------------------------
# HarnessResponse type
# ---------------------------------------------------------------------------


def test_harness_response_fields():
    r = HarnessResponse(
        status="success",
        summary="Found 5 papers",
        output={"papers": []},
        next_actions=["paper_ingest — add papers"],
        artifacts=["paper:1"],
        recovery_hint="",
        primitive="paper_search",
        backend="local",
        model_used="",
        cost_usd=0.0,
    )
    assert r.status == "success"
    assert r.next_actions == ["paper_ingest — add papers"]
    assert r.artifacts == ["paper:1"]


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------


def test_classify_error_no_text():
    hint = classify_error("no text available for summarization")
    assert "paper_coverage_check" in hint


def test_classify_error_no_api_key():
    hint = classify_error("No API key configured. Set KIMI_API_KEY...")
    assert "API_KEY" in hint


def test_classify_error_rate_limit():
    hint = classify_error("rate limit exceeded")
    assert "30s" in hint or "retry" in hint.lower()


def test_classify_error_unknown():
    hint = classify_error("some weird error nobody expected")
    assert "Unexpected" in hint


def test_classify_error_empty():
    assert classify_error("") == ""


def test_classify_error_topic_not_found():
    hint = classify_error("Topic not found: my-topic")
    assert "topic_list" in hint


# ---------------------------------------------------------------------------
# compute_summary
# ---------------------------------------------------------------------------


def test_summary_paper_search():
    result = PrimitiveResult(
        primitive="paper_search",
        success=True,
        output=PaperSearchOutput(papers=[], provider="multi", total_before_filter=20),
    )
    s = compute_summary("paper_search", result)
    assert "0 papers" in s
    assert "20" in s


def test_summary_claim_extract():
    claims = [
        Claim(claim_id="c1", content="claim 1", evidence_type="empirical"),
        Claim(claim_id="c2", content="claim 2", evidence_type="theoretical"),
    ]
    result = PrimitiveResult(
        primitive="claim_extract",
        success=True,
        output=ClaimExtractOutput(claims=claims, papers_processed=3),
    )
    s = compute_summary("claim_extract", result)
    assert "2 claims" in s
    assert "3 papers" in s


def test_summary_gap_detect_no_gaps():
    result = PrimitiveResult(
        primitive="gap_detect",
        success=True,
        output=GapDetectOutput(gaps=[], papers_analyzed=10),
    )
    s = compute_summary("gap_detect", result)
    assert "No gaps" in s or "saturated" in s


def test_summary_failed():
    result = PrimitiveResult(
        primitive="claim_extract",
        success=False,
        output=None,
        error="no text available",
    )
    s = compute_summary("claim_extract", result)
    assert "failed" in s


def test_summary_coverage_check():
    result = PrimitiveResult(
        primitive="paper_coverage_check",
        success=True,
        output=CoverageCheckOutput(items=[], total_meta_only=0, high_necessity_count=0),
    )
    s = compute_summary("paper_coverage_check", result)
    assert "no coverage gaps" in s.lower() or "All papers" in s


# ---------------------------------------------------------------------------
# compute_next_actions — dynamic derivation
# ---------------------------------------------------------------------------


def test_next_actions_claim_extract_few_claims():
    claims = [Claim(claim_id="c1", content="only one")]
    result = PrimitiveResult(
        primitive="claim_extract",
        success=True,
        output=ClaimExtractOutput(claims=claims, papers_processed=1),
    )
    actions = compute_next_actions("claim_extract", result)
    assert any("more" in a.lower() or "additional" in a.lower() for a in actions)


def test_next_actions_claim_extract_enough_claims():
    claims = [Claim(claim_id=f"c{i}", content=f"claim {i}") for i in range(5)]
    result = PrimitiveResult(
        primitive="claim_extract",
        success=True,
        output=ClaimExtractOutput(claims=claims, papers_processed=3),
    )
    actions = compute_next_actions("claim_extract", result)
    assert any("evidence_link" in a for a in actions)
    assert any("gap_detect" in a for a in actions)


def test_next_actions_gap_detect_no_gaps():
    result = PrimitiveResult(
        primitive="gap_detect",
        success=True,
        output=GapDetectOutput(gaps=[], papers_analyzed=10),
    )
    actions = compute_next_actions("gap_detect", result)
    assert any("section_draft" in a.lower() for a in actions)


def test_next_actions_gap_detect_high_severity():
    gaps = [Gap(gap_id="g1", description="missing", severity="high")]
    result = PrimitiveResult(
        primitive="gap_detect",
        success=True,
        output=GapDetectOutput(gaps=gaps, papers_analyzed=5),
    )
    actions = compute_next_actions("gap_detect", result)
    assert any("paper_search" in a for a in actions)


def test_next_actions_paper_search_no_results():
    result = PrimitiveResult(
        primitive="paper_search",
        success=True,
        output=PaperSearchOutput(papers=[]),
    )
    actions = compute_next_actions("paper_search", result)
    assert any("broader" in a.lower() or "retry" in a.lower() for a in actions)


# ---------------------------------------------------------------------------
# compute_next_actions — static fallback
# ---------------------------------------------------------------------------


def test_next_actions_static_fallback():
    result = PrimitiveResult(
        primitive="baseline_identify",
        success=True,
        output={"baselines": []},
    )
    actions = compute_next_actions("baseline_identify", result)
    assert actions == STATIC_NEXT_ACTIONS["baseline_identify"]


def test_next_actions_failed_result():
    result = PrimitiveResult(
        primitive="claim_extract",
        success=False,
        output=None,
        error="API error",
    )
    actions = compute_next_actions("claim_extract", result)
    # Failed results fall through to static
    assert isinstance(actions, list)


# ---------------------------------------------------------------------------
# compute_next_actions — orchestrator enrichment
# ---------------------------------------------------------------------------


def test_next_actions_with_orch_state():
    result = PrimitiveResult(
        primitive="claim_extract",
        success=True,
        output=ClaimExtractOutput(
            claims=[Claim(claim_id=f"c{i}", content=f"c{i}") for i in range(5)],
            papers_processed=3,
        ),
    )
    orch_state = {
        "run": {"current_stage": "evidence_structuring", "blocking_issue_count": 0},
        "stage": {"missing_artifacts": ["claims", "evidence_links"]},
        "gate": {"can_advance": False},
    }
    actions = compute_next_actions("claim_extract", result, orch_state)
    assert any("missing" in a.lower() for a in actions)


def test_next_actions_orch_can_advance():
    result = PrimitiveResult(
        primitive="section_draft",
        success=True,
        output=SectionDraftOutput(
            draft=DraftText(section="intro", content="...", word_count=500)
        ),
    )
    orch_state = {
        "run": {"current_stage": "draft_preparation", "blocking_issue_count": 0},
        "stage": {"missing_artifacts": []},
        "gate": {"can_advance": True},
    }
    actions = compute_next_actions("section_draft", result, orch_state)
    assert any("orchestrator_advance" in a for a in actions)


# ---------------------------------------------------------------------------
# extract_artifacts
# ---------------------------------------------------------------------------


def test_artifacts_claim_extract():
    claims = [
        Claim(claim_id="claim_abc", content="some claim"),
        Claim(claim_id="claim_def", content="another"),
    ]
    result = PrimitiveResult(
        primitive="claim_extract",
        success=True,
        output=ClaimExtractOutput(claims=claims, papers_processed=2),
    )
    artifacts = extract_artifacts(result)
    assert "claim:claim_abc" in artifacts
    assert "claim:claim_def" in artifacts


def test_artifacts_evidence_link():
    result = PrimitiveResult(
        primitive="evidence_link",
        success=True,
        output=EvidenceLinkOutput(
            link=EvidenceLink(claim_id="c1", source_type="paper", source_id="p5")
        ),
    )
    artifacts = extract_artifacts(result)
    assert any("evidence_link:c1" in a for a in artifacts)


def test_artifacts_section_draft():
    result = PrimitiveResult(
        primitive="section_draft",
        success=True,
        output=SectionDraftOutput(
            draft=DraftText(section="methodology", content="...", word_count=100)
        ),
    )
    artifacts = extract_artifacts(result)
    assert "draft:methodology" in artifacts


def test_artifacts_failed_result():
    result = PrimitiveResult(primitive="claim_extract", success=False, output=None)
    assert extract_artifacts(result) == []


# ---------------------------------------------------------------------------
# Static next_actions coverage
# ---------------------------------------------------------------------------


def test_all_primitives_have_static_defaults():
    expected = {
        "paper_search",
        "paper_ingest",
        "paper_summarize",
        "claim_extract",
        "evidence_link",
        "gap_detect",
        "paper_coverage_check",
        "baseline_identify",
        "section_draft",
        "consistency_check",
    }
    assert expected.issubset(set(STATIC_NEXT_ACTIONS.keys()))
