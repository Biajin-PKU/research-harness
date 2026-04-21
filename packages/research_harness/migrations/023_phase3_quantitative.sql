-- Phase 3: Quantitative extraction tables.

-- Extracted tables from PDF papers.
CREATE TABLE IF NOT EXISTS extracted_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    table_number INTEGER NOT NULL DEFAULT 0,
    caption TEXT NOT NULL DEFAULT '',
    headers TEXT NOT NULL DEFAULT '[]',     -- JSON list of column headers
    rows TEXT NOT NULL DEFAULT '[]',        -- JSON list of row arrays
    source_page INTEGER,
    extraction_method TEXT NOT NULL DEFAULT 'vision',  -- vision, text, manual
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_extracted_tables_paper ON extracted_tables(paper_id);

-- Interpreted figures from PDF papers.
CREATE TABLE IF NOT EXISTS extracted_figures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    figure_number INTEGER NOT NULL DEFAULT 0,
    caption TEXT NOT NULL DEFAULT '',
    interpretation TEXT NOT NULL DEFAULT '',  -- what the figure shows
    key_data_points TEXT NOT NULL DEFAULT '[]',  -- JSON list of extracted values
    figure_type TEXT NOT NULL DEFAULT '',     -- bar_chart, line_plot, scatter, diagram, etc.
    source_page INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_extracted_figures_paper ON extracted_figures(paper_id);

-- Aggregated metrics with provenance.
CREATE TABLE IF NOT EXISTS aggregated_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    method TEXT NOT NULL DEFAULT '',
    dataset TEXT NOT NULL DEFAULT '',
    metric TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'text',  -- table, text, figure
    source_ref TEXT NOT NULL DEFAULT '',        -- e.g., "Table 3, row 2" or "compiled_summary"
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_aggregated_metrics_topic ON aggregated_metrics(topic_id);
CREATE INDEX IF NOT EXISTS idx_aggregated_metrics_method ON aggregated_metrics(topic_id, method);
