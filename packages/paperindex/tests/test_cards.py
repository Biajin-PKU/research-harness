import json

from paperindex import PaperIndexer
from paperindex.cards import PaperCard



def _fake_llm_chat(self, prompt: str, model: str | None = None, temperature: float = 0.0) -> str:
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
            "authors": ["Jane Doe", "John Roe"],
            "venue": "NeurIPS",
            "year": "2024",
            "core_idea": "The paper proposes a budget pacing controller for cross-channel spend allocation.",
            "method_summary": "The method combines constrained optimization with staged controller updates.",
            "method_pipeline": ["Extract traffic signals", "Optimize spend allocation", "Replay on offline logs"],
            "method_family": "optimization_based",
            "method_tags": ["budget pacing", "constrained optimization"],
            "contributions": ["Introduces a stable pacing controller", "Shows offline gains over baselines"],
            "key_results": ["Improves efficiency by 12 percent over two baselines"],
            "limitations": ["Only evaluated on offline replay"],
            "tasks": ["budget allocation"],
            "datasets": ["offline replay logs"],
            "metrics": ["efficiency"],
            "baselines": ["baseline A", "baseline B"],
            "reproduction_notes": "Requires replay logs and controller hyperparameters.",
            "reproducibility_score": "medium",
            "evidence": [{"section": "experiments", "confidence": 0.83, "snippet": "improve efficiency by 12 percent"}],
            "structured_results": [{"metric": "efficiency", "value": "+12%", "baseline": "baseline A", "delta": "+12%"}],
            "artifact_links": [],
            "domain_tags": ["online advertising"],
            "technical_tags": ["budget pacing"],
            "motivation": "Budget pacing is unstable without coordinated control.",
            "problem_definition": "Allocate spend across channels under budget constraints.",
            "application_scenarios": ["cross-channel advertising"],
            "algorithmic_view": "Alternate between signal extraction and constrained budget updates.",
            "mathematical_formulation": {"objective": "maximize efficiency", "constraints": ["budget"], "key_equations": []},
            "related_work_positioning": "Extends prior pacing methods to cross-channel settings.",
            "key_references": ["Prior pacing work"],
            "assumptions": ["Offline logs reflect production traffic"],
            "future_directions": "Validate online.",
            "ablation_focus": ["controller stability"],
            "efficiency_signals": ["offline replay runtime"],
            "code_url": None,
            "source_url": None,
        }
    )



def test_build_card_uses_llm_output(sample_pdf, monkeypatch):
    monkeypatch.setattr("paperindex.llm.client.LLMClient.chat", _fake_llm_chat)

    indexer = PaperIndexer(llm_config={"provider": "kimi", "api_key": "test-key", "model": "kimi-k2-turbo-preview"})
    structure = indexer.extract_structure(sample_pdf)
    sections = [
        indexer.extract_section(structure, name)
        for name in ("summary", "methodology", "experiments", "equations", "limitations", "reproduction_notes")
    ]
    card = indexer.build_card(structure, sections)
    assert isinstance(card, PaperCard)
    assert card.title == "Sample Paper Title"
    assert card.method_family == "optimization_based"
    assert card.authors == ["Jane Doe", "John Roe"]
    assert card.structured_results[0].metric == "efficiency"
    assert card.evidence[0].section == "experiments"
