"""Checkpoint persistence for the auto-runner.

The checkpoint is the runner-local resume state. The orchestrator DB is
canonical for workflow semantics; the checkpoint is canonical for mid-stage
runner state (pending tool, retry counters, codex handoff, context summaries).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_checkpoint(
    topic_id: int,
    *,
    mode: str = "standard",
    session_command: list[str] | None = None,
) -> dict[str, Any]:
    """Create a fresh checkpoint seeded with defaults."""
    return {
        "schema_version": SCHEMA_VERSION,
        "topic_id": topic_id,
        "mode": mode,
        "session_command": session_command or ["claude-kimi"],
        "current_stage": "init",
        "current_stage_attempt": 1,
        "stage_state": "pending",  # pending | running | needs_codex | needs_human | complete | error
        "artifacts": {},
        "stage_context": {
            "summary_md": "",
            "paper_ids": [],
            "open_issue_ids": [],
            "search_queries": [],
        },
        "codex_handoff": {
            "requested": False,
            "stage": "",
            "request_path": "",
            "response_path": "",
            "verdict": "",
        },
        "last_error": {
            "kind": "",
            "message": "",
            "tool_name": "",
            "recovery_hint": "",
            "retry_count": 0,
        },
        "history": [],
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }


def checkpoint_path(base_dir: Path, topic_id: int) -> Path:
    """Return the checkpoint file path for a topic."""
    return base_dir / "auto_runner" / "checkpoints" / f"topic_{topic_id}.json"


def handoff_dir(base_dir: Path, topic_id: int, stage: str) -> Path:
    """Return the handoff directory for a topic stage."""
    return base_dir / "auto_runner" / "handoffs" / f"topic_{topic_id}" / stage


def _clean_stale_temps(directory: Path) -> None:
    """Remove stale .tmp files left by interrupted save_checkpoint calls."""
    if not directory.is_dir():
        return
    for tmp in directory.glob("*.tmp"):
        try:
            tmp.unlink()
            logger.info("Cleaned stale temp file: %s", tmp)
        except OSError:
            pass


def load_checkpoint(path: Path) -> dict[str, Any] | None:
    """Load checkpoint from file. Returns None if not found."""
    _clean_stale_temps(path.parent)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION:
            logger.warning("Checkpoint schema version mismatch: %s", path)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load checkpoint %s: %s", path, exc)
        return None


def save_checkpoint(path: Path, data: dict[str, Any]) -> None:
    """Persist checkpoint to file atomically (write-to-temp + rename)."""
    data["updated_at"] = _utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp_path, str(path))
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def record_event(
    data: dict[str, Any],
    *,
    stage: str,
    event: str,
    detail: str = "",
) -> None:
    """Append an event to the checkpoint history."""
    data.setdefault("history", []).append(
        {
            "ts": _utc_now(),
            "stage": stage,
            "event": event,
            "detail": detail,
        }
    )
    # Keep history bounded
    if len(data["history"]) > 200:
        data["history"] = data["history"][-200:]


def record_artifact(
    data: dict[str, Any],
    *,
    stage: str,
    artifact_type: str,
    artifact_id: int,
    version: int = 1,
) -> None:
    """Record an artifact ID in the checkpoint."""
    stage_artifacts = data.setdefault("artifacts", {}).setdefault(stage, {})
    stage_artifacts[artifact_type] = {
        "artifact_id": artifact_id,
        "version": version,
    }


def record_error(
    data: dict[str, Any],
    *,
    kind: str,
    message: str,
    tool_name: str = "",
    recovery_hint: str = "",
) -> None:
    """Record the latest error in the checkpoint."""
    err = data.setdefault("last_error", {})
    err["kind"] = kind
    err["message"] = message[:500]
    err["tool_name"] = tool_name
    err["recovery_hint"] = recovery_hint[:500]
    err["retry_count"] = err.get("retry_count", 0) + 1


def clear_error(data: dict[str, Any]) -> None:
    """Clear error state after successful recovery."""
    data["last_error"] = {
        "kind": "",
        "message": "",
        "tool_name": "",
        "recovery_hint": "",
        "retry_count": 0,
    }


def update_stage(
    data: dict[str, Any],
    *,
    stage: str,
    state: str,
    summary_md: str = "",
) -> None:
    """Update the current stage and state."""
    data["current_stage"] = stage
    data["stage_state"] = state
    if summary_md:
        data.setdefault("stage_context", {})["summary_md"] = summary_md


def set_codex_handoff(
    data: dict[str, Any],
    *,
    stage: str,
    request_path: str,
    response_path: str,
) -> None:
    """Mark that a codex handoff is pending."""
    data["codex_handoff"] = {
        "requested": True,
        "stage": stage,
        "request_path": request_path,
        "response_path": response_path,
        "verdict": "",
    }


def clear_codex_handoff(
    data: dict[str, Any], *, verdict: str = "", stage: str = ""
) -> None:
    """Clear codex handoff after completion. Preserves stage for verdict scoping."""
    prev_stage = data.get("codex_handoff", {}).get("stage", "")
    data["codex_handoff"] = {
        "requested": False,
        "stage": stage or prev_stage,
        "request_path": "",
        "response_path": "",
        "verdict": verdict,
    }
