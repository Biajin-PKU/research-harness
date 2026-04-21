-- Advisory engine storage
-- Sprint 3: lightweight heuristic-based research quality advisories

CREATE TABLE IF NOT EXISTS advisories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    project_id INTEGER,
    level TEXT NOT NULL CHECK (level IN ('info', 'warning')),
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TIMESTAMP,
    auto_resolved INTEGER NOT NULL DEFAULT 0
);
