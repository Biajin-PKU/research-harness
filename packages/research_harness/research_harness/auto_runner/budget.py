"""Budget monitoring for autonomous execution.

Tracks cumulative cost, tool calls, wall time, and paper count.
Auto-pauses at configurable thresholds.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BudgetState:
    """Current budget consumption."""

    total_cost_usd: float = 0.0
    total_tool_calls: int = 0
    total_papers: int = 0
    total_iterations: int = 0
    start_time: float = field(default_factory=time.monotonic)

    @property
    def elapsed_min(self) -> float:
        return (time.monotonic() - self.start_time) / 60.0


@dataclass(frozen=True)
class BudgetLimits:
    """Configurable budget limits."""

    max_cost_usd: float = 50.0
    max_wall_time_min: int = 480
    max_tool_calls: int = 500
    max_papers: int = 100
    max_iterations: int = 20
    warning_threshold: float = 0.8  # Warn at 80%

    @classmethod
    def from_policy_json(cls, policy_json: str) -> "BudgetLimits":
        """Create from RunPolicy JSON stored in orchestrator_runs."""
        import json

        try:
            data = json.loads(policy_json) if policy_json else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        return cls(
            max_cost_usd=float(data.get("max_cost_usd", 50.0)),
            max_wall_time_min=int(data.get("max_wall_time_min", 480)),
            max_tool_calls=int(data.get("max_tool_calls", 500)),
            max_papers=int(data.get("max_papers", 100)),
            max_iterations=int(data.get("max_iterations", 20)),
        )


class BudgetMonitor:
    """Monitors budget consumption and enforces limits."""

    def __init__(self, limits: BudgetLimits | None = None):
        self._limits = limits or BudgetLimits()
        self._state = BudgetState()
        self._warnings_issued: set[str] = set()
        self._cumulative_elapsed_min: float = 0.0

    @property
    def state(self) -> BudgetState:
        return self._state

    @property
    def limits(self) -> BudgetLimits:
        return self._limits

    def record_cost(self, cost_usd: float) -> None:
        self._state.total_cost_usd += cost_usd

    def record_tool_call(self) -> None:
        self._state.total_tool_calls += 1

    def record_paper(self) -> None:
        self._state.total_papers += 1

    def record_iteration(self) -> None:
        self._state.total_iterations += 1

    def sync_from_provenance(self, db: Any, topic_id: int | None = None) -> None:
        """Sync budget state from provenance records in the database.

        Reads actual cost and call counts from the provenance table
        to keep the budget monitor in sync with reality.
        """
        try:
            conn = db.connect()
            try:
                where = "WHERE topic_id = ?" if topic_id else ""
                params: tuple = (topic_id,) if topic_id else ()

                row = conn.execute(
                    f"""SELECT COALESCE(SUM(cost_usd), 0) as total_cost,
                               COUNT(*) as total_calls
                        FROM provenance_records {where}""",
                    params,
                ).fetchone()

                if row:
                    self._state.total_cost_usd = float(row["total_cost"])
                    self._state.total_tool_calls = int(row["total_calls"])

                if topic_id:
                    paper_row = conn.execute(
                        """SELECT COUNT(DISTINCT paper_id) as cnt
                           FROM paper_topics WHERE topic_id = ?""",
                        (topic_id,),
                    ).fetchone()
                    if paper_row:
                        self._state.total_papers = int(paper_row["cnt"])
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Failed to sync budget from provenance: %s", exc)

    def check(self) -> BudgetCheckResult:
        """Check all budget dimensions. Returns result with action."""
        total_elapsed = self._cumulative_elapsed_min + self._state.elapsed_min
        checks: list[DimensionCheck] = [
            self._check_dimension(
                "cost", self._state.total_cost_usd, self._limits.max_cost_usd, "USD"
            ),
            self._check_dimension(
                "wall_time", total_elapsed, self._limits.max_wall_time_min, "min"
            ),
            self._check_dimension(
                "tool_calls",
                self._state.total_tool_calls,
                self._limits.max_tool_calls,
                "calls",
            ),
            self._check_dimension(
                "papers", self._state.total_papers, self._limits.max_papers, "papers"
            ),
            self._check_dimension(
                "iterations",
                self._state.total_iterations,
                self._limits.max_iterations,
                "iters",
            ),
        ]

        # Determine overall action
        if any(c.action == "halt" for c in checks):
            halted = [c for c in checks if c.action == "halt"]
            return BudgetCheckResult(
                action="halt",
                checks=checks,
                message=f"Budget exhausted: {', '.join(c.dimension for c in halted)}",
            )

        warnings = [c for c in checks if c.action == "warn"]
        new_warnings = [c for c in warnings if c.dimension not in self._warnings_issued]
        if new_warnings:
            for w in new_warnings:
                self._warnings_issued.add(w.dimension)
                logger.warning(
                    "Budget warning: %s at %.0f%%", w.dimension, w.usage_pct * 100
                )
            return BudgetCheckResult(
                action="warn",
                checks=checks,
                message=f"Budget warning: {', '.join(c.dimension for c in new_warnings)}",
            )

        return BudgetCheckResult(action="ok", checks=checks, message="")

    def _check_dimension(
        self, dimension: str, current: float, limit: float, unit: str
    ) -> "DimensionCheck":
        if limit <= 0:
            return DimensionCheck(
                dimension=dimension,
                current=current,
                limit=limit,
                usage_pct=0.0,
                action="ok",
                unit=unit,
            )
        pct = current / limit
        if pct >= 1.0:
            action = "halt"
        elif pct >= self._limits.warning_threshold:
            action = "warn"
        else:
            action = "ok"
        return DimensionCheck(
            dimension=dimension,
            current=current,
            limit=limit,
            usage_pct=pct,
            action=action,
            unit=unit,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for checkpoint storage."""
        return {
            "total_cost_usd": self._state.total_cost_usd,
            "total_tool_calls": self._state.total_tool_calls,
            "total_papers": self._state.total_papers,
            "total_iterations": self._state.total_iterations,
            "elapsed_min": round(self._state.elapsed_min, 1),
            "cumulative_elapsed_min": round(
                self._cumulative_elapsed_min + self._state.elapsed_min, 1
            ),
        }

    @classmethod
    def from_checkpoint(
        cls, data: dict[str, Any], limits: BudgetLimits | None = None
    ) -> "BudgetMonitor":
        """Restore from checkpoint data."""
        monitor = cls(limits=limits)
        monitor._state.total_cost_usd = data.get("total_cost_usd", 0.0)
        monitor._state.total_tool_calls = data.get("total_tool_calls", 0)
        monitor._state.total_papers = data.get("total_papers", 0)
        monitor._state.total_iterations = data.get("total_iterations", 0)
        monitor._cumulative_elapsed_min = data.get("cumulative_elapsed_min", 0.0)
        return monitor


@dataclass(frozen=True)
class DimensionCheck:
    dimension: str
    current: float
    limit: float
    usage_pct: float
    action: str  # ok|warn|halt
    unit: str = ""


@dataclass(frozen=True)
class BudgetCheckResult:
    action: str  # ok|warn|halt
    checks: list[DimensionCheck] = field(default_factory=list)
    message: str = ""
