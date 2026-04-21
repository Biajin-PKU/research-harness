from __future__ import annotations

import re
from typing import Any

from ..types import CatalogEntry, PaperRecord, SearchResult, SectionNode, StructureMatch
from ..utils import first_nonempty_line, flatten_nodes
from .rerankers import RerankMode, rerank_search_results


CARD_SEARCH_FIELDS = ("core_idea", "method_summary", "key_results", "limitations")


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token]


def _score_text(terms: list[str], text: str) -> int:
    tokens = _tokenize(text)
    return sum(1 for term in terms if term in tokens)


def _rank_structure_nodes(tree: list[SectionNode], query: str, limit: int = 5) -> list[StructureMatch]:
    terms = _tokenize(query)
    if not terms:
        return []

    matches: list[StructureMatch] = []
    for node in flatten_nodes(tree):
        title_score = _score_text(terms, node.title) * 4
        summary_score = _score_text(terms, node.summary) * 3
        text_score = _score_text(terms, node.section_text) * 1
        total = float(title_score + summary_score + text_score)
        if total <= 0:
            continue
        matches.append(
            StructureMatch(
                node_id=node.node_id,
                title=node.title,
                start_page=node.start_page,
                end_page=node.end_page,
                score=total,
                snippet=first_nonempty_line(node.section_text)[:240],
                summary=node.summary,
            )
        )
    return sorted(matches, key=lambda item: (-item.score, item.start_page, item.title.lower()))[:limit]


def search_catalog(entries: list[CatalogEntry], query: str, limit: int = 5) -> list[SearchResult]:
    terms = _tokenize(query)
    if not terms:
        return []

    results: list[SearchResult] = []
    for entry in entries:
        field_hits: dict[str, int] = {}

        title_hits = _score_text(terms, entry.title)
        if title_hits:
            field_hits["title"] = title_hits * 5

        node_hits = _score_text(terms, " ".join(entry.node_titles))
        if node_hits:
            field_hits["structure"] = node_hits * 3

        node_summary_hits = _score_text(terms, " ".join(entry.node_summaries))
        if node_summary_hits:
            field_hits["structure_summary"] = node_summary_hits * 3

        section_hits = _score_text(terms, " ".join(entry.section_names))
        if section_hits:
            field_hits["sections"] = section_hits * 2

        summary_hits = _score_text(terms, entry.core_idea)
        if summary_hits:
            field_hits["summary"] = summary_hits * 2

        total_score = float(sum(field_hits.values()))
        if total_score <= 0:
            continue
        results.append(
            SearchResult(
                paper_id=entry.paper_id,
                title=entry.title,
                score=total_score,
                matched_fields=sorted(field_hits.keys()),
                snippet=(entry.core_idea or entry.title)[:240],
            )
        )
    return sorted(results, key=lambda item: (-item.score, item.title.lower()))[:limit]


def search_records(
    records: list[PaperRecord],
    query: str,
    limit: int = 5,
    rerank_mode: RerankMode = "heuristic",
    llm_config: dict[str, Any] | None = None,
) -> list[SearchResult]:
    terms = _tokenize(query)
    if not terms:
        return []

    coarse_results: list[SearchResult] = []
    for record in records:
        field_hits: dict[str, int] = {}
        snippet = ""

        title_hits = _score_text(terms, record.title)
        if title_hits:
            field_hits["title"] = title_hits * 5
            snippet = record.title

        structure_matches = _rank_structure_nodes(record.structure.tree, query, limit=3)
        if structure_matches:
            field_hits["structure"] = int(sum(item.score for item in structure_matches))
            snippet = snippet or structure_matches[0].summary or structure_matches[0].snippet or structure_matches[0].title

        card_text = " ".join(str(getattr(record.card, field) or "") for field in CARD_SEARCH_FIELDS)
        card_hits = _score_text(terms, card_text)
        if card_hits:
            field_hits["card"] = card_hits * 2
            snippet = snippet or first_nonempty_line(record.card.core_idea or "")

        section_hits = 0
        for name, section in record.sections.items():
            hits = _score_text(terms, name + " " + section.content)
            if hits:
                section_hits += hits
                snippet = snippet or first_nonempty_line(section.content)
        if section_hits:
            field_hits["sections"] = section_hits * 2

        total_score = float(sum(field_hits.values()))
        if total_score <= 0:
            continue
        coarse_results.append(
            SearchResult(
                paper_id=record.paper_id,
                title=record.title,
                score=total_score,
                matched_fields=sorted(field_hits.keys()),
                snippet=snippet[:240],
                structure_matches=structure_matches,
            )
        )

    return rerank_search_results(query, coarse_results, mode=rerank_mode, llm_config=llm_config)[:limit]


def find_structure_matches(record: PaperRecord, query: str, limit: int = 5) -> list[StructureMatch]:
    return _rank_structure_nodes(record.structure.tree, query, limit=limit)
