-- Add citation_count column to papers table.
-- Used by select_seeds and expand_citations primitives for ranking.
ALTER TABLE papers ADD COLUMN citation_count INTEGER;
