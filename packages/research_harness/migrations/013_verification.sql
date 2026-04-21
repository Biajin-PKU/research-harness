-- Sprint 3: Citation verification tracking table.

CREATE TABLE IF NOT EXISTS citation_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'not_found',  -- verified | partial_match | not_found | hallucinated
    confidence REAL DEFAULT 0.0,
    matched_title TEXT DEFAULT '',
    matched_doi TEXT DEFAULT '',
    source TEXT DEFAULT '',  -- crossref | datacite | openalex | semantic_scholar | doi_provided
    checked_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_citation_verifications_project
    ON citation_verifications(project_id);

CREATE INDEX IF NOT EXISTS idx_citation_verifications_status
    ON citation_verifications(project_id, status);
