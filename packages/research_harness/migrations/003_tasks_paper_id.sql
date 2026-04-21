ALTER TABLE tasks ADD COLUMN paper_id INTEGER REFERENCES papers(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_paper ON tasks(paper_id);
