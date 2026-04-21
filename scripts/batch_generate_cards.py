#!/usr/bin/env python3
"""
批量生成论文卡片
"""

import os
import sqlite3
import json
from pathlib import Path
from paperindex.indexer import PaperIndexer

DB_PATH = Path(".research-harness/pool.db")
ARTIFACTS_DIR = Path(".research-harness/artifacts")

DB_PATH = Path(".research-harness/pool.db")
ARTIFACTS_DIR = Path(".research-harness/artifacts")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def generate_card_for_paper(paper_id: int, pdf_path: str, title: str, arxiv_id: str = None):
    """为单篇论文生成卡片"""
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        # 尝试相对路径
        pdf_file = Path(os.environ.get("RESEARCH_HARNESS_ROOT", Path.home() / "code/research-harness")) / pdf_path
        if not pdf_file.exists():
            print(f"  ✗ PDF not found: {pdf_path}")
            return False

    try:
        # 初始化 indexer
        indexer = PaperIndexer()

        print(f"  Building record (indexing + card generation)...")
        # 构建完整记录 - 这包括结构提取、章节提取和卡片生成
        record = indexer.build_record(str(pdf_file))
        card = record.card

        # 保存卡片到 artifacts
        paper_artifact_dir = ARTIFACTS_DIR / f"paper_{paper_id}"
        paper_artifact_dir.mkdir(parents=True, exist_ok=True)

        card_path = paper_artifact_dir / "card.json"
        with open(card_path, 'w') as f:
            json.dump(card.to_dict(), f, indent=2, ensure_ascii=False)

        # 同时保存到 paper_library/papers/
        cards_dir = Path("paper_library/papers")
        cards_dir.mkdir(parents=True, exist_ok=True)

        if arxiv_id:
            export_path = cards_dir / f"card_{arxiv_id}.json"
        else:
            export_path = cards_dir / f"card_paper_{paper_id}.json"

        with open(export_path, 'w') as f:
            json.dump(card.to_dict(), f, indent=2, ensure_ascii=False)

        # 更新数据库状态
        conn = get_db_connection()
        conn.execute(
            "UPDATE papers SET status = 'annotated' WHERE id = ?",
            (paper_id,)
        )

        # 添加 paper_artifact 记录
        metadata = json.dumps({"version": "1.0", "source": "paperindex"})
        conn.execute(
            """INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata, created_at)
               VALUES (?, 'paperindex_card', ?, ?, datetime('now'))""",
            (paper_id, str(card_path), metadata)
        )

        conn.commit()
        conn.close()

        print(f"  ✓ Card saved to {card_path}")
        print(f"  ✓ Exported to {export_path}")
        return True

    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT id, title, arxiv_id, pdf_path, status
        FROM papers
        WHERE pdf_path IS NOT NULL
          AND pdf_path != ''
          AND status != 'annotated'
          AND status != 'deleted'
        ORDER BY id
    """).fetchall()
    conn.close()

    print(f"Found {len(rows)} papers needing cards\n")

    success_count = 0
    failed_papers = []

    for i, row in enumerate(rows, 1):
        paper_id = row['id']
        title = row['title'][:50] + "..." if len(row['title']) > 50 else row['title']
        arxiv_id = row['arxiv_id']
        pdf_path = row['pdf_path']

        print(f"[{i}/{len(rows)}] Paper {paper_id}: {title}")

        if generate_card_for_paper(paper_id, pdf_path, row['title'], arxiv_id):
            success_count += 1
        else:
            failed_papers.append({
                'id': paper_id,
                'title': row['title'],
                'pdf_path': pdf_path
            })

        print()

    print(f"{'='*60}")
    print(f"Success: {success_count}/{len(rows)}")
    print(f"Failed: {len(failed_papers)}")

    if failed_papers:
        print(f"\nFailed papers:")
        for p in failed_papers:
            print(f"  [{p['id']}] {p['title']}")

if __name__ == "__main__":
    main()
