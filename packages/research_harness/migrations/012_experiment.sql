-- Experiment execution tables for Sprint 2.
-- experiment_runs: tracks each iteration of the edit-run-eval loop
-- verified_numbers: whitelist of numbers from experiment results
-- stage_checkpoints: sub-step checkpoints for experiment stage resumability

CREATE TABLE IF NOT EXISTS experiment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    iteration INTEGER NOT NULL DEFAULT 0,
    code_hash TEXT NOT NULL DEFAULT '',
    entry_point TEXT NOT NULL DEFAULT 'main.py',
    primary_metric_name TEXT DEFAULT '',
    primary_metric_value REAL,
    all_metrics_json TEXT DEFAULT '{}',
    improved INTEGER DEFAULT 0,
    kept INTEGER DEFAULT 0,
    elapsed_sec REAL DEFAULT 0.0,
    returncode INTEGER DEFAULT 0,
    timed_out INTEGER DEFAULT 0,
    divergence TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_experiment_runs_project ON experiment_runs(project_id);

CREATE TABLE IF NOT EXISTS verified_numbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    source TEXT NOT NULL,
    number_original REAL NOT NULL,
    number_rounded REAL,
    number_percentage REAL,
    number_inverse REAL,
    tolerance REAL DEFAULT 0.01,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_verified_numbers_project ON verified_numbers(project_id);

CREATE TABLE IF NOT EXISTS stage_checkpoints (
    topic_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    sub_step TEXT NOT NULL DEFAULT '',
    iteration INTEGER DEFAULT 0,
    state_snapshot TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (topic_id, stage)
);
