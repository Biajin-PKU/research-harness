#!/usr/bin/env python3
"""
批量下载 arXiv PDF 论文
"""

import sqlite3
import urllib.request
import time
from pathlib import Path
from urllib.error import HTTPError

DB_PATH = Path(".research-harness/pool.db")
PDF_DIR = Path("paper_library/downloads")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def download_arxiv_pdf(arxiv_id: str, output_path: Path) -> bool:
    """下载 arXiv PDF"""
    # 清理 arxiv_id（移除版本号）
    clean_id = arxiv_id.split("v")[0]

    urls = [
        f"https://arxiv.org/pdf/{clean_id}.pdf",
        f"https://ar5iv.org/pdf/{clean_id}.pdf",
    ]

    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                output_path.write_bytes(response.read())
                return True
        except HTTPError as e:
            print(f"  HTTP Error {e.code} for {url}")
            continue
        except Exception as e:
            print(f"  Error: {e}")
            continue

    return False

def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()
    rows = conn.execute("""
        SELECT id, arxiv_id, title
        FROM papers
        WHERE status = 'meta_only'
          AND arxiv_id IS NOT NULL
          AND arxiv_id != ''
        ORDER BY id
    """).fetchall()
    conn.close()

    print(f"Found {len(rows)} arXiv papers to download\n")

    success_count = 0
    failed_ids = []

    for row in rows:
        paper_id = row['id']
        arxiv_id = row['arxiv_id']
        title = row['title'][:60] + "..." if len(row['title']) > 60 else row['title']

        output_path = PDF_DIR / f"{arxiv_id}.pdf"

        # 检查是否已存在
        if output_path.exists():
            print(f"[{paper_id}] {arxiv_id} - Already exists")
            success_count += 1
            continue

        print(f"[{paper_id}] Downloading {arxiv_id}...")
        print(f"  Title: {title}")

        if download_arxiv_pdf(arxiv_id, output_path):
            print(f"  ✓ Success -> {output_path}")
            success_count += 1

            # 更新数据库
            conn = get_db_connection()
            conn.execute(
                "UPDATE papers SET pdf_path = ? WHERE id = ?",
                (str(output_path), paper_id)
            )
            conn.commit()
            conn.close()
        else:
            print(f"  ✗ Failed")
            failed_ids.append((paper_id, arxiv_id, title))

        time.sleep(1)  # 礼貌间隔

    print(f"\n{'='*60}")
    print(f"Downloaded: {success_count}/{len(rows)}")
    print(f"Failed: {len(failed_ids)}")

    if failed_ids:
        print(f"\nFailed papers:")
        for paper_id, arxiv_id, title in failed_ids:
            print(f"  [{paper_id}] {arxiv_id}: {title}")

if __name__ == "__main__":
    main()
