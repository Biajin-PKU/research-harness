"""Trajectory recorder — captures rich decision traces beyond metadata.

Records tool calls, decisions, gate outcomes, and error recovery actions
with reasoning context, enabling downstream strategy distillation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..storage.db import Database
from .models import TrajectoryEvent

logger = logging.getLogger(__name__)

# Fields that should be truncated in summaries
_MAX_SUMMARY_LEN = 500


def _truncate(text: str | None, limit: int = _MAX_SUMMARY_LEN) -> str:
    if not text:
        return ""
    return text[:limit] if len(text) > limit else text


class TrajectoryRecorder:
    """Records trajectory events for a session.

    Each event captures what happened (tool_call, decision, etc.),
    why (reasoning), and the outcome. Events are ordered by
    sequence_number within a session.
    """

    def __init__(self, db: Database, session_id: str) -> None:
        self._db = db
        self._session_id = session_id
        self._sequence = 0

    @property
    def session_id(self) -> str:
        return self._session_id

    def record_tool_call(
        self,
        tool_name: str,
        *,
        stage: str = "",
        topic_id: int | None = None,
        project_id: int | None = None,
        input_summary: str = "",
        output_summary: str = "",
        reasoning: str = "",
        success: bool = True,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        parent_event_id: int | None = None,
    ) -> int:
        """Record a tool call event. Returns the event ID."""
        return self._insert(
            event_type="tool_call",
            tool_name=tool_name,
            stage=stage,
            topic_id=topic_id,
            project_id=project_id,
            input_summary=_truncate(input_summary),
            output_summary=_truncate(output_summary),
            reasoning=_truncate(reasoning),
            success=success,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            parent_event_id=parent_event_id,
        )

    def record_decision(
        self,
        decision_type: str,
        reasoning: str,
        *,
        stage: str = "",
        topic_id: int | None = None,
        project_id: int | None = None,
    ) -> int:
        """Record a decision event (e.g. stage transition, strategy choice)."""
        return self._insert(
            event_type="decision",
            tool_name=decision_type,
            stage=stage,
            topic_id=topic_id,
            project_id=project_id,
            reasoning=_truncate(reasoning),
        )

    def record_gate_outcome(
        self,
        gate_type: str,
        outcome: str,
        reasoning: str = "",
        *,
        stage: str = "",
        topic_id: int | None = None,
        project_id: int | None = None,
    ) -> int:
        """Record a gate check outcome."""
        return self._insert(
            event_type="gate_outcome",
            tool_name=gate_type,
            stage=stage,
            topic_id=topic_id,
            project_id=project_id,
            output_summary=outcome,
            reasoning=_truncate(reasoning),
        )

    def record_error_recovery(
        self,
        error: str,
        recovery_action: str,
        *,
        stage: str = "",
        topic_id: int | None = None,
    ) -> int:
        """Record an error and the recovery action taken."""
        return self._insert(
            event_type="error_recovery",
            stage=stage,
            topic_id=topic_id,
            input_summary=_truncate(error),
            output_summary=_truncate(recovery_action),
            success=False,
        )

    def record_user_override(
        self,
        what_was_overridden: str,
        reasoning: str = "",
        *,
        stage: str = "",
        topic_id: int | None = None,
    ) -> int:
        """Record when the user overrides agent behavior."""
        return self._insert(
            event_type="user_override",
            stage=stage,
            topic_id=topic_id,
            input_summary=_truncate(what_was_overridden),
            reasoning=_truncate(reasoning),
        )

    def _insert(
        self,
        *,
        event_type: str,
        tool_name: str = "",
        stage: str = "",
        topic_id: int | None = None,
        project_id: int | None = None,
        input_summary: str = "",
        output_summary: str = "",
        reasoning: str = "",
        success: bool = True,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        parent_event_id: int | None = None,
    ) -> int:
        """Insert a trajectory event. Returns event ID."""
        self._sequence += 1
        conn = self._db.connect()
        try:
            cursor = conn.execute(
                """INSERT INTO trajectory_events
                   (session_id, event_type, tool_name, stage, topic_id, project_id,
                    input_summary, output_summary, reasoning, success,
                    cost_usd, latency_ms, parent_event_id, sequence_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._session_id, event_type, tool_name, stage,
                    topic_id, project_id, input_summary, output_summary,
                    reasoning, int(success), cost_usd, latency_ms,
                    parent_event_id, self._sequence,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        except Exception:
            logger.debug("Failed to record trajectory event", exc_info=True)
            return 0
        finally:
            conn.close()

    # ---- Query methods ----

    def get_session_trajectory(
        self, session_id: str | None = None,
    ) -> list[TrajectoryEvent]:
        """Get all events for a session, ordered by sequence."""
        sid = session_id or self._session_id
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT * FROM trajectory_events
                   WHERE session_id = ?
                   ORDER BY sequence_number""",
                (sid,),
            ).fetchall()
            return [_row_to_event(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_stage_trajectories(
        db: Database,
        stage: str,
        *,
        topic_id: int | None = None,
        limit: int = 50,
    ) -> list[TrajectoryEvent]:
        """Get recent trajectory events for a stage across sessions."""
        conn = db.connect()
        try:
            if topic_id is not None:
                rows = conn.execute(
                    """SELECT * FROM trajectory_events
                       WHERE stage = ? AND topic_id = ?
                       ORDER BY id DESC LIMIT ?""",
                    (stage, topic_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM trajectory_events
                       WHERE stage = ?
                       ORDER BY id DESC LIMIT ?""",
                    (stage, limit),
                ).fetchall()
            return [_row_to_event(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_session_ids_for_stage(
        db: Database,
        stage: str,
        *,
        limit: int = 20,
    ) -> list[str]:
        """Get distinct session IDs that touched a given stage."""
        conn = db.connect()
        try:
            rows = conn.execute(
                """SELECT session_id, MAX(id) as max_id FROM trajectory_events
                   WHERE stage = ?
                   GROUP BY session_id
                   ORDER BY max_id DESC LIMIT ?""",
                (stage, limit),
            ).fetchall()
            return [r["session_id"] for r in rows]
        except Exception:
            return []
        finally:
            conn.close()

    @staticmethod
    def format_trajectory_text(events: list[TrajectoryEvent]) -> str:
        """Format trajectory events as a readable text block for LLM consumption."""
        if not events:
            return "(no trajectory events)"
        lines: list[str] = []
        for i, ev in enumerate(events, 1):
            status = "OK" if ev.success else "FAIL"
            line = f"[{i}] {ev.event_type}: {ev.tool_name or ev.stage} [{status}]"
            if ev.input_summary:
                line += f"\n     Input: {ev.input_summary[:200]}"
            if ev.output_summary:
                line += f"\n     Output: {ev.output_summary[:200]}"
            if ev.reasoning:
                line += f"\n     Reasoning: {ev.reasoning[:200]}"
            if ev.cost_usd > 0:
                line += f"\n     Cost: ${ev.cost_usd:.4f}"
            lines.append(line)
        return "\n".join(lines)


def _row_to_event(row: Any) -> TrajectoryEvent:
    """Convert a DB row to TrajectoryEvent."""
    return TrajectoryEvent(
        id=row["id"],
        session_id=row["session_id"],
        event_type=row["event_type"],
        tool_name=row["tool_name"] or "",
        stage=row["stage"] or "",
        topic_id=row["topic_id"],
        project_id=row["project_id"],
        input_summary=row["input_summary"] or "",
        output_summary=row["output_summary"] or "",
        reasoning=row["reasoning"] or "",
        success=bool(row["success"]),
        cost_usd=row["cost_usd"] or 0.0,
        latency_ms=row["latency_ms"] or 0,
        parent_event_id=row["parent_event_id"],
        sequence_number=row["sequence_number"] or 0,
        created_at=row["created_at"] or "",
    )
