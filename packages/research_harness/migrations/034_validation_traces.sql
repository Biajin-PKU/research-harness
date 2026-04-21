-- V2 Self-Evolution Phase 2: validation traces for experience gate.
-- Records each gate evaluation (tier1 applicability, tier2 strategy validity)
-- so we can audit and tune the gate's decisions over time.

CREATE TABLE IF NOT EXISTS validation_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experience_id INTEGER NOT NULL REFERENCES experience_records(id),
    tier TEXT NOT NULL,  -- tier1 | tier2
    verdict TEXT NOT NULL,  -- accepted | rejected | deferred
    score REAL,
    reasoning TEXT DEFAULT '',
    rule_scores TEXT DEFAULT '{}',  -- JSON: individual rule scores
    model_used TEXT DEFAULT '',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_vt_exp ON validation_traces(experience_id);
CREATE INDEX IF NOT EXISTS idx_vt_verdict ON validation_traces(verdict);
