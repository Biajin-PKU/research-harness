-- Migration 030: Writing observations table for Universal Writing Skill
--
-- Stores structural writing patterns extracted from deeply-read papers.
-- Each row is one observation about one dimension of one paper's writing.
-- Aggregated by WritingSkillAggregator into strategies for section_draft injection.

CREATE TABLE IF NOT EXISTS writing_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    dimension TEXT NOT NULL,          -- e.g. 'abstract_hook_type', 'exp_post_table_analysis'
    section TEXT NOT NULL,            -- e.g. 'abstract', 'experiments'
    observation TEXT NOT NULL,        -- structured observation (JSON)
    example_text TEXT DEFAULT '',     -- verbatim excerpt from the paper
    paper_venue TEXT DEFAULT '',      -- publication venue (e.g. 'NeurIPS')
    paper_venue_tier TEXT DEFAULT '', -- CCF tier (e.g. 'A', 'B')
    paper_year INTEGER DEFAULT 0,
    extractor_model TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (paper_id) REFERENCES papers(id)
);

CREATE INDEX IF NOT EXISTS idx_wo_dimension ON writing_observations(dimension);
CREATE INDEX IF NOT EXISTS idx_wo_section ON writing_observations(section);
CREATE INDEX IF NOT EXISTS idx_wo_paper ON writing_observations(paper_id);
