-- Migration 020: Add quality tracking fields to provenance records.
-- Enables correlating primitive execution with artifact quality and human acceptance.

ALTER TABLE provenance_records ADD COLUMN artifact_id INTEGER;
ALTER TABLE provenance_records ADD COLUMN quality_score REAL;
ALTER TABLE provenance_records ADD COLUMN human_accept INTEGER;
ALTER TABLE provenance_records ADD COLUMN loop_round INTEGER DEFAULT 0;
