-- Migration 029: Iterative retrieval convergence tracking.
-- Adds per-query round metrics so the iterative_retrieval_loop primitive can
-- record each round's overlap ratio (how much of the fresh search result set
-- was already in the topic's paper pool) and decide when the pool has
-- converged. Existing rows remain valid — new columns default to NULL so
-- historical queries are treated as "not yet measured".

ALTER TABLE search_query_registry ADD COLUMN round_index INTEGER;
ALTER TABLE search_query_registry ADD COLUMN total_hits INTEGER;
ALTER TABLE search_query_registry ADD COLUMN dedup_hits INTEGER;
ALTER TABLE search_query_registry ADD COLUMN existing_hits INTEGER;
ALTER TABLE search_query_registry ADD COLUMN new_papers_added INTEGER;
ALTER TABLE search_query_registry ADD COLUMN overlap_ratio REAL;
ALTER TABLE search_query_registry ADD COLUMN seed_gap TEXT;
ALTER TABLE search_query_registry ADD COLUMN last_round_cost_usd REAL;

CREATE INDEX IF NOT EXISTS idx_search_query_round
    ON search_query_registry(topic_id, round_index);
