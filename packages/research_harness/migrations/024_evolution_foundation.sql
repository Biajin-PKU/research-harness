-- Migration 024: Evolution foundation — trajectory capture, DB lessons, strategies.
--
-- Part of the self-evolution system inspired by SkillClaw's distillation pipeline.

-- Rich decision trajectories: captures reasoning and tool call chains beyond metadata.
CREATE TABLE IF NOT EXISTS trajectory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,          -- tool_call | decision | gate_outcome | error_recovery | user_override
    tool_name TEXT,
    stage TEXT,
    topic_id INTEGER,
    project_id INTEGER,
    input_summary TEXT,                -- sanitized summary of inputs
    output_summary TEXT,               -- sanitized summary of outputs
    reasoning TEXT,                    -- agent rationale if available
    success INTEGER DEFAULT 1,
    cost_usd REAL DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    parent_event_id INTEGER,           -- hierarchical trajectory support
    sequence_number INTEGER DEFAULT 0, -- ordering within session
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_traj_session ON trajectory_events(session_id);
CREATE INDEX IF NOT EXISTS idx_traj_stage ON trajectory_events(stage);
CREATE INDEX IF NOT EXISTS idx_traj_topic ON trajectory_events(topic_id);

-- Lessons in DB (coexists with JSONL for backward compat).
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT NOT NULL,
    content TEXT NOT NULL,
    lesson_type TEXT NOT NULL DEFAULT 'observation',  -- observation | success | failure | tip
    tags TEXT NOT NULL DEFAULT '[]',                   -- JSON array
    weight REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL DEFAULT 'manual',             -- manual | extracted | distilled
    source_session_id TEXT,
    source_project_id INTEGER,
    topic_id INTEGER,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_lessons_stage ON lessons(stage);
CREATE INDEX IF NOT EXISTS idx_lessons_type ON lessons(lesson_type);
CREATE INDEX IF NOT EXISTS idx_lessons_topic ON lessons(topic_id);

-- Distilled strategies: reusable research strategies per stage.
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT NOT NULL,
    strategy_key TEXT NOT NULL,        -- unique identifier e.g. 'build.citation_expansion'
    title TEXT NOT NULL,
    content TEXT NOT NULL,             -- markdown content
    scope TEXT NOT NULL DEFAULT 'global',  -- global | topic
    topic_id INTEGER,                  -- only set when scope='topic'
    version INTEGER NOT NULL DEFAULT 1,
    quality_score REAL,                -- from quality gate (0-1)
    gate_model TEXT,                   -- which model quality-gated this
    source_lesson_ids TEXT DEFAULT '[]',  -- JSON array of lesson IDs
    source_session_count INTEGER DEFAULT 0,
    injection_count INTEGER DEFAULT 0,   -- how many times injected into sessions
    positive_feedback INTEGER DEFAULT 0, -- positive outcomes after injection
    status TEXT NOT NULL DEFAULT 'draft', -- draft | active | superseded
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(strategy_key, version)
);
CREATE INDEX IF NOT EXISTS idx_strategies_stage ON strategies(stage);
CREATE INDEX IF NOT EXISTS idx_strategies_key ON strategies(strategy_key);
CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status);
