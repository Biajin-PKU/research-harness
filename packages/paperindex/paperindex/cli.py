from __future__ import annotations

import json
from pathlib import Path

import click

from .cards.extraction import CARD_EXTRACTION_SECTIONS
from .indexer import PaperIndexer
from .indexing.markdown import structure_to_markdown_outline
from .library import DEFAULT_LIBRARY_DIRNAME
from .llm.client import resolve_llm_config


def _default_library_root() -> Path:
    return Path.cwd() / DEFAULT_LIBRARY_DIRNAME


@click.group()
def main() -> None:
    """Developer CLI for paperindex."""


@main.command("structure")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option("--json-output", "json_output", is_flag=True, default=False)
def structure_cmd(pdf_path: Path, json_output: bool) -> None:
    result = PaperIndexer().extract_structure(pdf_path)
    if json_output:
        click.echo(json.dumps(result.to_dict(), ensure_ascii=False, default=str))
        return
    click.echo(structure_to_markdown_outline(result.tree))


@main.command("section")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option("--section", "section_name", required=True)
@click.option("--json-output", "json_output", is_flag=True, default=False)
def section_cmd(pdf_path: Path, section_name: str, json_output: bool) -> None:
    indexer = PaperIndexer()
    structure = indexer.extract_structure(pdf_path)
    result = indexer.extract_section(structure, section_name)
    payload = result.to_dict()
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    click.echo(result.content)


@main.command("card")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option("--json-output", "json_output", is_flag=True, default=False)
def card_cmd(pdf_path: Path, json_output: bool) -> None:
    indexer = PaperIndexer()
    structure = indexer.extract_structure(pdf_path)
    sections = [
        indexer.extract_section(structure, name) for name in CARD_EXTRACTION_SECTIONS
    ]
    card = indexer.build_card(structure, sections)
    payload = card.to_dict()
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@main.command("ingest")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--library-root", type=click.Path(path_type=Path), default=_default_library_root
)
@click.option("--json-output", "json_output", is_flag=True, default=False)
def ingest_cmd(pdf_path: Path, library_root: Path, json_output: bool) -> None:
    record = PaperIndexer().ingest(pdf_path, library_root)
    payload = record.to_dict()
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    click.echo(f"Indexed {record.paper_id} -> {library_root}")


@main.command("catalog")
@click.option(
    "--library-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=_default_library_root,
)
@click.option("--json-output", "json_output", is_flag=True, default=False)
def catalog_cmd(library_root: Path, json_output: bool) -> None:
    payload = [item.to_dict() for item in PaperIndexer().list_catalog(library_root)]
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    for item in payload:
        click.echo(f"{item['paper_id']} {item['title']}")


@main.command("search")
@click.argument("query")
@click.option(
    "--library-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=_default_library_root,
)
@click.option("--limit", type=int, default=5, show_default=True)
@click.option("--catalog-only", is_flag=True, default=False)
@click.option(
    "--rerank-mode",
    type=click.Choice(["heuristic", "none", "llm"]),
    default="heuristic",
    show_default=True,
)
@click.option("--json-output", "json_output", is_flag=True, default=False)
def search_cmd(
    query: str,
    library_root: Path,
    limit: int,
    catalog_only: bool,
    rerank_mode: str,
    json_output: bool,
) -> None:
    indexer = PaperIndexer()
    results = (
        indexer.search_catalog_only(query, library_root, limit=limit)
        if catalog_only
        else indexer.search(query, library_root, limit=limit, rerank_mode=rerank_mode)
    )
    payload = [item.to_dict() for item in results]
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    if not payload:
        click.echo("No results found.")
        return
    for item in payload:
        click.echo(f"[{item['score']:.1f}] {item['paper_id']} {item['title']}")
        if item.get("rerank_reason"):
            click.echo(f"reason: {item['rerank_reason']}")
        if item["snippet"]:
            click.echo(item["snippet"])
        for match in item.get("structure_matches", []):
            click.echo(
                f"  - {match['node_id']} {match['title']} ({match['start_page']}-{match['end_page']})"
            )


@main.command("show")
@click.argument("paper_id")
@click.option(
    "--library-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=_default_library_root,
)
@click.option("--json-output", "json_output", is_flag=True, default=False)
def show_cmd(paper_id: str, library_root: Path, json_output: bool) -> None:
    record = PaperIndexer().load_record(paper_id, library_root)
    payload = record.to_dict()
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    click.echo(json.dumps(payload["card"], ensure_ascii=False, indent=2))


@main.command("show-structure")
@click.argument("paper_id")
@click.option(
    "--library-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=_default_library_root,
)
@click.option("--with-text", is_flag=True, default=False)
@click.option("--json-output", "json_output", is_flag=True, default=False)
def show_structure_cmd(
    paper_id: str, library_root: Path, with_text: bool, json_output: bool
) -> None:
    indexer = PaperIndexer()
    payload = indexer.get_structure(paper_id, library_root, include_text=with_text)
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    click.echo(
        structure_to_markdown_outline(
            indexer.load_record(paper_id, library_root).structure.tree
        )
    )


@main.command("show-content")
@click.argument("paper_id")
@click.option(
    "--library-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=_default_library_root,
)
@click.option("--section-name", type=str)
@click.option("--node-id", type=str)
@click.option("--title-query", type=str)
@click.option("--json-output", "json_output", is_flag=True, default=False)
def show_content_cmd(
    paper_id: str,
    library_root: Path,
    section_name: str | None,
    node_id: str | None,
    title_query: str | None,
    json_output: bool,
) -> None:
    payload = PaperIndexer().get_section_content(
        paper_id,
        library_root,
        section_name=section_name,
        node_id=node_id,
        title_query=title_query,
    )
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    if payload["mode"] == "section":
        click.echo(payload["section"]["content"])
        return
    click.echo(payload["node"]["content"])


@main.command("structure-search")
@click.argument("paper_id")
@click.argument("query")
@click.option(
    "--library-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=_default_library_root,
)
@click.option("--limit", type=int, default=5, show_default=True)
@click.option("--json-output", "json_output", is_flag=True, default=False)
def structure_search_cmd(
    paper_id: str, query: str, library_root: Path, limit: int, json_output: bool
) -> None:
    payload = [
        item.to_dict()
        for item in PaperIndexer().get_structure_matches(
            paper_id, query, library_root, limit=limit
        )
    ]
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))
        return
    if not payload:
        click.echo("No structure matches found.")
        return
    for item in payload:
        click.echo(
            f"[{item['score']:.1f}] {item['node_id']} {item['title']} ({item['start_page']}-{item['end_page']})"
        )
        if item["snippet"]:
            click.echo(item["snippet"])


@main.command("doctor")
@click.option("--json-output", "json_output", is_flag=True, default=False)
def doctor_cmd(json_output: bool) -> None:
    """Print resolved LLM configuration and check connectivity."""
    config = resolve_llm_config()
    status: dict[str, str] = {
        "provider": config.provider,
        "model": config.model or "(not set)",
        "api_key": ("***" + config.api_key[-4:])
        if len(config.api_key) > 4
        else ("(not set)" if not config.api_key else "***"),
        "base_url": config.base_url or "(default)",
    }

    if config.api_key and config.model:
        try:
            from .llm.client import LLMClient

            client = LLMClient(config)
            client.chat(prompt="Reply with exactly: ok", temperature=0.0)
            status["connectivity"] = "ok"
        except Exception as exc:
            status["connectivity"] = f"error: {exc}"
    else:
        status["connectivity"] = "skipped (no api_key or model)"

    if json_output:
        click.echo(json.dumps(status, ensure_ascii=False))
        return
    for key, value in status.items():
        click.echo(f"{key}: {value}")


if __name__ == "__main__":
    main()
