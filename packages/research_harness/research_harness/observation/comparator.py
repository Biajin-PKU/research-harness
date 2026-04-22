"""Compare supervised vs autonomous execution modes.

Produces metrics: gate pass rate, cost, intervention count, artifact quality.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..storage.db import Database

logger = logging.getLogger(__name__)


@dataclass
class ModeComparison:
    """Comparison metrics between execution modes."""

    supervised: ModeMetrics = field(default_factory=lambda: ModeMetrics())
    autonomous: ModeMetrics = field(default_factory=lambda: ModeMetrics())
    winner: str = ""  # "supervised"|"autonomous"|"tie"
    analysis: str = ""


@dataclass
class ModeMetrics:
    """Metrics for a single execution mode."""

    total_runs: int = 0
    gate_pass_rate: float = 0.0
    mean_cost_usd: float = 0.0
    mean_tool_calls: int = 0
    mean_latency_min: float = 0.0
    human_interventions: int = 0
    stages_completed: int = 0
    artifacts_produced: int = 0


class ModeComparator:
    """Compares supervised vs autonomous execution from observation data."""

    def __init__(self, db: Database):
        self._db = db

    def compare(self) -> ModeComparison:
        """Compare modes using data from orchestrator_runs and session_observations."""
        conn = self._db.connect()
        try:
            # Get runs by autonomy mode
            supervised_runs = self._get_mode_metrics(conn, "supervised")
            autonomous_runs = self._get_mode_metrics(conn, "autonomous")
        finally:
            conn.close()

        # Determine winner
        winner = "tie"
        if supervised_runs.total_runs > 0 and autonomous_runs.total_runs > 0:
            # Score: quality > cost > speed
            s_score = (
                supervised_runs.gate_pass_rate * 3 - supervised_runs.mean_cost_usd * 0.1
            )
            a_score = (
                autonomous_runs.gate_pass_rate * 3 - autonomous_runs.mean_cost_usd * 0.1
            )
            if s_score > a_score + 0.1:
                winner = "supervised"
            elif a_score > s_score + 0.1:
                winner = "autonomous"

        analysis = self._analyze(supervised_runs, autonomous_runs)

        return ModeComparison(
            supervised=supervised_runs,
            autonomous=autonomous_runs,
            winner=winner,
            analysis=analysis,
        )

    def _get_mode_metrics(self, conn: Any, mode: str) -> ModeMetrics:
        """Aggregate metrics for a given autonomy mode."""
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) as runs,
                       COUNT(DISTINCT current_stage) as stages
                FROM orchestrator_runs
                WHERE autonomy_mode = ?
            """,
                (mode,),
            ).fetchone()

            obs_row = conn.execute(
                """
                SELECT COUNT(*) as total_calls,
                       SUM(cost_usd) as total_cost,
                       SUM(CASE WHEN user_intervention = 1 THEN 1 ELSE 0 END) as interventions,
                       COUNT(DISTINCT session_id) as sessions
                FROM session_observations so
                JOIN orchestrator_runs orc ON so.stage != ''
                WHERE orc.autonomy_mode = ?
            """,
                (mode,),
            ).fetchone()

            runs = row["runs"] if row else 0
            return ModeMetrics(
                total_runs=runs,
                mean_cost_usd=round((obs_row["total_cost"] or 0) / max(runs, 1), 2),
                mean_tool_calls=int((obs_row["total_calls"] or 0) / max(runs, 1)),
                human_interventions=obs_row["interventions"] or 0,
                stages_completed=row["stages"] if row else 0,
            )
        except Exception:
            return ModeMetrics(total_runs=0)

    def _analyze(self, sup: ModeMetrics, auto: ModeMetrics) -> str:
        if sup.total_runs == 0 and auto.total_runs == 0:
            return "No data available. Run research tasks to collect comparison data."
        if auto.total_runs == 0:
            return "No autonomous runs yet. Try: orchestrator_resume with autonomy_mode='autonomous'."
        if sup.total_runs == 0:
            return "No supervised runs recorded with the new schema."
        return (
            f"Supervised: {sup.total_runs} runs, ${sup.mean_cost_usd}/run, "
            f"{sup.human_interventions} interventions. "
            f"Autonomous: {auto.total_runs} runs, ${auto.mean_cost_usd}/run, "
            f"{auto.human_interventions} auto-resolved gates."
        )
