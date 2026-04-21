import sys, os
sys.path.insert(0, 'packages/research_harness')
sys.path.insert(0, 'packages/paperindex')

from research_harness.storage.db import Database
from research_harness.config import find_workspace_root
from research_harness.integrations.paperindex_adapter import PaperIndexAdapter

ws = find_workspace_root() or os.getcwd()
db = Database(os.path.join(ws, '.research-harness', 'pool.db'))
db.migrate()
conn = db.connect()

rows = conn.execute("""
    SELECT id, title, pdf_path FROM papers
    WHERE pdf_path != '' AND pdf_path IS NOT NULL
    AND status != 'annotated'
    ORDER BY id
""").fetchall()

print('Papers to annotate: ' + str(len(rows)), flush=True)
adapter = PaperIndexAdapter(conn, artifacts_root=os.path.join(str(db.db_path.parent), 'artifacts'))

success = 0
failed = []
for row in rows:
    paper_id = row['id']
    pdf_path = row['pdf_path']
    try:
        result = adapter.annotate_paper(paper_id, pdf_path)
        ac = result.get('annotation_count', 0)
        print(f'[OK] paper {paper_id}: {ac} sections annotated', flush=True)
        success += 1
    except Exception as e:
        print(f'[FAIL] paper {paper_id}: {e}', flush=True)
        failed.append((paper_id, str(e)))

conn.close()
print(f'Done. Success: {success}, Failed: {len(failed)}', flush=True)
