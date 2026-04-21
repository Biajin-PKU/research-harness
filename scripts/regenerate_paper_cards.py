import os
import sys

sys.path.insert(0, 'packages/research_harness')
sys.path.insert(0, 'packages/paperindex')

from research_harness.config import find_workspace_root
from research_harness.integrations.paperindex_adapter import PaperIndexAdapter
from research_harness.storage.db import Database

ws = find_workspace_root() or os.getcwd()
db = Database(os.path.join(ws, '.research-harness', 'pool.db'))
db.migrate()
conn = db.connect()

rows = conn.execute(
    """
    SELECT id, title, pdf_path, status
    FROM papers
    WHERE pdf_path IS NOT NULL AND pdf_path != ''
    ORDER BY id
    """
).fetchall()

print(f'Papers with PDF: {len(rows)}', flush=True)
adapter = PaperIndexAdapter(conn, artifacts_root=os.path.join(str(db.db_path.parent), 'artifacts'))

success = 0
failed = []
for row in rows:
    paper_id = row['id']
    title = row['title']
    pdf_path = row['pdf_path']
    try:
        result = adapter.annotate_paper(paper_id, pdf_path)
        print(f"[OK] paper {paper_id}: {title} -> {result.get('card_path')}", flush=True)
        success += 1
    except Exception as exc:
        print(f"[FAIL] paper {paper_id}: {title}: {exc}", flush=True)
        failed.append((paper_id, str(exc)))

print(f'Done. Success: {success}, Failed: {len(failed)}', flush=True)
if failed:
    for paper_id, error in failed:
        print(f'  - {paper_id}: {error}', flush=True)

conn.close()
