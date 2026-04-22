"""Paper acquisition pipeline: download → annotate → triage."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..pdf_download import PaperDownloadCandidate
from ..storage.db import Database
from .downloader import DownloadResult, download_batch

logger = logging.getLogger(__name__)

DEFAULT_DOWNLOAD_DIR = ".research-harness/downloads"
DEFAULT_MANUAL_DIR = ".research-harness/manual_downloads"


def _record_event(
    db: Database, paper_id: int, event_type: str, detail: str = "", provider: str = ""
) -> None:
    """Append a pipeline event to the event log."""
    try:
        conn = db.connect()
        conn.execute(
            "INSERT INTO pipeline_events (paper_id, event_type, detail, provider) VALUES (?, ?, ?, ?)",
            (paper_id, event_type, detail, provider),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.debug(
            "Failed to record pipeline event %s for paper %d",
            event_type,
            paper_id,
            exc_info=True,
        )


@dataclass
class AcquisitionReport:
    topic_id: int
    total_papers: int = 0
    downloaded: int = 0
    annotated: int = 0
    needs_manual: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    manual_list: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build_candidates(db: Database, topic_id: int) -> list[PaperDownloadCandidate]:
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.year, p.venue, p.doi, p.arxiv_id, p.url,
                   p.status, p.pdf_path
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND (p.status = 'meta_only' OR p.pdf_path IS NULL OR p.pdf_path = '')
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY p.id
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    candidates = []
    for row in rows:
        candidates.append(
            PaperDownloadCandidate(
                paper_id=int(row["id"]),
                title=row["title"] or "",
                year=row["year"],
                venue=row["venue"] or "",
                doi=row["doi"] or "",
                arxiv_id=row["arxiv_id"] or "",
                url=row["url"] or "",
            )
        )
    return candidates


def _annotate_paper(
    db: Database, paper_id: int, pdf_path: Path, artifacts_root: Path
) -> bool:
    try:
        from ..integrations.paperindex_adapter import PaperIndexAdapter
    except ImportError:
        logger.warning(
            "paperindex not installed, skipping annotation for paper %d", paper_id
        )
        return False

    conn = db.connect()
    try:
        adapter = PaperIndexAdapter(conn, artifacts_root)
        adapter.annotate_paper(paper_id, pdf_path, skip_card=True)
        # Defensive: ensure pdf_path is written even if adapter didn't set it
        conn.execute(
            "UPDATE papers SET pdf_path = COALESCE(NULLIF(pdf_path, ''), ?) WHERE id = ?",
            (str(pdf_path), paper_id),
        )
        conn.commit()
        logger.info("Annotated paper %d from %s", paper_id, pdf_path)
        return True
    except Exception:
        logger.exception("Failed to annotate paper %d", paper_id)
        conn.execute(
            "UPDATE papers SET pdf_path = ?, status = ? WHERE id = ?",
            (str(pdf_path), "downloaded", paper_id),
        )
        conn.commit()
        return False
    finally:
        conn.close()


def _process_results(
    db: Database,
    results: list[DownloadResult],
    candidates: list[PaperDownloadCandidate],
    artifacts_root: Path,
) -> AcquisitionReport:
    candidate_map = {c.paper_id: c for c in candidates}
    report = AcquisitionReport(topic_id=0, total_papers=len(results))

    for result in results:
        entry: dict[str, Any] = {
            "paper_id": result.paper_id,
            "status": result.status,
            "path": str(result.path) if result.path else None,
            "failure_reason": result.failure_reason,
        }

        if result.status == "success" and result.path:
            _record_event(
                db, result.paper_id, "download_ok", provider=result.provider or ""
            )
            report.downloaded += 1
            _record_event(db, result.paper_id, "annotate_start")
            if _annotate_paper(db, result.paper_id, result.path, artifacts_root):
                _record_event(db, result.paper_id, "annotate_ok")
                report.annotated += 1
                entry["annotated"] = True
                # Eagerly compile structured summary while annotations are fresh
                try:
                    from ..execution.compiled_summary import ensure_compiled_summary

                    ensure_compiled_summary(db, result.paper_id)
                except Exception:
                    logging.getLogger(__name__).debug(
                        "Eager compilation failed for paper %d",
                        result.paper_id,
                        exc_info=True,
                    )
            else:
                _record_event(db, result.paper_id, "annotate_fail")
                entry["annotated"] = False
        elif result.status == "needs_manual":
            _record_event(
                db,
                result.paper_id,
                "download_fail",
                detail=result.failure_reason or "needs manual",
                provider="paywall",
            )
            report.needs_manual += 1
            cand = candidate_map.get(result.paper_id)
            if cand:
                report.manual_list.append(
                    {
                        "paper_id": cand.paper_id,
                        "title": cand.title,
                        "year": cand.year,
                        "venue": cand.venue,
                        "doi": cand.doi,
                        "arxiv_id": cand.arxiv_id,
                        "failure_reason": result.failure_reason,
                    }
                )
        else:
            _record_event(
                db,
                result.paper_id,
                "download_fail",
                detail=result.failure_reason or "all URLs failed",
            )
            report.failed += 1

        report.results.append(entry)

    return report


def acquire_papers(
    db: Database,
    topic_id: int,
    download_dir: str | Path | None = None,
    artifacts_root: str | Path | None = None,
) -> AcquisitionReport:
    download_path = Path(download_dir or DEFAULT_DOWNLOAD_DIR)
    artifacts_path = Path(artifacts_root or ".research-harness/artifacts")

    candidates = _build_candidates(db, topic_id)
    if not candidates:
        logger.info("No papers need downloading for topic %d", topic_id)
        return AcquisitionReport(topic_id=topic_id, total_papers=0)

    logger.info("Downloading %d papers for topic %d", len(candidates), topic_id)
    for c in candidates:
        _record_event(db, c.paper_id, "download_start")
    results = asyncio.run(download_batch(candidates, download_path))

    report = _process_results(db, results, candidates, artifacts_path)
    report.topic_id = topic_id

    if report.manual_list:
        _write_manual_list(report.manual_list, Path(DEFAULT_MANUAL_DIR))

    return report


def _write_manual_list(manual_list: list[dict[str, Any]], manual_dir: Path) -> None:
    manual_dir.mkdir(parents=True, exist_ok=True)

    json_path = manual_dir / "pending_manual.json"
    existing: list[dict[str, Any]] = []
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []

    existing_ids = {item["paper_id"] for item in existing}
    for item in manual_list:
        if item["paper_id"] not in existing_ids:
            existing.append(item)

    json_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))

    readme_path = manual_dir / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# Manual Downloads\n\n"
            "Place PDF files here with filename format: `{paper_id}_{title}.pdf`\n\n"
            "The paper_id prefix is required for matching. Example: `42_attention_is_all_you_need.pdf`\n\n"
            "After placing files, run: `rhub paper ingest-manual`\n"
        )

    logger.info(
        "Wrote %d papers to manual download list: %s", len(manual_list), json_path
    )


def ingest_manual_downloads(
    db: Database,
    manual_dir: str | Path | None = None,
    artifacts_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    manual_path = Path(manual_dir or DEFAULT_MANUAL_DIR)
    artifacts_path = Path(artifacts_root or ".research-harness/artifacts")

    if not manual_path.exists():
        return []

    results: list[dict[str, Any]] = []
    for pdf_file in sorted(manual_path.glob("*.pdf")):
        name = pdf_file.stem
        parts = name.split("_", 1)
        try:
            paper_id = int(parts[0])
        except (ValueError, IndexError):
            logger.warning(
                "Skipping %s: filename must start with paper_id", pdf_file.name
            )
            results.append(
                {
                    "file": pdf_file.name,
                    "status": "skipped",
                    "reason": "invalid filename",
                }
            )
            continue

        if _annotate_paper(db, paper_id, pdf_file, artifacts_path):
            results.append(
                {"file": pdf_file.name, "paper_id": paper_id, "status": "annotated"}
            )
        else:
            results.append(
                {
                    "file": pdf_file.name,
                    "paper_id": paper_id,
                    "status": "downloaded_only",
                }
            )

    if results:
        pending_path = manual_path / "pending_manual.json"
        if pending_path.exists():
            try:
                pending = json.loads(pending_path.read_text())
                ingested_ids = {r["paper_id"] for r in results if "paper_id" in r}
                remaining = [p for p in pending if p["paper_id"] not in ingested_ids]
                pending_path.write_text(
                    json.dumps(remaining, ensure_ascii=False, indent=2)
                )
            except (json.JSONDecodeError, OSError):
                pass

    return results
