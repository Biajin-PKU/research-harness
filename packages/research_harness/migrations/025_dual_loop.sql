-- Migration 025: Dual loop — experiment log + meta-reflections.
--
-- Supports AI-Research-SKILLs-inspired outer loop that reflects across
-- experiments and decides DEEPEN / BROADEN / PIVOT / CONCLUDE.

-- Experiment log: tracks individual experiment runs within a project
CREATE TABLE IF NOT EXISTS experiment_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    experiment_number INTEGER NOT NULL,
    hypothesis TEXT NOT NULL,
    study_spec_artifact_id INTEGER,
    result_artifact_id INTEGER,
    primary_metric_name TEXT,
    primary_metric_value REAL,
    metrics_json TEXT DEFAULT '{}',
    outcome TEXT NOT NULL DEFAULT 'pending',  -- pending | success | partial | failure
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_explog_project ON experiment_log(project_id);
CREATE INDEX IF NOT EXISTS idx_explog_topic ON experiment_log(topic_id);

-- Meta-reflection records: outer loop decisions
CREATE TABLE IF NOT EXISTS meta_reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    reflection_number INTEGER NOT NULL,
    trigger_type TEXT NOT NULL,          -- periodic | failure_streak | manual
    experiments_reviewed TEXT DEFAULT '[]',  -- JSON array of experiment_log IDs
    patterns_observed TEXT DEFAULT '',
    decision TEXT NOT NULL,              -- DEEPEN | BROADEN | PIVOT | CONCLUDE
    reasoning TEXT NOT NULL,
    next_hypothesis TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5,
    model_used TEXT DEFAULT '',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_metarefl_project ON meta_reflections(project_id);
