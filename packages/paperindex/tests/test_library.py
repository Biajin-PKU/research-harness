import os

import pytest

from paperindex import PaperIndexer
from paperindex.library import PaperLibrary
from paperindex.retrieval import find_structure_matches, search_catalog, search_records
from paperindex.retrieval.rerankers import _extract_ranked_items

pytestmark = pytest.mark.skipif(
    not (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CURSOR_AGENT_ENABLED")
        or os.getenv("CODEX_ENABLED")
    ),
    reason="Requires an LLM provider (OPENAI_API_KEY / ANTHROPIC_API_KEY / CURSOR_AGENT_ENABLED / CODEX_ENABLED)",
)


def test_library_lists_saved_records(sample_pdf, tmp_path):
    library_root = tmp_path / "library"
    record = PaperIndexer().ingest(sample_pdf, library_root)

    records = PaperLibrary(library_root).list()
    assert len(records) == 1
    assert records[0].paper_id == record.paper_id


def test_library_builds_catalog(sample_pdf, tmp_path):
    library_root = tmp_path / "library"
    record = PaperIndexer().ingest(sample_pdf, library_root)

    catalog = PaperLibrary(library_root).list_catalog()
    assert len(catalog) == 1
    assert catalog[0].paper_id == record.paper_id
    assert "summary" in catalog[0].section_names
    assert "Method" in catalog[0].node_titles
    assert catalog[0].node_summaries


def test_search_records_matches_metadata(sample_pdf, tmp_path):
    library_root = tmp_path / "library"
    record = PaperIndexer().ingest(sample_pdf, library_root)
    results = search_records([record], "controller efficiency")

    assert len(results) == 1
    assert results[0].paper_id == record.paper_id
    assert results[0].matched_fields
    assert results[0].score > 0
    assert results[0].structure_matches
    assert results[0].structure_matches[0].summary
    assert results[0].rerank_reason


def test_search_records_llm_mode_requires_model(sample_pdf, tmp_path):
    library_root = tmp_path / "library"
    record = PaperIndexer().ingest(sample_pdf, library_root)
    try:
        search_records([record], "controller", rerank_mode="llm")
    except ValueError as exc:
        assert "llm_config['model']" in str(exc)
    else:
        raise AssertionError("expected llm rerank to require a model")


def test_extract_ranked_items_supports_reasons():
    payload = '{"ranked_results": [{"paper_id": "p1", "reason": "Matches method section closely."}, {"paper_id": "p2", "reason": "Less direct evidence."}]}'
    ranked = _extract_ranked_items(payload)
    assert ranked[0]["paper_id"] == "p1"
    assert "method section" in ranked[0]["reason"]


def test_search_catalog_matches_structure_titles(sample_pdf, tmp_path):
    library_root = tmp_path / "library"
    PaperIndexer().ingest(sample_pdf, library_root)
    catalog = PaperLibrary(library_root).list_catalog()
    results = search_catalog(catalog, "controller")

    assert len(results) == 1
    assert (
        "structure_summary" in results[0].matched_fields
        or "structure" in results[0].matched_fields
    )


def test_find_structure_matches_returns_node_hits(sample_pdf):
    record = PaperIndexer().build_record(sample_pdf)
    matches = find_structure_matches(record, "controller")

    assert matches
    assert matches[0].node_id
    assert matches[0].summary
    assert matches[0].start_page >= 1
