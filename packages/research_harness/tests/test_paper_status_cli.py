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


def test_paper_status_reports_missing_sections_before_annotation(runner):
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert runner.invoke(main, ["paper", "ingest", "--title", "Loose Paper", "--topic", "demo"]).exit_code == 0

    result = runner.invoke(main, ["--json", "paper", "status", "1"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ready"]["has_pdf"] is False
    assert payload["ready"]["needs_annotation"] is True
    assert payload["artifact_status"]["count"] == 0
    assert payload["annotation_status"]["count"] == 0
    assert "summary" in payload["annotation_status"]["missing_sections"]
    assert payload["linked_topics"][0]["name"] == "demo"


def test_paper_status_reports_artifacts_sections_and_notes(runner, tmp_path):
    pdf_path = _make_pdf(tmp_path / "status.pdf")
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert runner.invoke(
        main,
        ["paper", "ingest", "--title", "Status Paper", "--topic", "demo", "--pdf-path", str(pdf_path)],
    ).exit_code == 0
    assert runner.invoke(main, ["paper", "annotate", "1", "--section", "summary", "--section", "experiments"]).exit_code == 0
    assert runner.invoke(
        main,
        ["paper", "note", "set", "--paper-id", "1", "--topic", "demo", "--type", "relevance", "--content", "Important for pacing", "--source", "codex"],
    ).exit_code == 0

    result = runner.invoke(main, ["--json", "paper", "status", "1"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ready"]["has_pdf"] is True
    assert payload["ready"]["can_export_card"] is True
    assert payload["artifact_status"]["has_structure"] is True
    assert payload["artifact_status"]["has_card"] is True
    assert set(payload["annotation_status"]["completed_sections"]) == {"summary", "experiments"}
    assert "methodology" in payload["annotation_status"]["missing_sections"]
    assert payload["topic_note_status"]["count"] == 1
    assert payload["topic_note_status"]["by_topic"]["demo"] == ["relevance"]
