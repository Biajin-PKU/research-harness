from __future__ import annotations

import json
from pathlib import Path

import fitz

from research_harness.cli import main


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    for title, body in [
        ("Sample Paper Title", "Abstract\nThis paper studies budget pacing and proposes a stable control policy."),
        ("Method", "Method\nWe optimize spend allocation with a constrained controller and staged updates."),
        ("Experiments", "Experiments\nWe compare against two baselines and improve efficiency by 12 percent."),
    ]:
        page = doc.new_page()
        page.insert_text((72, 72), title, fontsize=18)
        page.insert_text((72, 120), body, fontsize=11)
    doc.set_toc([[1, "Abstract", 1], [1, "Method", 2], [1, "Experiments", 3]])
    doc.save(path)
    doc.close()
    return path


def test_paper_queue_prioritizes_missing_pdf_then_missing_sections_then_ready(runner, tmp_path):
    pdf_a = _make_pdf(tmp_path / "a.pdf")
    pdf_b = _make_pdf(tmp_path / "b.pdf")
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0

    assert runner.invoke(main, ["paper", "ingest", "--title", "No PDF Paper", "--topic", "demo"]).exit_code == 0
    assert runner.invoke(main, ["paper", "ingest", "--title", "Needs Sections", "--topic", "demo", "--pdf-path", str(pdf_a)]).exit_code == 0
    assert runner.invoke(main, ["paper", "ingest", "--title", "Ready Paper", "--topic", "demo", "--pdf-path", str(pdf_b)]).exit_code == 0

    assert runner.invoke(main, ["paper", "annotate", "2", "--section", "summary"]).exit_code == 0
    assert runner.invoke(main, ["paper", "annotate", "3"]).exit_code == 0
    assert runner.invoke(main, ["paper", "note", "set", "--paper-id", "3", "--topic", "demo", "--type", "relevance", "--content", "ready", "--source", "codex"]).exit_code == 0

    result = runner.invoke(main, ["--json", "paper", "queue", "--topic", "demo"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["topic"] == "demo"
    assert payload["summary"]["by_bucket"]["missing_pdf"] == 1
    assert payload["summary"]["by_bucket"]["missing_sections"] == 1
    assert payload["summary"]["by_bucket"]["ready"] == 1

    titles = [item["title"] for item in payload["papers"]]
    assert titles == ["No PDF Paper", "Needs Sections", "Ready Paper"]
    assert payload["papers"][0]["next_actions"] == ["attach_pdf"]
    assert payload["papers"][1]["queue_bucket"] == "missing_sections"
    assert "methodology" in payload["papers"][1]["missing_sections"]
    assert payload["papers"][2]["queue_bucket"] == "ready"


def test_paper_queue_only_actionable_filters_ready_items(runner, tmp_path):
    pdf_path = _make_pdf(tmp_path / "ready.pdf")
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert runner.invoke(main, ["paper", "ingest", "--title", "Ready Paper", "--topic", "demo", "--pdf-path", str(pdf_path)]).exit_code == 0
    assert runner.invoke(main, ["paper", "annotate", "1"]).exit_code == 0
    assert runner.invoke(main, ["paper", "note", "set", "--paper-id", "1", "--topic", "demo", "--type", "relevance", "--content", "ready", "--source", "codex"]).exit_code == 0

    result = runner.invoke(main, ["--json", "paper", "queue", "--topic", "demo", "--only-actionable"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["total_papers"] == 0
    assert payload["papers"] == []


def test_paper_queue_suggests_card_draft_for_missing_topic_note(runner, tmp_path):
    pdf_path = _make_pdf(tmp_path / "needs-note.pdf")
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert runner.invoke(main, ["paper", "ingest", "--title", "Needs Note", "--topic", "demo", "--pdf-path", str(pdf_path)]).exit_code == 0
    assert runner.invoke(main, ["paper", "annotate", "1"]).exit_code == 0

    result = runner.invoke(main, ["--json", "paper", "queue", "--topic", "demo"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["by_bucket"]["missing_topic_note"] == 1
    assert payload["papers"][0]["queue_bucket"] == "missing_topic_note"
    assert payload["papers"][0]["next_actions"] == ["draft_topic_note_from_card"]
