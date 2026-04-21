#!/usr/bin/env python3
"""
串行生成论文卡片 - 一次处理一篇，带重试机制
"""

import os
import sqlite3
import json
import time
from pathlib import Path
from paperindex.indexer import PaperIndexer

DB_PATH = Path(".research-harness/pool.db")
ARTIFACTS_DIR = Path(".research-harness/artifacts")
PROGRESS_FILE = Path(".research-harness/card_generation_progress.json")

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

def load_progress():
    """加载进度"""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": [], "failed": {}}

def save_progress(progress):
    """保存进度"""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)

def generate_card_for_paper(row, max_retries=3):
    """
    为单篇论文生成卡片，带重试机制
    返回: (success: bool, error_msg: str)
    """
    paper_id = row['id']
    pdf_path = row['pdf_path']
    arxiv_id = row['arxiv_id']

    # 检查PDF路径
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        pdf_file = Path(os.environ.get("RESEARCH_HARNESS_ROOT", Path.home() / "code/research-harness")) / pdf_path
        if not pdf_file.exists():
            return False, f"PDF not found: {pdf_path}"

    # 重试循环
    for attempt in range(1, max_retries + 1):
        try:
            print(f"    尝试 {attempt}/{max_retries}...")

            # 创建 indexer 并生成卡片
            indexer = PaperIndexer()
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

            return True, str(export_path)

        except Exception as e:
            error_msg = str(e)
            print(f"    ⚠️  失败: {error_msg[:100]}")

            if attempt < max_retries:
                wait_time = attempt * 2  # 递增等待时间
                print(f"    ⏳ 等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            else:
                return False, error_msg

    return False, "Max retries exceeded"

def main():
    papers = get_pending_papers()

    if not papers:
        print("✅ 所有论文都已完成卡片生成！")
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
        return

    # 加载进度
    progress = load_progress()
    completed_ids = set(progress.get("completed", []))
    failed_ids = progress.get("failed", {})

    # 过滤已完成的
    papers_to_process = [p for p in papers if p['id'] not in completed_ids]

    print("=" * 70)
    print(f"📊 论文卡片生成（串行模式）")
    print("=" * 70)
    print(f"总待处理: {len(papers)} 篇")
    print(f"已完成: {len(completed_ids)} 篇")
    print(f"本次处理: {len(papers_to_process)} 篇")
    print("=" * 70)
    print()

    success_count = 0
    new_failed = {}

    for i, row in enumerate(papers_to_process, 1):
        paper_id = row['id']
        title = row['title'][:60] + "..." if len(row['title']) > 60 else row['title']
        arxiv_id = row['arxiv_id'] or "N/A"
        venue = row['venue'] or "未知"

        print(f"\n[{i}/{len(papers_to_process)}] ID:{paper_id} | arXiv:{arxiv_id}")
        print(f"    标题: {title}")
        print(f"    期刊: {venue}")
        print("-" * 70)

        # 串行处理 - 一次一篇
        success, result = generate_card_for_paper(row, max_retries=3)

        if success:
            print(f"    ✅ 成功: {result.name}")
            completed_ids.add(paper_id)
            success_count += 1

            # 每成功一篇就保存进度
            progress["completed"] = list(completed_ids)
            save_progress(progress)

            # 成功后的延迟，避免API限流
            if i < len(papers_to_process):
                print(f"    ⏳ 等待 3 秒后继续...")
                time.sleep(3)
        else:
            print(f"    ❌ 失败: {result[:100]}")
            new_failed[paper_id] = {
                "title": row['title'],
                "error": result,
                "pdf_path": row['pdf_path']
            }
            failed_ids[str(paper_id)] = new_failed[paper_id]
            progress["failed"] = failed_ids
            save_progress(progress)

            # 询问是否继续
            response = input(f"\n继续处理下一篇? [Enter=是 / q=退出]: ").strip().lower()
            if response == 'q':
                print("\n已暂停，下次运行会继续处理")
                break

    # 最终报告
    print(f"\n{'=' * 70}")
    print(f"📊 处理报告")
    print(f"{'=' * 70}")
    print(f"本次成功: {success_count} 篇")
    print(f"累计完成: {len(completed_ids)} / {len(papers)} 篇")
    print(f"剩余: {len(papers) - len(completed_ids)} 篇")

    if failed_ids:
        print(f"\n⚠️  失败的论文:")
        for pid, info in failed_ids.items():
            print(f"    [{pid}] {info['title'][:50]}...")

    if len(completed_ids) >= len(papers):
        print(f"\n🎉 全部完成！")
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()

if __name__ == "__main__":
    main()
