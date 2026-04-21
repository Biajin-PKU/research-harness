#!/usr/bin/env python3
"""Batch deep read for a single topic. Run one instance per topic in parallel."""
import argparse
import json
import sqlite3
import sys
import time
import traceback
from pathlib import Path

# Ensure packages are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "research_harness"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "paperindex"))

from research_harness.execution.llm_primitives import deep_read
from research_harness.storage.db import Database

DB_PATH = Path(__file__).resolve().parents[1] / ".research-harness" / "pool.db"


def get_top_papers(topic_id: int, limit: int = 100, year_from: int = 2021):
    """Get top papers with PDFs for a topic, sorted by priority."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        """
        SELECT p.id, p.title, p.pdf_path, p.year, p.citation_count
        FROM papers p
        JOIN paper_topics pt ON p.id = pt.paper_id
        WHERE pt.topic_id = ?
          AND p.pdf_path IS NOT NULL AND p.pdf_path != ''
          AND (p.year IS NULL OR p.year >= ?)
        ORDER BY
          CASE WHEN p.citation_count IS NOT NULL THEN p.citation_count ELSE 0 END DESC,
          CASE WHEN p.year IS NOT NULL THEN p.year ELSE 2020 END DESC
        LIMIT ?
        """,
        (topic_id, year_from, limit),
    ).fetchall()
    conn.close()
    return [(r[0], r[1], r[2]) for r in rows if Path(r[2]).exists()]


def already_read(topic_id: int, paper_id: int) -> bool:
    """Check if paper already has deep reading annotation."""
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT COUNT(*) FROM paper_annotations WHERE paper_id=? AND section='deep_reading'",
        (paper_id,),
    ).fetchone()
    conn.close()
    return row[0] > 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("topic_id", type=int)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--year-from", type=int, default=2021)
    parser.add_argument("--focus", type=str, default="")
    args = parser.parse_args()

    db = Database(str(DB_PATH))
    papers = get_top_papers(args.topic_id, args.limit, args.year_from)
    print(f"Topic {args.topic_id}: {len(papers)} papers with PDFs (limit={args.limit})")

    done, skipped, failed = 0, 0, 0
    for i, (pid, title, pdf_path) in enumerate(papers):
        if already_read(args.topic_id, pid):
            skipped += 1
            continue
        try:
            print(f"[{i+1}/{len(papers)}] Reading [{pid}] {title[:60]}...", flush=True)
            result = deep_read(
                db=db,
                paper_id=pid,
                topic_id=args.topic_id,
                focus=args.focus or None,
            )
            has_note = result.note is not None
            print(f"  → {'OK' if has_note else 'FAIL'} [{result.pass1_model}/{result.pass2_model}]", flush=True)
            done += 1
            time.sleep(1)  # rate limit
        except Exception as e:
            print(f"  → ERROR: {e}", flush=True)
            failed += 1
            time.sleep(2)

    print(f"\nDone: {done}, Skipped (already read): {skipped}, Failed: {failed}")


if __name__ == "__main__":
    main()
