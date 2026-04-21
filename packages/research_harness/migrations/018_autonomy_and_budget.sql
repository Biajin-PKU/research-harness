-- Migration 018: Add autonomy mode and budget policy to orchestrator runs.
-- Supports dual-axis model: workflow_mode × autonomy_mode.

ALTER TABLE orchestrator_runs ADD COLUMN autonomy_mode TEXT DEFAULT 'supervised';
ALTER TABLE orchestrator_runs ADD COLUMN task_profile TEXT DEFAULT 'exploratory';
ALTER TABLE orchestrator_runs ADD COLUMN policy_json TEXT DEFAULT '{}';
