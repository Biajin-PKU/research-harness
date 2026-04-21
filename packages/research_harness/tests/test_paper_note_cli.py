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


def test_paper_note_set_and_list_json(runner):
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert runner.invoke(main, ["paper", "ingest", "--title", "Sample Paper", "--topic", "demo"]).exit_code == 0

    set_result = runner.invoke(
        main,
        [
            "--json", "paper", "note", "set",
            "--paper-id", "1",
            "--topic", "demo",
            "--type", "relevance",
            "--content", "High relevance for this topic",
            "--source", "codex",
        ],
    )
    assert set_result.exit_code == 0
    payload = json.loads(set_result.output)
    assert payload["topic"] == "demo"
    assert payload["note_type"] == "relevance"
    assert payload["source"] == "codex"

    list_result = runner.invoke(main, ["--json", "paper", "note", "list", "--paper-id", "1", "--topic", "demo"])
    assert list_result.exit_code == 0
    notes = json.loads(list_result.output)
    assert len(notes) == 1
    assert notes[0]["content"] == "High relevance for this topic"

    paper_show = runner.invoke(main, ["--json", "paper", "show", "1"])
    assert paper_show.exit_code == 0
    show_payload = json.loads(paper_show.output)
    assert len(show_payload["topic_notes"]) == 1


def test_paper_note_draft_from_card_preview_and_save(runner, tmp_path):
    pdf_path = _make_pdf(tmp_path / "draft.pdf")
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert runner.invoke(main, ["paper", "ingest", "--title", "Draft Paper", "--topic", "demo", "--pdf-path", str(pdf_path)]).exit_code == 0
    assert runner.invoke(main, ["paper", "annotate", "1"]).exit_code == 0

    draft = runner.invoke(
        main,
        [
            "--json", "paper", "note", "draft",
            "--paper-id", "1",
            "--topic", "demo",
            "--type", "relevance",
        ],
    )
    assert draft.exit_code == 0
    payload = json.loads(draft.output)
    assert payload["saved"] is False
    assert payload["topic"] == "demo"
    assert payload["note_type"] == "relevance"
    assert "Topic: demo" in payload["content"]
    assert "Why it matters:" in payload["content"]

    save = runner.invoke(
        main,
        [
            "--json", "paper", "note", "draft",
            "--paper-id", "1",
            "--topic", "demo",
            "--type", "relevance",
            "--save",
        ],
    )
    assert save.exit_code == 0
    save_payload = json.loads(save.output)
    assert save_payload["saved"] is True
    assert save_payload["source"] == "paperindex:card-draft"

    listed = runner.invoke(main, ["--json", "paper", "note", "list", "--paper-id", "1", "--topic", "demo", "--type", "relevance"])
    assert listed.exit_code == 0
    notes = json.loads(listed.output)
    assert len(notes) == 1
    assert notes[0]["content"] == save_payload["content"]
    assert notes[0]["source"] == "paperindex:card-draft"


def test_paper_note_draft_requires_card_artifact(runner):
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert runner.invoke(main, ["paper", "ingest", "--title", "No Card Yet", "--topic", "demo"]).exit_code == 0

    result = runner.invoke(
        main,
        [
            "paper", "note", "draft",
            "--paper-id", "1",
            "--topic", "demo",
            "--type", "relevance",
        ],
    )
    assert result.exit_code != 0
    assert "run 'paper annotate 1' first" in result.output


def test_paper_note_set_requires_topic_link(runner):
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert runner.invoke(main, ["paper", "ingest", "--title", "Loose Paper"]).exit_code == 0

    result = runner.invoke(
        main,
        [
            "paper", "note", "set",
            "--paper-id", "1",
            "--topic", "demo",
            "--type", "relevance",
            "--content", "Should fail",
        ],
    )
    assert result.exit_code != 0
    assert "not linked to topic" in result.output
