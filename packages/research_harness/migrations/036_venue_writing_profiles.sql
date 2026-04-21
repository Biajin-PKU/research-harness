-- Migration 036: Venue writing profiles — persistent competitive learning cache.
--
-- Stores aggregated writing patterns per venue/dimension pair.
-- Populated by competitive_learning, consumed by section_draft.
-- Survives across sessions; refreshed when stale (>180 days).

CREATE TABLE IF NOT EXISTS venue_writing_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue TEXT NOT NULL,
    dimension TEXT NOT NULL,
    top_pattern TEXT NOT NULL,
    distribution TEXT DEFAULT '{}',
    examples TEXT DEFAULT '[]',
    paper_count INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.0,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(venue, dimension)
);

CREATE INDEX IF NOT EXISTS idx_vwp_venue ON venue_writing_profiles(venue);
