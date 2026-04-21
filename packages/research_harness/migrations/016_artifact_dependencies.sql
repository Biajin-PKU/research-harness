-- Artifact dependency tracking + stale propagation
-- Sprint 2.2: enables downstream invalidation when upstream artifacts change

CREATE TABLE IF NOT EXISTS artifact_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_artifact_id INTEGER NOT NULL REFERENCES project_artifacts(id),
    to_artifact_id INTEGER NOT NULL REFERENCES project_artifacts(id),
    dependency_type TEXT NOT NULL DEFAULT 'consumed_by',  -- consumed_by | derived_from
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_artifact_id, to_artifact_id, dependency_type)
);

-- Add stale tracking columns to project_artifacts
ALTER TABLE project_artifacts ADD COLUMN stale INTEGER NOT NULL DEFAULT 0;
ALTER TABLE project_artifacts ADD COLUMN stale_reason TEXT;
