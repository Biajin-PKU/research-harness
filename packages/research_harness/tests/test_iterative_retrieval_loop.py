"""Tests for iterative_retrieval_loop primitive.

These tests stub out query_refine, paper_search, and paper_ingest so the loop
can be driven deterministically without hitting the LLM or external providers.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from research_harness.execution import llm_primitives
from research_harness.primitives.types import (
    PaperIngestOutput,
    PaperRef,
    PaperSearchOutput,
    QueryCandidate,
    QueryRefineOutput,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_ref(arxiv_id: str = "", doi: str = "", title: str = "") -> PaperRef:
    return PaperRef(
        title=title or f"Paper {arxiv_id or doi or '?'}",
        arxiv_id=arxiv_id,
        doi=doi,
    )


def _insert_topic(db, name: str = "t1") -> int:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES (?)", (name,))
        tid = int(conn.execute("SELECT id FROM topics WHERE name = ?", (name,)).fetchone()["id"])
        conn.commit()
        return tid
    finally:
        conn.close()


def _insert_paper_into_pool(db, *, arxiv_id: str = "", doi: str = "", topic_id: int | None = None) -> int:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, arxiv_id, doi, s2_id) VALUES (?, ?, ?, NULL)",
            (f"Pool paper {arxiv_id or doi}", arxiv_id or None, doi or None),
        )
        paper_id = int(conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"])
        if topic_id is not None:
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, 'medium')",
                (paper_id, topic_id),
            )
        conn.commit()
        return paper_id
    finally:
        conn.close()


class _StubScript:
    """Simple scripted driver for query_refine + paper_search.

    Each entry in ``rounds`` is a list of (query, list_of_paper_refs) tuples.
    Round N returns the N-th entry; paper_search lookups hit the query→refs
    map inside that round.
    """

    def __init__(self, rounds: list[list[tuple[str, list[PaperRef]]]]):
        self.rounds = rounds
        self.round_idx = -1
        self.query_to_refs: dict[str, list[PaperRef]] = {}
        self.ingested: list[str] = []

    def next_round_candidates(self) -> list[QueryCandidate]:
        self.round_idx += 1
        if self.round_idx >= len(self.rounds):
            return []
        entries = self.rounds[self.round_idx]
        self.query_to_refs = {q: refs for q, refs in entries}
        return [
            QueryCandidate(query=q, rationale=f"round-{self.round_idx}", priority="high")
            for q, _ in entries
        ]


def _install_stubs(monkeypatch, script: _StubScript, topic_id: int, db):
    """Install monkeypatches for query_refine + paper_search + paper_ingest."""

    def _fake_query_refine(*, db, topic_id, max_candidates=8, _model=None, **_):
        return QueryRefineOutput(
            topic_id=topic_id,
            candidates=script.next_round_candidates(),
            model_used="stub-model",
        )

    def _fake_paper_search(*, db, query, **kwargs):
        papers = script.query_to_refs.get(query, [])
        return PaperSearchOutput(
            papers=list(papers),
            provider="stub",
            query_used=query,
            providers_queried=["stub"],
        )

    def _fake_paper_ingest(*, db, source, topic_id=None, **kwargs):
        script.ingested.append(source)
        # Actually insert into the real DB so subsequent rounds see the paper.
        # Use NULL for unused identifier columns to avoid UNIQUE collisions
        # on empty strings across multiple inserts.
        conn = db.connect()
        try:
            if "/" in source:  # doi-shaped
                conn.execute(
                    "INSERT INTO papers (title, arxiv_id, doi, s2_id) VALUES (?, NULL, ?, NULL)",
                    (f"Ingested {source}", source),
                )
            else:
                conn.execute(
                    "INSERT INTO papers (title, arxiv_id, doi, s2_id) VALUES (?, ?, NULL, NULL)",
                    (f"Ingested {source}", source),
                )
            paper_id = int(conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"])
            if topic_id is not None:
                conn.execute(
                    "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, 'medium')",
                    (paper_id, topic_id),
                )
            conn.commit()
        finally:
            conn.close()
        return PaperIngestOutput(
            paper_id=paper_id,
            title=f"Ingested {source}",
            status="inserted",
        )

    # llm_primitives.query_refine is called directly inside the loop
    monkeypatch.setattr(llm_primitives, "query_refine", _fake_query_refine)
    # paper_search and paper_ingest are lazily imported inside the loop impl
    monkeypatch.setattr(
        "research_harness.primitives.impls.paper_search",
        _fake_paper_search,
    )
    monkeypatch.setattr(
        "research_harness.primitives.impls.paper_ingest",
        _fake_paper_ingest,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_two_round_convergence(db, monkeypatch) -> None:
    """Round 1 finds new papers; round 2 hits mostly duplicates → converged."""
    topic_id = _insert_topic(db)

    # Round 1: two queries, each finds 3 fresh papers (overlap=0)
    round1 = [
        ("query alpha", [_mk_ref(arxiv_id="2301.0001"), _mk_ref(arxiv_id="2301.0002"), _mk_ref(arxiv_id="2301.0003")]),
        ("query beta",  [_mk_ref(arxiv_id="2301.0004"), _mk_ref(arxiv_id="2301.0005"), _mk_ref(arxiv_id="2301.0006")]),
    ]
    # Round 2: two NEW queries but the hits are mostly existing papers
    round2 = [
        ("query gamma", [
            _mk_ref(arxiv_id="2301.0001"),  # existing
            _mk_ref(arxiv_id="2301.0002"),  # existing
            _mk_ref(arxiv_id="2301.0003"),  # existing
            _mk_ref(arxiv_id="2301.0004"),  # existing
        ]),
        ("query delta", [
            _mk_ref(arxiv_id="2301.0005"),  # existing
            _mk_ref(arxiv_id="2301.0006"),  # existing
            _mk_ref(arxiv_id="2301.0099"),  # new (1 of 7 total = low ratio, but within floor)
        ]),
    ]
    # Round 3: same as round 2, nearly-all duplicates — second converged round
    round3 = [
        ("query epsilon", [
            _mk_ref(arxiv_id="2301.0001"),
            _mk_ref(arxiv_id="2301.0002"),
            _mk_ref(arxiv_id="2301.0003"),
        ]),
        ("query zeta", [
            _mk_ref(arxiv_id="2301.0004"),
            _mk_ref(arxiv_id="2301.0005"),
        ]),
    ]

    script = _StubScript([round1, round2, round3])
    _install_stubs(monkeypatch, script, topic_id, db)

    result = llm_primitives.iterative_retrieval_loop(
        db=db,
        topic_id=topic_id,
        max_rounds=5,
        convergence_threshold=0.8,
        window=2,
        new_paper_floor=5,
        queries_per_round=4,
    )

    assert result.rounds_run == 3
    assert result.convergence_reached is True
    assert result.stop_reason == "converged"
    # Round 1 adds 6 new, round 2 adds 1 new, round 3 adds 0
    assert result.total_new_papers == 7
    assert result.per_round_new_papers == [6, 1, 0]
    assert result.per_round_mean_overlap[0] == pytest.approx(0.0)
    assert result.per_round_mean_overlap[1] > 0.8
    assert result.per_round_mean_overlap[2] == pytest.approx(1.0)
    # Each query got persisted to search_query_registry
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT query, round_index, overlap_ratio FROM search_query_registry WHERE topic_id = ? ORDER BY round_index, query",
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 6


def test_query_exhaustion_stops_loop(db, monkeypatch) -> None:
    """When query_refine returns no fresh queries, loop stops."""
    topic_id = _insert_topic(db)
    script = _StubScript([
        [("q1", [_mk_ref(arxiv_id="2401.0001")])],
        [],  # round 2: nothing fresh
    ])
    _install_stubs(monkeypatch, script, topic_id, db)

    result = llm_primitives.iterative_retrieval_loop(
        db=db, topic_id=topic_id, max_rounds=5, queries_per_round=2,
    )
    assert result.stop_reason == "query_refine_exhausted"
    assert result.rounds_run == 1
    assert result.total_new_papers == 1


def test_dedup_on_identity_key(db, monkeypatch) -> None:
    """Same paper returned twice (once by arxiv, once by doi) counts once."""
    topic_id = _insert_topic(db)
    # Two PaperRefs with the same arxiv_id: should dedup to 1
    script = _StubScript([
        [("q1", [
            _mk_ref(arxiv_id="2501.0001"),
            _mk_ref(arxiv_id="2501.0001"),  # duplicate
            _mk_ref(arxiv_id="2501.0002"),
        ])],
    ])
    _install_stubs(monkeypatch, script, topic_id, db)

    result = llm_primitives.iterative_retrieval_loop(
        db=db, topic_id=topic_id, max_rounds=1, queries_per_round=2,
    )
    assert result.rounds_run == 1
    assert result.rounds[0].total_hits == 3
    assert result.rounds[0].dedup_hits == 2
    assert result.total_new_papers == 2


def test_papers_without_identity_are_dropped(db, monkeypatch) -> None:
    """PaperRefs with no arxiv_id/doi/s2_id are excluded from overlap check."""
    topic_id = _insert_topic(db)
    script = _StubScript([
        [("q1", [
            _mk_ref(arxiv_id="2501.0001"),
            _mk_ref(title="No identifier paper"),  # dropped
            _mk_ref(doi="10.1/xyz"),
        ])],
    ])
    _install_stubs(monkeypatch, script, topic_id, db)

    result = llm_primitives.iterative_retrieval_loop(
        db=db, topic_id=topic_id, max_rounds=1, queries_per_round=2,
    )
    assert result.rounds[0].total_hits == 3
    assert result.rounds[0].dedup_hits == 2  # dropped the identifier-less one


def test_empty_query_not_counted_in_overlap(db, monkeypatch) -> None:
    """A query that returns zero hits should not affect mean_overlap."""
    topic_id = _insert_topic(db)
    # Pre-populate pool with one paper so the real query has 100% overlap
    _insert_paper_into_pool(db, arxiv_id="2301.0100", topic_id=topic_id)

    script = _StubScript([
        [
            ("dead query", []),  # zero hits — must not make mean look 0%
            ("real query", [_mk_ref(arxiv_id="2301.0100")]),  # existing
        ],
    ])
    _install_stubs(monkeypatch, script, topic_id, db)

    result = llm_primitives.iterative_retrieval_loop(
        db=db, topic_id=topic_id, max_rounds=1, queries_per_round=2,
    )
    # real query overlap = 1.0 (1/1), dead query excluded → mean = 1.0
    assert result.per_round_mean_overlap[0] == pytest.approx(1.0)


def test_existing_papers_not_reingested(db, monkeypatch) -> None:
    """Papers already in the pool must not be re-ingested."""
    topic_id = _insert_topic(db)
    _insert_paper_into_pool(db, arxiv_id="2301.9999", topic_id=topic_id)

    script = _StubScript([
        [("q1", [
            _mk_ref(arxiv_id="2301.9999"),  # already in pool
            _mk_ref(arxiv_id="2301.0001"),  # new
        ])],
    ])
    _install_stubs(monkeypatch, script, topic_id, db)

    result = llm_primitives.iterative_retrieval_loop(
        db=db, topic_id=topic_id, max_rounds=1, queries_per_round=2,
    )
    assert result.rounds[0].existing_hits == 1
    assert result.rounds[0].new_papers_added == 1
    assert script.ingested == ["2301.0001"]


def test_known_queries_filtered(db, monkeypatch) -> None:
    """Queries already in search_query_registry must be skipped."""
    topic_id = _insert_topic(db)
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO search_query_registry (topic_id, query, source) VALUES (?, 'q1', 'manual')",
            (topic_id,),
        )
        conn.commit()
    finally:
        conn.close()

    script = _StubScript([
        [
            ("q1", [_mk_ref(arxiv_id="2301.0001")]),  # already known — skipped
            ("q2", [_mk_ref(arxiv_id="2301.0002")]),  # fresh
        ],
        [],  # stop after round 1
    ])
    _install_stubs(monkeypatch, script, topic_id, db)

    result = llm_primitives.iterative_retrieval_loop(
        db=db, topic_id=topic_id, max_rounds=3, queries_per_round=4,
    )
    # Only q2 actually ran
    assert result.total_new_papers == 1
    assert len(result.rounds) == 1
    assert result.rounds[0].query == "q2"


def test_cost_budget_stops_loop(db, monkeypatch) -> None:
    """If budget_per_new_paper_usd is exceeded, loop stops with cost_budget_exceeded."""
    topic_id = _insert_topic(db)
    script = _StubScript([
        [("q1", [_mk_ref(arxiv_id="2301.0001")])],
        [("q2", [_mk_ref(arxiv_id="2301.0002")])],
    ])
    _install_stubs(monkeypatch, script, topic_id, db)

    # Force the token accumulator to reflect a huge cost before each round so
    # cost_per_new_paper will trigger
    original_accumulated = llm_primitives._accumulated_tokens

    def _fake_accum():
        return (100_000_000, 50_000_000)  # ~$50 + $75 = $125

    monkeypatch.setattr(llm_primitives, "_accumulated_tokens", _fake_accum)

    result = llm_primitives.iterative_retrieval_loop(
        db=db,
        topic_id=topic_id,
        max_rounds=5,
        queries_per_round=2,
        budget_per_new_paper_usd=0.01,
    )
    assert result.stop_reason == "cost_budget_exceeded"
