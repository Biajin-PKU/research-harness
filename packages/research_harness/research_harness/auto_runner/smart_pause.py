"""SmartPause — simplified 3-signal auto-pause for autonomous runs.

.. deprecated::
    Superseded by ``budget.py:BudgetMonitor`` which is wired into runner.py.
    This module is retained only for backward compatibility with test_evolution.py.

Monitors three signals:
1. Cumulative cost (USD)
2. Wall-clock time (seconds)
3. Consecutive failures

When any signal exceeds its threshold, returns a PauseDecision
(warn → pause escalation).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class PauseAction(str, Enum):
    CONTINUE = "continue"
    WARN = "warn"
    PAUSE = "pause"


@dataclass
class PauseThresholds:
    """Configurable thresholds for the three pause signals."""

    max_cost_usd: float = 5.0  # warn at this cost
    hard_cost_usd: float = 10.0  # pause at this cost
    max_wall_clock_sec: float = 3600.0  # warn at 1 hour
    hard_wall_clock_sec: float = 7200.0  # pause at 2 hours
    max_consecutive_failures: int = 3  # warn after 3 consecutive failures
    hard_consecutive_failures: int = 5  # pause after 5 consecutive failures


@dataclass
class PauseDecision:
    """Decision from SmartPause evaluation."""

    action: PauseAction
    reason: str = ""
    signals: dict[str, float] = field(default_factory=dict)


class SmartPause:
    """Three-signal pause controller for autonomous research runs."""

    def __init__(self, thresholds: PauseThresholds | None = None) -> None:
        self._thresholds = thresholds or PauseThresholds()
        self._start_time = time.monotonic()
        self._cumulative_cost = 0.0
        self._consecutive_failures = 0
        self._total_calls = 0

    def record_success(self, cost_usd: float = 0.0) -> None:
        """Record a successful operation."""
        self._cumulative_cost += cost_usd
        self._consecutive_failures = 0
        self._total_calls += 1

    def record_failure(self, cost_usd: float = 0.0) -> None:
        """Record a failed operation."""
        self._cumulative_cost += cost_usd
        self._consecutive_failures += 1
        self._total_calls += 1

    def evaluate(self) -> PauseDecision:
        """Evaluate all three signals and return a pause decision."""
        t = self._thresholds
        elapsed = time.monotonic() - self._start_time

        signals = {
            "cost_usd": self._cumulative_cost,
            "wall_clock_sec": elapsed,
            "consecutive_failures": float(self._consecutive_failures),
            "total_calls": float(self._total_calls),
        }

        # Check hard limits first (PAUSE)
        if self._cumulative_cost >= t.hard_cost_usd:
            return PauseDecision(
                action=PauseAction.PAUSE,
                reason=f"Cost ${self._cumulative_cost:.2f} exceeds hard limit ${t.hard_cost_usd:.2f}",
                signals=signals,
            )
        if elapsed >= t.hard_wall_clock_sec:
            return PauseDecision(
                action=PauseAction.PAUSE,
                reason=f"Wall-clock {elapsed:.0f}s exceeds hard limit {t.hard_wall_clock_sec:.0f}s",
                signals=signals,
            )
        if self._consecutive_failures >= t.hard_consecutive_failures:
            return PauseDecision(
                action=PauseAction.PAUSE,
                reason=f"{self._consecutive_failures} consecutive failures exceeds hard limit {t.hard_consecutive_failures}",
                signals=signals,
            )

        # Check soft limits (WARN)
        if self._cumulative_cost >= t.max_cost_usd:
            return PauseDecision(
                action=PauseAction.WARN,
                reason=f"Cost ${self._cumulative_cost:.2f} approaching limit ${t.hard_cost_usd:.2f}",
                signals=signals,
            )
        if elapsed >= t.max_wall_clock_sec:
            return PauseDecision(
                action=PauseAction.WARN,
                reason=f"Wall-clock {elapsed:.0f}s approaching limit {t.hard_wall_clock_sec:.0f}s",
                signals=signals,
            )
        if self._consecutive_failures >= t.max_consecutive_failures:
            return PauseDecision(
                action=PauseAction.WARN,
                reason=f"{self._consecutive_failures} consecutive failures — consider intervention",
                signals=signals,
            )

        return PauseDecision(action=PauseAction.CONTINUE, signals=signals)

    @property
    def cumulative_cost(self) -> float:
        return self._cumulative_cost

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def elapsed_sec(self) -> float:
        return time.monotonic() - self._start_time

    def reset(self) -> None:
        """Reset all counters."""
        self._start_time = time.monotonic()
        self._cumulative_cost = 0.0
        self._consecutive_failures = 0
        self._total_calls = 0
