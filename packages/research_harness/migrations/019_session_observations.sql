-- Migration 019: Session observation table for MCP tool call pattern recording.
-- Powers the SkillClaw-inspired self-evolution loop.

CREATE TABLE IF NOT EXISTS session_observations (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_hash TEXT,
    result_summary TEXT,
    success INTEGER DEFAULT 1,
    cost_usd REAL DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    stage TEXT,
    gate_outcome TEXT,
    user_intervention INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_obs_session ON session_observations(session_id);
CREATE INDEX IF NOT EXISTS idx_obs_tool ON session_observations(tool_name);
