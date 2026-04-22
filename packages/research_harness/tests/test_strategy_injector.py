"""Tests for StrategyInjector (Sprint 2 — strategy injection)."""

from __future__ import annotations


from research_harness.evolution.injector import StrategyInjector


def _insert_strategy(
    db,
    *,
    stage="build",
    key="build.test",
    title="Test Strategy",
    content="Do X then Y",
    scope="global",
    topic_id=None,
    version=1,
    quality_score=0.85,
    status="active",
):
    """Insert a test strategy directly into DB."""
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO strategies
               (stage, strategy_key, title, content, scope, topic_id, version,
                quality_score, gate_model, source_lesson_ids, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                stage,
                key,
                title,
                content,
                scope,
                topic_id,
                version,
                quality_score,
                "test-model",
                "[]",
                status,
            ),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    finally:
        conn.close()


class TestStrategyInjector:
    def test_empty_overlay(self, db):
        injector = StrategyInjector(db)
        overlay = injector.build_strategy_overlay("build")
        assert overlay == ""

    def test_single_strategy_overlay(self, db):
        _insert_strategy(db, content="## Steps\n1. Use CrossRef first")
        injector = StrategyInjector(db)
        overlay = injector.build_strategy_overlay("build")
        assert "Research Strategies" in overlay
        assert "Test Strategy" in overlay
        assert "Use CrossRef first" in overlay

    def test_max_strategies_limit(self, db):
        for i in range(5):
            _insert_strategy(
                db,
                key=f"build.strat_{i}",
                title=f"Strategy {i}",
                quality_score=0.9 - i * 0.1,
            )
        injector = StrategyInjector(db)
        strategies = injector.get_active_strategies("build", max_strategies=3)
        assert len(strategies) == 3
        # Should be ordered by quality_score desc
        assert strategies[0].quality_score >= strategies[1].quality_score

    def test_global_and_topic_strategies(self, db):
        _insert_strategy(db, key="build.global", title="Global", scope="global")
        _insert_strategy(
            db, key="build.topic1", title="Topic 1", scope="topic", topic_id=1
        )
        _insert_strategy(
            db, key="build.topic2", title="Topic 2", scope="topic", topic_id=2
        )

        injector = StrategyInjector(db)

        # Without topic_id: only global
        strategies = injector.get_active_strategies("build")
        assert len(strategies) == 1
        assert strategies[0].title == "Global"

        # With topic_id=1: global + topic 1
        strategies = injector.get_active_strategies("build", topic_id=1)
        titles = {s.title for s in strategies}
        assert "Global" in titles
        assert "Topic 1" in titles
        assert "Topic 2" not in titles

    def test_draft_strategies_excluded(self, db):
        _insert_strategy(db, key="build.active", title="Active", status="active")
        _insert_strategy(db, key="build.draft", title="Draft", status="draft")

        injector = StrategyInjector(db)
        strategies = injector.get_active_strategies("build")
        assert len(strategies) == 1
        assert strategies[0].title == "Active"

    def test_superseded_strategies_excluded(self, db):
        _insert_strategy(db, key="build.v1", title="V1", version=1, status="superseded")
        _insert_strategy(db, key="build.v1", title="V2", version=2, status="active")

        injector = StrategyInjector(db)
        strategies = injector.get_active_strategies("build")
        assert len(strategies) == 1
        assert strategies[0].title == "V2"

    def test_get_all_strategy_overlays(self, db):
        _insert_strategy(db, stage="build", key="build.test", title="Build Strat")
        _insert_strategy(db, stage="analyze", key="analyze.test", title="Analyze Strat")

        injector = StrategyInjector(db)
        overlays = injector.get_all_strategy_overlays()
        assert "build" in overlays
        assert "analyze" in overlays
        assert "Build Strat" in overlays["build"]
        assert "Analyze Strat" in overlays["analyze"]

    def test_record_injection(self, db):
        sid = _insert_strategy(db)
        injector = StrategyInjector(db)
        injector.record_injection(sid)
        injector.record_injection(sid)

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT injection_count FROM strategies WHERE id = ?", (sid,)
            ).fetchone()
            assert row["injection_count"] == 2
        finally:
            conn.close()

    def test_record_positive_feedback(self, db):
        sid = _insert_strategy(db)
        injector = StrategyInjector(db)
        injector.record_positive_feedback(sid)

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT positive_feedback FROM strategies WHERE id = ?", (sid,)
            ).fetchone()
            assert row["positive_feedback"] == 1
        finally:
            conn.close()

    def test_overlay_shows_scope_tag(self, db):
        _insert_strategy(
            db, key="build.topic_strat", title="Topic Strat", scope="topic", topic_id=1
        )

        injector = StrategyInjector(db)
        overlay = injector.build_strategy_overlay("build", topic_id=1)
        assert "[topic]" in overlay

    def test_stage_isolation(self, db):
        _insert_strategy(db, stage="build", key="build.s", title="Build Only")
        _insert_strategy(db, stage="analyze", key="analyze.s", title="Analyze Only")

        injector = StrategyInjector(db)
        overlay = injector.build_strategy_overlay("build")
        assert "Build Only" in overlay
        assert "Analyze Only" not in overlay
