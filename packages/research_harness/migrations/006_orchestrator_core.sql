-- Orchestrator core schema: runs, stage events, project artifacts, review issues/responses

CREATE TABLE IF NOT EXISTS orchestrator_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    mode TEXT NOT NULL DEFAULT 'standard',
    current_stage TEXT NOT NULL DEFAULT 'topic_framing',
    stage_status TEXT NOT NULL DEFAULT 'in_progress',
    gate_status TEXT NOT NULL DEFAULT '',
    blocking_issue_count INTEGER NOT NULL DEFAULT 0,
    unresolved_issue_count INTEGER NOT NULL DEFAULT 0,
    latest_plan_artifact_id INTEGER,
    latest_draft_artifact_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orchestrator_runs_topic ON orchestrator_runs(topic_id);

CREATE TABLE IF NOT EXISTS orchestrator_stage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES orchestrator_runs(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_stage_events_run ON orchestrator_stage_events(run_id);
CREATE INDEX IF NOT EXISTS idx_stage_events_project ON orchestrator_stage_events(project_id);

CREATE TABLE IF NOT EXISTS project_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    parent_artifact_id INTEGER REFERENCES project_artifacts(id),
    provenance_record_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_artifacts_project_stage ON project_artifacts(project_id, stage, artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifacts_topic ON project_artifacts(topic_id, artifact_type);

CREATE TABLE IF NOT EXISTS review_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_review_issues_project ON review_issues(project_id);
CREATE INDEX IF NOT EXISTS idx_review_issues_status ON review_issues(status);

CREATE TABLE IF NOT EXISTS review_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL REFERENCES review_issues(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    response_type TEXT NOT NULL DEFAULT 'change',
    status TEXT NOT NULL DEFAULT 'proposed',
    artifact_id INTEGER REFERENCES project_artifacts(id),
    response_text TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_review_responses_issue ON review_responses(issue_id);
