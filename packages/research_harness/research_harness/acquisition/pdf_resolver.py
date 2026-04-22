"""PDF path resolver — discovers and links existing PDFs to papers in the DB.

Solves the cross-session problem: PDFs exist on disk in multiple directories
but papers.pdf_path is empty, so new sessions can't find them.

Usage:
    from research_harness.acquisition.pdf_resolver import backfill_pdf_paths
    stats = backfill_pdf_paths(db, topic_id=2)  # example topic
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..storage.db import Database

logger = logging.getLogger(__name__)

MIN_PDF_BYTES = 10_000  # 10 KB — skip corrupt/truncated files

# Standard PDF directories relative to project root
STANDARD_PDF_DIRS = [
    ".research-harness/downloads",
    ".research-harness/papers",
    "paper_library/cross-budget-rebalancing/pdfs",
    "paper_library/downloads",
]


def _find_project_root() -> Path:
    """Walk up from cwd or known paths to find the project root (has .research-harness/)."""
    candidates = [
        Path.cwd(),
        Path(__file__)
        .resolve()
        .parents[4],  # packages/research_harness/research_harness/acquisition -> root
        Path.home() / "code" / "research-harness",
    ]
    for p in candidates:
        if (p / ".research-harness").is_dir():
            return p
    return Path.cwd()


def _is_valid_pdf(path: Path) -> bool:
    """Check file exists, meets minimum size, and starts with %PDF."""
    if not path.is_file():
        return False
    if path.stat().st_size < MIN_PDF_BYTES:
        return False
    try:
        with open(path, "rb") as f:
            return f.read(5).startswith(b"%PDF")
    except OSError:
        return False


def _build_search_index(project_root: Path) -> dict[str, dict[str, list[Path]]]:
    """Build lookup indices for all PDF files in standard directories.

    Returns:
        {
            "by_paper_id": {"57": [Path(...), ...], ...},
            "by_arxiv_id": {"2602.08261": [Path(...), ...], ...},
            "by_doi_fragment": {"3637528.3671526": [Path(...), ...], ...},
        }
    """
    by_paper_id: dict[str, list[Path]] = {}
    by_arxiv_id: dict[str, list[Path]] = {}
    by_doi_fragment: dict[str, list[Path]] = {}

    for rel_dir in STANDARD_PDF_DIRS:
        dir_path = project_root / rel_dir
        if not dir_path.is_dir():
            continue
        for fname in os.listdir(dir_path):
            if not fname.endswith(".pdf"):
                continue
            full_path = dir_path / fname
            base = fname[:-4]  # strip .pdf

            # Index by paper_id prefix: "57_Some_Title" -> "57"
            parts = base.split("_", 1)
            if parts[0].isdigit():
                pid = parts[0]
                by_paper_id.setdefault(pid, []).append(full_path)

            # Index by arxiv_id: "2602.08261" (exact filename)
            dot_parts = base.split(".")
            if (
                len(dot_parts) == 2
                and dot_parts[0].isdigit()
                and dot_parts[1].isdigit()
            ):
                by_arxiv_id.setdefault(base, []).append(full_path)

            # Index manual_ prefix: "manual_57_..." -> paper_id "57"
            if base.startswith("manual_"):
                rest = base[len("manual_") :]
                m_parts = rest.split("_", 1)
                if m_parts[0].isdigit():
                    by_paper_id.setdefault(m_parts[0], []).append(full_path)

            # Index by DOI-like fragment (ACM style): "3637528.3671526"
            # These appear in filenames from manual_recovered_pdfs
            if "." in base and all(c.isdigit() or c == "." for c in base):
                by_doi_fragment.setdefault(base, []).append(full_path)

    return {
        "by_paper_id": by_paper_id,
        "by_arxiv_id": by_arxiv_id,
        "by_doi_fragment": by_doi_fragment,
    }


def resolve_pdf_path(
    paper_id: int,
    arxiv_id: str,
    doi: str,
    title: str,
    index: dict[str, dict[str, list[Path]]],
) -> Path | None:
    """Resolve the PDF path for a single paper using the pre-built index.

    Search priority:
      1. paper_id prefix match in downloads/
      2. arxiv_id exact match in papers/
      3. manual_{paper_id} match
      4. DOI fragment match
    """
    pid_str = str(paper_id)
    clean_arxiv = arxiv_id.replace("arxiv:", "").strip()

    # 1. Paper ID prefix match (highest priority — most recent downloads)
    candidates = index["by_paper_id"].get(pid_str, [])
    for c in candidates:
        if _is_valid_pdf(c):
            return c

    # 2. ArXiv ID exact match
    if clean_arxiv:
        candidates = index["by_arxiv_id"].get(clean_arxiv, [])
        for c in candidates:
            if _is_valid_pdf(c):
                return c

    # 3. DOI fragment match (e.g., "10.1145/3637528.3671526" -> "3637528.3671526")
    if doi:
        # Extract the suffix after the registrant code
        doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
        # Try the part after "10.xxxx/"
        if "/" in doi_clean:
            fragment = doi_clean.split("/", 1)[1]
            candidates = index["by_doi_fragment"].get(fragment, [])
            for c in candidates:
                if _is_valid_pdf(c):
                    return c

    return None


@dataclass
class BackfillStats:
    total_missing: int = 0
    matched: int = 0
    unmatched: int = 0
    errors: int = 0
    unmatched_papers: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_missing": self.total_missing,
            "matched": self.matched,
            "unmatched": self.unmatched,
            "errors": self.errors,
            "unmatched_papers": self.unmatched_papers,
        }


def backfill_pdf_paths(
    db: Database,
    topic_id: int | None = None,
    dry_run: bool = False,
    project_root: Path | None = None,
) -> BackfillStats:
    """Discover existing PDFs and populate papers.pdf_path in the DB.

    Args:
        db: Database instance.
        topic_id: If set, only process papers in this topic.
        dry_run: If True, don't write to DB — just report matches.
        project_root: Override project root for testing.

    Returns:
        BackfillStats with match/unmatch counts.
    """
    root = project_root or _find_project_root()
    index = _build_search_index(root)

    conn = db.connect()
    try:
        if topic_id is not None:
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.arxiv_id, p.doi, p.url
                FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                  AND (p.pdf_path IS NULL OR p.pdf_path = '')
                ORDER BY p.id
                """,
                (topic_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, title, arxiv_id, doi, url
                FROM papers
                WHERE pdf_path IS NULL OR pdf_path = ''
                ORDER BY id
                """,
            ).fetchall()

        stats = BackfillStats(total_missing=len(rows))

        for row in rows:
            pid = row["id"]
            try:
                found = resolve_pdf_path(
                    paper_id=pid,
                    arxiv_id=row["arxiv_id"] or "",
                    doi=row["doi"] or "",
                    title=row["title"] or "",
                    index=index,
                )
            except Exception:
                logger.exception("Error resolving PDF for paper %d", pid)
                stats.errors += 1
                continue

            if found:
                stats.matched += 1
                logger.info("Resolved paper %d -> %s", pid, found)
                if not dry_run:
                    conn.execute(
                        "UPDATE papers SET pdf_path = ?, status = CASE WHEN status = 'meta_only' THEN 'downloaded' ELSE status END WHERE id = ?",
                        (str(found), pid),
                    )
            else:
                stats.unmatched += 1
                stats.unmatched_papers.append(
                    {
                        "paper_id": pid,
                        "title": (row["title"] or "")[:80],
                        "arxiv_id": row["arxiv_id"] or "",
                        "doi": row["doi"] or "",
                    }
                )

        if not dry_run:
            conn.commit()

        return stats
    finally:
        conn.close()
