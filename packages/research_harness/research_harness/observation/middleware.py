"""MCP tool call observation middleware.

Wraps tool dispatch to record observations without affecting execution.
Privacy-safe: hashes arguments, truncates results, never stores paper text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Callable

from ..storage.db import Database
from .models import SessionObservation

logger = logging.getLogger(__name__)

# Fields that may contain paper text or other sensitive content
_SENSITIVE_FIELDS = frozenset(
    {
        "text",
        "content",
        "abstract",
        "code",
        "pdf_path",
        "study_spec",
        "previous_code",
        "review_feedback",
        "outline",
        "sections",
        "evidence_summary",
    }
)


def _sanitize_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields, keep structure for pattern analysis."""
    sanitized = {}
    for key, value in arguments.items():
        if key in _SENSITIVE_FIELDS:
            sanitized[key] = f"<{type(value).__name__}:{len(str(value))}>"
        elif isinstance(value, str) and len(value) > 200:
            sanitized[key] = value[:200] + "..."
        else:
            sanitized[key] = value
    return sanitized


def _hash_args(arguments: dict[str, Any]) -> str:
    """Produce a short hash of sanitized arguments."""
    sanitized = _sanitize_args(arguments)
    raw = json.dumps(sanitized, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _truncate_result(result: Any, limit: int = 500) -> str:
    """Extract a short summary from tool result."""
    if result is None:
        return ""
    text = str(result)
    return text[:limit]


def _summarize_args(arguments: dict[str, Any]) -> str:
    """Build a human-readable summary of tool arguments for trajectory capture."""
    sanitized = _sanitize_args(arguments)
    parts: list[str] = []
    for key, value in sanitized.items():
        parts.append(f"{key}={value}")
    return ", ".join(parts)[:500]


def _init_trajectory_recorder(db: Database, session_id: str) -> Any:
    """Initialize TrajectoryRecorder, returning None if table not yet migrated."""
    try:
        from ..evolution.trajectory import TrajectoryRecorder

        return TrajectoryRecorder(db, session_id)
    except Exception:
        logger.debug("TrajectoryRecorder not available (migration pending?)")
        return None


class ObservationMiddleware:
    """Records MCP tool invocations for pattern analysis and skill evolution."""

    def __init__(self, db: Database, session_id: str | None = None):
        self._db = db
        self._session_id = session_id or str(uuid.uuid4())[:12]
        self._trajectory_recorder = _init_trajectory_recorder(db, self._session_id)
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create table if it doesn't exist (idempotent)."""
        conn = self._db.connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_observations (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_hash TEXT,
                    result_summary TEXT,
                    success INTEGER DEFAULT 1,
                    cost_usd REAL DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0,
                    stage TEXT,
                    gate_outcome TEXT,
                    user_intervention INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_session ON session_observations(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_tool ON session_observations(tool_name)"
            )
            conn.commit()
        except Exception:
            logger.debug("observation table setup skipped (may already exist)")
        finally:
            conn.close()

    @property
    def session_id(self) -> str:
        return self._session_id

    def record(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any = None,
        success: bool = True,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        stage: str = "",
        gate_outcome: str = "",
    ) -> None:
        """Record a tool invocation observation (non-blocking, fire-and-forget)."""
        try:
            obs = SessionObservation(
                session_id=self._session_id,
                tool_name=tool_name,
                arguments_hash=_hash_args(arguments),
                result_summary=_truncate_result(result),
                success=success,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                stage=stage,
                gate_outcome=gate_outcome,
            )
            conn = self._db.connect()
            try:
                conn.execute(
                    """INSERT INTO session_observations
                       (session_id, tool_name, arguments_hash, result_summary,
                        success, cost_usd, latency_ms, stage, gate_outcome)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        obs.session_id,
                        obs.tool_name,
                        obs.arguments_hash,
                        obs.result_summary,
                        int(obs.success),
                        obs.cost_usd,
                        obs.latency_ms,
                        obs.stage,
                        obs.gate_outcome,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            # Never let observation recording break tool execution
            logger.debug(
                "Failed to record observation for %s", tool_name, exc_info=True
            )

    @property
    def trajectory_recorder(self) -> Any:
        """Access the TrajectoryRecorder (may be None if table not ready)."""
        return self._trajectory_recorder

    def wrap_tool(
        self,
        tool_name: str,
        tool_fn: Callable,
        arguments: dict[str, Any],
        stage: str = "",
    ) -> Any:
        """Execute a tool and record the observation + trajectory event."""
        start = time.monotonic()
        try:
            result = tool_fn(tool_name, arguments)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            # Extract cost from result if available
            cost = 0.0
            if isinstance(result, dict):
                cost = result.get("cost_usd", 0.0)

            self.record(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                success=True,
                cost_usd=cost,
                latency_ms=elapsed_ms,
                stage=stage,
            )

            # Trajectory: richer capture with input/output summaries
            if self._trajectory_recorder is not None:
                try:
                    self._trajectory_recorder.record_tool_call(
                        tool_name,
                        stage=stage,
                        topic_id=arguments.get("topic_id"),
                        project_id=arguments.get("project_id"),
                        input_summary=_summarize_args(arguments),
                        output_summary=_truncate_result(result),
                        success=True,
                        cost_usd=cost,
                        latency_ms=elapsed_ms,
                    )
                except Exception:
                    logger.debug(
                        "Trajectory recording failed for %s", tool_name, exc_info=True
                    )

            return result
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self.record(
                tool_name=tool_name,
                arguments=arguments,
                result=str(exc),
                success=False,
                latency_ms=elapsed_ms,
                stage=stage,
            )

            # Trajectory: record failure
            if self._trajectory_recorder is not None:
                try:
                    self._trajectory_recorder.record_tool_call(
                        tool_name,
                        stage=stage,
                        topic_id=arguments.get("topic_id"),
                        project_id=arguments.get("project_id"),
                        input_summary=_summarize_args(arguments),
                        output_summary=str(exc)[:500],
                        success=False,
                        latency_ms=elapsed_ms,
                    )
                except Exception:
                    logger.debug(
                        "Trajectory recorder failed for %s",
                        tool_name,
                        exc_info=True,
                    )

            raise

    def get_session_summary(self) -> dict[str, Any]:
        """Get summary of current session's observations."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT tool_name, success, cost_usd, latency_ms, stage
                   FROM session_observations
                   WHERE session_id = ?
                   ORDER BY id""",
                (self._session_id,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return {"session_id": self._session_id, "total_tools": 0}

        tools = [r["tool_name"] for r in rows]
        stages = sorted({r["stage"] for r in rows if r["stage"]})
        total_cost = sum(r["cost_usd"] or 0 for r in rows)
        total_latency = sum(r["latency_ms"] or 0 for r in rows)
        successes = sum(1 for r in rows if r["success"])

        return {
            "session_id": self._session_id,
            "tool_sequence": tools,
            "total_tools": len(tools),
            "total_cost_usd": round(total_cost, 4),
            "total_latency_ms": total_latency,
            "success_rate": round(successes / len(tools), 3),
            "stages_visited": stages,
        }
