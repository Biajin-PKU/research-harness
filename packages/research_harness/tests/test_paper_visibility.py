from __future__ import annotations

import json
from pathlib import Path

import fitz

from research_harness.cli import main


def _make_pdf(path: Path) -> Path:
    doc = fitz.open()
    for title, body in [
        (
            "Sample Paper Title",
            "Abstract\nThis paper studies budget pacing and proposes a stable control policy.",
        ),
        (
            "Method",
            "Method\nWe optimize spend allocation with a constrained controller and staged updates.",
        ),
        (
            "Experiments",
            "Experiments\nWe compare against two baselines and improve efficiency by 12 percent.",
        ),
    ]:
        page = doc.new_page()
        page.insert_text((72, 72), title, fontsize=18)
        page.insert_text((72, 120), body, fontsize=11)
    doc.set_toc([[1, "Abstract", 1], [1, "Method", 2], [1, "Experiments", 3]])
    doc.save(path)
    doc.close()
    return path


def test_paper_artifacts_and_annotations_commands(runner, tmp_path):
    pdf_path = _make_pdf(tmp_path / "sample.pdf")
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    ingest = runner.invoke(
        main,
        [
            "--json",
            "paper",
            "ingest",
            "--title",
            "Sample Paper",
            "--topic",
            "demo",
            "--pdf-path",
            str(pdf_path),
        ],
    )
    assert ingest.exit_code == 0
    assert runner.invoke(main, ["--json", "paper", "annotate", "1"]).exit_code == 0

    artifacts = runner.invoke(main, ["--json", "paper", "artifacts", "1"])
    assert artifacts.exit_code == 0
    artifact_payload = json.loads(artifacts.output)
    assert len(artifact_payload) == 2
    assert {item["artifact_type"] for item in artifact_payload} == {
        "paperindex_structure",
        "paperindex_card",
    }

    annotations = runner.invoke(
        main, ["--json", "paper", "annotations", "1", "--section", "summary"]
    )
    assert annotations.exit_code == 0
    annotation_payload = json.loads(annotations.output)
    assert len(annotation_payload) == 1
    assert annotation_payload[0]["section"] == "summary"

    paper_show = runner.invoke(main, ["--json", "paper", "show", "1"])
    assert paper_show.exit_code == 0
    show_payload = json.loads(paper_show.output)
    assert len(show_payload["artifacts"]) == 2


def test_paper_card_command_reads_and_exports_card(runner, tmp_path):
    pdf_path = _make_pdf(tmp_path / "card.pdf")
    export_path = tmp_path / "exports" / "paper-card.json"
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert (
        runner.invoke(
            main,
            [
                "paper",
                "ingest",
                "--title",
                "Card Paper",
                "--topic",
                "demo",
                "--pdf-path",
                str(pdf_path),
            ],
        ).exit_code
        == 0
    )
    assert runner.invoke(main, ["paper", "annotate", "1"]).exit_code == 0

    card = runner.invoke(main, ["--json", "paper", "card", "1"])
    assert card.exit_code == 0
    payload = json.loads(card.output)
    assert payload["artifact_type"] == "paperindex_card"
    assert payload["metadata"]["section_count"] == 6
    assert payload["card"]["paper_id"]
    assert payload["card"]["core_idea"]
    assert payload["card"]["evidence"]

    exported = runner.invoke(
        main, ["--json", "paper", "card", "1", "--output", str(export_path)]
    )
    assert exported.exit_code == 0
    export_payload = json.loads(exported.output)
    assert export_payload["exported_to"] == str(export_path)
    assert json.loads(export_path.read_text()) == export_payload["card"]


def test_paper_card_command_requires_existing_artifact(runner):
    assert runner.invoke(main, ["topic", "init", "demo"]).exit_code == 0
    assert (
        runner.invoke(
            main, ["paper", "ingest", "--title", "No Card Yet", "--topic", "demo"]
        ).exit_code
        == 0
    )

    result = runner.invoke(main, ["paper", "card", "1"])
    assert result.exit_code != 0
    assert "run 'paper annotate 1' first" in result.output
