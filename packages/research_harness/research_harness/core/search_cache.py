"""SQLite-backed search cache with per-source TTL.

Caches external provider search results to reduce API calls and enable
graceful degradation when providers are down (stale cache fallback).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.db import Database

logger = logging.getLogger(__name__)

# Per-source TTL in hours.
SOURCE_TTL_HOURS: dict[str, int] = {
    "arxiv": 24,
    "semantic_scholar": 72,
    "openalex": 48,
    "openreview": 48,
    "google_scholar": 24,
    "pasa": 24,
    "citation_verify": 8760,  # ~1 year
}

DEFAULT_TTL_HOURS = 48


def _cache_key(query: str, source: str, params: dict[str, Any] | None = None) -> str:
    raw = f"{query}|{source}|{json.dumps(params or {}, sort_keys=True)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl_for_source(source: str) -> int:
    return SOURCE_TTL_HOURS.get(source, DEFAULT_TTL_HOURS)


def cache_get(
    db: Database,
    query: str,
    source: str,
    params: dict[str, Any] | None = None,
    *,
    allow_stale: bool = False,
) -> list[dict] | None:
    """Return cached results or None.

    If *allow_stale* is True, return expired entries (for circuit-breaker fallback).
    """
    key = _cache_key(query, source, params)
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT result_json, expires_at FROM search_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        expires = row["expires_at"]
        now = _now_iso()
        if now > expires and not allow_stale:
            return None
        return json.loads(row["result_json"])
    except Exception as exc:
        logger.debug("Cache read error for %s/%s: %s", source, query[:30], exc)
        return None
    finally:
        conn.close()


def cache_put(
    db: Database,
    query: str,
    source: str,
    results: list[dict],
    params: dict[str, Any] | None = None,
) -> None:
    """Store search results in cache."""
    key = _cache_key(query, source, params)
    ttl_hours = _ttl_for_source(source)
    expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
    conn = db.connect()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO search_cache
               (cache_key, source, query_hash, result_json, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (key, source, query[:200], json.dumps(results, default=str), expires),
        )
        conn.commit()
    except Exception as exc:
        logger.debug("Cache write error for %s/%s: %s", source, query[:30], exc)
    finally:
        conn.close()


def cache_evict_expired(db: Database) -> int:
    """Remove all expired entries. Returns count removed."""
    now = _now_iso()
    conn = db.connect()
    try:
        cursor = conn.execute(
            "DELETE FROM search_cache WHERE expires_at < ?", (now,)
        )
        conn.commit()
        return cursor.rowcount
    except Exception:
        return 0
    finally:
        conn.close()
