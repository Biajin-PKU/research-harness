"""Nudge manager — Hermes-inspired periodic prompts to extract strategies.

Every N tool calls, injects a nudge into the agent's context suggesting
it consider extracting strategies or reflecting on the session. Nudges
are passive — the agent can choose to act on them or ignore them.
"""

from __future__ import annotations

import logging
from typing import Any

from ..storage.db import Database
from .models import NudgeDecision

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 20

# Nudge type priorities (higher = more important)
_NUDGE_PRIORITY = {
    "reflection_prompt": "high",
    "strategy_extraction": "medium",
    "cost_awareness": "medium",
    "pattern_alert": "low",
}


class NudgeManager:
    """Checks whether to nudge the agent based on session activity."""

    def __init__(
        self,
        db: Database,
        session_id: str,
        interval: int = DEFAULT_INTERVAL,
    ) -> None:
        self._db = db
        self._session_id = session_id
        self._interval = interval
        self._call_count = 0
        self._last_nudge_at = 0  # call_count when last nudge was issued

    def tick(self) -> None:
        """Increment the tool call counter."""
        self._call_count += 1

    @property
    def call_count(self) -> int:
        return self._call_count

    def check_nudge(
        self,
        *,
        stage: str = "",
        cost_usd: float = 0.0,
        experiment_count: int = 0,
        reflection_interval: int = 3,
    ) -> NudgeDecision | None:
        """Check if a nudge should be issued. Returns None if not time yet."""
        calls_since_nudge = self._call_count - self._last_nudge_at
        if calls_since_nudge < self._interval:
            return None

        # Decide nudge type based on context
        nudge = self._pick_nudge(
            stage=stage,
            cost_usd=cost_usd,
            experiment_count=experiment_count,
            reflection_interval=reflection_interval,
        )
        if nudge is not None:
            self._last_nudge_at = self._call_count
            self._record_nudge(nudge, stage)
        return nudge

    def _pick_nudge(
        self,
        *,
        stage: str,
        cost_usd: float,
        experiment_count: int,
        reflection_interval: int,
    ) -> NudgeDecision | None:
        """Select the most appropriate nudge type."""
        # Priority 1: reflection prompt if enough experiments
        if experiment_count > 0 and experiment_count % reflection_interval == 0:
            return NudgeDecision(
                nudge_type="reflection_prompt",
                message=(
                    f"You've completed {experiment_count} experiments. "
                    "Consider running `meta_reflect` to analyze cross-experiment "
                    "patterns and decide whether to DEEPEN, BROADEN, PIVOT, or CONCLUDE."
                ),
                stage=stage,
                priority="high",
            )

        # Priority 2: cost awareness if spending is notable
        if cost_usd > 1.0:
            return NudgeDecision(
                nudge_type="cost_awareness",
                message=(
                    f"Session cost has reached ${cost_usd:.2f}. "
                    "Consider whether the current approach is cost-effective."
                ),
                stage=stage,
                priority="medium",
            )

        # Priority 3: strategy extraction
        return NudgeDecision(
            nudge_type="strategy_extraction",
            message=(
                f"You've made {self._call_count} tool calls in the '{stage}' stage. "
                "Consider running `strategy_distill` to capture what's working "
                "as a reusable strategy for future sessions."
            ),
            stage=stage,
            priority="medium",
        )

    def _record_nudge(self, nudge: NudgeDecision, stage: str) -> None:
        """Record nudge delivery to DB."""
        try:
            conn = self._db.connect()
            try:
                conn.execute(
                    """INSERT INTO nudge_log
                       (session_id, nudge_type, nudge_text, stage)
                       VALUES (?, ?, ?, ?)""",
                    (self._session_id, nudge.nudge_type, nudge.message, stage),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.debug("Failed to record nudge", exc_info=True)

    def record_acceptance(self, nudge_type: str) -> None:
        """Record that the agent acted on a nudge."""
        try:
            conn = self._db.connect()
            try:
                # Find the most recent unaccepted nudge of this type
                row = conn.execute(
                    """SELECT id FROM nudge_log
                       WHERE session_id = ? AND nudge_type = ? AND accepted = 0
                       ORDER BY id DESC LIMIT 1""",
                    (self._session_id, nudge_type),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE nudge_log SET accepted = 1 WHERE id = ?",
                        (row["id"],),
                    )
                    conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.debug("Failed to record nudge acceptance", exc_info=True)

    def format_nudge(self, nudge: NudgeDecision) -> str:
        """Format a nudge for inclusion in tool response metadata."""
        priority_marker = {"high": "!!", "medium": "!", "low": ""}.get(
            nudge.priority, ""
        )
        return f"[NUDGE{priority_marker}] {nudge.message}"

    def get_nudge_stats(self) -> dict[str, Any]:
        """Get nudge delivery/acceptance stats for the session."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT nudge_type,
                          COUNT(*) as delivered,
                          SUM(accepted) as accepted
                   FROM nudge_log
                   WHERE session_id = ?
                   GROUP BY nudge_type""",
                (self._session_id,),
            ).fetchall()
        except Exception:
            return {}
        finally:
            conn.close()

        return {
            r["nudge_type"]: {
                "delivered": r["delivered"],
                "accepted": r["accepted"] or 0,
            }
            for r in rows
        }
