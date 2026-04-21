"""MCP tool definitions and execution — wraps research_harness primitives."""

from __future__ import annotations

import json
import logging
import os
import shutil
import zlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from mcp.types import Tool

from research_harness.config import find_workspace_root, load_runtime_config
from research_harness.execution.backend import BackendInfo
from research_harness.execution.factory import create_backend
from research_harness.execution.tracked import TrackedBackend
from research_harness.execution.harness_actions import classify_error
from research_harness.primitives.registry import list_primitives
from research_harness.primitives.types import PrimitiveResult
from research_harness.provenance.recorder import ProvenanceRecorder
from research_harness.storage.db import Database

# ---------------------------------------------------------------------------
# DB / backend helpers
# ---------------------------------------------------------------------------

_SESSION_ACTIVITY: dict[str, Any] = {
    "last_topic_id": None,
    "streak": 0,
}
_SESSION_NUDGE_MGR: dict[str, Any] = {"instance": None, "cost_usd": 0.0, "experiment_count": 0}
_SESSION_TRIGGER_TOOLS = {
    "paper_search",
    "paper_ingest",
    "paper_acquire",
    "claim_extract",
    "gap_detect",
    "query_refine",
    "search_query_add",
}

def _resolve_db() -> Database:
    """Resolve database path from env or workspace default."""
    db_path = os.environ.get("RESEARCH_HARNESS_DB_PATH") or os.environ.get("RESEARCH_HUB_DB_PATH")
    if db_path:
        db = Database(Path(db_path))
    else:
        ws = find_workspace_root()
        if ws:
            db = Database(ws / ".research-harness" / "pool.db")
        else:
            db = Database(Path.home() / ".research-harness" / "pool.db")
    logger.info("Using DB: %s", db.db_path)
    db.migrate()
    return db


def _create_tracked_backend(db: Database) -> TrackedBackend:
    """Create a tracked research_harness backend."""
    backend_name = os.environ.get("RESEARCH_HARNESS_BACKEND") or os.environ.get("RESEARCH_HUB_BACKEND", "research_harness")
    inner = create_backend(backend_name, db=db)
    recorder = ProvenanceRecorder(db)
    return TrackedBackend(inner=inner, recorder=recorder)


# ---------------------------------------------------------------------------
# Primitive tools — auto-generated from PRIMITIVE_REGISTRY
# ---------------------------------------------------------------------------

def _primitive_tool_definitions() -> list[Tool]:
    """Convert registered PrimitiveSpecs into MCP Tool definitions."""
    tools = []
    for spec in list_primitives():
        tools.append(Tool(
            name=spec.name,
            description=spec.description,
            inputSchema=spec.input_schema,
        ))
    return tools


def _try_get_orch_state(db: Database, topic_id: int | None) -> dict[str, Any] | None:
    """Try to fetch orchestrator state for context-aware next_actions."""
    if topic_id is None:
        return None
    try:
        from research_harness.orchestrator import OrchestratorService
        svc = OrchestratorService(db)
        # Find project by topic_id
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT project_id FROM orchestrator_runs WHERE topic_id = ? LIMIT 1",
                (topic_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return svc.get_status(row["project_id"])
    except Exception:
        return None


def _extract_topic_id(arguments: dict[str, Any]) -> int | None:
    topic_id = arguments.get("topic_id")
    if topic_id is None:
        return None
    try:
        return int(topic_id)
    except (TypeError, ValueError):
        return None


def _maybe_session_advisory(
    db: Database,
    name: str,
    arguments: dict[str, Any],
    orch_state: dict[str, Any] | None,
) -> str:
    if name not in _SESSION_TRIGGER_TOOLS:
        return ""

    topic_id = _extract_topic_id(arguments)
    if topic_id is None:
        return ""

    if _SESSION_ACTIVITY["last_topic_id"] == topic_id:
        _SESSION_ACTIVITY["streak"] += 1
    else:
        _SESSION_ACTIVITY["last_topic_id"] = topic_id
        _SESSION_ACTIVITY["streak"] = 1

    if orch_state is not None:
        return ""

    if _SESSION_ACTIVITY["streak"] < 3:
        return ""

    return (
        f"Detected {_SESSION_ACTIVITY['streak']} consecutive operations on topic {topic_id}. "
        "Consider starting or resuming the full orchestrated literature workflow "
        "with orchestrator_resume, then record artifacts as you progress."
    )


def _get_nudge_manager(db: Database) -> Any:
    """Get or create session-level NudgeManager."""
    if _SESSION_NUDGE_MGR["instance"] is None:
        try:
            from research_harness.evolution.nudge import NudgeManager
            import uuid
            _SESSION_NUDGE_MGR["instance"] = NudgeManager(db, f"mcp-{uuid.uuid4().hex[:8]}")
        except Exception:
            pass
    return _SESSION_NUDGE_MGR["instance"]


def _check_nudge(db: Database, name: str, arguments: dict[str, Any], result: PrimitiveResult) -> str:
    """Check if a nudge should be emitted after this tool call."""
    mgr = _get_nudge_manager(db)
    if mgr is None:
        return ""
    try:
        mgr.tick()
        if result.cost_usd:
            _SESSION_NUDGE_MGR["cost_usd"] += result.cost_usd
        if name == "experiment_run":
            _SESSION_NUDGE_MGR["experiment_count"] += 1

        # Infer stage from orchestrator state or argument
        stage = arguments.get("stage", "")
        if not stage:
            orch = _try_get_orch_state(db, arguments.get("topic_id"))
            if orch and isinstance(orch, dict):
                stage = orch.get("current_stage", "")

        nudge = mgr.check_nudge(
            stage=stage,
            cost_usd=_SESSION_NUDGE_MGR["cost_usd"],
            experiment_count=_SESSION_NUDGE_MGR["experiment_count"],
        )
        if nudge:
            return mgr.format_nudge(nudge)
    except Exception:
        pass
    return ""


def _inject_strategy_overlay(raw: dict[str, Any]) -> str:
    """Build strategy overlay for the current orchestrator stage."""
    try:
        # Extract stage from response
        stage = raw.get("current_stage", "")
        if not stage:
            run = raw.get("run", {})
            stage = run.get("current_stage", "")
        if not stage:
            stage = raw.get("to_stage", "")
        if not stage:
            return ""

        # Extract topic_id
        topic_id = raw.get("topic_id")
        if not topic_id:
            run = raw.get("run", {})
            topic_id = run.get("topic_id")

        db = _resolve_db()
        from research_harness.evolution.injector import StrategyInjector
        injector = StrategyInjector(db)
        overlay = injector.build_strategy_overlay(
            stage, topic_id=topic_id, max_strategies=3,
        )

        # Record injection counts
        strategies = injector.get_active_strategies(stage, topic_id=topic_id, max_strategies=3)
        for s in strategies:
            injector.record_injection(s.id)

        return overlay
    except Exception:
        return ""


def _record_iterative_retrieval_artifact(
    db: Database, arguments: dict[str, Any], result: PrimitiveResult
) -> None:
    """Persist an iterative_retrieval_loop result as an orchestrator artifact.

    The build-stage coverage gate consults this artifact to decide whether the
    paper pool has truly converged. Failures are swallowed so the primitive
    return value is never masked by bookkeeping errors.
    """
    topic_id = arguments.get("topic_id")
    if topic_id is None:
        return
    try:
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT project_id FROM orchestrator_runs WHERE topic_id = ? LIMIT 1",
                (int(topic_id),),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return
        project_id = int(row["project_id"])

        output = result.output
        if output is None:
            return
        payload = asdict(output) if hasattr(output, "__dataclass_fields__") else dict(output)

        from research_harness.orchestrator import OrchestratorService

        svc = OrchestratorService(db)
        svc.record_artifact(
            project_id=project_id,
            topic_id=int(topic_id),
            stage="build",
            artifact_type="iterative_retrieval_loop_result",
            title=(
                f"Retrieval loop: {payload.get('rounds_run', 0)} rounds, "
                f"+{payload.get('total_new_papers', 0)} papers, "
                f"converged={payload.get('convergence_reached', False)}"
            ),
            payload=payload,
        )
    except Exception:  # pragma: no cover - best-effort bookkeeping
        pass


def _execute_primitive(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a research primitive and return serializable result."""
    db = _resolve_db()
    backend = _create_tracked_backend(db)
    result: PrimitiveResult = backend.execute(name, **arguments)

    # Post-execution hooks
    if name == "iterative_retrieval_loop" and result.success:
        _record_iterative_retrieval_artifact(db, arguments, result)

    if name == "paper_search" and result.success:
        topic_id = arguments.get("topic_id")
        if topic_id:
            conn = db.connect()
            try:
                conn.execute(
                    "UPDATE topics SET last_search_at = datetime('now') WHERE id = ?",
                    (topic_id,),
                )
                # Also update per-query freshness if query is present
                query_text = arguments.get("query", "")
                if query_text:
                    conn.execute(
                        """INSERT INTO search_query_registry (topic_id, query, source, last_searched_at)
                           VALUES (?, ?, 'auto_generated', datetime('now'))
                           ON CONFLICT(topic_id, query) DO UPDATE SET last_searched_at = datetime('now')""",
                        (topic_id, query_text),
                    )
                conn.commit()
            except Exception:
                pass  # Non-critical, don't fail the search
            finally:
                conn.close()

    # Auto-extract writing patterns after successful deep_read
    if name == "deep_read" and result.success:
        paper_id = arguments.get("paper_id")
        if paper_id:
            try:
                backend.execute("writing_pattern_extract", paper_id=int(paper_id))
                logger.info("Auto-extracted writing patterns for paper %s", paper_id)
            except Exception as exc:
                logger.debug("Writing pattern extract skipped for paper %s: %s", paper_id, exc)

    orch_state = _try_get_orch_state(db, arguments.get("topic_id"))
    session_advisory = _maybe_session_advisory(db, name, arguments, orch_state)
    nudge_text = _check_nudge(db, name, arguments, result)
    return _serialize_result(result, orch_state, session_advisory=session_advisory, nudge=nudge_text)


# ---------------------------------------------------------------------------
# Convenience tools — direct DB queries
# ---------------------------------------------------------------------------

_CONVENIENCE_TOOLS: dict[str, Tool] = {
    "topic_list": Tool(
        name="topic_list",
        description="List all research topics",
        inputSchema={"type": "object", "properties": {}},
    ),
    "topic_show": Tool(
        name="topic_show",
        description="Show details for a research topic by name",
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Topic name"}},
            "required": ["name"],
        },
    ),
    "paper_list": Tool(
        name="paper_list",
        description="List papers, optionally filtered by topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic name filter"},
            },
        },
    ),
    "task_list": Tool(
        name="task_list",
        description="List tasks, optionally filtered by topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic name filter"},
                "status": {"type": "string", "description": "Status filter (pending/done/skipped)"},
            },
        },
    ),
    "provenance_summary": Tool(
        name="provenance_summary",
        description="Get aggregated provenance statistics (cost, operations, success rate)",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Optional topic ID filter"},
            },
        },
    ),
    "provenance_export": Tool(
        name="provenance_export",
        description="Export serialized provenance records for analysis",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Optional topic ID filter"},
                "format": {"type": "string", "enum": ["json"], "description": "Serialization format"},
            },
        },
    ),
    "provenance_token_report": Tool(
        name="provenance_token_report",
        description=(
            "Long-term token/cost accounting per (backend, model). Groups every "
            "provenance record by agent identity and reports call count, prompt "
            "tokens, completion tokens, total cost and cost-per-call. Optionally "
            "scoped to a single topic for per-paper agent budgeting."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Optional topic ID filter"},
            },
        },
    ),
    "paper_dismiss": Tool(
        name="paper_dismiss",
        description=(
            "Record that the user has decided not to read a paper in full. "
            "Stores the dismissal reason in topic_paper_notes and downgrades relevance to 'low'. "
            "Dismissed papers are excluded from future coverage checks and their reasons "
            "are used to calibrate necessity scoring for similar papers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "paper_id": {"type": "integer", "description": "ID of the paper to dismiss"},
                "topic_id": {"type": "integer", "description": "Topic the paper belongs to"},
                "reason": {"type": "string", "description": "Why the user is dismissing this paper"},
            },
            "required": ["paper_id", "topic_id", "reason"],
        },
    ),
    "decision_log_record": Tool(
        name="decision_log_record",
        description="Record a human or auto decision at a research checkpoint",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "topic_id": {"type": "integer"},
                "stage": {"type": "string", "description": "Stage name (V2 or legacy)"},
                "checkpoint": {"type": "string", "description": "Checkpoint name (e.g. direction_selection)"},
                "choice": {"type": "string", "description": "What was decided"},
                "reasoning": {"type": "string", "description": "Why this choice was made"},
                "params": {"type": "object", "description": "Parameter snapshot at decision time"},
            },
            "required": ["project_id", "topic_id", "stage", "checkpoint", "choice"],
        },
    ),
    "decision_log_list": Tool(
        name="decision_log_list",
        description="List decision log entries for a project (useful for writing motivation)",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "stage": {"type": "string", "description": "Optional stage filter"},
            },
            "required": ["project_id"],
        },
    ),
    "search_query_list": Tool(
        name="search_query_list",
        description="List registered search queries with freshness status for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
            },
            "required": ["topic_id"],
        },
    ),
    "search_query_add": Tool(
        name="search_query_add",
        description="Register a new search query for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "query": {"type": "string"},
                "source": {"type": "string", "description": "user / auto_generated / method_expansion"},
            },
            "required": ["topic_id", "query"],
        },
    ),
    "advisory_check": Tool(
        name="advisory_check",
        description="Run heuristic advisory rules and return newly created advisories for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "project_id": {"type": "integer"},
            },
            "required": ["topic_id"],
        },
    ),
    "advisory_list": Tool(
        name="advisory_list",
        description="List advisories for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "level": {"type": "string", "description": "Optional level filter: info or warning"},
            },
            "required": ["topic_id"],
        },
    ),
    "advisory_acknowledge": Tool(
        name="advisory_acknowledge",
        description="Mark an advisory as acknowledged",
        inputSchema={
            "type": "object",
            "properties": {
                "advisory_id": {"type": "integer"},
            },
            "required": ["advisory_id"],
        },
    ),
    "paper_purge": Tool(
        name="paper_purge",
        description=(
            "Permanently delete a paper and all its related records from the database. "
            "Use when a paper record is corrupted and causes queries on the entire topic to fail. "
            "This is irreversible — prefer paper_dismiss for normal exclusion."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "paper_id": {"type": "integer", "description": "ID of the paper to permanently delete"},
            },
            "required": ["paper_id"],
        },
    ),
    "venue_refresh": Tool(
        name="venue_refresh",
        description=(
            "Refresh venue metadata for papers with stale venues (arXiv.org, empty). "
            "Queries Semantic Scholar for updated venue info. "
            "Use after Build stage to catch papers that were published at conferences after initial ingestion."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID to refresh venues for"},
            },
            "required": ["topic_id"],
        },
    ),
}


def _execute_convenience(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a convenience query tool."""
    db = _resolve_db()
    conn = db.connect()
    try:
        if name == "topic_list":
            rows = conn.execute("SELECT id, name, description, status FROM topics ORDER BY id").fetchall()
            return {"topics": [dict(r) for r in rows]}

        elif name == "topic_show":
            row = conn.execute(
                "SELECT * FROM topics WHERE name = ?",
                (arguments["name"],),
            ).fetchone()
            if row is None:
                return {"error": f"Topic not found: {arguments['name']}"}
            result = dict(row)
            # Compute freshness info
            last_search = result.get("last_search_at") or ""
            if last_search:
                from datetime import datetime, timezone
                try:
                    last_dt = datetime.fromisoformat(last_search.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    delta = (now - last_dt).days
                    result["days_since_last_search"] = delta
                    warn = result.get("freshness_warn_days", 7)
                    stale = result.get("freshness_stale_days", 30)
                    if delta >= stale:
                        result["freshness_status"] = "stale"
                    elif delta >= warn:
                        result["freshness_status"] = "warn"
                    else:
                        result["freshness_status"] = "fresh"
                except (ValueError, TypeError):
                    result["days_since_last_search"] = None
                    result["freshness_status"] = "unknown"
            else:
                result["days_since_last_search"] = None
                result["freshness_status"] = "never_searched"
            return result

        elif name == "paper_list":
            topic = arguments.get("topic")
            if topic:
                rows = conn.execute(
                    """SELECT p.id, p.title, p.year, p.venue, p.url, p.affiliations, pt.relevance
                       FROM papers p
                       JOIN paper_topics pt ON p.id = pt.paper_id
                       JOIN topics t ON t.id = pt.topic_id
                       WHERE t.name = ?
                       ORDER BY p.id""",
                    (topic,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, title, year, venue, url, affiliations FROM papers ORDER BY id"
                ).fetchall()
            papers = []
            for r in rows:
                d = dict(r)
                if "affiliations" in d and isinstance(d["affiliations"], str):
                    try:
                        d["affiliations"] = json.loads(d["affiliations"])
                    except (json.JSONDecodeError, TypeError):
                        d["affiliations"] = []
                papers.append(d)
            return {"papers": papers}

        elif name == "task_list":
            clauses = ["1=1"]
            params: list[Any] = []
            if arguments.get("topic"):
                clauses.append("t.name = ?")
                params.append(arguments["topic"])
            if arguments.get("status"):
                clauses.append("tk.status = ?")
                params.append(arguments["status"])
            where = " AND ".join(clauses)
            rows = conn.execute(
                f"""SELECT tk.id, tk.title, tk.status, tk.priority, t.name as topic
                    FROM tasks tk
                    JOIN topics t ON t.id = tk.topic_id
                    WHERE {where}
                    ORDER BY tk.priority DESC, tk.id""",
                params,
            ).fetchall()
            return {"tasks": [dict(r) for r in rows]}

        elif name == "provenance_summary":
            recorder = ProvenanceRecorder(db)
            topic_id = arguments.get("topic_id")
            summary = recorder.summarize(topic_id=topic_id)
            return asdict(summary)

        elif name == "provenance_export":
            recorder = ProvenanceRecorder(db)
            topic_id = arguments.get("topic_id")
            fmt = arguments.get("format", "json")
            if fmt != "json":
                return {"error": f"Unsupported format: {fmt}"}
            records = recorder.list_records(topic_id=topic_id, limit=10000)
            return {"format": fmt, "records": [asdict(record) for record in records]}

        elif name == "provenance_token_report":
            recorder = ProvenanceRecorder(db)
            topic_id = arguments.get("topic_id")
            rows = recorder.token_report_by_agent(topic_id=topic_id)
            totals = {
                "calls": sum(r["calls"] for r in rows),
                "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
                "completion_tokens": sum(r["completion_tokens"] for r in rows),
                "total_tokens": sum(r["total_tokens"] for r in rows),
                "cost_usd": sum(r["cost_usd"] for r in rows),
            }
            return {"topic_id": topic_id, "agents": rows, "totals": totals}

        elif name == "paper_dismiss":
            paper_id = int(arguments["paper_id"])
            topic_id = int(arguments["topic_id"])
            reason = str(arguments.get("reason", "")).strip()

            # Verify paper exists
            paper = conn.execute("SELECT id, title FROM papers WHERE id = ?", (paper_id,)).fetchone()
            if paper is None:
                return {"error": f"Paper not found: {paper_id}"}

            # Downgrade relevance to 'low' in paper_topics
            conn.execute(
                "UPDATE paper_topics SET relevance = 'low' WHERE paper_id = ? AND topic_id = ?",
                (paper_id, topic_id),
            )

            # Upsert dismissal note — replace if a previous dismissal exists
            existing = conn.execute(
                "SELECT id FROM topic_paper_notes WHERE paper_id = ? AND topic_id = ? AND note_type = 'user_dismissed'",
                (paper_id, topic_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE topic_paper_notes SET content = ?, source = 'user', created_at = datetime('now') WHERE id = ?",
                    (reason, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO topic_paper_notes (paper_id, topic_id, note_type, content, source) VALUES (?, ?, 'user_dismissed', ?, 'user')",
                    (paper_id, topic_id, reason),
                )
            conn.commit()

            return {
                "dismissed": True,
                "paper_id": paper_id,
                "title": paper["title"],
                "reason_recorded": reason,
            }

        elif name == "decision_log_record":
            from research_harness.orchestrator.service import OrchestratorService
            svc = OrchestratorService(db)
            return svc.record_decision(
                project_id=int(arguments["project_id"]),
                topic_id=int(arguments["topic_id"]),
                stage=arguments["stage"],
                checkpoint=arguments["checkpoint"],
                choice=arguments["choice"],
                reasoning=arguments.get("reasoning", ""),
                params=arguments.get("params"),
            )

        elif name == "decision_log_list":
            from research_harness.orchestrator.service import OrchestratorService
            svc = OrchestratorService(db)
            return {
                "decisions": svc.list_decisions(
                    project_id=int(arguments["project_id"]),
                    stage=arguments.get("stage"),
                ),
            }

        elif name == "search_query_list":
            topic_id = int(arguments["topic_id"])
            rows = conn.execute(
                "SELECT * FROM search_query_registry WHERE topic_id = ? ORDER BY created_at",
                (topic_id,),
            ).fetchall()
            queries = []
            for r in rows:
                q = dict(r)
                last = q.get("last_searched_at") or ""
                if last:
                    from datetime import datetime, timezone
                    try:
                        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                        q["days_since_search"] = (datetime.now(timezone.utc) - dt).days
                    except (ValueError, TypeError):
                        q["days_since_search"] = None
                else:
                    q["days_since_search"] = None
                    q["freshness_status"] = "never_searched"
                queries.append(q)
            return {"queries": queries}

        elif name == "search_query_add":
            topic_id = int(arguments["topic_id"])
            query_text = arguments["query"]
            source = arguments.get("source", "user")
            conn.execute(
                """INSERT INTO search_query_registry (topic_id, query, source)
                   VALUES (?, ?, ?)
                   ON CONFLICT(topic_id, query) DO UPDATE SET source = ?""",
                (topic_id, query_text, source, source),
            )
            conn.commit()
            return {"success": True, "topic_id": topic_id, "query": query_text, "source": source}

        elif name == "advisory_check":
            from research_harness.advisory import AdvisoryEngine

            engine = AdvisoryEngine(db)
            advisories = engine.run(
                topic_id=int(arguments["topic_id"]),
                project_id=int(arguments["project_id"]) if arguments.get("project_id") is not None else None,
            )
            return {
                "advisories": [asdict(item) for item in advisories],
                "count": len(advisories),
            }

        elif name == "advisory_list":
            from research_harness.advisory import AdvisoryEngine

            engine = AdvisoryEngine(db)
            advisories = engine.list(
                topic_id=int(arguments["topic_id"]),
                level=arguments.get("level"),
            )
            return {
                "advisories": [asdict(item) for item in advisories],
                "count": len(advisories),
            }

        elif name == "advisory_acknowledge":
            from research_harness.advisory import AdvisoryEngine

            engine = AdvisoryEngine(db)
            advisory = engine.acknowledge(int(arguments["advisory_id"]))
            if advisory is None:
                return {"error": f"Advisory not found: {arguments['advisory_id']}"}
            return {"advisory": asdict(advisory)}

        elif name == "paper_purge":
            paper_id = int(arguments["paper_id"])
            paper = conn.execute("SELECT id, title FROM papers WHERE id = ?", (paper_id,)).fetchone()
            if paper is None:
                return {"error": f"Paper not found: {paper_id}"}
            title = paper["title"] or f"Paper #{paper_id}"
            # Delete in dependency order (CASCADE should handle most, but be explicit)
            for table in (
                "topic_paper_notes",
                "paper_annotations",
                "paper_artifacts",
                "bib_entries",
                "paper_topics",
            ):
                conn.execute(f"DELETE FROM {table} WHERE paper_id = ?", (paper_id,))
            conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
            conn.commit()
            return {"purged": True, "paper_id": paper_id, "title": title}

        elif name == "venue_refresh":
            import time as _time
            import urllib.request
            import urllib.error

            topic_id = int(arguments["topic_id"])
            # Find papers with stale venues
            stale_venues = ("", "arxiv", "arxiv.org", "arxiv preprint")
            rows = conn.execute(
                """SELECT p.id, p.arxiv_id, p.doi, p.s2_id, p.venue
                   FROM papers p
                   JOIN paper_topics pt ON p.id = pt.paper_id
                   WHERE pt.topic_id = ?
                     AND (p.venue IS NULL OR LOWER(TRIM(p.venue)) IN (?, ?, ?, ?))
                   ORDER BY p.id""",
                (topic_id, *stale_venues),
            ).fetchall()

            updated = []
            skipped = 0
            api_key = os.environ.get("S2_API_KEY") or os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or ""
            for row in rows:
                # Build S2 lookup ID
                lookup_id = None
                if row["arxiv_id"]:
                    clean = (row["arxiv_id"] or "").strip().removeprefix("arxiv:").removeprefix("arXiv:")
                    lookup_id = f"ARXIV:{clean}"
                elif row["doi"]:
                    clean = (row["doi"] or "").strip().removeprefix("doi:").removeprefix("DOI:")
                    lookup_id = f"DOI:{clean}"
                elif row["s2_id"]:
                    lookup_id = (row["s2_id"] or "").strip()
                if not lookup_id:
                    skipped += 1
                    continue

                url = f"https://api.semanticscholar.org/graph/v1/paper/{lookup_id}?fields=venue"
                try:
                    headers = {"User-Agent": "research-harness/1.0"}
                    if api_key:
                        headers["x-api-key"] = api_key
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode())
                    new_venue = (data.get("venue") or "").strip()
                    if new_venue and new_venue.lower() not in stale_venues:
                        conn.execute("UPDATE papers SET venue = ? WHERE id = ?", (new_venue, row["id"]))
                        updated.append({"paper_id": row["id"], "new_venue": new_venue})
                except Exception:
                    pass  # Skip on error, don't block
                _time.sleep(1.05)  # S2 rate limit

            conn.commit()
            return {
                "topic_id": topic_id,
                "stale_count": len(rows),
                "updated_count": len(updated),
                "skipped_no_id": skipped,
                "updated": updated,
            }

        return {"error": f"Unknown convenience tool: {name}"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Orchestrator tools
# ---------------------------------------------------------------------------

_ORCHESTRATOR_TOOLS: dict[str, Tool] = {
    "orchestrator_status": Tool(
        name="orchestrator_status",
        description="Show orchestrator status for a project (current stage, gate, artifacts, issues)",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
            },
            "required": ["project_id"],
        },
    ),
    "orchestrator_advance": Tool(
        name="orchestrator_advance",
        description="Advance the project to the next orchestrator stage (checks gates and artifacts)",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "actor": {"type": "string", "description": "Actor name (default: system)"},
            },
            "required": ["project_id"],
        },
    ),
    "orchestrator_record_artifact": Tool(
        name="orchestrator_record_artifact",
        description="Record a new artifact for the current orchestrator stage",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "stage": {"type": "string", "description": "Stage name"},
                "artifact_type": {"type": "string", "description": "Artifact type"},
                "title": {"type": "string", "description": "Artifact title"},
                "payload": {"type": "object", "description": "Artifact payload as JSON object"},
                "dependency_artifact_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional upstream artifact IDs this artifact depends on",
                },
                "dependency_type": {
                    "type": "string",
                    "description": "Dependency edge type (default: consumed_by)",
                },
            },
            "required": ["project_id", "topic_id", "stage", "artifact_type"],
        },
    ),
    "orchestrator_add_artifact_dependency": Tool(
        name="orchestrator_add_artifact_dependency",
        description="Declare that one artifact depends on another",
        inputSchema={
            "type": "object",
            "properties": {
                "from_artifact_id": {"type": "integer", "description": "Upstream artifact ID"},
                "to_artifact_id": {"type": "integer", "description": "Downstream artifact ID"},
                "dependency_type": {"type": "string", "description": "consumed_by or derived_from"},
            },
            "required": ["from_artifact_id", "to_artifact_id"],
        },
    ),
    "orchestrator_mark_artifact_stale": Tool(
        name="orchestrator_mark_artifact_stale",
        description="Mark an artifact stale and optionally propagate to dependents",
        inputSchema={
            "type": "object",
            "properties": {
                "artifact_id": {"type": "integer", "description": "Artifact ID"},
                "reason": {"type": "string", "description": "Why this artifact is stale"},
                "propagate": {"type": "boolean", "description": "Propagate stale state downstream"},
            },
            "required": ["artifact_id"],
        },
    ),
    "orchestrator_clear_artifact_stale": Tool(
        name="orchestrator_clear_artifact_stale",
        description="Clear stale state for an artifact after acknowledgement or refresh",
        inputSchema={
            "type": "object",
            "properties": {
                "artifact_id": {"type": "integer", "description": "Artifact ID"},
            },
            "required": ["artifact_id"],
        },
    ),
    "orchestrator_list_stale_artifacts": Tool(
        name="orchestrator_list_stale_artifacts",
        description="List active stale artifacts for a project",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
            },
            "required": ["project_id"],
        },
    ),
    "orchestrator_resume": Tool(
        name="orchestrator_resume",
        description=(
            "Resume (or create) an orchestrator run, automatically inferring the current "
            "stage from existing artifacts so projects that predate orchestrator tracking "
            "start at the right stage instead of always at topic_framing. "
            "Pass force_stage to override the inferred stage."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "topic_id": {"type": "integer", "description": "Topic ID"},
                "mode": {"type": "string", "description": "Workflow mode (default: standard)"},
                "force_stage": {
                    "type": "string",
                    "description": "Override inferred stage (optional)",
                },
                "stop_before": {
                    "type": "string",
                    "description": (
                        "Hard stop: advance() will refuse to enter this stage. "
                        "E.g. 'experiment' to auto-run init→build→analyze→propose then stop. "
                        "Pass empty string to clear."
                    ),
                },
            },
            "required": ["project_id", "topic_id"],
        },
    ),
    "orchestrator_gate_check": Tool(
        name="orchestrator_gate_check",
        description="Check the gate for the current or specified stage",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "stage": {"type": "string", "description": "Stage to check (defaults to current)"},
            },
            "required": ["project_id"],
        },
    ),
    "integrity_check": Tool(
        name="integrity_check",
        description="Run 5-phase integrity verification (references, citation context, statistics, originality, claims)",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "phase": {"type": "string", "enum": ["references", "citation_context", "statistical_data", "originality", "claims"]},
                            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                            "category": {"type": "string"},
                            "summary": {"type": "string"},
                            "details": {"type": "string"},
                        },
                        "required": ["phase", "severity", "summary"],
                    },
                    "description": "External findings from agent review",
                },
            },
            "required": ["project_id"],
        },
    ),
    "finalize_project": Tool(
        name="finalize_project",
        description="Create final submission bundle and process summary for a completed project",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
            },
            "required": ["project_id"],
        },
    ),
    "review_bundle_create": Tool(
        name="review_bundle_create",
        description="Create a review bundle linking integrity and scholarly review report artifacts",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "integrity_artifact_id": {"type": "integer", "description": "Integrity report artifact ID"},
                "scholarly_artifact_id": {"type": "integer", "description": "Scholarly report artifact ID"},
            },
            "required": ["project_id"],
        },
    ),
    "review_add_issue": Tool(
        name="review_add_issue",
        description="Add a review finding as an issue (critical/high auto-blocks gate)",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "review_type": {"type": "string", "enum": ["integrity", "scholarly"], "description": "Review type"},
                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"], "description": "Issue severity"},
                "category": {"type": "string", "description": "Issue category (methodology, evidence, writing, etc.)"},
                "summary": {"type": "string", "description": "Issue summary"},
                "details": {"type": "string", "description": "Detailed description"},
                "recommended_action": {"type": "string", "description": "Recommended fix"},
                "review_artifact_id": {"type": "integer", "description": "Source review artifact ID"},
            },
            "required": ["project_id", "review_type", "severity", "category", "summary"],
        },
    ),
    "review_issues": Tool(
        name="review_issues",
        description="List review issues for a project, optionally filtered by stage/status/blocking",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "stage": {"type": "string", "description": "Filter by stage"},
                "status": {"type": "string", "enum": ["open", "in_progress", "resolved", "wontfix"], "description": "Filter by status"},
                "blocking_only": {"type": "boolean", "description": "Show only blocking issues"},
            },
            "required": ["project_id"],
        },
    ),
    "review_respond": Tool(
        name="review_respond",
        description="Record a response to a review issue (change/clarify/dispute/acknowledge)",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "issue_id": {"type": "integer", "description": "Issue ID to respond to"},
                "response_type": {"type": "string", "enum": ["change", "clarify", "dispute", "acknowledge"], "description": "Response type"},
                "response_text": {"type": "string", "description": "Response text"},
                "artifact_id": {"type": "integer", "description": "Linked artifact ID"},
                "evidence": {"type": "object", "description": "Supporting evidence as JSON"},
            },
            "required": ["project_id", "issue_id", "response_type", "response_text"],
        },
    ),
    "review_resolve": Tool(
        name="review_resolve",
        description="Mark a review issue as resolved or wontfix",
        inputSchema={
            "type": "object",
            "properties": {
                "issue_id": {"type": "integer", "description": "Issue ID to resolve"},
                "status": {"type": "string", "enum": ["resolved", "wontfix"], "description": "Resolution status"},
            },
            "required": ["issue_id", "status"],
        },
    ),
    "review_status": Tool(
        name="review_status",
        description="Get review summary: issue counts, decision, cycle info, gate status",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
            },
            "required": ["project_id"],
        },
    ),
    "adversarial_run": Tool(
        name="adversarial_run",
        description="Run an adversarial round: submit proposal with objections for challenge",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "artifact_id": {"type": "integer", "description": "Target artifact ID to review"},
                "proposal_snapshot": {"type": "object", "description": "Proposal snapshot as JSON"},
                "objections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string"},
                            "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                            "target": {"type": "string"},
                            "reasoning": {"type": "string"},
                            "suggested_fix": {"type": "string"},
                        },
                        "required": ["category", "severity", "target", "reasoning"],
                    },
                    "description": "List of objections",
                },
                "proposer_responses": {"type": "array", "description": "Proposer responses to objections"},
                "resolver_notes": {"type": "string", "description": "Resolver notes"},
            },
            "required": ["project_id", "artifact_id", "proposal_snapshot", "objections"],
        },
    ),
    "adversarial_resolve": Tool(
        name="adversarial_resolve",
        description="Resolve an adversarial round with scores and determine outcome",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "round_artifact_id": {"type": "integer", "description": "Round artifact ID to resolve"},
                "scores": {"type": "object", "description": "Dimension scores as JSON (e.g. {\"novelty\": 4.5})"},
                "notes": {"type": "string", "description": "Resolution notes"},
            },
            "required": ["project_id", "round_artifact_id"],
        },
    ),
    "adversarial_status": Tool(
        name="adversarial_status",
        description="Check adversarial optimization status for a project",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
            },
            "required": ["project_id"],
        },
    ),
    "adversarial_review": Tool(
        name="adversarial_review",
        description=(
            "Run an independent cross-model adversarial review on a project artifact. "
            "Automatically dispatches to a DIFFERENT model than the current executor: "
            "Claude sessions → Codex/GPT review, Codex sessions → Anthropic Opus review. "
            "Returns structured verdict with issues/scores and auto-records as adversarial_round artifact."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Project ID"},
                "artifact_id": {"type": "integer", "description": "Artifact ID to review"},
                "focus": {"type": "string", "description": "Review focus (e.g. 'novelty and method soundness')"},
                "evidence_summary": {"type": "string", "description": "Optional evidence summary to provide reviewer context"},
            },
            "required": ["project_id", "artifact_id"],
        },
    ),
}


def _execute_adversarial_review(
    svc: Any,
    db: Any,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Run cross-model adversarial review and persist as artifact.

    Dispatches to a different model than the current executor:
    - Default (Claude sessions): calls ``codex exec`` (OpenAI/GPT model)
    - RESEARCH_HARNESS_ADVERSARIAL_BACKEND=anthropic (Codex sessions):
      calls Anthropic Opus API

    Returns structured verdict and records an ``adversarial_round`` artifact.
    """
    from research_harness.auto_runner.codex_bridge import (
        codex_issues_to_objections,
        run_codex_review,
    )

    project_id = arguments["project_id"]
    artifact_id = arguments["artifact_id"]
    focus = arguments.get("focus", "")
    evidence_summary = arguments.get("evidence_summary", "")

    # Get the run to know current stage and topic
    run = svc.get_run(project_id)
    if run is None:
        return {"success": False, "error": "No orchestrator run found for this project"}

    # Get artifact content for context
    artifact = svc._artifact_manager.get(artifact_id)
    if artifact is None:
        return {"success": False, "error": f"Artifact {artifact_id} not found"}

    # Build evidence from artifact payload
    artifact_content = json.dumps(artifact.payload, ensure_ascii=False, indent=2)[:3000]
    if evidence_summary:
        full_evidence = f"{evidence_summary}\n\nArtifact content:\n{artifact_content}"
    else:
        full_evidence = f"Artifact content:\n{artifact_content}"

    # Dispatch to independent reviewer (codex exec or Anthropic Opus)
    review = run_codex_review(
        artifact_path=Path(artifact.path) if artifact.path else Path(f"artifact_{artifact_id}"),
        stage=run.current_stage,
        focus=focus or f"Review {artifact.artifact_type} artifact",
        evidence_summary=full_evidence,
    )

    if not review.get("success"):
        return {
            "success": False,
            "error": f"Adversarial review failed: {review.get('error', 'unknown')}",
            "backend": review.get("backend", "unknown"),
        }

    # Convert review issues to adversarial objections
    objections = codex_issues_to_objections(review.get("issues", []))

    # Build proposal snapshot from artifact
    proposal_snapshot = {
        "artifact_id": artifact_id,
        "artifact_type": artifact.artifact_type,
        "stage": artifact.stage,
        "title": artifact.title,
        "content_preview": artifact_content[:1000],
    }

    # Record as adversarial round
    round_result = svc.run_adversarial_round(
        project_id=project_id,
        target_artifact_id=artifact_id,
        proposal_snapshot=proposal_snapshot,
        objections=[
            {
                "category": o.get("category", "general"),
                "severity": o.get("severity", "minor"),
                "target": o.get("target", ""),
                "reasoning": o.get("reasoning", ""),
                "suggested_fix": o.get("suggested_fix", ""),
            }
            for o in objections
        ],
    )

    # Auto-resolve with scores from review
    scores = review.get("scores", {})
    if scores and round_result.get("success"):
        resolve_result = svc.resolve_adversarial_round(
            project_id=project_id,
            round_artifact_id=round_result["artifact_id"],
            scores=scores,
            notes=review.get("notes", ""),
        )
    else:
        resolve_result = {}

    return {
        "success": True,
        "verdict": review.get("verdict", ""),
        "issues_count": len(objections),
        "critical_count": sum(1 for o in objections if o.get("severity") == "critical"),
        "major_count": sum(1 for o in objections if o.get("severity") == "major"),
        "scores": scores,
        "notes": review.get("notes", ""),
        "round_artifact_id": round_result.get("artifact_id"),
        "resolution_artifact_id": resolve_result.get("artifact_id"),
        "backend": review.get("backend", "unknown"),
        "model": review.get("model", ""),
        "stage": run.current_stage,
    }


def _execute_orchestrator(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute an orchestrator tool."""
    from research_harness.orchestrator import OrchestratorService
    from research_harness.orchestrator.stages import resolve_stage

    db = _resolve_db()
    svc = OrchestratorService(db)

    # Normalize legacy stage names in arguments
    if "stage" in arguments:
        arguments["stage"] = resolve_stage(arguments["stage"])
    if "force_stage" in arguments:
        arguments["force_stage"] = resolve_stage(arguments["force_stage"])

    if name == "orchestrator_resume":
        stop_before = arguments.get("stop_before")
        if stop_before:
            stop_before = resolve_stage(stop_before)
        run = svc.resume_run(
            project_id=arguments["project_id"],
            topic_id=arguments["topic_id"],
            mode=arguments.get("mode", "standard"),
            force_stage=arguments.get("force_stage"),
            stop_before=stop_before,
        )
        inferred = svc.infer_stage_from_artifacts(arguments["project_id"])
        result = {
            "success": True,
            "run_id": run.id,
            "project_id": run.project_id,
            "current_stage": run.current_stage,
            "inferred_stage": inferred,
            "stage_status": run.stage_status,
        }
        if run.stop_before:
            result["stop_before"] = run.stop_before
        return result

    if name == "orchestrator_status":
        status = svc.get_status(arguments["project_id"])
        # Include db_path for debugging (Bug: DB path inconsistency)
        status["db_path"] = str(db.db_path)
        return status

    elif name == "orchestrator_advance":
        return svc.advance(
            arguments["project_id"],
            actor=arguments.get("actor", "system"),
        )

    elif name == "orchestrator_record_artifact":
        artifact = svc.record_artifact(
            project_id=arguments["project_id"],
            topic_id=arguments["topic_id"],
            stage=arguments["stage"],
            artifact_type=arguments["artifact_type"],
            title=arguments.get("title", ""),
            payload=arguments.get("payload"),
            dependency_artifact_ids=arguments.get("dependency_artifact_ids"),
            dependency_type=arguments.get("dependency_type", "consumed_by"),
        )
        return {
            "success": True,
            "artifact_id": artifact.id,
            "version": artifact.version,
            "stage": artifact.stage,
            "type": artifact.artifact_type,
        }

    elif name == "orchestrator_add_artifact_dependency":
        return svc.add_artifact_dependency(
            from_artifact_id=arguments["from_artifact_id"],
            to_artifact_id=arguments["to_artifact_id"],
            dependency_type=arguments.get("dependency_type", "consumed_by"),
        )

    elif name == "orchestrator_mark_artifact_stale":
        return svc.mark_artifact_stale(
            artifact_id=arguments["artifact_id"],
            reason=arguments.get("reason", ""),
            propagate=arguments.get("propagate", True),
        )

    elif name == "orchestrator_clear_artifact_stale":
        return svc.clear_artifact_stale(arguments["artifact_id"])

    elif name == "orchestrator_list_stale_artifacts":
        artifacts = svc.list_stale_artifacts(arguments["project_id"])
        return {
            "artifacts": [asdict(artifact) for artifact in artifacts],
            "count": len(artifacts),
        }

    elif name == "orchestrator_gate_check":
        decision = svc.check_gate(
            arguments["project_id"],
            stage=arguments.get("stage"),
        )
        return {"gate_decision": decision}

    elif name == "integrity_check":
        return svc.run_integrity_check(
            project_id=arguments["project_id"],
            findings=arguments.get("findings"),
        )

    elif name == "finalize_project":
        return svc.finalize_project(
            project_id=arguments["project_id"],
        )

    elif name == "review_bundle_create":
        return svc.create_review_bundle(
            project_id=arguments["project_id"],
            integrity_artifact_id=arguments.get("integrity_artifact_id"),
            scholarly_artifact_id=arguments.get("scholarly_artifact_id"),
        )

    elif name == "review_add_issue":
        return svc.add_review_issue(
            project_id=arguments["project_id"],
            review_type=arguments["review_type"],
            severity=arguments["severity"],
            category=arguments["category"],
            summary=arguments["summary"],
            details=arguments.get("details", ""),
            recommended_action=arguments.get("recommended_action", ""),
            review_artifact_id=arguments.get("review_artifact_id"),
        )

    elif name == "review_issues":
        return {
            "issues": svc.list_review_issues(
                project_id=arguments["project_id"],
                stage=arguments.get("stage"),
                status=arguments.get("status"),
                blocking_only=arguments.get("blocking_only", False),
            )
        }

    elif name == "review_respond":
        return svc.respond_to_issue(
            issue_id=arguments["issue_id"],
            project_id=arguments["project_id"],
            response_type=arguments["response_type"],
            response_text=arguments["response_text"],
            artifact_id=arguments.get("artifact_id"),
            evidence=arguments.get("evidence"),
        )

    elif name == "review_resolve":
        return svc.resolve_review_issue(
            issue_id=arguments["issue_id"],
            resolution_status=arguments["status"],
        )

    elif name == "review_status":
        return svc.get_review_status(arguments["project_id"])

    elif name == "adversarial_run":
        return svc.run_adversarial_round(
            project_id=arguments["project_id"],
            target_artifact_id=arguments["artifact_id"],
            proposal_snapshot=arguments["proposal_snapshot"],
            objections=arguments["objections"],
            proposer_responses=arguments.get("proposer_responses"),
            resolver_notes=arguments.get("resolver_notes", ""),
        )

    elif name == "adversarial_resolve":
        return svc.resolve_adversarial_round(
            project_id=arguments["project_id"],
            round_artifact_id=arguments["round_artifact_id"],
            scores=arguments.get("scores", {}),
            notes=arguments.get("notes", ""),
        )

    elif name == "adversarial_status":
        return svc.check_adversarial_status(arguments["project_id"])

    elif name == "adversarial_review":
        return _execute_adversarial_review(svc, db, arguments)

    return {"error": f"Unknown orchestrator tool: {name}"}


# ---------------------------------------------------------------------------
# Paperindex tools
# ---------------------------------------------------------------------------

_PAPERINDEX_TOOLS: dict[str, Tool] = {
    "paperindex_search": Tool(
        name="paperindex_search",
        description="Search the local paper library by keyword",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        },
    ),
    "paperindex_structure": Tool(
        name="paperindex_structure",
        description="Extract hierarchical structure from a PDF file",
        inputSchema={
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "description": "Path to PDF file"},
            },
            "required": ["pdf_path"],
        },
    ),
    "paperindex_card": Tool(
        name="paperindex_card",
        description="Build a comprehensive paper card from a PDF",
        inputSchema={
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "description": "Path to PDF file"},
            },
            "required": ["pdf_path"],
        },
    ),
}


def _execute_paperindex(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a paperindex tool."""
    from paperindex import PaperIndexer

    indexer = PaperIndexer()

    if name == "paperindex_search":
        ws = find_workspace_root()
        library_root = str(ws / ".paperindex") if ws else ".paperindex"
        results = indexer.search(
            arguments["query"],
            library_root=library_root,
            limit=arguments.get("limit", 5),
        )
        return {"results": [r.to_dict() for r in results]}

    elif name == "paperindex_structure":
        structure = indexer.extract_structure(arguments["pdf_path"])
        return structure.to_dict()

    elif name == "paperindex_card":
        record = indexer.build_record(arguments["pdf_path"])
        card = record.card or {}
        return card

    return {"error": f"Unknown paperindex tool: {name}"}


# ---------------------------------------------------------------------------
# Acquisition tools
# ---------------------------------------------------------------------------

_ACQUISITION_TOOLS: dict[str, Tool] = {
    # NOTE: paper_acquire is registered as a primitive (PAPER_ACQUIRE_SPEC); do not re-declare here.
    "paper_ingest_manual": Tool(
        name="paper_ingest_manual",
        description="Ingest manually downloaded PDFs from the manual_downloads directory",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    "paper_resolve_pdfs": Tool(
        name="paper_resolve_pdfs",
        description="Discover existing PDFs on disk and link them to papers.pdf_path in the DB. Use this to fix papers that have PDFs downloaded but pdf_path is empty.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "Topic ID to scope resolution (optional, resolves all if omitted)"},
                "dry_run": {"type": "boolean", "description": "If true, report matches without writing to DB", "default": False},
            },
        },
    ),
}


def _execute_acquisition(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute an acquisition tool."""
    db = _resolve_db()

    if name == "paper_ingest_manual":
        from research_harness.acquisition.pipeline import ingest_manual_downloads
        results = ingest_manual_downloads(db)
        return {"results": results, "count": len(results)}

    elif name == "paper_resolve_pdfs":
        from research_harness.acquisition.pdf_resolver import backfill_pdf_paths
        stats = backfill_pdf_paths(
            db,
            topic_id=arguments.get("topic_id"),
            dry_run=arguments.get("dry_run", False),
        )
        return stats.to_dict()

    return {"error": f"Unknown acquisition tool: {name}"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_PRIMITIVE_NAMES: set[str] = set()


def list_tool_definitions() -> list[Tool]:
    """Return all MCP tool definitions."""
    global _PRIMITIVE_NAMES
    primitive_tools = _primitive_tool_definitions()
    _PRIMITIVE_NAMES = {t.name for t in primitive_tools}
    return (
        primitive_tools
        + list(_CONVENIENCE_TOOLS.values())
        + list(_ORCHESTRATOR_TOOLS.values())
        + list(_PAPERINDEX_TOOLS.values())
        + list(_ACQUISITION_TOOLS.values())
    )


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route and execute any tool by name.

    All results are wrapped in HarnessResponse envelope for uniform
    agent guidance (status, summary, next_actions, recovery_hint).
    """
    # Ensure names are populated
    if not _PRIMITIVE_NAMES:
        list_tool_definitions()

    if name in _PRIMITIVE_NAMES:
        return _execute_primitive(name, arguments)
    elif name in _CONVENIENCE_TOOLS:
        raw = _execute_convenience(name, arguments)
        db = _resolve_db()
        orch_state = _try_get_orch_state(db, _extract_topic_id(arguments))
        session_advisory = _maybe_session_advisory(db, name, arguments, orch_state)
        return _wrap_convenience(name, raw, session_advisory=session_advisory)
    elif name in _ORCHESTRATOR_TOOLS:
        raw = _execute_orchestrator(name, arguments)
        return _wrap_orchestrator(name, raw)
    elif name in _PAPERINDEX_TOOLS:
        raw = _execute_paperindex(name, arguments)
        return _wrap_convenience(name, raw)  # reuse convenience wrapper
    elif name in _ACQUISITION_TOOLS:
        raw = _execute_acquisition(name, arguments)
        return _wrap_convenience(name, raw)
    else:
        return _wrap_convenience(name, {"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize_result(
    result: PrimitiveResult,
    orch_state: dict[str, Any] | None = None,
    session_advisory: str = "",
    nudge: str = "",
) -> dict[str, Any]:
    """Convert PrimitiveResult to a HarnessResponse-shaped dict.

    Follows the Agent Harness pattern: every tool response includes
    status, summary, next_actions, artifacts, and recovery_hint.
    """
    from research_harness.execution.harness_actions import (
        classify_error,
        compute_next_actions,
        compute_summary,
        extract_artifacts,
    )

    output = result.output
    if output is not None and hasattr(output, "__dataclass_fields__"):
        output = asdict(output)
    resp: dict[str, Any] = {
        "status": "success" if result.success else "error",
        "summary": compute_summary(result.primitive, result),
        "output": output,
        "next_actions": compute_next_actions(result.primitive, result, orch_state),
        "artifacts": extract_artifacts(result),
        "recovery_hint": classify_error(result.error) if not result.success else "",
        "primitive": result.primitive,
        "backend": result.backend,
        "model_used": result.model_used,
        "cost_usd": result.cost_usd,
        "session_advisory": session_advisory,
    }
    if nudge:
        resp["nudge"] = nudge
    return resp


def _wrap_convenience(name: str, raw: dict[str, Any], session_advisory: str = "") -> dict[str, Any]:
    """Wrap a convenience tool result in HarnessResponse envelope."""
    is_error = "error" in raw
    return {
        "status": "error" if is_error else "success",
        "summary": raw.get("error", f"{name} completed"),
        "output": raw,
        "next_actions": [],
        "artifacts": [],
        "recovery_hint": classify_error(raw["error"]) if is_error else "",
        "primitive": name,
        "backend": "local",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": session_advisory,
    }


def _wrap_orchestrator(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Wrap an orchestrator tool result in HarnessResponse envelope."""
    is_error = "error" in raw
    summary = raw.get("error", "")
    next_actions: list[str] = []

    if not is_error:
        if name == "orchestrator_status":
            run = raw.get("run", {})
            gate = raw.get("gate", {})
            stage = run.get("current_stage", "?")
            summary = f"Stage: {stage}, gate: {gate.get('decision', '?')}"
            if gate.get("can_advance"):
                next_actions.append(
                    f"orchestrator_advance — gate passed, ready to move past {stage}"
                )
            missing = raw.get("stage", {}).get("missing_artifacts", [])
            if missing:
                next_actions.append(
                    f"Record missing artifacts: {', '.join(missing)}"
                )
        elif name == "orchestrator_resume":
            stage = raw.get("current_stage", "?")
            inferred = raw.get("inferred_stage", stage)
            summary = f"Resumed run at stage: {stage} (inferred from artifacts: {inferred})"
            next_actions.append("orchestrator_status — check current stage requirements")
        elif name == "orchestrator_advance":
            summary = f"Advanced to next stage"
            next_actions.append("orchestrator_status — check new stage requirements")
        elif name == "orchestrator_record_artifact":
            summary = f"Recorded artifact: {raw.get('type', '?')} (id={raw.get('artifact_id', '?')})"
            next_actions.append("orchestrator_gate_check — check if gate now passes")
        elif name == "orchestrator_add_artifact_dependency":
            summary = (
                f"Linked artifact {raw.get('to_artifact_id', '?')} to upstream "
                f"{raw.get('from_artifact_id', '?')}"
            )
        elif name == "orchestrator_mark_artifact_stale":
            count = len(raw.get("stale_ids", []))
            summary = f"Marked {count} artifact(s) stale"
            next_actions.append("orchestrator_list_stale_artifacts — inspect affected downstream artifacts")
        elif name == "orchestrator_clear_artifact_stale":
            summary = f"Cleared stale flag for artifact {raw.get('artifact_id', '?')}"
        elif name == "orchestrator_list_stale_artifacts":
            count = raw.get("count", 0)
            summary = f"{count} stale artifact(s) currently active"
            if count:
                next_actions.append("Refresh or supersede stale artifacts, then clear flags if appropriate")
        elif name == "orchestrator_gate_check":
            decision = raw.get("gate_decision", "?")
            summary = f"Gate decision: {decision}"
            if decision == "pass":
                next_actions.append("orchestrator_advance — gate passed")
            elif decision == "fail":
                next_actions.append("orchestrator_status — check what's missing")
        elif name == "adversarial_review":
            verdict = raw.get("verdict", "?")
            backend = raw.get("backend", "?")
            issues = raw.get("issues_count", 0)
            critical = raw.get("critical_count", 0)
            summary = (
                f"Independent review ({backend}): verdict={verdict}, "
                f"{issues} issues ({critical} critical)"
            )
            if verdict == "revise":
                next_actions.append("Address critical/major issues, then re-run adversarial_review")
            else:
                next_actions.append("orchestrator_gate_check — check if ready to advance")
        else:
            summary = f"{name} completed"

    resp: dict[str, Any] = {
        "status": "error" if is_error else "success",
        "summary": summary,
        "output": raw,
        "next_actions": next_actions,
        "artifacts": [],
        "recovery_hint": classify_error(raw["error"]) if is_error else "",
        "primitive": name,
        "backend": "orchestrator",
        "model_used": "",
        "cost_usd": 0.0,
        "session_advisory": "",
    }

    # Auto-inject strategy overlay for stage-aware orchestrator tools
    if not is_error and name in ("orchestrator_status", "orchestrator_resume", "orchestrator_advance"):
        strategy_overlay = _inject_strategy_overlay(raw)
        if strategy_overlay:
            resp["strategy_overlay"] = strategy_overlay

    return resp
