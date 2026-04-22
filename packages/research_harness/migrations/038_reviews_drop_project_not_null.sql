-- Migration 038: Make project_id nullable across all tables that referenced projects.
-- Code now writes topic_id only; project_id kept for backward compat but no longer required.
-- SQLite does not support ALTER COLUMN, so we recreate affected tables.

-- 1. reviews
CREATE TABLE IF NOT EXISTS reviews_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
    gate TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    verdict TEXT NOT NULL,
    score REAL,
    findings TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

INSERT INTO reviews_new (id, project_id, topic_id, gate, reviewer, verdict, score, findings, created_at)
    SELECT id, project_id, topic_id, gate, reviewer, verdict, score, findings, created_at
    FROM reviews;

DROP TABLE reviews;
ALTER TABLE reviews_new RENAME TO reviews;
CREATE INDEX IF NOT EXISTS idx_reviews_topic ON reviews(topic_id);

-- 2. orchestrator_runs
CREATE TABLE IF NOT EXISTS orchestrator_runs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    mode TEXT NOT NULL DEFAULT 'standard',
    current_stage TEXT NOT NULL DEFAULT 'topic_framing',
    stage_status TEXT NOT NULL DEFAULT 'in_progress',
    gate_status TEXT NOT NULL DEFAULT '',
    blocking_issue_count INTEGER NOT NULL DEFAULT 0,
    unresolved_issue_count INTEGER NOT NULL DEFAULT 0,
    latest_plan_artifact_id INTEGER,
    latest_draft_artifact_id INTEGER,
    stop_before TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

INSERT INTO orchestrator_runs_new (id, project_id, topic_id, mode, current_stage, stage_status, gate_status, blocking_issue_count, unresolved_issue_count, latest_plan_artifact_id, latest_draft_artifact_id, stop_before, created_at, updated_at)
    SELECT id, project_id, topic_id, mode, current_stage, stage_status, gate_status, blocking_issue_count, unresolved_issue_count, latest_plan_artifact_id, latest_draft_artifact_id, COALESCE(stop_before, ''), created_at, updated_at
    FROM orchestrator_runs;

DROP TABLE orchestrator_runs;
ALTER TABLE orchestrator_runs_new RENAME TO orchestrator_runs;
CREATE INDEX IF NOT EXISTS idx_orchestrator_runs_topic ON orchestrator_runs(topic_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_orchestrator_runs_topic_unique ON orchestrator_runs(topic_id);

-- 3. orchestrator_stage_events — project_id was NOT NULL with no FK, make nullable
CREATE TABLE IF NOT EXISTS orchestrator_stage_events_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES orchestrator_runs(id) ON DELETE CASCADE,
    project_id INTEGER,
    topic_id INTEGER NOT NULL,
    from_stage TEXT NOT NULL,
    to_stage TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    gate_type TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);

INSERT INTO orchestrator_stage_events_new (id, run_id, project_id, topic_id, from_stage, to_stage, event_type, status, gate_type, actor, rationale, payload_json, created_at)
    SELECT id, run_id, project_id, topic_id, from_stage, to_stage, event_type, status, gate_type, actor, rationale, payload_json, created_at
    FROM orchestrator_stage_events;

DROP TABLE orchestrator_stage_events;
ALTER TABLE orchestrator_stage_events_new RENAME TO orchestrator_stage_events;
CREATE INDEX IF NOT EXISTS idx_stage_events_run ON orchestrator_stage_events(run_id);

-- 4. project_artifacts
CREATE TABLE IF NOT EXISTS project_artifacts_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    parent_artifact_id INTEGER,
    provenance_record_id INTEGER,
    stale INTEGER NOT NULL DEFAULT 0,
    stale_reason TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

INSERT INTO project_artifacts_new (id, project_id, topic_id, stage, artifact_type, status, version, title, path, payload_json, metadata_json, parent_artifact_id, provenance_record_id, stale, stale_reason, created_at, updated_at)
    SELECT id, project_id, topic_id, stage, artifact_type, status, version, title, path, payload_json, metadata_json, parent_artifact_id, provenance_record_id, stale, stale_reason, created_at, updated_at
    FROM project_artifacts;

DROP TABLE project_artifacts;
ALTER TABLE project_artifacts_new RENAME TO project_artifacts;
CREATE INDEX IF NOT EXISTS idx_artifacts_topic ON project_artifacts(topic_id, artifact_type);

-- 5. review_issues
CREATE TABLE IF NOT EXISTS review_issues_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    review_artifact_id INTEGER REFERENCES project_artifacts(id),
    stage TEXT NOT NULL,
    review_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    affected_object_type TEXT NOT NULL DEFAULT '',
    affected_object_id TEXT NOT NULL DEFAULT '',
    blocking INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    summary TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    recommended_action TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

INSERT INTO review_issues_new (id, project_id, topic_id, review_artifact_id, stage, review_type, severity, category, affected_object_type, affected_object_id, blocking, status, summary, details, recommended_action, created_at, updated_at)
    SELECT id, project_id, topic_id, review_artifact_id, stage, review_type, severity, category, affected_object_type, affected_object_id, blocking, status, summary, details, recommended_action, created_at, updated_at
    FROM review_issues;

DROP TABLE review_issues;
ALTER TABLE review_issues_new RENAME TO review_issues;
CREATE INDEX IF NOT EXISTS idx_review_issues_status ON review_issues(status);

-- 6. review_responses
CREATE TABLE IF NOT EXISTS review_responses_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL REFERENCES review_issues(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
    response_type TEXT NOT NULL DEFAULT 'change',
    status TEXT NOT NULL DEFAULT 'proposed',
    artifact_id INTEGER REFERENCES project_artifacts(id),
    response_text TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

INSERT INTO review_responses_new (id, issue_id, project_id, topic_id, response_type, status, artifact_id, response_text, evidence_json, created_at, updated_at)
    SELECT id, issue_id, project_id, topic_id, response_type, status, artifact_id, response_text, evidence_json, created_at, updated_at
    FROM review_responses;

DROP TABLE review_responses;
ALTER TABLE review_responses_new RENAME TO review_responses;
CREATE INDEX IF NOT EXISTS idx_review_responses_issue ON review_responses(issue_id);

-- 7. experiment_runs
CREATE TABLE IF NOT EXISTS experiment_runs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
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

INSERT INTO experiment_runs_new (id, project_id, topic_id, iteration, code_hash, entry_point, primary_metric_name, primary_metric_value, all_metrics_json, improved, kept, elapsed_sec, returncode, timed_out, divergence, error, created_at)
    SELECT id, project_id, topic_id, iteration, code_hash, entry_point, primary_metric_name, primary_metric_value, all_metrics_json, improved, kept, elapsed_sec, returncode, timed_out, divergence, error, created_at
    FROM experiment_runs;

DROP TABLE experiment_runs;
ALTER TABLE experiment_runs_new RENAME TO experiment_runs;

-- 8. verified_numbers
CREATE TABLE IF NOT EXISTS verified_numbers_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    topic_id INTEGER REFERENCES topics(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    number_original REAL NOT NULL,
    number_rounded REAL,
    number_percentage REAL,
    number_inverse REAL,
    tolerance REAL DEFAULT 0.01,
    created_at TEXT DEFAULT (datetime('now'))
);

INSERT INTO verified_numbers_new (id, project_id, topic_id, source, number_original, number_rounded, number_percentage, number_inverse, tolerance, created_at)
    SELECT id, project_id, topic_id, source, number_original, number_rounded, number_percentage, number_inverse, tolerance, created_at
    FROM verified_numbers;

DROP TABLE verified_numbers;
ALTER TABLE verified_numbers_new RENAME TO verified_numbers;
