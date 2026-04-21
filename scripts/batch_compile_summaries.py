#!/usr/bin/env python3
"""Batch compile summaries for papers missing them in specified topics."""
import os
import sys
import sqlite3
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault(
    "RESEARCH_HARNESS_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", ".research-harness", "pool.db"),
)

from research_harness.storage.db import Database
from research_harness.execution.compiled_summary import ensure_compiled_summary


def get_pending_ids(db_path: str, topic_id: int) -> list[int]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT DISTINCT p.id FROM papers p
        JOIN paper_topics pt ON p.id = pt.paper_id
        WHERE pt.topic_id = ?
        AND p.pdf_path IS NOT NULL AND p.pdf_path != ''
        AND (p.compiled_summary IS NULL OR p.compiled_summary = '')
        ORDER BY p.id
        """,
        (topic_id,),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def process_one(db: Database, paper_id: int) -> tuple[int, bool, str]:
    try:
        result = ensure_compiled_summary(db, paper_id)
        if result:
            return (paper_id, True, "")
        return (paper_id, False, "no source data")
    except Exception as e:
        return (paper_id, False, str(e)[:200])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("topic_ids", nargs="+", type=int)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    db_path = os.environ["RESEARCH_HARNESS_DB_PATH"]
    db = Database()

    all_ids = []
    for tid in args.topic_ids:
        ids = get_pending_ids(db_path, tid)
        print(f"Topic {tid}: {len(ids)} papers pending", flush=True)
        all_ids.extend(ids)

    seen = set()
    unique_ids = []
    for pid in all_ids:
        if pid not in seen:
            seen.add(pid)
            unique_ids.append(pid)

    if args.limit > 0:
        unique_ids = unique_ids[: args.limit]

    print(f"\nProcessing {len(unique_ids)} unique papers with {args.workers} workers\n", flush=True)

    success = 0
    fail = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_one, db, pid): pid for pid in unique_ids}
        for i, f in enumerate(as_completed(futures), 1):
            pid, ok, err = f.result()
            if ok:
                success += 1
                status = "OK"
            else:
                fail += 1
                status = f"FAIL: {err}"
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            print(f"[{i}/{len(unique_ids)}] paper={pid} {status}  ({rate:.1f}/s)", flush=True)

    elapsed = time.time() - t0
    print(f"\nDone: {success} success, {fail} failed, {elapsed:.0f}s total")


if __name__ == "__main__":
    main()
