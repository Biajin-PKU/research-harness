-- Migration 027: Add stop_before column to orchestrator_runs.
--
-- Allows configuring a hard stop: advance() refuses to enter the
-- specified stage, returning an error instead. Used for "auto-run
-- up to propose, then wait for human review" workflows.

ALTER TABLE orchestrator_runs ADD COLUMN stop_before TEXT DEFAULT '';
