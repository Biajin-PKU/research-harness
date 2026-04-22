"""Tests for V2 Self-Evolution Phase 4: Preference Learning (ELO + Beta-Bernoulli)."""

from __future__ import annotations


from research_harness.evolution.preference import (
    PreferenceLearner,
    SourceReliability,
)


def _seed_strategies(conn, stage: str = "section_draft", count: int = 3) -> list[int]:
    """Insert test strategies and return their IDs."""
    ids = []
    for i in range(count):
        cur = conn.execute(
            """INSERT INTO strategies
               (stage, strategy_key, title, content, scope, version,
                quality_score, status, elo_rating, beta_alpha, beta_beta)
               VALUES (?, ?, ?, ?, 'global', 1, 0.8, 'active', 1500.0, 1.0, 1.0)""",
            (stage, f"{stage}.theme_{i}", f"Strategy {i}", f"Content {i}"),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


class TestSourceReliability:
    def test_human_edit_highest(self):
        sr = SourceReliability()
        assert sr.weight("human_edit") == 1.0

    def test_gold_comparison(self):
        sr = SourceReliability()
        assert sr.weight("gold_comparison") == 0.9

    def test_self_review(self):
        sr = SourceReliability()
        assert sr.weight("self_review") == 0.7

    def test_auto_extracted(self):
        sr = SourceReliability()
        assert sr.weight("auto_extracted") == 0.5

    def test_unknown_source_returns_minimum(self):
        sr = SourceReliability()
        assert sr.weight("unknown_kind") == 0.3

    def test_ordering(self):
        sr = SourceReliability()
        assert (
            sr.weight("human_edit")
            > sr.weight("gold_comparison")
            > sr.weight("self_review")
            > sr.weight("auto_extracted")
            > sr.weight("unknown")
        )


class TestELOUpdate:
    def test_winner_gains_loser_loses(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn)
        conn.close()

        learner = PreferenceLearner(db)
        learner.update_elo(winner_id=ids[0], loser_id=ids[1])

        conn = db.connect()
        w = conn.execute(
            "SELECT elo_rating FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        loser = conn.execute(
            "SELECT elo_rating FROM strategies WHERE id = ?", (ids[1],)
        ).fetchone()
        conn.close()

        assert w["elo_rating"] > 1500.0
        assert loser["elo_rating"] < 1500.0

    def test_elo_is_zero_sum(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn)
        conn.close()

        learner = PreferenceLearner(db)
        learner.update_elo(winner_id=ids[0], loser_id=ids[1])

        conn = db.connect()
        w = conn.execute(
            "SELECT elo_rating FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        loser = conn.execute(
            "SELECT elo_rating FROM strategies WHERE id = ?", (ids[1],)
        ).fetchone()
        conn.close()

        assert abs((w["elo_rating"] + loser["elo_rating"]) - 3000.0) < 0.01

    def test_elo_with_custom_k(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn)
        conn.close()

        learner = PreferenceLearner(db)
        learner.update_elo(winner_id=ids[0], loser_id=ids[1], k=64)

        conn = db.connect()
        w = conn.execute(
            "SELECT elo_rating FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        conn.close()

        assert (
            w["elo_rating"] > 1500.0 + 16
        )  # k=64 means larger swing than default k=32

    def test_elo_with_source_weight(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn)
        conn.close()

        learner = PreferenceLearner(db)
        learner.update_elo(
            winner_id=ids[0], loser_id=ids[1], source_kind="auto_extracted"
        )

        conn = db.connect()
        w = conn.execute(
            "SELECT elo_rating FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        conn.close()

        gain_weighted = w["elo_rating"] - 1500.0

        # Reset
        conn = db.connect()
        conn.execute(
            "UPDATE strategies SET elo_rating = 1500.0 WHERE id IN (?, ?)",
            (ids[0], ids[1]),
        )
        conn.commit()
        conn.close()

        learner.update_elo(winner_id=ids[0], loser_id=ids[1], source_kind="human_edit")

        conn = db.connect()
        w2 = conn.execute(
            "SELECT elo_rating FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        conn.close()

        gain_full = w2["elo_rating"] - 1500.0

        assert gain_full > gain_weighted

    def test_upset_gives_larger_swing(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn)
        conn.execute(
            "UPDATE strategies SET elo_rating = 1700.0 WHERE id = ?", (ids[0],)
        )
        conn.execute(
            "UPDATE strategies SET elo_rating = 1300.0 WHERE id = ?", (ids[1],)
        )
        conn.commit()
        conn.close()

        learner = PreferenceLearner(db)
        # Underdog (1300) beats favorite (1700)
        learner.update_elo(winner_id=ids[1], loser_id=ids[0])

        conn = db.connect()
        underdog = conn.execute(
            "SELECT elo_rating FROM strategies WHERE id = ?", (ids[1],)
        ).fetchone()
        conn.close()

        # Underdog should gain more than 16 (the equal-rating gain)
        assert underdog["elo_rating"] - 1300.0 > 16.0


class TestBetaUpdate:
    def test_success_increases_alpha(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn)
        conn.close()

        learner = PreferenceLearner(db)
        learner.update_beta(strategy_id=ids[0], outcome=True)

        conn = db.connect()
        row = conn.execute(
            "SELECT beta_alpha, beta_beta FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        conn.close()

        assert row["beta_alpha"] > 1.0
        assert row["beta_beta"] == 1.0

    def test_failure_increases_beta(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn)
        conn.close()

        learner = PreferenceLearner(db)
        learner.update_beta(strategy_id=ids[0], outcome=False)

        conn = db.connect()
        row = conn.execute(
            "SELECT beta_alpha, beta_beta FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        conn.close()

        assert row["beta_alpha"] == 1.0
        assert row["beta_beta"] > 1.0

    def test_source_weight_scales_update(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn)
        conn.close()

        learner = PreferenceLearner(db)
        learner.update_beta(
            strategy_id=ids[0], outcome=True, source_kind="auto_extracted"
        )

        conn = db.connect()
        row = conn.execute(
            "SELECT beta_alpha FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        conn.close()

        alpha_auto = row["beta_alpha"]

        # Reset
        conn = db.connect()
        conn.execute("UPDATE strategies SET beta_alpha = 1.0 WHERE id = ?", (ids[0],))
        conn.commit()
        conn.close()

        learner.update_beta(strategy_id=ids[0], outcome=True, source_kind="human_edit")

        conn = db.connect()
        row2 = conn.execute(
            "SELECT beta_alpha FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        conn.close()

        alpha_human = row2["beta_alpha"]
        assert alpha_human > alpha_auto

    def test_posterior_mean_converges(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn)
        conn.close()

        learner = PreferenceLearner(db)
        # 8 successes, 2 failures → mean should approach 0.8
        for _ in range(8):
            learner.update_beta(strategy_id=ids[0], outcome=True)
        for _ in range(2):
            learner.update_beta(strategy_id=ids[0], outcome=False)

        conn = db.connect()
        row = conn.execute(
            "SELECT beta_alpha, beta_beta FROM strategies WHERE id = ?", (ids[0],)
        ).fetchone()
        conn.close()

        mean = row["beta_alpha"] / (row["beta_alpha"] + row["beta_beta"])
        assert 0.7 < mean < 0.85


class TestRankStrategies:
    def test_rank_by_combined_score(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn, count=3)
        # Set varied ratings
        conn.execute(
            "UPDATE strategies SET elo_rating = 1600.0, beta_alpha = 9.0, beta_beta = 1.0 WHERE id = ?",
            (ids[0],),
        )
        conn.execute(
            "UPDATE strategies SET elo_rating = 1400.0, beta_alpha = 1.0, beta_beta = 9.0 WHERE id = ?",
            (ids[1],),
        )
        conn.execute(
            "UPDATE strategies SET elo_rating = 1500.0, beta_alpha = 5.0, beta_beta = 5.0 WHERE id = ?",
            (ids[2],),
        )
        conn.commit()
        conn.close()

        learner = PreferenceLearner(db)
        ranked = learner.rank_strategies(stage="section_draft")

        assert len(ranked) == 3
        # Best strategy (high ELO + high beta mean) should be first
        assert ranked[0][0] == ids[0]
        # Worst (low ELO + low beta mean) should be last
        assert ranked[-1][0] == ids[1]

    def test_rank_empty_stage(self, db):
        learner = PreferenceLearner(db)
        ranked = learner.rank_strategies(stage="nonexistent_stage")
        assert ranked == []

    def test_rank_only_active(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn, count=2)
        conn.execute(
            "UPDATE strategies SET status = 'superseded' WHERE id = ?", (ids[1],)
        )
        conn.commit()
        conn.close()

        learner = PreferenceLearner(db)
        ranked = learner.rank_strategies(stage="section_draft")
        assert len(ranked) == 1
        assert ranked[0][0] == ids[0]

    def test_rank_returns_composite_score(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn, count=1)
        conn.execute(
            "UPDATE strategies SET elo_rating = 1600.0, beta_alpha = 8.0, beta_beta = 2.0 WHERE id = ?",
            (ids[0],),
        )
        conn.commit()
        conn.close()

        learner = PreferenceLearner(db)
        ranked = learner.rank_strategies(stage="section_draft")
        assert len(ranked) == 1
        sid, score = ranked[0]
        assert sid == ids[0]
        assert 0.0 < score < 10.0  # bounded composite


class TestInjectorELOFallback:
    def test_sort_by_elo_when_available(self, db):
        conn = db.connect()
        ids = _seed_strategies(conn, count=2)
        conn.execute(
            "UPDATE strategies SET elo_rating = 1600.0, quality_score = 0.5 WHERE id = ?",
            (ids[0],),
        )
        conn.execute(
            "UPDATE strategies SET elo_rating = 1400.0, quality_score = 0.9 WHERE id = ?",
            (ids[1],),
        )
        conn.commit()
        conn.close()

        from research_harness.evolution.injector import StrategyInjector

        injector = StrategyInjector(db)
        strategies = injector.get_active_strategies("section_draft")

        # With ELO sorting, ids[0] (ELO=1600) should come first despite lower quality_score
        assert strategies[0].id == ids[0]
