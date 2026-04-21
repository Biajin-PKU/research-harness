from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from research_harness.paper_sources import PaperRecord, SearchQuery
from research_harness.primitives import (
    Claim,
    ClaimExtractOutput,
    ConsistencyCheckOutput,
    DraftText,
    EvidenceLink,
    EvidenceLinkOutput,
    GapDetectOutput,
    PaperIngestOutput,
    PaperSearchOutput,
    PrimitiveCategory,
    PrimitiveResult,
    SectionDraftOutput,
    SummaryOutput,
    get_primitive_impl,
    list_by_category,
)
from research_harness.primitives.registry import PRIMITIVE_REGISTRY


def test_primitive_registry_has_all_specs() -> None:
    assert len(PRIMITIVE_REGISTRY) == 69
    for spec in PRIMITIVE_REGISTRY.values():
        assert spec.name
        assert spec.category
        assert spec.description
        assert spec.input_schema
        assert spec.output_type


def test_list_by_category() -> None:
    assert {spec.name for spec in list_by_category(PrimitiveCategory.RETRIEVAL)} == {
        "paper_search",
        "paper_ingest",
        "paper_acquire",
        "select_seeds",
        "expand_citations",
        "iterative_retrieval_loop",
        "method_layer_expansion",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.EXTRACTION)} == {
        "claim_extract",
        "evidence_link",
        "baseline_identify",
        "lesson_extract",
        "experiment_log",
        "enrich_affiliations",
        "table_extract",
        "figure_interpret",
        "writing_pattern_extract",
        "experience_ingest",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.ANALYSIS)} == {
        "gap_detect",
        "paper_coverage_check",
        "query_refine",
        "reading_prioritize",
        "method_taxonomy",
        "experiment_design_checklist",
        "evidence_matrix",
        "contradiction_detect",
        "dataset_index",
        "author_coverage",
        "metrics_aggregate",
        "meta_reflect",
        "competitive_learning",
        "direction_ranking",
        "project_set_contributions",
        "project_get_contributions",
        "design_gap_probe",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.GENERATION)} == {
        "section_draft",
        "code_generate",
        "outline_generate",
        "section_revise",
        "latex_compile",
        "rebuttal_format",
        "paper_finalize",
        "algorithm_candidate_generate",
        "figure_generate",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.VERIFICATION)} == {
        "consistency_check",
        "code_validate",
        "experiment_run",
        "verified_registry_build",
        "verified_registry_check",
        "paper_verify_numbers",
        "citation_verify",
        "evidence_trace",
        "section_review",
        "originality_boundary_check",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.COMPREHENSION)} == {
        "paper_summarize",
        "deep_read",
        "get_deep_reading",
    }
    assert {spec.name for spec in list_by_category(PrimitiveCategory.SYNTHESIS)} == {
        "lesson_overlay",
        "strategy_distill",
        "strategy_inject",
        "topic_export",
        "visualize_topic",
        "topic_framing",
        "writing_architecture",
        "writing_skill_aggregate",
        "figure_plan",
        "design_brief_expand",
        "algorithm_design_refine",
        "algorithm_design_loop",
        "cold_start_run",
    }


def test_paper_search_local(db) -> None:
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Attention Is All You Need",
                '["Vaswani"]',
                2017,
                "NeurIPS",
                "10.1000/attention",
                "1706.03762",
                "s2-attention",
            ),
        )
        conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Attention for Vision Transformers",
                '["Dosovitskiy"]',
                2020,
                "ICLR",
                "10.1000/vit",
                "2010.11929",
                "s2-vit",
            ),
        )
        conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, doi, arxiv_id, s2_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Convolutional Networks",
                '["LeCun"]',
                1998,
                "IEEE",
                "10.1000/cnn",
                "9801001",
                "s2-cnn",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="attention")

    assert isinstance(result, PaperSearchOutput)
    assert result.query_used == "attention"
    titles = {paper.title for paper in result.papers}
    assert titles == {"Attention Is All You Need", "Attention for Vision Transformers"}
    assert len(result.papers) == 2
    # 2020 ICLR paper ranks above 2017 NeurIPS due to recency boost
    assert result.papers[0].year >= result.papers[1].year


def test_paper_search_with_topic_filter(db) -> None:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('topic-a')")
        topic_id = int(
            conn.execute("SELECT id FROM topics WHERE name = 'topic-a'").fetchone()["id"]
        )
        first = conn.execute(
            "INSERT INTO papers (title, authors, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?)",
            (
                "Attention Is All You Need",
                '["A"]',
                "10.1000/topic-a",
                "topic-a-arxiv",
                "topic-s2-a",
            ),
        )
        conn.execute(
            "INSERT INTO papers (title, authors, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?)",
            (
                "Attention and Memory",
                '["B"]',
                "10.1000/topic-b",
                "topic-b-arxiv",
                "topic-s2-b",
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
            (int(first.lastrowid), topic_id, "high"),
        )
        conn.commit()
    finally:
        conn.close()

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="attention", topic_id=topic_id)

    assert [paper.title for paper in result.papers] == ["Attention Is All You Need"]


def test_paper_ingest_new(db) -> None:
    impl = get_primitive_impl("paper_ingest")
    assert impl is not None

    result = impl(db=db, source="10.1000/new-doi")

    assert isinstance(result, PaperIngestOutput)
    assert result.status == "new"
    assert result.paper_id > 0


def test_paper_ingest_duplicate(db) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
            ("Known Paper", "10.1000/dup", "dup-arxiv", "dup-s2"),
        )
        conn.commit()
    finally:
        conn.close()

    impl = get_primitive_impl("paper_ingest")
    assert impl is not None
    result = impl(db=db, source="10.1000/dup")

    assert result.status == "existing"


def test_normalize_relevance() -> None:
    from research_harness.primitives.impls import _normalize_relevance

    # Categorical labels pass through
    assert _normalize_relevance("high") == "high"
    assert _normalize_relevance("medium") == "medium"
    assert _normalize_relevance("low") == "low"
    assert _normalize_relevance("HIGH") == "high"

    # Float-like strings map to buckets
    assert _normalize_relevance("0.9") == "high"
    assert _normalize_relevance("0.7") == "high"
    assert _normalize_relevance("0.5") == "medium"
    assert _normalize_relevance("0.4") == "medium"
    assert _normalize_relevance("0.3") == "low"
    assert _normalize_relevance("0.0") == "low"

    # Aliases
    assert _normalize_relevance("core") == "high"
    assert _normalize_relevance("peripheral") == "low"

    # Unknown strings default to medium
    assert _normalize_relevance("unknown") == "medium"
    assert _normalize_relevance("") == "medium"


def test_paper_ingest_normalizes_relevance(db) -> None:
    # Create a topic
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('test-topic')")
        conn.commit()
        topic_id = conn.execute("SELECT id FROM topics WHERE name = 'test-topic'").fetchone()["id"]
    finally:
        conn.close()

    impl = get_primitive_impl("paper_ingest")
    assert impl is not None

    # Pass a float-like relevance
    result = impl(db=db, source="10.1000/float-rel", topic_id=topic_id, relevance="0.85")
    assert result.paper_id > 0

    # Verify it was stored as "high" not "0.85"
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT relevance FROM paper_topics WHERE paper_id = ? AND topic_id = ?",
            (result.paper_id, topic_id),
        ).fetchone()
        assert row["relevance"] == "high"
    finally:
        conn.close()


def test_primitive_result_hashing() -> None:
    result = PrimitiveResult(
        primitive="paper_search",
        success=True,
        output=PaperSearchOutput(),
    )

    input_hash_1 = result.input_hash({"query": "transformer", "limit": 5})
    input_hash_2 = result.input_hash({"limit": 5, "query": "transformer"})
    output_hash_1 = result.output_hash()
    output_hash_2 = result.output_hash()

    assert input_hash_1 == input_hash_2
    assert output_hash_1 == output_hash_2


def test_claim_id_generation() -> None:
    claim = Claim(claim_id="", content="Transformers improve translation quality.")
    assert claim.claim_id.startswith("claim_")
    assert len(claim.claim_id) == 18


def test_frozen_dataclasses() -> None:
    outputs = [
        PaperSearchOutput(),
        PaperIngestOutput(paper_id=1, title="x", status="new"),
        SummaryOutput(paper_id=1, summary="x"),
        ClaimExtractOutput(),
        EvidenceLinkOutput(link=EvidenceLink(claim_id="c", source_type="paper", source_id="1")),
        GapDetectOutput(),
        SectionDraftOutput(draft=DraftText(section="intro", content="hi")),
        ConsistencyCheckOutput(),
    ]

    for output in outputs:
        try:
            output.sentinel = 1  # type: ignore[attr-defined]
        except FrozenInstanceError:
            continue
        raise AssertionError(f"{type(output).__name__} is not frozen")


# ---------------------------------------------------------------------------
# Multi-provider search tests
# ---------------------------------------------------------------------------


class _StubProvider:
    name = "stub"

    def __init__(self, records: list[PaperRecord]):
        self._records = records

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        return self._records


def test_paper_search_with_external_providers(db, monkeypatch) -> None:
    """External provider results appear in output."""
    stub_records = [
        PaperRecord(
            title="External Paper on Transformers",
            authors=["Smith"],
            year=2024,
            venue="NeurIPS",
            doi="10.1000/ext-1",
            arxiv_id="2401.00001",
            provider="stub",
            citation_count=50,
            abstract="A study of transformers.",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="transformers")

    assert isinstance(result, PaperSearchOutput)
    assert result.provider == "multi"
    assert "stub" in result.providers_queried
    assert len(result.papers) >= 1
    titles = [p.title for p in result.papers]
    assert "External Paper on Transformers" in titles


def test_paper_search_tier_filter(db, monkeypatch) -> None:
    """tier_filter excludes papers below threshold."""
    stub_records = [
        PaperRecord(
            title="Top Venue Paper",
            year=2024,
            venue="NeurIPS",
            doi="10.1000/top",
            provider="stub",
        ),
        PaperRecord(
            title="Workshop Paper",
            year=2024,
            venue="Unknown Workshop",
            doi="10.1000/ws",
            provider="stub",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="paper", tier_filter="ccf_b")

    titles = [p.title for p in result.papers]
    assert "Top Venue Paper" in titles
    assert "Workshop Paper" not in titles


def test_paper_search_auto_ingest(db, monkeypatch) -> None:
    """auto_ingest stores results in the paper pool."""
    stub_records = [
        PaperRecord(
            title="Auto Ingest Test Paper",
            year=2024,
            venue="CVPR",
            doi="10.1000/auto-ingest",
            provider="stub",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="ingest test", auto_ingest=True)

    assert result.ingested_count >= 1

    # Verify paper exists in DB
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT title FROM papers WHERE doi = ?", ("10.1000/auto-ingest",)
        ).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_paper_search_recency_ranking(db, monkeypatch) -> None:
    """Recent papers rank above older ones with equal relevance."""
    stub_records = [
        PaperRecord(
            title="Recent Attention Model",
            year=2024,
            venue="CVPR",
            provider="stub",
        ),
        PaperRecord(
            title="Old Attention Model",
            year=2010,
            venue="CVPR",
            provider="stub",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="attention model")

    assert len(result.papers) == 2
    assert result.papers[0].title == "Recent Attention Model"


def test_paper_search_dedup_across_sources(db, monkeypatch) -> None:
    """Same paper from local and external is deduplicated."""
    # Insert in local DB
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, authors, year, venue, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Attention Is All You Need", '["Vaswani"]', 2017, "NeurIPS", "10.1000/attention", "1706.03762", ""),
        )
        conn.commit()
    finally:
        conn.close()

    # Same paper from external with citation_count
    stub_records = [
        PaperRecord(
            title="Attention Is All You Need",
            year=2017,
            venue="NeurIPS",
            doi="10.1000/attention",
            arxiv_id="1706.03762",
            provider="stub",
            citation_count=100000,
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="attention")

    # Should be exactly 1 result (deduplicated)
    attention_papers = [p for p in result.papers if "Attention Is All You Need" in p.title]
    assert len(attention_papers) == 1
    # Should have citation_count from external
    assert attention_papers[0].citation_count == 100000


def test_paper_search_venue_tier_enrichment(db, monkeypatch) -> None:
    """Results include venue_tier labels."""
    stub_records = [
        PaperRecord(
            title="A NeurIPS Paper",
            year=2024,
            venue="NeurIPS",
            provider="stub",
        ),
    ]
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [_StubProvider(stub_records)],
    )

    impl = get_primitive_impl("paper_search")
    assert impl is not None
    result = impl(db=db, query="neurips paper")

    assert len(result.papers) >= 1
    paper = result.papers[0]
    assert "CCF-A*" in paper.venue_tier
