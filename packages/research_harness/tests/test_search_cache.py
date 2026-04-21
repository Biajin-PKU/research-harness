"""Tests for core.search_cache — SQLite-backed search result cache with TTL."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from research_harness.core.search_cache import (
    _cache_key,
    cache_evict_expired,
    cache_get,
    cache_put,
)
from research_harness.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.migrate()
    return d


def test_cache_miss_returns_none(db):
    assert cache_get(db, "transformer attention", "arxiv") is None


def test_cache_put_and_get(db):
    results = [{"title": "Paper A", "year": 2024}]
    cache_put(db, "transformer", "arxiv", results)
    got = cache_get(db, "transformer", "arxiv")
    assert got is not None
    assert len(got) == 1
    assert got[0]["title"] == "Paper A"


def test_cache_key_deterministic():
    k1 = _cache_key("q", "s", {"a": 1})
    k2 = _cache_key("q", "s", {"a": 1})
    assert k1 == k2
    assert len(k1) == 32


def test_cache_key_differs_for_different_params():
    k1 = _cache_key("q", "arxiv", {"limit": 50})
    k2 = _cache_key("q", "arxiv", {"limit": 100})
    assert k1 != k2


def test_expired_entry_not_returned(db):
    results = [{"title": "Old"}]
    cache_put(db, "old_query", "arxiv", results)
    # Manually expire the entry
    conn = db.connect()
    try:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE search_cache SET expires_at = ? WHERE source = 'arxiv'",
            (past,),
        )
        conn.commit()
    finally:
        conn.close()
    assert cache_get(db, "old_query", "arxiv") is None


def test_stale_fallback(db):
    results = [{"title": "Stale"}]
    cache_put(db, "stale_query", "arxiv", results)
    # Expire it
    conn = db.connect()
    try:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE search_cache SET expires_at = ? WHERE source = 'arxiv'",
            (past,),
        )
        conn.commit()
    finally:
        conn.close()
    # Normal get returns None
    assert cache_get(db, "stale_query", "arxiv") is None
    # Stale fallback returns the entry
    got = cache_get(db, "stale_query", "arxiv", allow_stale=True)
    assert got is not None
    assert got[0]["title"] == "Stale"


def test_evict_expired(db):
    cache_put(db, "q1", "arxiv", [{"title": "A"}])
    cache_put(db, "q2", "arxiv", [{"title": "B"}])
    # Expire q1 only
    conn = db.connect()
    try:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE search_cache SET expires_at = ? WHERE query_hash = 'q1'",
            (past,),
        )
        conn.commit()
    finally:
        conn.close()
    removed = cache_evict_expired(db)
    assert removed == 1
    assert cache_get(db, "q1", "arxiv") is None
    assert cache_get(db, "q2", "arxiv") is not None


def test_cache_overwrite(db):
    cache_put(db, "q", "s2", [{"title": "V1"}])
    cache_put(db, "q", "s2", [{"title": "V2"}])
    got = cache_get(db, "q", "s2")
    assert got[0]["title"] == "V2"
