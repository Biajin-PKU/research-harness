-- Provenance tracking for research primitive executions

CREATE TABLE IF NOT EXISTS provenance_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    primitive   TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    backend     TEXT NOT NULL,
    model_used  TEXT NOT NULL DEFAULT 'none',
    topic_id    INTEGER,
    stage       TEXT NOT NULL DEFAULT '',
    input_hash  TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    cost_usd    REAL NOT NULL DEFAULT 0.0,
    success     INTEGER NOT NULL DEFAULT 1,
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    parent_id   INTEGER REFERENCES provenance_records(id),
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_provenance_primitive ON provenance_records(primitive);
CREATE INDEX IF NOT EXISTS idx_provenance_backend ON provenance_records(backend);
CREATE INDEX IF NOT EXISTS idx_provenance_topic ON provenance_records(topic_id);
CREATE INDEX IF NOT EXISTS idx_provenance_created ON provenance_records(created_at);
