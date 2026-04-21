-- Migration 021: Compiled summary cache infrastructure
-- Per-paper structured summary cache + topic-level overview cache

ALTER TABLE papers ADD COLUMN compiled_summary TEXT DEFAULT '';
ALTER TABLE papers ADD COLUMN compiled_from_hash TEXT DEFAULT '';

CREATE TABLE IF NOT EXISTS topic_summaries (
    topic_id INTEGER PRIMARY KEY REFERENCES topics(id) ON DELETE CASCADE,
    summary TEXT NOT NULL DEFAULT '',
    paper_count INTEGER NOT NULL DEFAULT 0,
    paper_ids_json TEXT NOT NULL DEFAULT '[]',
    compiled_at TEXT DEFAULT (datetime('now'))
);
