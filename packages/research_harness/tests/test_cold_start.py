"""Tests for V2 Cold Start: gold-standard paper comparison for bootstrap."""

from __future__ import annotations


from research_harness.evolution.cold_start import (
    ColdStartRunner,
    TemporalRelevance,
)
from research_harness.evolution.gold_selector import GoldSelector


def _seed_papers(conn, topic_id: int = 1) -> list[int]:
    """Insert test papers with varying quality signals."""
    conn.execute(
        "INSERT OR IGNORE INTO topics (id, name, description) VALUES (?, ?, ?)",
        (topic_id, "test-topic", "test"),
    )
    papers = [
        ("Gold Paper A", "NeurIPS", 2024, 150, "2401.00001", "full_text"),
        ("Gold Paper B", "ICML", 2023, 200, "2301.00002", "full_text"),
        ("Recent Preprint", "arXiv", 2025, 5, "2501.00003", "meta_only"),
        ("Old Classic", "KDD", 2018, 500, "1801.00004", "full_text"),
        ("Low Cite Paper", "Workshop", 2024, 2, "2401.00005", "full_text"),
    ]
    paper_ids = []
    for i, (title, venue, year, cites, arxiv, status) in enumerate(papers):
        cur = conn.execute(
            """INSERT INTO papers (title, authors, venue, year, citation_count, arxiv_id, s2_id, doi, status, pdf_path, pdf_hash)
               VALUES (?, '[]', ?, ?, ?, ?, NULL, NULL, ?, '', '')""",
            (title, venue, year, cites, arxiv, status),
        )
        paper_ids.append(cur.lastrowid)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, 'high')",
            (cur.lastrowid, topic_id),
        )
    conn.commit()
    return paper_ids


class TestTemporalRelevance:
    def test_fresh_is_high(self):
        tr = TemporalRelevance()
        score = tr.score(age_months=3, field="llm_systems")
        assert score > 0.8

    def test_old_is_low(self):
        tr = TemporalRelevance()
        score = tr.score(age_months=60, field="llm_systems")
        assert score < 0.2

    def test_field_specific_decay(self):
        tr = TemporalRelevance()
        llm = tr.score(age_months=24, field="llm_systems")
        se = tr.score(age_months=24, field="software_engineering")
        assert llm < se

    def test_venue_recency_boost(self):
        tr = TemporalRelevance()
        base = tr.score(age_months=12, field="default")
        boosted = tr.score(age_months=12, field="default", venue_tier="ccf_a")
        assert boosted >= base

    def test_citation_velocity(self):
        tr = TemporalRelevance()
        low = tr.score(age_months=24, field="default", citations=10)
        high = tr.score(age_months=24, field="default", citations=200)
        assert high >= low


class TestGoldSelector:
    def test_selects_high_quality_papers(self, db):
        conn = db.connect()
        _paper_ids = _seed_papers(conn)
        conn.close()

        selector = GoldSelector(db)
        gold = selector.select(topic_id=1, max_papers=2)
        titles = [g["title"] for g in gold]
        assert len(gold) <= 2
        # Should prefer high-cite, recent, top-venue papers
        assert "Gold Paper A" in titles or "Gold Paper B" in titles

    def test_excludes_meta_only(self, db):
        conn = db.connect()
        _seed_papers(conn)
        conn.close()

        selector = GoldSelector(db)
        gold = selector.select(topic_id=1, max_papers=5)
        titles = [g["title"] for g in gold]
        assert "Recent Preprint" not in titles

    def test_excludes_old_papers(self, db):
        conn = db.connect()
        _seed_papers(conn)
        conn.close()

        selector = GoldSelector(db)
        gold = selector.select(topic_id=1, max_papers=5, max_age_years=3)
        titles = [g["title"] for g in gold]
        assert "Old Classic" not in titles

    def test_empty_pool_returns_empty(self, db):
        selector = GoldSelector(db)
        gold = selector.select(topic_id=999)
        assert gold == []


class TestColdStartRunner:
    def test_bootstrap_generates_experiences(self, db):
        conn = db.connect()
        _paper_ids = _seed_papers(conn)
        conn.close()

        runner = ColdStartRunner(db)
        report = runner.bootstrap(topic_id=1, max_papers=1, dry_run=True)
        assert report["papers_evaluated"] >= 0

    def test_run_comparison_produces_records(self, db):
        conn = db.connect()
        paper_ids = _seed_papers(conn)
        conn.close()

        runner = ColdStartRunner(db)
        records = runner.run_comparison(
            paper_id=paper_ids[0],
            section="method",
            gold_text="The gold standard method uses advanced technique A.",
            topic_id=1,
        )
        assert isinstance(records, list)
        assert len(records) == 1
        for rec in records:
            assert rec.source_kind == "gold_comparison"
