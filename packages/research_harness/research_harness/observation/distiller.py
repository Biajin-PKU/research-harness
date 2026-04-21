"""Offline distillation of observation data into skill/policy improvements.

Implements the SkillClaw Summarize -> Aggregate -> Execute pattern,
adapted for MCP-native observation data instead of API proxy transcripts.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..storage.db import Database

logger = logging.getLogger(__name__)


@dataclass
class ToolPattern:
    """A frequently observed tool usage pattern."""

    tools: tuple[str, ...]
    frequency: int = 0
    avg_success_rate: float = 1.0
    avg_cost_usd: float = 0.0
    stages: list[str] = field(default_factory=list)


@dataclass
class DistillationReport:
    """Output of a distillation run."""

    total_sessions: int = 0
    total_observations: int = 0
    top_patterns: list[ToolPattern] = field(default_factory=list)
    failure_hotspots: list[dict[str, Any]] = field(default_factory=list)
    improvement_candidates: list[dict[str, Any]] = field(default_factory=list)
    user_intervention_points: list[dict[str, Any]] = field(default_factory=list)


class ObservationDistiller:
    """Distills observation data into actionable improvements.

    Three-phase pipeline (from SkillClaw):
    1. Summarize: aggregate per-session statistics
    2. Aggregate: find cross-session patterns
    3. Execute: generate improvement candidates
    """

    def __init__(self, db: Database):
        self._db = db

    def distill(self, min_sessions: int = 3) -> DistillationReport:
        """Run the full distillation pipeline."""
        # Phase 1: Summarize sessions
        sessions = self._summarize_sessions()
        if len(sessions) < min_sessions:
            logger.info("Not enough sessions for distillation (%d < %d)", len(sessions), min_sessions)
            return DistillationReport(total_sessions=len(sessions))

        # Phase 2: Aggregate patterns
        patterns = self._aggregate_patterns(sessions)
        failures = self._find_failure_hotspots(sessions)
        interventions = self._find_intervention_points(sessions)

        # Phase 3: Generate improvement candidates
        candidates = self._generate_candidates(patterns, failures, interventions)

        total_obs = sum(s.get("total_tools", 0) for s in sessions)
        return DistillationReport(
            total_sessions=len(sessions),
            total_observations=total_obs,
            top_patterns=patterns[:10],
            failure_hotspots=failures[:10],
            improvement_candidates=candidates[:10],
            user_intervention_points=interventions[:10],
        )

    def _summarize_sessions(self) -> list[dict[str, Any]]:
        """Phase 1: Per-session summaries."""
        conn = self._db.connect()
        try:
            rows = conn.execute("""
                SELECT session_id,
                       COUNT(*) as total,
                       SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                       SUM(cost_usd) as total_cost,
                       GROUP_CONCAT(tool_name, ',') as tool_seq,
                       GROUP_CONCAT(DISTINCT stage) as stages
                FROM session_observations
                GROUP BY session_id
                HAVING total >= 3
                ORDER BY MIN(id)
            """).fetchall()
        except Exception:
            return []
        finally:
            conn.close()

        return [
            {
                "session_id": r["session_id"],
                "total_tools": r["total"],
                "success_rate": r["successes"] / r["total"] if r["total"] else 1.0,
                "total_cost": r["total_cost"] or 0.0,
                "tool_sequence": (r["tool_seq"] or "").split(","),
                "stages": (r["stages"] or "").split(","),
            }
            for r in rows
        ]

    def _aggregate_patterns(self, sessions: list[dict[str, Any]]) -> list[ToolPattern]:
        """Phase 2: Find common tool sequence patterns (bigrams and trigrams)."""
        bigram_counter: Counter[tuple[str, str]] = Counter()
        trigram_counter: Counter[tuple[str, str, str]] = Counter()

        for session in sessions:
            tools = session["tool_sequence"]
            for i in range(len(tools) - 1):
                bigram_counter[(tools[i], tools[i + 1])] += 1
            for i in range(len(tools) - 2):
                trigram_counter[(tools[i], tools[i + 1], tools[i + 2])] += 1

        patterns: list[ToolPattern] = []
        for tools, freq in bigram_counter.most_common(20):
            if freq >= 2:
                patterns.append(ToolPattern(tools=tools, frequency=freq))
        for tools, freq in trigram_counter.most_common(10):
            if freq >= 2:
                patterns.append(ToolPattern(tools=tools, frequency=freq))

        patterns.sort(key=lambda p: p.frequency, reverse=True)
        return patterns

    def _find_failure_hotspots(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Find tools that fail most frequently."""
        conn = self._db.connect()
        try:
            rows = conn.execute("""
                SELECT tool_name, COUNT(*) as total,
                       SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failures
                FROM session_observations
                GROUP BY tool_name
                HAVING failures > 0
                ORDER BY failures DESC
                LIMIT 20
            """).fetchall()
        except Exception:
            return []
        finally:
            conn.close()

        return [
            {
                "tool": r["tool_name"],
                "total_calls": r["total"],
                "failures": r["failures"],
                "failure_rate": r["failures"] / r["total"] if r["total"] else 0,
            }
            for r in rows
        ]

    def _find_intervention_points(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Find where users intervened (corrected agent behavior)."""
        conn = self._db.connect()
        try:
            rows = conn.execute("""
                SELECT tool_name, stage, COUNT(*) as interventions
                FROM session_observations
                WHERE user_intervention = 1
                GROUP BY tool_name, stage
                ORDER BY interventions DESC
                LIMIT 20
            """).fetchall()
        except Exception:
            return []
        finally:
            conn.close()

        return [
            {"tool": r["tool_name"], "stage": r["stage"], "count": r["interventions"]}
            for r in rows
        ]

    def _generate_candidates(
        self,
        patterns: list[ToolPattern],
        failures: list[dict[str, Any]],
        interventions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Phase 3: Generate improvement candidates from patterns."""
        candidates: list[dict[str, Any]] = []

        # Candidate 1: High-failure tools need better error handling or prompts
        for f in failures[:5]:
            if f["failure_rate"] > 0.3:
                candidates.append({
                    "type": "prompt_improvement",
                    "target": f["tool"],
                    "reason": f"High failure rate ({f['failure_rate']:.0%})",
                    "suggestion": f"Review and improve prompt for {f['tool']}",
                })

        # Candidate 2: Frequent intervention points need better defaults
        for i in interventions[:5]:
            candidates.append({
                "type": "default_improvement",
                "target": f"{i['tool']}@{i['stage']}",
                "reason": f"User intervened {i['count']} times",
                "suggestion": f"Improve defaults for {i['tool']} in {i['stage']} stage",
            })

        # Candidate 3: Common patterns could become stage macros
        for p in patterns[:3]:
            if p.frequency >= 5 and len(p.tools) >= 3:
                candidates.append({
                    "type": "stage_macro",
                    "target": "->".join(p.tools),
                    "reason": f"Pattern repeated {p.frequency} times",
                    "suggestion": f"Create macro tool for sequence: {' -> '.join(p.tools)}",
                })

        return candidates
