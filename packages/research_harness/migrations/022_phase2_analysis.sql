-- Phase 2: Cross-paper qualitative analysis tables.

-- Method taxonomy: hierarchical classification of methods across papers.
CREATE TABLE IF NOT EXISTS taxonomy_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES taxonomy_nodes(id) ON DELETE SET NULL,
    description TEXT NOT NULL DEFAULT '',
    aliases TEXT NOT NULL DEFAULT '[]',  -- JSON list of alias names
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(topic_id, name)
);

-- Paper-to-taxonomy assignments.
CREATE TABLE IF NOT EXISTS taxonomy_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES taxonomy_nodes(id) ON DELETE CASCADE,
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(paper_id, node_id)
);

-- Normalized claims: structured version of claims for cross-paper comparison.
CREATE TABLE IF NOT EXISTS normalized_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT '',
    dataset TEXT NOT NULL DEFAULT '',
    metric TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT '',  -- 'higher_better', 'lower_better', 'qualitative'
    confidence REAL NOT NULL DEFAULT 0.5,
    source_section TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_normalized_claims_topic ON normalized_claims(topic_id);
CREATE INDEX IF NOT EXISTS idx_normalized_claims_paper ON normalized_claims(paper_id);
CREATE INDEX IF NOT EXISTS idx_normalized_claims_method ON normalized_claims(topic_id, method);
CREATE INDEX IF NOT EXISTS idx_normalized_claims_dataset ON normalized_claims(topic_id, dataset);

-- Contradiction candidates: detected tensions between claims.
CREATE TABLE IF NOT EXISTS contradictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    claim_a_id INTEGER NOT NULL REFERENCES normalized_claims(id) ON DELETE CASCADE,
    claim_b_id INTEGER NOT NULL REFERENCES normalized_claims(id) ON DELETE CASCADE,
    same_task INTEGER NOT NULL DEFAULT 0,
    same_dataset INTEGER NOT NULL DEFAULT 0,
    same_metric INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0.5,
    conflict_reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',  -- candidate, confirmed, dismissed
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contradictions_topic ON contradictions(topic_id);
