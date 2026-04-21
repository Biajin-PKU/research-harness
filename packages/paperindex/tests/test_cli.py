import json

from click.testing import CliRunner

from paperindex.cli import main


def test_cli_json(sample_pdf, tmp_path):
    runner = CliRunner()
    structure = runner.invoke(main, ["structure", str(sample_pdf), "--json-output"])
    assert structure.exit_code == 0
    payload = json.loads(structure.output)
    assert payload["page_count"] == 3

    section = runner.invoke(main, ["section", str(sample_pdf), "--section", "summary", "--json-output"])
    assert section.exit_code == 0
    assert "budget pacing" in json.loads(section.output)["content"].lower()

    card = runner.invoke(main, ["card", str(sample_pdf), "--json-output"])
    assert card.exit_code == 0
    assert json.loads(card.output)["title"] == "Sample Paper Title"

    library_root = tmp_path / "library"
    ingest = runner.invoke(main, ["ingest", str(sample_pdf), "--library-root", str(library_root), "--json-output"])
    assert ingest.exit_code == 0
    record = json.loads(ingest.output)
    assert record["paper_id"]

    catalog = runner.invoke(main, ["catalog", "--library-root", str(library_root), "--json-output"])
    assert catalog.exit_code == 0
    catalog_payload = json.loads(catalog.output)
    assert catalog_payload[0]["paper_id"] == record["paper_id"]

    search = runner.invoke(
        main,
        ["search", "budget pacing", "--library-root", str(library_root), "--json-output"],
    )
    assert search.exit_code == 0
    results = json.loads(search.output)
    assert len(results) == 1
    assert results[0]["paper_id"] == record["paper_id"]
    assert results[0]["structure_matches"]
    assert "summary" in record["sections"]

    show = runner.invoke(main, ["show", record["paper_id"], "--library-root", str(library_root), "--json-output"])
    assert show.exit_code == 0
    shown = json.loads(show.output)
    assert shown["paper_id"] == record["paper_id"]
    assert shown["card"]["title"] == "Sample Paper Title"

    show_structure = runner.invoke(
        main,
        ["show-structure", record["paper_id"], "--library-root", str(library_root), "--json-output"],
    )
    assert show_structure.exit_code == 0
    structure_payload = json.loads(show_structure.output)
    assert structure_payload["structure"][0]["title"] == "Abstract"
    assert "section_text" not in structure_payload["structure"][0]

    show_content = runner.invoke(
        main,
        [
            "show-content",
            record["paper_id"],
            "--library-root",
            str(library_root),
            "--section-name",
            "summary",
            "--json-output",
        ],
    )
    assert show_content.exit_code == 0
    content_payload = json.loads(show_content.output)
    assert content_payload["mode"] == "section"
    assert "budget pacing" in content_payload["section"]["content"].lower()

    structure_search = runner.invoke(
        main,
        [
            "structure-search",
            record["paper_id"],
            "controller",
            "--library-root",
            str(library_root),
            "--json-output",
        ],
    )
    assert structure_search.exit_code == 0
    structure_hits = json.loads(structure_search.output)
    assert structure_hits
    assert structure_hits[0]["node_id"]
