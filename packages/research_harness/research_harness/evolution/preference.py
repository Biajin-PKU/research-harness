"""V2 Self-Evolution Phase 4: Preference Learning (ELO + Beta-Bernoulli).

Online quality estimation for strategies using two complementary signals:
- **ELO**: pairwise ranking from A/B comparisons (which strategy produced better output)
- **Beta-Bernoulli**: posterior success probability from binary outcomes

Both are weighted by source reliability (human_edit > gold_comparison > self_review > auto_extracted).
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_WEIGHTS: dict[str, float] = {
    "human_edit": 1.0,
    "gold_comparison": 0.9,
    "self_review": 0.7,
    "auto_extracted": 0.5,
}

DEFAULT_SOURCE_WEIGHT = 0.3


class SourceReliability:
    """Per-source_kind weighting for preference updates."""

    def weight(self, source_kind: str) -> float:
        return SOURCE_WEIGHTS.get(source_kind, DEFAULT_SOURCE_WEIGHT)


class PreferenceLearner:
    """Online preference learning for strategy quality."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self._reliability = SourceReliability()

    def update_elo(
        self,
        winner_id: int,
        loser_id: int,
        *,
        k: float = 32.0,
        source_kind: str = "human_edit",
    ) -> None:
        """Standard ELO update weighted by source reliability."""
        weight = self._reliability.weight(source_kind)
        effective_k = k * weight

        conn = self._db.connect()
        try:
            w_row = conn.execute(
                "SELECT elo_rating FROM strategies WHERE id = ?", (winner_id,)
            ).fetchone()
            l_row = conn.execute(
                "SELECT elo_rating FROM strategies WHERE id = ?", (loser_id,)
            ).fetchone()
            if not w_row or not l_row:
                return

            r_w = w_row["elo_rating"] or 1500.0
            r_l = l_row["elo_rating"] or 1500.0

            e_w = 1.0 / (1.0 + math.pow(10, (r_l - r_w) / 400.0))
            e_l = 1.0 - e_w

            new_w = r_w + effective_k * (1.0 - e_w)
            new_l = r_l + effective_k * (0.0 - e_l)

            conn.execute(
                "UPDATE strategies SET elo_rating = ? WHERE id = ?", (new_w, winner_id)
            )
            conn.execute(
                "UPDATE strategies SET elo_rating = ? WHERE id = ?", (new_l, loser_id)
            )
            conn.commit()
        finally:
            conn.close()

    def update_beta(
        self,
        strategy_id: int,
        outcome: bool,
        *,
        source_kind: str = "human_edit",
    ) -> None:
        """Beta-Bernoulli posterior update weighted by source reliability."""
        weight = self._reliability.weight(source_kind)

        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT beta_alpha, beta_beta FROM strategies WHERE id = ?",
                (strategy_id,),
            ).fetchone()
            if not row:
                return

            alpha = row["beta_alpha"] or 1.0
            beta = row["beta_beta"] or 1.0

            if outcome:
                alpha += weight
            else:
                beta += weight

            conn.execute(
                "UPDATE strategies SET beta_alpha = ?, beta_beta = ? WHERE id = ?",
                (alpha, beta, strategy_id),
            )
            conn.commit()
        finally:
            conn.close()

    def rank_strategies(
        self,
        stage: str,
        *,
        topic_id: int | None = None,
        elo_weight: float = 0.6,
        beta_weight: float = 0.4,
    ) -> list[tuple[int, float]]:
        """Rank active strategies by composite ELO + Beta score.

        Returns list of (strategy_id, composite_score) sorted descending.
        """
        conn = self._db.connect()
        try:
            if topic_id is not None:
                rows = conn.execute(
                    """SELECT id, elo_rating, beta_alpha, beta_beta FROM strategies
                       WHERE stage = ? AND status = 'active'
                         AND (scope = 'global' OR (scope = 'topic' AND topic_id = ?))""",
                    (stage, topic_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, elo_rating, beta_alpha, beta_beta FROM strategies
                       WHERE stage = ? AND status = 'active'""",
                    (stage,),
                ).fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        scored: list[tuple[int, float]] = []
        for row in rows:
            elo = (row["elo_rating"] or 1500.0) / 1500.0
            alpha = row["beta_alpha"] or 1.0
            beta = row["beta_beta"] or 1.0
            beta_mean = alpha / (alpha + beta)

            composite = elo_weight * elo + beta_weight * beta_mean
            scored.append((row["id"], round(composite, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
