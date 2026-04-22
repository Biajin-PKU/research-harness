"""Strategy injector — builds context overlays from active strategies.

Reads strategies from the DB for a given stage and formats them as
markdown text for injection into LLM system prompts or MCP tool context.
Supports both global (cross-topic) and topic-scoped strategies.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..storage.db import Database
from .models import Strategy

logger = logging.getLogger(__name__)


class StrategyInjector:
    """Injects active strategies into session context."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get_active_strategies(
        self,
        stage: str,
        *,
        topic_id: int | None = None,
        max_strategies: int = 5,
    ) -> list[Strategy]:
        """Fetch active strategies for a stage, ranked by quality score."""
        conn = self._db.connect()
        try:
            has_elo = self._has_elo_column(conn)
            order_clause = (
                "ORDER BY elo_rating DESC NULLS LAST, quality_score DESC"
                if has_elo
                else "ORDER BY quality_score DESC"
            )
            if topic_id is not None:
                rows = conn.execute(
                    f"""SELECT * FROM strategies
                       WHERE stage = ? AND status = 'active'
                         AND (scope = 'global' OR (scope = 'topic' AND topic_id = ?))
                       {order_clause}
                       LIMIT ?""",
                    (stage, topic_id, max_strategies),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""SELECT * FROM strategies
                       WHERE stage = ? AND status = 'active' AND scope = 'global'
                       {order_clause}
                       LIMIT ?""",
                    (stage, max_strategies),
                ).fetchall()
        finally:
            conn.close()

        return [_row_to_strategy(r) for r in rows]

    def build_strategy_overlay(
        self,
        stage: str,
        *,
        topic_id: int | None = None,
        max_strategies: int = 3,
    ) -> str:
        """Build a markdown overlay from active strategies for prompt injection.

        Returns empty string if no strategies are available.
        """
        strategies = self.get_active_strategies(
            stage,
            topic_id=topic_id,
            max_strategies=max_strategies,
        )
        if not strategies:
            return ""

        lines = [f"## Research Strategies (stage: {stage})\n"]
        lines.append(
            "_The following strategies were distilled from previous research sessions._\n"
        )

        for i, s in enumerate(strategies, 1):
            scope_tag = f" [{s.scope}]" if s.scope == "topic" else ""
            lines.append(f"### {i}. {s.title}{scope_tag}")
            lines.append(s.content)
            lines.append("")

        return "\n".join(lines)

    def get_all_strategy_overlays(
        self,
        *,
        topic_id: int | None = None,
    ) -> dict[str, str]:
        """Build strategy overlays for all stages. Returns stage→overlay mapping."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT stage FROM strategies WHERE status = 'active'"
            ).fetchall()
        finally:
            conn.close()

        overlays: dict[str, str] = {}
        for r in rows:
            stage = r["stage"]
            overlay = self.build_strategy_overlay(
                stage,
                topic_id=topic_id,
            )
            if overlay:
                overlays[stage] = overlay
        return overlays

    @staticmethod
    def _has_elo_column(conn: Any) -> bool:
        """Check if elo_rating column exists (graceful fallback for pre-035 DBs)."""
        try:
            info = conn.execute("PRAGMA table_info(strategies)").fetchall()
            return any(row["name"] == "elo_rating" for row in info)
        except Exception:
            return False

    def record_injection(self, strategy_id: int) -> None:
        """Increment the injection_count for a strategy (for probation tracking)."""
        conn = self._db.connect()
        try:
            conn.execute(
                "UPDATE strategies SET injection_count = injection_count + 1 WHERE id = ?",
                (strategy_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def record_positive_feedback(self, strategy_id: int) -> None:
        """Record positive feedback for a strategy (for probation → active promotion)."""
        conn = self._db.connect()
        try:
            conn.execute(
                "UPDATE strategies SET positive_feedback = positive_feedback + 1 WHERE id = ?",
                (strategy_id,),
            )
            conn.commit()
        finally:
            conn.close()


def _row_to_strategy(row: Any) -> Strategy:
    """Convert a DB row to a Strategy dataclass."""
    lesson_ids_raw = row["source_lesson_ids"] or "[]"
    try:
        lesson_ids = json.loads(lesson_ids_raw)
    except (json.JSONDecodeError, TypeError):
        lesson_ids = []

    return Strategy(
        id=row["id"],
        stage=row["stage"],
        strategy_key=row["strategy_key"],
        title=row["title"],
        content=row["content"],
        scope=row["scope"] or "global",
        topic_id=row["topic_id"],
        version=row["version"],
        quality_score=row["quality_score"] or 0.0,
        gate_model=row["gate_model"] or "",
        source_lesson_ids=lesson_ids,
        source_session_count=row["source_session_count"] or 0,
        injection_count=row["injection_count"] or 0,
        positive_feedback=row["positive_feedback"] or 0,
        status=row["status"],
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )
