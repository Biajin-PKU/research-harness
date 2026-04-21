#!/usr/bin/env python3
"""
下载非 arXiv 来源的 PDF 论文
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

def download_pdf(url: str, output_path: Path, referer: str = None) -> bool:
    """下载 PDF"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read()
            # 检查是否为 PDF
            if content[:4] == b'%PDF':
                output_path.write_bytes(content)
                return True
            else:
                print(f"    Not a PDF, content-type: {response.headers.get('content-type', 'unknown')}")
                return False
    except HTTPError as e:
        print(f"    HTTP Error {e.code}: {e.reason}")
        return False
    except Exception as e:
        print(f"    Error: {e}")
        return False

def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()
    rows = conn.execute("""
        SELECT id, title, doi, url, venue
        FROM papers
        WHERE status = 'meta_only'
          AND (arxiv_id IS NULL OR arxiv_id = '')
          AND (doi IS NOT NULL OR url IS NOT NULL)
        ORDER BY id
    """).fetchall()
    conn.close()

    print(f"Found {len(rows)} non-arXiv papers to download\n")

    success_count = 0
    needs_manual = []
    no_source = []

    for row in rows:
        paper_id = row['id']
        doi = row['doi']
        url = row['url']
        title = row['title'][:60] + "..." if len(row['title']) > 60 else row['title']
        venue = row['venue'] or ''

        print(f"[{paper_id}] {title}")
        print(f"  Venue: {venue}")

        # 确定文件名
        if doi:
            filename = doi.replace('/', '_').replace('.', '_') + ".pdf"
        elif url:
            filename = f"paper_{paper_id}.pdf"
        else:
            filename = f"paper_{paper_id}.pdf"

        output_path = PDF_DIR / filename

        # 检查是否已存在
        if output_path.exists():
            print(f"  Already exists")
            success_count += 1
            continue

        # 尝试下载
        sources_to_try = []

        if url and url.endswith('.pdf'):
            sources_to_try.append((url, None))
        elif url:
            sources_to_try.append((url, None))

        # 为 DOI 添加 Sci-Hub 链接（如果有 DOI 但没有直接 URL）
        if doi and not url:
            # 记录为需要手动处理
            pass

        downloaded = False
        for src_url, referer in sources_to_try:
            print(f"  Trying: {src_url[:80]}...")
            if download_pdf(src_url, output_path, referer):
                print(f"  ✓ Success")
                downloaded = True
                success_count += 1

                # 更新数据库
                conn = get_db_connection()
                conn.execute(
                    "UPDATE papers SET pdf_path = ? WHERE id = ?",
                    (str(output_path), paper_id)
                )
                conn.commit()
                conn.close()
                break
            time.sleep(1)

        if not downloaded:
            if doi or url:
                needs_manual.append({
                    'id': paper_id,
                    'title': row['title'],
                    'doi': doi,
                    'url': url,
                    'venue': venue
                })
            else:
                no_source.append({
                    'id': paper_id,
                    'title': row['title'],
                    'venue': venue
                })

        print()
        time.sleep(2)

    print(f"\n{'='*60}")
    print(f"Downloaded: {success_count}/{len(rows)}")
    print(f"Needs manual download: {len(needs_manual)}")
    print(f"No source available: {len(no_source)}")

    # 保存需要手动下载的论文
    if needs_manual:
        import json
        manual_file = Path("papers_needing_manual_download.json")
        with open(manual_file, 'w') as f:
            json.dump(needs_manual, f, indent=2)
        print(f"\nSaved {len(needs_manual)} papers to {manual_file}")

        # 同时生成 Markdown 报告
        md_file = Path("papers_needing_manual_download.md")
        with open(md_file, 'w') as f:
            f.write("# 需要手动下载的论文\n\n")
            f.write("这些论文有 DOI 或 URL，但自动下载失败。可能需要通过机构访问或购买。\n\n")

            for paper in needs_manual:
                f.write(f"## [{paper['id']}] {paper['title']}\n\n")
                f.write(f"- **期刊/会议**: {paper['venue']}\n")
                if paper['doi']:
                    f.write(f"- **DOI**: [{paper['doi']}](https://doi.org/{paper['doi']})\n")
                if paper['url']:
                    f.write(f"- **URL**: [{paper['url']}]({paper['url']})\n")
                f.write(f"- **建议**: 通过北大图书馆 VPN 或联系作者获取\n\n")

        print(f"Saved Markdown report to {md_file}")

if __name__ == "__main__":
    main()
