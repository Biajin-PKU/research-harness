from __future__ import annotations

import json
from pathlib import Path

from ..types import CatalogEntry, PaperRecord
from ..utils import first_nonempty_line, flatten_nodes

DEFAULT_LIBRARY_DIRNAME = ".paperindex"
CATALOG_FILENAME = "_catalog.json"


class PaperLibrary:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.papers_dir = self.root / "papers"
        self.papers_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: PaperRecord) -> Path:
        path = self.papers_dir / f"{record.paper_id}.json"
        path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._save_catalog_entry(self.build_catalog_entry(record))
        return path

    def get(self, paper_id: str) -> PaperRecord:
        path = self.papers_dir / f"{paper_id}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        return PaperRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self) -> list[PaperRecord]:
        records: list[PaperRecord] = []
        for path in sorted(self.papers_dir.glob("*.json")):
            if path.name == CATALOG_FILENAME:
                continue
            records.append(PaperRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return records

    def find_by_hash(self, pdf_hash: str) -> PaperRecord | None:
        for record in self.list():
            if record.pdf_hash == pdf_hash:
                return record
        return None

    def list_catalog(self) -> list[CatalogEntry]:
        catalog_path = self.root / CATALOG_FILENAME
        if catalog_path.exists():
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
            return [CatalogEntry.from_dict(item) for item in data]
        return [self.build_catalog_entry(record) for record in self.list()]

    @staticmethod
    def build_catalog_entry(record: PaperRecord) -> CatalogEntry:
        nodes = flatten_nodes(record.structure.tree)
        return CatalogEntry(
            paper_id=record.paper_id,
            title=record.title,
            doc_name=record.doc_name,
            pdf_hash=record.pdf_hash,
            page_count=record.page_count,
            source_path=record.source_path,
            indexed_at=record.indexed_at,
            section_names=sorted(record.sections.keys()),
            node_titles=[node.title for node in nodes],
            node_summaries=[node.summary for node in nodes if node.summary],
            core_idea=first_nonempty_line(record.card.core_idea or ""),
        )

    def _save_catalog_entry(self, entry: CatalogEntry) -> None:
        catalog_path = self.root / CATALOG_FILENAME
        existing = {item.paper_id: item for item in self.list_catalog()}
        existing[entry.paper_id] = entry
        payload = [item.to_dict() for item in sorted(existing.values(), key=lambda item: item.title.lower())]
        catalog_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
