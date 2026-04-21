#!/usr/bin/env python3
"""
单篇论文卡片生成 - 交互式逐个处理
"""

import os
import sqlite3
import json
from pathlib import Path
from paperindex.indexer import PaperIndexer

DB_PATH = Path(".research-harness/pool.db")
ARTIFACTS_DIR = Path(".research-harness/artifacts")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_pending_papers():
    """获取需要生成卡片的论文"""
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT id, title, arxiv_id, pdf_path, venue, year
        FROM papers
        WHERE pdf_path IS NOT NULL
          AND pdf_path != ''
          AND status != 'annotated'
          AND status != 'deleted'
        ORDER BY id
    """).fetchall()
    conn.close()
    return rows

def generate_card(paper_id: int, pdf_path: str, arxiv_id: str = None) -> tuple[bool, str]:
    """为单篇论文生成卡片，返回 (是否成功, 错误信息)"""
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        pdf_file = Path(os.environ.get("RESEARCH_HARNESS_ROOT", Path.home() / "code/research-harness")) / pdf_path
        if not pdf_file.exists():
            return False, f"PDF not found: {pdf_path}"

    try:
        indexer = PaperIndexer()
        print(f"  🔄 正在索引 PDF: {pdf_file.name}")
        record = indexer.build_record(str(pdf_file))
        card = record.card

        # 保存到 artifacts
        paper_artifact_dir = ARTIFACTS_DIR / f"paper_{paper_id}"
        paper_artifact_dir.mkdir(parents=True, exist_ok=True)

        card_path = paper_artifact_dir / "card.json"
        with open(card_path, 'w') as f:
            json.dump(card.to_dict(), f, indent=2, ensure_ascii=False)

        # 保存到 paper_library/papers/
        cards_dir = Path("paper_library/papers")
        cards_dir.mkdir(parents=True, exist_ok=True)

        if arxiv_id:
            export_path = cards_dir / f"card_{arxiv_id}.json"
        else:
            export_path = cards_dir / f"card_paper_{paper_id}.json"

        with open(export_path, 'w') as f:
            json.dump(card.to_dict(), f, indent=2, ensure_ascii=False)

        # 更新数据库
        conn = get_db_connection()
        conn.execute(
            "UPDATE papers SET status = 'annotated' WHERE id = ?",
            (paper_id,)
        )

        metadata = json.dumps({"version": "1.0", "source": "paperindex"})
        conn.execute(
            """INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata, created_at)
               VALUES (?, 'paperindex_card', ?, ?, datetime('now'))""",
            (paper_id, str(card_path), metadata)
        )

        conn.commit()
        conn.close()

        return True, f"Card saved: {export_path}"

    except Exception as e:
        return False, str(e)

def main():
    papers = get_pending_papers()

    if not papers:
        print("✅ 所有论文都已完成卡片生成！")
        return

    print(f"=" * 70)
    print(f"共有 {len(papers)} 篇论文需要生成卡片")
    print(f"=" * 70)
    print()

    success_count = 0
    failed_papers = []

    for i, row in enumerate(papers, 1):
        paper_id = row['id']
        title = row['title']
        arxiv_id = row['arxiv_id']
        venue = row['venue'] or "未知"
        year = row['year'] or "未知"

        print(f"\n[{i}/{len(papers)}] ID: {paper_id}")
        print(f"Title: {title}")
        print(f"Venue: {venue} ({year})")
        print("-" * 70)

        # 自动处理，不询问
        print("  🔄 正在生成卡片...")
        success, msg = generate_card(paper_id, row['pdf_path'], arxiv_id)

        if success:
            print(f"  ✅ {msg}")
            success_count += 1
        else:
            print(f"  ❌ 失败: {msg}")
            failed_papers.append({
                'id': paper_id,
                'title': title,
                'error': msg
            })
            # 询问是否继续
            response = input(f"\n继续处理下一篇? [y/n/q]: ").strip().lower()
            if response == 'q':
                print("退出处理")
                break
            elif response == 'n':
                continue

    print(f"\n{'=' * 70}")
    print(f"处理完成: {success_count}/{len(papers)} 成功")
    if failed_papers:
        print(f"失败: {len(failed_papers)} 篇")
        print("\n失败的论文:")
        for p in failed_papers:
            print(f"  [{p['id']}] {p['title']}")
            print(f"    Error: {p['error'][:100]}")

if __name__ == "__main__":
    main()
