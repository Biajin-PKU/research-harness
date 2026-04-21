-- V2 Self-Evolution: unified experience ingestion pipeline.
-- All experience sources (human_edit, self_review, gold_comparison, auto_extracted)
-- flow through a single table. Each record may be gated (accepted/rejected/deferred)
-- by the validation gate (Phase 2). V1 bridge: ExperienceStore.ingest() also calls
-- DBLessonStore.append() so existing lesson-based flows continue unmodified.

CREATE TABLE IF NOT EXISTS experience_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kind TEXT NOT NULL,  -- human_edit | self_review | gold_comparison | auto_extracted
    stage TEXT NOT NULL,
    section TEXT DEFAULT '',
    before_text TEXT DEFAULT '',
    after_text TEXT DEFAULT '',
    diff_summary TEXT DEFAULT '',
    quality_delta REAL DEFAULT 0.0,
    topic_id INTEGER,
    project_id INTEGER,
    paper_id INTEGER,
    metadata TEXT DEFAULT '{}',
    gate_verdict TEXT DEFAULT 'pending',  -- pending | accepted | rejected | deferred
    gate_score REAL,
    lesson_id INTEGER,  -- FK to lessons table (V1 bridge)
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_exp_source ON experience_records(source_kind);
CREATE INDEX IF NOT EXISTS idx_exp_stage ON experience_records(stage);
CREATE INDEX IF NOT EXISTS idx_exp_topic ON experience_records(topic_id);
CREATE INDEX IF NOT EXISTS idx_exp_gate ON experience_records(gate_verdict);
CREATE INDEX IF NOT EXISTS idx_exp_project ON experience_records(project_id);
