"""Tool usage frequency tracking for consolidation decisions.

Answers: which tools are actually used? Which should be merged/hidden?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..storage.db import Database


@dataclass
class ToolUsageReport:
    """Tool usage statistics for consolidation decisions."""

    total_calls: int = 0
    unique_tools: int = 0
    tools: list[ToolStats] = field(default_factory=list)
    never_used: list[str] = field(default_factory=list)
    consolidation_candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolStats:
    """Per-tool usage statistics."""

    name: str
    call_count: int = 0
    success_rate: float = 1.0
    avg_latency_ms: int = 0
    avg_cost_usd: float = 0.0
    stages: list[str] = field(default_factory=list)


class ToolUsageTracker:
    """Tracks and reports tool usage from observation data."""

    def __init__(self, db: Database):
        self._db = db

    def report(self) -> ToolUsageReport:
        """Generate tool usage report."""
        conn = self._db.connect()
        try:
            rows = conn.execute("""
                SELECT tool_name,
                       COUNT(*) as calls,
                       SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                       AVG(latency_ms) as avg_latency,
                       AVG(cost_usd) as avg_cost,
                       GROUP_CONCAT(DISTINCT stage) as stages
                FROM session_observations
                GROUP BY tool_name
                ORDER BY calls DESC
            """).fetchall()
        except Exception:
            return ToolUsageReport()
        finally:
            conn.close()

        tools = []
        used_names = set()
        for r in rows:
            name = r["tool_name"]
            used_names.add(name)
            tools.append(
                ToolStats(
                    name=name,
                    call_count=r["calls"],
                    success_rate=round(r["successes"] / r["calls"], 3)
                    if r["calls"]
                    else 1.0,
                    avg_latency_ms=int(r["avg_latency"] or 0),
                    avg_cost_usd=round(r["avg_cost"] or 0, 4),
                    stages=(r["stages"] or "").split(","),
                )
            )

        # Find never-used tools from the primitive registry
        try:
            from ..primitives.registry import PRIMITIVE_REGISTRY

            all_tools = set(PRIMITIVE_REGISTRY.keys())
            never_used = sorted(all_tools - used_names)
        except Exception:
            never_used = []

        # Consolidation candidates: low-use tools that could be merged
        candidates = []
        for t in tools:
            if t.call_count <= 2:
                candidates.append(
                    {
                        "tool": t.name,
                        "calls": t.call_count,
                        "suggestion": "Consider hiding or merging — rarely used",
                    }
                )

        total_calls = sum(t.call_count for t in tools)
        return ToolUsageReport(
            total_calls=total_calls,
            unique_tools=len(tools),
            tools=tools,
            never_used=never_used,
            consolidation_candidates=candidates,
        )
