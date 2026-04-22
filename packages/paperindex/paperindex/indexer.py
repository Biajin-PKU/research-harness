from __future__ import annotations

from pathlib import Path
from typing import Any

from .cards.extraction import build_paper_card
from .extraction.section_extractor import extract_section_content
from .indexing.page_index import extract_structure_tree
from .indexing.section_text import attach_section_text, normalize_section_title
from .library import PaperLibrary
from llm_router.client import resolve_llm_config
from .retrieval import find_structure_matches, search_catalog, search_records
from .types import (
    EXTRACTABLE_SECTIONS,
    CatalogEntry,
    PaperRecord,
    SearchResult,
    SectionNode,
    SectionResult,
    StructureMatch,
    StructureResult,
)
from .utils import flatten_nodes, sha256_file
from .cards.schema import PaperCard


class PaperIndexer:
    def __init__(self, llm_config: dict[str, Any] | None = None):
        self._llm_config = resolve_llm_config(llm_config).to_dict()

    def extract_structure(self, pdf_path: str | Path) -> StructureResult:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)
        tree, raw = extract_structure_tree(pdf_path, llm_config=self._llm_config)
        attach_section_text(tree, raw.get("pages_text", []))
        return StructureResult(
            doc_name=pdf_path.name,
            tree=tree,
            pdf_hash=sha256_file(pdf_path),
            page_count=int(raw.get("page_count", 0)),
            raw=raw,
        )

    def extract_section(
        self,
        structure: StructureResult,
        section: str,
        pdf_path: str | Path | None = None,
    ) -> SectionResult:
        if section not in EXTRACTABLE_SECTIONS:
            raise ValueError(
                f"Unknown section '{section}'. Must be one of: {EXTRACTABLE_SECTIONS}"
            )
        return extract_section_content(
            structure, section, llm_config=self._llm_config, pdf_path=pdf_path
        )

    def build_card(
        self,
        structure: StructureResult,
        sections: list[SectionResult] | None = None,
        pdf_path: str | Path | None = None,
    ) -> PaperCard:
        return build_paper_card(
            structure,
            sections or [],
            llm_config=self._llm_config,
            pdf_path=str(pdf_path) if pdf_path else None,
        )

    def build_record(
        self,
        pdf_path: str | Path,
        section_names: tuple[str, ...] = EXTRACTABLE_SECTIONS,
    ) -> PaperRecord:
        source_path = Path(pdf_path)
        structure = self.extract_structure(source_path)
        sections = {
            name: self.extract_section(structure, name, pdf_path=source_path)
            for name in section_names
        }
        card = self.build_card(structure, list(sections.values()), pdf_path=source_path)
        return PaperRecord(
            paper_id=card.paper_id or "",
            title=str(card.title or structure.raw.get("title") or source_path.stem),
            doc_name=structure.doc_name,
            pdf_hash=structure.pdf_hash,
            page_count=structure.page_count,
            structure=structure,
            sections=sections,
            card=card,
            source_path=str(source_path),
        )

    def ingest(self, pdf_path: str | Path, library_root: str | Path) -> PaperRecord:
        record = self.build_record(pdf_path)
        PaperLibrary(library_root).save(record)
        return record

    def list_catalog(self, library_root: str | Path) -> list[CatalogEntry]:
        return PaperLibrary(library_root).list_catalog()

    def search(
        self,
        query: str,
        library_root: str | Path,
        limit: int = 5,
        rerank_mode: str = "heuristic",
    ) -> list[SearchResult]:
        records = PaperLibrary(library_root).list()
        if records:
            return search_records(
                records,
                query,
                limit=limit,
                rerank_mode=rerank_mode,
                llm_config=self._llm_config,
            )
        return search_catalog(
            PaperLibrary(library_root).list_catalog(), query, limit=limit
        )

    def search_catalog_only(
        self, query: str, library_root: str | Path, limit: int = 5
    ) -> list[SearchResult]:
        return search_catalog(
            PaperLibrary(library_root).list_catalog(), query, limit=limit
        )

    def load_record(self, paper_id: str, library_root: str | Path) -> PaperRecord:
        return PaperLibrary(library_root).get(paper_id)

    def get_structure(
        self, paper_id: str, library_root: str | Path, include_text: bool = False
    ) -> dict[str, Any]:
        record = self.load_record(paper_id, library_root)
        return record.structure.to_dict(include_text=include_text)

    def get_section_content(
        self,
        paper_id: str,
        library_root: str | Path,
        *,
        section_name: str | None = None,
        node_id: str | None = None,
        title_query: str | None = None,
    ) -> dict[str, Any]:
        record = self.load_record(paper_id, library_root)

        if section_name:
            result = record.sections.get(section_name)
            if result is None:
                raise KeyError(f"Section '{section_name}' not found")
            return {
                "paper_id": record.paper_id,
                "title": record.title,
                "mode": "section",
                "section": result.to_dict(),
            }

        nodes = flatten_nodes(record.structure.tree)
        if node_id:
            for node in nodes:
                if node.node_id == node_id:
                    return self._node_payload(record, node)
            raise KeyError(f"Node '{node_id}' not found")

        if title_query:
            normalized_query = normalize_section_title(title_query)
            ranked = []
            for node in nodes:
                normalized_title = normalize_section_title(node.title)
                score = 3 if normalized_query in normalized_title else 0
                if score == 0 and any(
                    token in normalized_title
                    for token in normalized_query.split()
                    if token
                ):
                    score = 1
                if score > 0:
                    ranked.append((score, node.start_page, node))
            if not ranked:
                raise KeyError(f"No node matched title query '{title_query}'")
            ranked.sort(key=lambda item: (-item[0], item[1]))
            return self._node_payload(record, ranked[0][2])

        raise ValueError(
            "One of section_name, node_id, or title_query must be provided"
        )

    def get_structure_matches(
        self, paper_id: str, query: str, library_root: str | Path, limit: int = 5
    ) -> list[StructureMatch]:
        record = self.load_record(paper_id, library_root)
        return find_structure_matches(record, query, limit=limit)

    @staticmethod
    def _node_payload(record: PaperRecord, node: SectionNode) -> dict[str, Any]:
        return {
            "paper_id": record.paper_id,
            "title": record.title,
            "mode": "node",
            "node": {
                "node_id": node.node_id,
                "title": node.title,
                "start_page": node.start_page,
                "end_page": node.end_page,
                "summary": node.summary,
                "content": node.section_text,
            },
        }
