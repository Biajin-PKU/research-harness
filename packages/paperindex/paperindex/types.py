from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .cards.schema import PaperCard


@dataclass
class SectionNode:
    title: str
    start_page: int
    end_page: int
    node_id: str = ""
    section_text: str = ""
    summary: str = ""
    children: list["SectionNode"] = field(default_factory=list)

    def to_dict(self, include_text: bool = True) -> dict[str, Any]:
        data = {
            "title": self.title,
            "start_index": self.start_page,
            "end_index": self.end_page,
            "node_id": self.node_id,
        }
        if self.summary:
            data["summary"] = self.summary
        if include_text:
            data["section_text"] = self.section_text
        if self.children:
            data["nodes"] = [child.to_dict(include_text=include_text) for child in self.children]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SectionNode":
        return cls(
            title=data.get("title", ""),
            start_page=int(data.get("start_index", 0) or 0),
            end_page=int(data.get("end_index", 0) or 0),
            node_id=data.get("node_id", ""),
            section_text=data.get("section_text", ""),
            summary=data.get("summary", ""),
            children=[cls.from_dict(item) for item in data.get("nodes", [])],
        )


@dataclass
class StructureResult:
    doc_name: str
    tree: list[SectionNode]
    pdf_hash: str
    page_count: int
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_text: bool = True) -> dict[str, Any]:
        return {
            "doc_name": self.doc_name,
            "structure": [node.to_dict(include_text=include_text) for node in self.tree],
            "pdf_hash": self.pdf_hash,
            "page_count": self.page_count,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructureResult":
        return cls(
            doc_name=data.get("doc_name", ""),
            tree=[SectionNode.from_dict(item) for item in data.get("structure", [])],
            pdf_hash=data.get("pdf_hash", ""),
            page_count=int(data.get("page_count", 0) or 0),
            raw=data.get("raw", {}),
        )


@dataclass
class SectionResult:
    section: str
    content: str
    confidence: float = 1.0
    extractor_version: str = ""
    source_pdf_hash: str = ""
    model_used: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "content": self.content,
            "confidence": self.confidence,
            "extractor_version": self.extractor_version,
            "source_pdf_hash": self.source_pdf_hash,
            "model_used": self.model_used,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SectionResult":
        return cls(
            section=data.get("section", ""),
            content=data.get("content", ""),
            confidence=float(data.get("confidence", 1.0) or 0.0),
            extractor_version=data.get("extractor_version", ""),
            source_pdf_hash=data.get("source_pdf_hash", ""),
            model_used=data.get("model_used", ""),
        )


@dataclass
class PaperRecord:
    paper_id: str
    title: str
    doc_name: str
    pdf_hash: str
    page_count: int
    structure: StructureResult
    sections: dict[str, SectionResult] = field(default_factory=dict)
    card: PaperCard = field(default_factory=PaperCard)
    source_path: str = ""
    indexed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "doc_name": self.doc_name,
            "pdf_hash": self.pdf_hash,
            "page_count": self.page_count,
            "structure": self.structure.to_dict(),
            "sections": {name: result.to_dict() for name, result in self.sections.items()},
            "card": self.card.to_dict(),
            "source_path": self.source_path,
            "indexed_at": self.indexed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperRecord":
        card_data = data.get("card", {})
        card = card_data if isinstance(card_data, PaperCard) else PaperCard.from_dict(card_data)
        return cls(
            paper_id=data.get("paper_id", ""),
            title=data.get("title", ""),
            doc_name=data.get("doc_name", ""),
            pdf_hash=data.get("pdf_hash", ""),
            page_count=int(data.get("page_count", 0) or 0),
            structure=StructureResult.from_dict(data.get("structure", {})),
            sections={name: SectionResult.from_dict(result) for name, result in data.get("sections", {}).items()},
            card=card,
            source_path=data.get("source_path", ""),
            indexed_at=data.get("indexed_at", ""),
        )


@dataclass
class CatalogEntry:
    paper_id: str
    title: str
    doc_name: str
    pdf_hash: str
    page_count: int
    source_path: str
    indexed_at: str
    section_names: list[str] = field(default_factory=list)
    node_titles: list[str] = field(default_factory=list)
    node_summaries: list[str] = field(default_factory=list)
    core_idea: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "doc_name": self.doc_name,
            "pdf_hash": self.pdf_hash,
            "page_count": self.page_count,
            "source_path": self.source_path,
            "indexed_at": self.indexed_at,
            "section_names": self.section_names,
            "node_titles": self.node_titles,
            "node_summaries": self.node_summaries,
            "core_idea": self.core_idea,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogEntry":
        return cls(
            paper_id=data.get("paper_id", ""),
            title=data.get("title", ""),
            doc_name=data.get("doc_name", ""),
            pdf_hash=data.get("pdf_hash", ""),
            page_count=int(data.get("page_count", 0) or 0),
            source_path=data.get("source_path", ""),
            indexed_at=data.get("indexed_at", ""),
            section_names=list(data.get("section_names", [])),
            node_titles=list(data.get("node_titles", [])),
            node_summaries=list(data.get("node_summaries", [])),
            core_idea=data.get("core_idea", ""),
        )


@dataclass
class StructureMatch:
    node_id: str
    title: str
    start_page: int
    end_page: int
    score: float
    snippet: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "score": self.score,
            "snippet": self.snippet,
            "summary": self.summary,
        }


@dataclass
class SearchResult:
    paper_id: str
    title: str
    score: float
    matched_fields: list[str] = field(default_factory=list)
    snippet: str = ""
    structure_matches: list[StructureMatch] = field(default_factory=list)
    rerank_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "score": self.score,
            "matched_fields": self.matched_fields,
            "snippet": self.snippet,
            "structure_matches": [item.to_dict() for item in self.structure_matches],
            "rerank_reason": self.rerank_reason,
        }


EXTRACTABLE_SECTIONS = (
    "summary",
    "methodology",
    "experiments",
    "equations",
    "limitations",
    "reproduction_notes",
)
