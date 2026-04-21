from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any

sys.path.insert(0, "packages/research_harness")
sys.path.insert(0, "packages/paperindex")

from research_harness.config import find_workspace_root
from research_harness.pdf_download import MIN_PDF_BYTES, PaperDownloadCandidate, build_candidate_urls, is_pdf_bytes, preferred_filename
from research_harness.storage.db import Database


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download missing PDFs using stored URLs, identifier heuristics, and optional PKU cookies.")
    parser.add_argument("--paper-id", type=int, action="append", help="Restrict to one or more paper IDs.")
    parser.add_argument("--cookies", help="Path to a Netscape/Mozilla cookie jar exported from the logged-in browser.")
    parser.add_argument("--manifest", help="Optional JSON file mapping paper_id to manual candidate URLs.")
    parser.add_argument("--report", help="Optional JSON path for a structured download report.")
    parser.add_argument("--download-dir", help="Override output directory.")
    parser.add_argument("--min-bytes", type=int, default=MIN_PDF_BYTES, help="Reject downloaded files smaller than this size.")
    parser.add_argument("--dry-run", action="store_true", help="Print candidate URLs without downloading.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of papers to process.")
    return parser.parse_args()


def load_manifest(path: str | None) -> dict[int, list[str]]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, dict) and "papers" in payload:
        payload = payload["papers"]
    elif isinstance(payload, dict) and "records" in payload:
        payload = payload["records"]
    if isinstance(payload, dict):
        return {int(key): _coerce_urls(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return {int(item["paper_id"]): _coerce_urls(item) for item in payload}
    raise ValueError("manifest must be a dict or list")


def _coerce_urls(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key in ("all_pdf_like_urls", "manual_urls", "urls", "url"):
            if key not in value:
                continue
            inner = value[key]
            if isinstance(inner, str):
                return [inner]
            if isinstance(inner, list):
                return [item for item in inner if isinstance(item, str)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def build_opener(cookie_path: str | None) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if cookie_path:
        cookie_jar = MozillaCookieJar(cookie_path)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        handlers.append(urllib.request.HTTPCookieProcessor(cookie_jar))
    return urllib.request.build_opener(*handlers)


def fetch_pdf(opener: urllib.request.OpenerDirector, url: str, destination: Path, min_bytes: int) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with opener.open(request, timeout=45) as response:
            payload = response.read()
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, f"URL error: {exc.reason}"
    except Exception as exc:  # pragma: no cover
        return False, str(exc)

    if len(payload) < min_bytes:
        return False, f"too_small:{len(payload)}"
    if not is_pdf_bytes(payload):
        return False, f"not_pdf:{final_url}"

    destination.write_bytes(payload)
    return True, final_url


def write_report(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    args = parse_args()
    ws = find_workspace_root() or os.getcwd()
    db = Database(os.path.join(ws, ".research-harness", "pool.db"))
    db.migrate()
    conn = db.connect()

    download_dir = Path(args.download_dir or os.path.join(ws, "paper_library", "cross-budget-rebalancing", "pdfs"))
    download_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(args.manifest)
    opener = build_opener(args.cookies)

    sql = """
        SELECT id, title, arxiv_id, doi, year, venue, url
        FROM papers
        WHERE (pdf_path = '' OR pdf_path IS NULL)
    """
    params: list[object] = []
    if args.paper_id:
        placeholders = ",".join("?" for _ in args.paper_id)
        sql += f" AND id IN ({placeholders})"
        params.extend(args.paper_id)
    sql += " ORDER BY id"
    if args.limit:
        sql += " LIMIT ?"
        params.append(args.limit)

    rows = conn.execute(sql, params).fetchall()

    downloaded = 0
    failures: list[tuple[int, str, str]] = []
    report_records: list[dict[str, Any]] = []

    for row in rows:
        candidate = PaperDownloadCandidate(
            paper_id=row["id"],
            title=row["title"],
            year=row["year"],
            venue=row["venue"] or "",
            doi=row["doi"] or "",
            arxiv_id=row["arxiv_id"] or "",
            url=row["url"] or "",
        )
        urls = build_candidate_urls(candidate, manual_urls=manifest.get(candidate.paper_id, []))
        report_record: dict[str, Any] = {
            "paper_id": candidate.paper_id,
            "title": candidate.title,
            "urls": urls,
            "status": "pending",
            "attempts": [],
        }
        if args.dry_run:
            report_record["status"] = "dry_run"
            report_records.append(report_record)
            print(json.dumps({"paper_id": candidate.paper_id, "title": candidate.title, "urls": urls}, ensure_ascii=False))
            continue
        if not urls:
            failures.append((candidate.paper_id, candidate.title, "no_candidate_urls"))
            report_record["status"] = "failed"
            report_record["failure_reason"] = "no_candidate_urls"
            report_records.append(report_record)
            continue

        destination = download_dir / preferred_filename(candidate)
        last_error = "no_attempt"
        for url in urls:
            ok, detail = fetch_pdf(opener, url, destination, args.min_bytes)
            report_record["attempts"].append({"url": url, "ok": ok, "detail": detail})
            if ok:
                conn.execute(
                    "UPDATE papers SET pdf_path = ?, url = CASE WHEN url = '' THEN ? ELSE url END WHERE id = ?",
                    (str(destination), detail, candidate.paper_id),
                )
                conn.commit()
                downloaded += 1
                report_record["status"] = "downloaded"
                report_record["final_url"] = detail
                report_record["destination"] = str(destination)
                report_records.append(report_record)
                print(f"[ok] {candidate.paper_id}: {detail} -> {destination.name}")
                break
            last_error = f"{url} ({detail})"
        else:
            failures.append((candidate.paper_id, candidate.title, last_error))
            report_record["status"] = "failed"
            report_record["failure_reason"] = last_error
            report_records.append(report_record)

    conn.close()

    report_payload = {
        "downloaded": downloaded,
        "failed": len(failures),
        "download_dir": str(download_dir),
        "cookie_path": args.cookies or "",
        "manifest_path": args.manifest or "",
        "min_bytes": args.min_bytes,
        "dry_run": bool(args.dry_run),
        "records": report_records,
    }
    write_report(args.report, report_payload)

    print(f"Downloaded {downloaded} PDFs, failed {len(failures)}")
    for pid, title, reason in failures:
        print(f"  [{pid}] {reason}: {title[:80]}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
