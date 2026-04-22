"""End-to-end integration tests for the literature review pipeline.

Tests the full flow: topic init → paper ingest → claim_extract → gap_detect →
outline_generate → section_draft → section_review.

Uses mocked LLM responses so tests are deterministic and fast.
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import patch

import pytest

from research_harness.execution.harness import ResearchHarnessBackend
from research_harness.execution.tracked import TrackedBackend
from research_harness.primitives.types import (
    SCHOLARLY_REVIEW_DIMENSIONS,
    SECTION_REVIEW_DIMENSIONS,
)
from research_harness.provenance.recorder import ProvenanceRecorder
from research_harness.storage.db import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_db(tmp_path):
    """Create a test DB with a topic and papers pre-loaded."""
    db = Database(tmp_path / "e2e.db")
    db.migrate()
    conn = db.connect()
    try:
        # Create topic
        conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("auto-bidding", "Automated bidding in online advertising"),
        )
        # Create a project with contributions so outline_generate's
        # fail-fast guard is satisfied in e2e tests.
        _e2e_contributions = (
            "Paper title: DeepBid\n"
            "1. A reinforcement-learning auto-bidder that jointly optimizes budget pacing and auction bids.\n"
            "2. An offline-to-online training pipeline calibrated on real ad logs.\n"
            "3. Empirical evaluation showing +5% revenue vs. prior art."
        )
        conn.execute(
            """INSERT INTO projects (topic_id, name, description, contributions)
               VALUES (1, 'e2e-test', 'E2E project', ?)""",
            (_e2e_contributions,),
        )
        # Create papers
        for i, (title, year, venue) in enumerate(
            [
                ("Deep Bidding: Reinforcement Learning for Ad Auctions", 2023, "KDD"),
                ("Budget-Constrained Bidding with Pacing", 2022, "NeurIPS"),
                ("Auction Design for Auto-Bidders", 2024, "ICML"),
            ],
            start=1,
        ):
            conn.execute(
                """INSERT INTO papers (title, year, venue, status, s2_id, arxiv_id, doi)
                   VALUES (?, ?, ?, 'ingested', ?, ?, ?)""",
                (title, year, venue, f"s2_test_{i}", f"arxiv_test_{i}", f"10.test/{i}"),
            )
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, 1, 'high')",
                (i,),
            )
            # Add summary annotations so primitives have text to work with
            conn.execute(
                """INSERT INTO paper_annotations (paper_id, section, content, source, confidence)
                   VALUES (?, 'summary', ?, 'test', 0.9)""",
                (
                    i,
                    f"This paper studies {title.lower()} in the context of automated advertising.",
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.fixture
def backend(pipeline_db):
    """Create a tracked backend for e2e testing."""
    inner = ResearchHarnessBackend(db=pipeline_db)
    recorder = ProvenanceRecorder(pipeline_db)
    return TrackedBackend(inner=inner, recorder=recorder)


# ---------------------------------------------------------------------------
# Mock LLM responses
# ---------------------------------------------------------------------------

_CLAIM_EXTRACT_RESPONSE = json.dumps(
    {
        "claims": [
            {
                "content": "RL-based bidding outperforms rule-based by 15%",
                "evidence_type": "empirical",
                "confidence": 0.8,
            },
            {
                "content": "Budget pacing reduces overspend by 30%",
                "evidence_type": "empirical",
                "confidence": 0.7,
            },
            {
                "content": "Auction design affects bidder welfare",
                "evidence_type": "theoretical",
                "confidence": 0.9,
            },
        ]
    }
)

_GAP_DETECT_RESPONSE = json.dumps(
    {
        "gaps": [
            {
                "description": "No work on multi-objective bidding with fairness constraints",
                "gap_type": "methodological",
                "severity": "high",
            },
            {
                "description": "Limited empirical evaluation on real-world ad exchanges",
                "gap_type": "empirical",
                "severity": "medium",
            },
        ]
    }
)

_QUERY_REFINE_RESPONSE = json.dumps(
    {
        "candidates": [
            {
                "query": "fairness constrained auto bidding",
                "rationale": "Targets the uncovered fairness direction from gap detection",
                "coverage_direction": "methodological gap",
                "priority": "high",
            },
            {
                "query": "real world ad exchange bidding evaluation",
                "rationale": "Expands empirical coverage beyond simulated settings",
                "coverage_direction": "empirical gap",
                "priority": "medium",
            },
        ]
    }
)

_OUTLINE_RESPONSE = json.dumps(
    {
        "title": "Multi-Objective Auto-Bidding with Fairness Constraints",
        "abstract_draft": "We propose a multi-objective framework for automated bidding that balances efficiency with fairness.",
        "sections": [
            {
                "section": "introduction",
                "title": "Introduction",
                "target_words": 900,
                "key_points": ["Motivation", "Contribution"],
            },
            {
                "section": "related_work",
                "title": "Related Work",
                "target_words": 800,
                "key_points": ["RL bidding", "Auction design"],
            },
            {
                "section": "method",
                "title": "Method",
                "target_words": 1500,
                "key_points": ["Framework", "Optimization"],
            },
            {
                "section": "experiments",
                "title": "Experiments",
                "target_words": 1200,
                "key_points": ["Setup", "Results"],
            },
            {
                "section": "conclusion",
                "title": "Conclusion",
                "target_words": 300,
                "key_points": ["Summary"],
            },
        ],
    }
)

_SECTION_DRAFT_RESPONSE = json.dumps(
    {
        "content": "Automated bidding has emerged as a critical component of online advertising [1]. Recent work demonstrates significant improvements through reinforcement learning approaches [2].",
        "citations_used": [1, 2],
        "word_count": 25,
    }
)

_SECTION_REVIEW_RESPONSE = json.dumps(
    {
        "dimensions": [
            {"dimension": "clarity", "score": 0.8, "comment": "Clear writing"},
            {"dimension": "novelty", "score": 0.6, "comment": "Standard framing"},
            {"dimension": "correctness", "score": 0.9, "comment": "Accurate claims"},
            {
                "dimension": "significance",
                "score": 0.7,
                "comment": "Relevant contribution",
            },
            {
                "dimension": "reproducibility",
                "score": 0.5,
                "comment": "Missing some details",
            },
            {"dimension": "writing_quality", "score": 0.8, "comment": "Good style"},
            {"dimension": "evidence_support", "score": 0.7, "comment": "Has citations"},
            {
                "dimension": "logical_flow",
                "score": 0.8,
                "comment": "Logical progression",
            },
            {"dimension": "completeness", "score": 0.6, "comment": "Could cover more"},
            {"dimension": "conciseness", "score": 0.9, "comment": "No filler"},
        ],
        "suggestions": ["Add more recent references", "Expand motivation section"],
        "overall_score": 0.73,
    }
)

_SECTION_REVISE_RESPONSE = json.dumps(
    {
        "revised_content": "Automated bidding has emerged as a critical component in modern online advertising [1]. Recent advances in reinforcement learning have demonstrated significant improvements over traditional rule-based approaches [2], achieving up to 15% better ROI.",
        "changes_made": [
            "Added more recent framing",
            "Expanded motivation with concrete metrics",
        ],
        "word_count": 38,
    }
)

# Map prompt patterns to responses for mock routing
_MOCK_RESPONSES: dict[str, str] = {
    "claim extractor": _CLAIM_EXTRACT_RESPONSE,
    "gap analyst": _GAP_DETECT_RESPONSE,
    "retrieval strategist": _QUERY_REFINE_RESPONSE,
    "paper architect": _OUTLINE_RESPONSE,
    "academic writer drafting": _SECTION_DRAFT_RESPONSE,
    "rigorous academic paper reviewer": _SECTION_REVIEW_RESPONSE,
    "revising a paper section": _SECTION_REVISE_RESPONSE,
}


def _mock_chat(client: Any, prompt: str, **_: Any) -> str:
    """Route prompts to canned responses based on role markers."""
    for marker, response in _MOCK_RESPONSES.items():
        if marker in prompt.lower():
            return response
    return "{}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CURSOR_AGENT_ENABLED")
        or os.getenv("CODEX_ENABLED")
    ),
    reason="Requires an LLM provider (OPENAI_API_KEY / ANTHROPIC_API_KEY / CURSOR_AGENT_ENABLED / CODEX_ENABLED)",
)
class TestE2ELiteratureReview:
    """End-to-end pipeline test with mocked LLM."""

    @pytest.fixture(autouse=True)
    def _mock_llm(self):
        """Mock LLM client to return deterministic responses."""
        with patch(
            "research_harness.execution.llm_primitives._client_chat",
            side_effect=_mock_chat,
        ):
            yield

    def test_claim_extract(self, backend):
        result = backend.execute("claim_extract", paper_ids=[1, 2, 3], topic_id=1)
        assert result.success, f"claim_extract failed: {result.error}"
        assert len(result.output.claims) == 3
        assert result.output.papers_processed == 3
        assert "RL-based" in result.output.claims[0].content

    def test_gap_detect(self, backend):
        result = backend.execute("gap_detect", topic_id=1)
        assert result.success, f"gap_detect failed: {result.error}"
        assert len(result.output.gaps) == 2
        assert result.output.gaps[0].severity == "high"

    def test_query_refine(self, backend, pipeline_db):
        conn = pipeline_db.connect()
        try:
            conn.execute(
                "INSERT INTO search_query_registry (topic_id, query, source) VALUES (1, ?, 'user')",
                ("existing autobidding query",),
            )
            conn.commit()
        finally:
            conn.close()

        result = backend.execute("query_refine", topic_id=1)
        assert result.success, f"query_refine failed: {result.error}"
        assert len(result.output.candidates) == 2
        assert result.output.candidates[0].query == "fairness constrained auto bidding"
        assert "existing autobidding query" in result.output.known_queries
        assert result.output.model_used != "stub"

    def test_outline_generate(self, backend):
        result = backend.execute("outline_generate", topic_id=1, project_id=1)
        assert result.success, f"outline_generate failed: {result.error}"
        output = result.output
        assert output.title != ""
        assert output.abstract_draft != ""
        assert len(output.sections) == 5
        assert output.model_used != "stub"
        assert output.total_target_words > 0

    def test_section_draft(self, backend):
        result = backend.execute("section_draft", section="introduction", topic_id=1)
        assert result.success, f"section_draft failed: {result.error}"
        assert result.output.draft is not None
        assert len(result.output.draft.content) > 0

    def test_section_review(self, backend):
        content = (
            "Automated bidding has emerged as a critical component of online advertising [1]. "
            "Recent work demonstrates significant improvements through reinforcement learning approaches [2]. "
            * 50  # Make it long enough for word count
        )
        result = backend.execute(
            "section_review", section="introduction", content=content
        )
        assert result.success, f"section_review failed: {result.error}"
        output = result.output
        # LLM dimensions should have real scores (not all 0.0)
        assert output.overall_score > 0.0
        assert output.model_used != "deterministic_only"
        assert len(output.dimensions) == 10
        scored = [d for d in output.dimensions if d.score > 0.0]
        assert len(scored) > 0, "Expected non-zero LLM dimension scores"
        # Deterministic checks should also be present
        assert len(output.deterministic_checks) > 0

    def test_section_revise(self, backend):
        result = backend.execute(
            "section_revise",
            section="introduction",
            content="Some draft text.",
            review_feedback="Add more citations and expand motivation.",
        )
        assert result.success, f"section_revise failed: {result.error}"
        output = result.output
        assert output.revised_content != "Some draft text."
        assert output.model_used != "stub"
        assert len(output.changes_made) > 0

    def test_full_pipeline(self, backend):
        """Run the full literature review pipeline end-to-end."""
        # Step 1: claim_extract
        r1 = backend.execute("claim_extract", paper_ids=[1, 2, 3], topic_id=1)
        assert r1.success

        # Step 2: gap_detect
        r2 = backend.execute("gap_detect", topic_id=1)
        assert r2.success

        # Step 3: outline_generate
        r3 = backend.execute("outline_generate", topic_id=1, project_id=1)
        assert r3.success
        assert r3.output.title != ""

        # Step 4: section_draft (draft the introduction)
        r4 = backend.execute("section_draft", section="introduction", topic_id=1)
        assert r4.success
        draft_content = r4.output.draft.content

        # Step 5: section_review
        r5 = backend.execute(
            "section_review",
            section="introduction",
            content=draft_content,
        )
        assert r5.success
        assert r5.output.overall_score > 0.0

        # Step 6: section_revise (if review suggests revision)
        if r5.output.needs_revision:
            feedback = "; ".join(r5.output.suggestions)
            r6 = backend.execute(
                "section_revise",
                section="introduction",
                content=draft_content,
                review_feedback=feedback,
            )
            assert r6.success
            assert r6.output.revised_content != draft_content

    def test_provenance_recorded(self, pipeline_db, backend):
        """Verify that provenance records are created for each primitive call."""
        backend.execute("claim_extract", paper_ids=[1], topic_id=1)
        backend.execute("gap_detect", topic_id=1)

        conn = pipeline_db.connect()
        try:
            rows = conn.execute(
                "SELECT primitive, success FROM provenance_records ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

        primitives_run = [r["primitive"] for r in rows]
        assert "claim_extract" in primitives_run
        assert "gap_detect" in primitives_run
        assert all(r["success"] for r in rows)


class TestUnifiedDimensions:
    """Verify dimension definitions are consistent across the codebase."""

    def test_section_dimensions_count(self):
        assert len(SECTION_REVIEW_DIMENSIONS) == 10

    def test_scholarly_dimensions_count(self):
        assert len(SCHOLARLY_REVIEW_DIMENSIONS) == 7

    def test_scholarly_weights_sum_to_one(self):
        total = sum(d["weight"] for d in SCHOLARLY_REVIEW_DIMENSIONS.values())
        assert abs(total - 1.0) < 0.001

    def test_writing_checks_uses_unified_source(self):
        from research_harness.execution.writing_checks import REVIEW_DIMENSIONS

        assert REVIEW_DIMENSIONS is SECTION_REVIEW_DIMENSIONS

    def test_review_module_uses_unified_source(self):
        from research_harness.orchestrator.review import REVIEW_DIMENSIONS

        assert REVIEW_DIMENSIONS is SCHOLARLY_REVIEW_DIMENSIONS


# ---------------------------------------------------------------------------
# Tool dispatch integration
# ---------------------------------------------------------------------------


class TestToolDispatchIntegration:
    """Test dispatch_stage_tools with budget monitoring."""

    def test_dispatch_with_budget_monitor(self, pipeline_db):
        from research_harness.auto_runner.budget import BudgetLimits, BudgetMonitor
        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools
        from research_harness.orchestrator.service import OrchestratorService

        svc = OrchestratorService(pipeline_db)

        # Create project and orchestrator run
        conn = pipeline_db.connect()
        try:
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'test', 'test')"
            )
            conn.commit()
        finally:
            conn.close()

        monitor = BudgetMonitor(BudgetLimits(max_cost_usd=100.0))

        result = dispatch_stage_tools(
            db=pipeline_db,
            svc=svc,
            project_id=1,
            topic_id=1,
            stage="build",
            tools=("paper_list",),
            context={},
            budget_monitor=monitor,
        )

        assert "summary" in result
        assert "budget" in result
        assert result["budget"]["total_cost_usd"] >= 0

    def test_dispatch_query_paper_list(self, pipeline_db):
        from research_harness.auto_runner.tool_dispatch import dispatch
        from research_harness.orchestrator.service import OrchestratorService

        svc = OrchestratorService(pipeline_db)

        result = dispatch(
            "paper_list",
            db=pipeline_db,
            svc=svc,
            project_id=1,
            topic_id=1,
            stage="build",
            context={},
        )

        assert result.success
        assert result.output["count"] == 3

    def test_dispatch_unknown_tool(self, pipeline_db):
        from research_harness.auto_runner.tool_dispatch import dispatch
        from research_harness.orchestrator.service import OrchestratorService

        svc = OrchestratorService(pipeline_db)

        result = dispatch(
            "nonexistent_tool",
            db=pipeline_db,
            svc=svc,
            project_id=1,
            topic_id=1,
            stage="build",
            context={},
        )

        assert not result.success
        assert "Unknown tool" in result.error
