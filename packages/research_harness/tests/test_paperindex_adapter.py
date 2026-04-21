from __future__ import annotations

import json
from pathlib import Path

import fitz

from research_harness.cli import main



def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    pages = [
        ("Sample Paper Title", "Abstract\nThis paper studies budget pacing and proposes a stable control policy."),
        ("Method", "Method\nWe optimize spend allocation with a constrained controller and staged updates."),
        ("Experiments", "Experiments\nWe compare against two baselines and improve efficiency by 12 percent."),
    ]
    for title, body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), title, fontsize=18)
        page.insert_text((72, 120), body, fontsize=11)
    doc.set_toc([[1, "Abstract", 1], [1, "Method", 2], [1, "Experiments", 3]])
    doc.save(path)
    doc.close()
    return path



def _fake_llm_chat(self, prompt: str, model: str | None = None, temperature: float = 0.0) -> str:
    del self, model, temperature
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
            "evidence": [{"section": "summary", "confidence": 0.9, "snippet": "budget pacing"}],
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



def test_paper_annotate_cli(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("paperindex.llm.client.LLMClient.chat", _fake_llm_chat)
    pdf_path = _make_pdf(tmp_path / "sample.pdf")

    topic = runner.invoke(main, ["topic", "init", "demo"])
    assert topic.exit_code == 0

    ingest = runner.invoke(
        main,
        [
            "--json", "paper", "ingest",
            "--arxiv-id", "1706.03762",
            "--title", "Attention Is All You Need",
            "--authors", "Vaswani,Shazeer",
            "--year", "2017",
            "--venue", "NeurIPS",
            "--topic", "demo",
            "--pdf-path", str(pdf_path),
        ],
    )
    assert ingest.exit_code == 0

    annotate = runner.invoke(main, ["--json", "paper", "annotate", "1"])
    assert annotate.exit_code == 0
    payload = json.loads(annotate.output)
    assert payload["annotation_count"] == 6
    assert payload["structure_source"] == "fresh"
    assert set(payload["extracted_sections"]) == {
        "summary",
        "methodology",
        "experiments",
        "equations",
        "limitations",
        "reproduction_notes",
    }
    assert payload["reused_sections"] == []
    assert Path(payload["structure_path"]).exists()
    assert Path(payload["card_path"]).exists()

    card = json.loads(Path(payload["card_path"]).read_text())
    assert "budget pacing" in (card.get("core_idea") or "").lower()
    assert "controller" in (card.get("method_summary") or "").lower()
    assert card.get("method_pipeline")
    assert card.get("method_family") == "optimization_based"

    show = runner.invoke(main, ["--json", "paper", "show", "1"])
    assert show.exit_code == 0
    show_payload = json.loads(show.output)
    assert show_payload["paper"]["status"] == "annotated"
    assert {item["section"] for item in show_payload["annotations"]} >= {
        "summary",
        "methodology",
        "experiments",
        "equations",
        "limitations",
        "reproduction_notes",
    }



def test_paper_annotate_incremental_reuses_cached_sections(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("paperindex.llm.client.LLMClient.chat", _fake_llm_chat)
    pdf_path = _make_pdf(tmp_path / "incremental.pdf")
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert runner.invoke(
        main,
        ["paper", "ingest", "--title", "Incremental Paper", "--topic", "demo", "--pdf-path", str(pdf_path)],
    ).exit_code == 0

    first = runner.invoke(main, ["--json", "paper", "annotate", "1", "--section", "summary"])
    assert first.exit_code == 0
    first_payload = json.loads(first.output)
    assert first_payload["structure_source"] == "fresh"
    assert first_payload["extracted_sections"] == ["summary"]
    assert first_payload["reused_sections"] == []

    second = runner.invoke(main, ["--json", "paper", "annotate", "1", "--section", "experiments"])
    assert second.exit_code == 0
    second_payload = json.loads(second.output)
    assert second_payload["structure_source"] == "cache"
    assert second_payload["extracted_sections"] == ["experiments"]
    assert second_payload["reused_sections"] == []

    third = runner.invoke(main, ["--json", "paper", "annotate", "1", "--section", "summary"])
    assert third.exit_code == 0
    third_payload = json.loads(third.output)
    assert third_payload["structure_source"] == "cache"
    assert third_payload["extracted_sections"] == []
    assert third_payload["reused_sections"] == ["summary"]

    annotations = runner.invoke(main, ["--json", "paper", "annotations", "1"])
    assert annotations.exit_code == 0
    annotation_payload = json.loads(annotations.output)
    assert {item["section"] for item in annotation_payload} == {"summary", "experiments"}

    artifacts = runner.invoke(main, ["--json", "paper", "artifacts", "1"])
    assert artifacts.exit_code == 0
    artifact_payload = json.loads(artifacts.output)
    metadata_by_type = {item["artifact_type"]: json.loads(item["metadata"]) for item in artifact_payload}
    assert metadata_by_type["paperindex_structure"]["source"] == "cache"
    assert metadata_by_type["paperindex_card"]["section_count"] == 2
