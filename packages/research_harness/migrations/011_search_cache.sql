-- Search result cache with per-source TTL.
-- Used by paper_search to avoid redundant external API calls
-- and enable graceful degradation when providers are down.
CREATE TABLE IF NOT EXISTS search_cache (
    cache_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    query_hash TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON search_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_search_cache_source ON search_cache(source);
