-- Migration 028: Add token-level usage tracking to provenance records.
-- Enables long-term per-topic / per-agent token consumption analytics and
-- cross-validates cost_usd against the provider-reported token counts.
-- Old records are left as NULL so historical cost_usd remains authoritative.

ALTER TABLE provenance_records ADD COLUMN prompt_tokens INTEGER;
ALTER TABLE provenance_records ADD COLUMN completion_tokens INTEGER;
