-- Migration 026: Nudge tracking — records nudge delivery and acceptance.
--
-- Part of Hermes-inspired nudge mechanism that periodically reminds
-- the agent to extract strategies or reflect on the session.

CREATE TABLE IF NOT EXISTS nudge_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    nudge_type TEXT NOT NULL,    -- strategy_extraction | pattern_alert | cost_awareness | reflection_prompt
    nudge_text TEXT NOT NULL,
    accepted INTEGER DEFAULT 0,
    stage TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_nudge_session ON nudge_log(session_id);
CREATE INDEX IF NOT EXISTS idx_nudge_type ON nudge_log(nudge_type);
