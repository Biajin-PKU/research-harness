import json

import pytest

from paperindex import PaperIndexer
from paperindex.library import PaperLibrary


def _fake_llm_chat(
    self, prompt: str, model: str | None = None, temperature: float = 0.0
) -> str:
    del self, model, temperature
    if "section structure of a paper PDF" in prompt:
        return json.dumps(
            {
                "sections": [
                    {"title": "Abstract", "start_page": 1},
                    {"title": "Introduction", "start_page": 2},
                    {"title": "Method", "start_page": 3},
                ]
            }
        )
    return json.dumps(
        {
            "title": "Sample Paper Title",
            "authors": ["Jane Doe"],
            "venue": "NeurIPS",
            "year": "2024",
            "core_idea": "The paper studies budget pacing.",
            "method_summary": "It uses a constrained controller.",
            "method_pipeline": ["Observe", "Optimize", "Replay"],
            "method_family": "optimization_based",
            "method_tags": ["budget pacing"],
            "contributions": ["Stable controller"],
            "key_results": ["12 percent gain"],
            "limitations": ["Offline only"],
            "tasks": ["budget allocation"],
            "datasets": ["offline logs"],
            "metrics": ["efficiency"],
            "baselines": ["baseline A"],
            "reproduction_notes": "Needs logs.",
            "reproducibility_score": "medium",
            "evidence": [
                {"section": "summary", "confidence": 0.9, "snippet": "budget pacing"}
            ],
            "structured_results": [],
            "artifact_links": [],
            "domain_tags": [],
            "technical_tags": [],
            "motivation": None,
            "problem_definition": None,
            "application_scenarios": [],
            "algorithmic_view": None,
            "mathematical_formulation": None,
            "related_work_positioning": None,
            "key_references": [],
            "assumptions": [],
            "future_directions": None,
            "ablation_focus": [],
            "efficiency_signals": [],
            "code_url": None,
            "source_url": None,
        }
    )


def _indexer_with_llm(monkeypatch) -> PaperIndexer:
    monkeypatch.setattr("llm_router.client.LLMClient.chat", _fake_llm_chat)
    return PaperIndexer(
        llm_config={
            "provider": "kimi",
            "api_key": "test-key",
            "model": "kimi-k2-turbo-preview",
        }
    )


def test_extract_structure_from_toc(sample_pdf):
    result = PaperIndexer().extract_structure(sample_pdf)
    assert result.page_count == 3
    assert len(result.tree) == 3
    assert result.tree[0].title == "Abstract"
    assert result.tree[0].start_page == 1
    assert result.tree[1].title == "Method"
    assert result.tree[2].end_page == 3
    assert result.tree[0].node_id == "0000"
    assert result.raw["source"] == "toc"
    assert result.tree[0].summary


def test_extract_structure_without_toc_uses_llm(no_toc_pdf, monkeypatch):
    indexer = _indexer_with_llm(monkeypatch)
    result = indexer.extract_structure(no_toc_pdf)
    assert result.raw["source"] == "llm"
    assert [node.title for node in result.tree] == [
        "Abstract",
        "Introduction",
        "Method",
    ]
    assert result.tree[1].start_page == 2


def test_extract_structure_without_toc_requires_llm(no_toc_pdf, monkeypatch):
    for name in (
        "KIMI_API_KEY",
        "KIMI_MODEL",
        "KIMI_BASE_URL",
        "OPENAI_API_KEY",
        "PAPERINDEX_LLM_MODEL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="LLM-backed section structure extraction"):
        PaperIndexer().extract_structure(no_toc_pdf)


def test_build_record_persists_sections(sample_pdf, monkeypatch):
    record = _indexer_with_llm(monkeypatch).build_record(sample_pdf)
    assert record.paper_id
    assert record.title == "Sample Paper Title"
    assert record.sections["summary"].source_pdf_hash == record.pdf_hash
    assert "budget pacing" in record.sections["summary"].content.lower()
    assert record.card.paper_id == record.paper_id
    assert record.card.method_family == "optimization_based"


def test_ingest_and_load_from_library(sample_pdf, tmp_path, monkeypatch):
    library_root = tmp_path / "library"
    indexer = _indexer_with_llm(monkeypatch)
    saved = indexer.ingest(sample_pdf, library_root)

    loaded = PaperLibrary(library_root).get(saved.paper_id)
    assert loaded.paper_id == saved.paper_id
    assert loaded.card.title == "Sample Paper Title"
    assert loaded.sections["experiments"].content


def test_get_structure_returns_text_free_tree(sample_pdf, tmp_path, monkeypatch):
    library_root = tmp_path / "library"
    record = _indexer_with_llm(monkeypatch).ingest(sample_pdf, library_root)

    payload = PaperIndexer().get_structure(
        record.paper_id, library_root, include_text=False
    )
    assert payload["structure"][0]["title"] == "Abstract"
    assert "section_text" not in payload["structure"][0]
    assert payload["structure"][0]["summary"]


def test_get_section_content_by_title_query(sample_pdf, tmp_path, monkeypatch):
    library_root = tmp_path / "library"
    record = _indexer_with_llm(monkeypatch).ingest(sample_pdf, library_root)

    payload = PaperIndexer().get_section_content(
        record.paper_id, library_root, title_query="method"
    )
    assert payload["mode"] == "node"
    assert payload["node"]["title"] == "Method"
    assert payload["node"]["summary"]
    assert "controller" in payload["node"]["content"].lower()
