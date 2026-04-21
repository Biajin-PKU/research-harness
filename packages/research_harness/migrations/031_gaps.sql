-- Persist gap_detect output so direction_ranking can consume it.
-- Before this migration, gap_detect only returned a GapDetectOutput object
-- without writing to DB, so direction_ranking's `SELECT ... FROM gaps WHERE topic_id=?`
-- always returned empty and produced "No gaps detected yet." recommendations.

CREATE TABLE IF NOT EXISTS gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    gap_type TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'medium',  -- high, medium, low
    related_paper_ids TEXT NOT NULL DEFAULT '[]',  -- JSON list of paper IDs
    focus TEXT NOT NULL DEFAULT '',  -- focus string that generated this gap
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(topic_id, description)
);

CREATE INDEX IF NOT EXISTS idx_gaps_topic ON gaps(topic_id);
CREATE INDEX IF NOT EXISTS idx_gaps_severity ON gaps(topic_id, severity);
