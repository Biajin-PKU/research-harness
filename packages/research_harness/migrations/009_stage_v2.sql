-- Stage V2: 5-stage redesign support
-- Adds freshness tracking, per-query registry, decision log, and paper enrichment fields.

-- Topic-level freshness tracking
ALTER TABLE topics ADD COLUMN last_search_at TEXT DEFAULT NULL;
ALTER TABLE topics ADD COLUMN freshness_warn_days INTEGER DEFAULT 7;
ALTER TABLE topics ADD COLUMN freshness_stale_days INTEGER DEFAULT 30;

-- Paper enrichment: auto-generated BibTeX and OpenAlex concept tags
ALTER TABLE papers ADD COLUMN bibtex_auto TEXT DEFAULT '';
ALTER TABLE papers ADD COLUMN concepts_json TEXT DEFAULT '';

-- Per-query freshness tracking
CREATE TABLE IF NOT EXISTS search_query_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL REFERENCES topics(id),
    query TEXT NOT NULL,
    source TEXT DEFAULT 'user',
    last_searched_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(topic_id, query)
);

-- Decision log for human checkpoints
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    checkpoint TEXT NOT NULL,
    choice TEXT NOT NULL,
    reasoning TEXT DEFAULT '',
    params_snapshot TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
