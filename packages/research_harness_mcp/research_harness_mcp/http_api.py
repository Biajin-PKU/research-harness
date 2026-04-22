"""FastAPI HTTP API for research-harness — REST endpoints for the Next.js frontend.

Wraps the SQLite pool.db as JSON endpoints with pagination, search, and CORS.
Write/action endpoints delegate to MCP tool handlers via execute_tool().
Run standalone: python -m research_harness_mcp.http_api
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from research_harness_mcp.tools import execute_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / ".research-harness" / "pool.db"

DB_PATH = Path(os.environ.get("RESEARCH_HARNESS_DB_PATH") or str(_DEFAULT_DB_PATH))


@contextmanager
def get_db():
    """Yield a sqlite3 connection with Row factory and WAL mode."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [_row_to_dict(r) for r in rows]


def _parse_json_field(value: str | None, fallback: Any = None) -> Any:
    """Safely parse a JSON string field. Returns fallback on failure."""
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class PaginationMeta(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class PaginatedResponse(BaseModel):
    data: list[dict[str, Any]]
    pagination: PaginationMeta


class TopicSummary(BaseModel):
    id: int
    name: str
    description: str
    status: str
    target_venue: str
    deadline: str
    created_at: str
    paper_count: int


class TopicDetail(BaseModel):
    id: int
    name: str
    description: str
    status: str
    target_venue: str
    deadline: str
    created_at: str
    paper_count: int
    project_count: int
    annotation_count: int
    stages: dict[str, int]  # stage -> artifact count


class ProjectSummary(BaseModel):
    id: int
    topic_id: int
    topic_name: str
    name: str
    description: str
    status: str
    target_venue: str
    deadline: str
    created_at: str
    updated_at: str
    current_stage: str | None
    stage_status: str | None
    gate_status: str | None


class ProjectDetail(BaseModel):
    id: int
    topic_id: int
    topic_name: str
    name: str
    description: str
    status: str
    target_venue: str
    deadline: str
    contributions: str
    created_at: str
    updated_at: str
    current_stage: str | None
    stage_status: str | None
    gate_status: str | None
    mode: str | None
    stop_before: str | None
    blocking_issue_count: int
    unresolved_issue_count: int
    artifact_counts: dict[str, int]


class PaperDetail(BaseModel):
    id: int
    title: str
    authors: list[Any]
    year: int | None
    venue: str
    doi: str
    arxiv_id: str
    s2_id: str
    url: str
    abstract: str
    citation_count: int | None
    status: str
    pdf_path: str
    created_at: str
    annotations: list[dict[str, Any]]
    topics: list[dict[str, Any]]


class DashboardStats(BaseModel):
    total_papers: int
    total_topics: int
    total_projects: int
    total_artifacts: int
    total_provenance_records: int
    papers_with_pdf: int
    recent_papers: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]


class ProvenanceSummary(BaseModel):
    total_records: int
    total_cost_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    by_backend: list[dict[str, Any]]
    by_primitive: list[dict[str, Any]]
    recent_records: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Research Harness API",
    description="REST API for the research-harness pool.db — read endpoints + write/action endpoints via MCP tools",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health_check():
    """Basic liveness probe."""
    exists = DB_PATH.exists()
    return {"status": "ok" if exists else "db_missing", "db_path": str(DB_PATH)}


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


@app.get("/api/topics", response_model=list[TopicSummary])
def list_topics():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT t.*,
                   COUNT(pt.paper_id) AS paper_count
            FROM topics t
            LEFT JOIN paper_topics pt ON pt.topic_id = t.id
            GROUP BY t.id
            ORDER BY t.id
            """
        ).fetchall()
    return [
        TopicSummary(
            id=r["id"],
            name=r["name"],
            description=r["description"] or "",
            status=r["status"] or "active",
            target_venue=r["target_venue"] or "",
            deadline=r["deadline"] or "",
            created_at=r["created_at"] or "",
            paper_count=r["paper_count"],
        )
        for r in rows
    ]


@app.get("/api/topics/{topic_id}", response_model=TopicDetail)
def get_topic(topic_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")

        paper_count = conn.execute(
            "SELECT COUNT(*) AS c FROM paper_topics WHERE topic_id = ?", (topic_id,)
        ).fetchone()["c"]

        project_count = conn.execute(
            "SELECT COUNT(*) AS c FROM projects WHERE topic_id = ?", (topic_id,)
        ).fetchone()["c"]

        annotation_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM paper_annotations pa
            JOIN paper_topics pt ON pt.paper_id = pa.paper_id
            WHERE pt.topic_id = ?
            """,
            (topic_id,),
        ).fetchone()["c"]

        # Artifact counts per stage for projects under this topic
        stage_rows = conn.execute(
            """
            SELECT pa.stage, COUNT(*) AS cnt
            FROM project_artifacts pa
            WHERE pa.topic_id = ?
            GROUP BY pa.stage
            """,
            (topic_id,),
        ).fetchall()
        stages = {r["stage"]: r["cnt"] for r in stage_rows}

    return TopicDetail(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        status=row["status"] or "active",
        target_venue=row["target_venue"] or "",
        deadline=row["deadline"] or "",
        created_at=row["created_at"] or "",
        paper_count=paper_count,
        project_count=project_count,
        annotation_count=annotation_count,
        stages=stages,
    )


@app.get("/api/topics/{topic_id}/papers", response_model=PaginatedResponse)
def list_topic_papers(
    topic_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query("", description="Search in title/authors/venue"),
    sort: str = Query(
        "created_at", description="Sort field: created_at, year, title, citation_count"
    ),
    order: str = Query("desc", description="asc or desc"),
):
    with get_db() as conn:
        # Verify topic exists
        topic = conn.execute(
            "SELECT id FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic:
            raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")

        allowed_sort = {"created_at", "year", "title", "citation_count", "venue"}
        sort_col = sort if sort in allowed_sort else "created_at"
        sort_dir = "ASC" if order.lower() == "asc" else "DESC"

        base_where = "pt.topic_id = ?"
        params: list[Any] = [topic_id]

        if search:
            base_where += " AND (p.title LIKE ? OR p.authors LIKE ? OR p.venue LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like])

        count_sql = f"SELECT COUNT(*) AS c FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id WHERE {base_where}"
        total = conn.execute(count_sql, params).fetchone()["c"]

        offset = (page - 1) * per_page
        data_sql = f"""
            SELECT p.*, pt.relevance
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE {base_where}
            ORDER BY p.{sort_col} {sort_dir}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(data_sql, [*params, per_page, offset]).fetchall()

    papers = []
    for r in rows:
        d = _row_to_dict(r)
        d["authors"] = _parse_json_field(d.get("authors"), [])
        papers.append(d)

    total_pages = max(1, (total + per_page - 1) // per_page)
    return PaginatedResponse(
        data=papers,
        pagination=PaginationMeta(
            page=page, per_page=per_page, total=total, total_pages=total_pages
        ),
    )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@app.get("/api/projects", response_model=list[ProjectSummary])
def list_projects():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT p.*,
                   t.name AS topic_name,
                   o.current_stage,
                   o.stage_status,
                   o.gate_status
            FROM projects p
            JOIN topics t ON t.id = p.topic_id
            LEFT JOIN orchestrator_runs o ON o.project_id = p.id
            ORDER BY p.updated_at DESC
            """
        ).fetchall()
    return [
        ProjectSummary(
            id=r["id"],
            topic_id=r["topic_id"],
            topic_name=r["topic_name"],
            name=r["name"],
            description=r["description"] or "",
            status=r["status"] or "planning",
            target_venue=r["target_venue"] or "",
            deadline=r["deadline"] or "",
            created_at=r["created_at"] or "",
            updated_at=r["updated_at"] or "",
            current_stage=r["current_stage"],
            stage_status=r["stage_status"],
            gate_status=r["gate_status"],
        )
        for r in rows
    ]


@app.get("/api/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT p.*,
                   t.name AS topic_name,
                   o.current_stage,
                   o.stage_status,
                   o.gate_status,
                   o.mode,
                   o.stop_before,
                   o.blocking_issue_count,
                   o.unresolved_issue_count
            FROM projects p
            JOIN topics t ON t.id = p.topic_id
            LEFT JOIN orchestrator_runs o ON o.project_id = p.id
            WHERE p.id = ?
            """,
            (project_id,),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=404, detail=f"Project {project_id} not found"
            )

        # Artifact counts per stage
        art_rows = conn.execute(
            """
            SELECT stage, COUNT(*) AS cnt
            FROM project_artifacts
            WHERE project_id = ?
            GROUP BY stage
            """,
            (project_id,),
        ).fetchall()
        artifact_counts = {r["stage"]: r["cnt"] for r in art_rows}

    return ProjectDetail(
        id=row["id"],
        topic_id=row["topic_id"],
        topic_name=row["topic_name"],
        name=row["name"],
        description=row["description"] or "",
        status=row["status"] or "planning",
        target_venue=row["target_venue"] or "",
        deadline=row["deadline"] or "",
        contributions=row["contributions"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        current_stage=row["current_stage"],
        stage_status=row["stage_status"],
        gate_status=row["gate_status"],
        mode=row["mode"],
        stop_before=row["stop_before"],
        blocking_issue_count=row["blocking_issue_count"] or 0,
        unresolved_issue_count=row["unresolved_issue_count"] or 0,
        artifact_counts=artifact_counts,
    )


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------


@app.get("/api/papers", response_model=PaginatedResponse)
def list_papers(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query("", description="Search in title/authors/venue"),
    topic_id: int | None = Query(None, description="Filter by topic"),
    status: str | None = Query(None, description="Filter by paper status"),
    sort: str = Query("created_at", description="Sort field"),
    order: str = Query("desc", description="asc or desc"),
):
    with get_db() as conn:
        conditions: list[str] = []
        params: list[Any] = []

        if topic_id is not None:
            conditions.append("pt.topic_id = ?")
            params.append(topic_id)

        if status:
            conditions.append("p.status = ?")
            params.append(status)

        if search:
            conditions.append("(p.title LIKE ? OR p.authors LIKE ? OR p.venue LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        join_clause = ""
        if topic_id is not None:
            join_clause = "JOIN paper_topics pt ON pt.paper_id = p.id"
        else:
            join_clause = "LEFT JOIN paper_topics pt ON pt.paper_id = p.id"

        # Use DISTINCT to avoid duplicate rows when paper belongs to multiple topics
        count_sql = f"SELECT COUNT(DISTINCT p.id) AS c FROM papers p {join_clause} {where_clause}"
        total = conn.execute(count_sql, params).fetchone()["c"]

        allowed_sort = {"created_at", "year", "title", "citation_count", "venue", "id"}
        sort_col = sort if sort in allowed_sort else "created_at"
        sort_dir = "ASC" if order.lower() == "asc" else "DESC"
        offset = (page - 1) * per_page

        data_sql = f"""
            SELECT DISTINCT p.*
            FROM papers p
            {join_clause}
            {where_clause}
            ORDER BY p.{sort_col} {sort_dir}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(data_sql, [*params, per_page, offset]).fetchall()

    papers = []
    for r in rows:
        d = _row_to_dict(r)
        d["authors"] = _parse_json_field(d.get("authors"), [])
        papers.append(d)

    total_pages = max(1, (total + per_page - 1) // per_page)
    return PaginatedResponse(
        data=papers,
        pagination=PaginationMeta(
            page=page, per_page=per_page, total=total, total_pages=total_pages
        ),
    )


@app.get("/api/papers/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")

        ann_rows = conn.execute(
            """
            SELECT id, section, content, source, confidence, created_at, updated_at
            FROM paper_annotations
            WHERE paper_id = ?
            ORDER BY section
            """,
            (paper_id,),
        ).fetchall()

        topic_rows = conn.execute(
            """
            SELECT t.id, t.name, pt.relevance
            FROM topics t
            JOIN paper_topics pt ON pt.topic_id = t.id
            WHERE pt.paper_id = ?
            """,
            (paper_id,),
        ).fetchall()

    annotations = []
    for a in ann_rows:
        d = _row_to_dict(a)
        d["content"] = _parse_json_field(d.get("content"), d.get("content"))
        annotations.append(d)

    return PaperDetail(
        id=row["id"],
        title=row["title"] or "",
        authors=_parse_json_field(row["authors"], []),
        year=row["year"],
        venue=row["venue"] or "",
        doi=row["doi"] or "",
        arxiv_id=row["arxiv_id"] or "",
        s2_id=row["s2_id"] or "",
        url=row["url"] or "",
        abstract=row["abstract"] or "",
        citation_count=row["citation_count"],
        status=row["status"] or "meta_only",
        pdf_path=row["pdf_path"] or "",
        created_at=row["created_at"] or "",
        annotations=annotations,
        topics=_rows_to_list(topic_rows),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@app.get("/api/projects/{project_id}/artifacts")
def list_project_artifacts(
    project_id: int,
    stage: str | None = Query(None, description="Filter by stage"),
):
    with get_db() as conn:
        proj = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not proj:
            raise HTTPException(
                status_code=404, detail=f"Project {project_id} not found"
            )

        conditions = ["project_id = ?"]
        params: list[Any] = [project_id]
        if stage:
            conditions.append("stage = ?")
            params.append(stage)

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""
            SELECT id, project_id, topic_id, stage, artifact_type, status,
                   version, title, path, payload_json, metadata_json,
                   parent_artifact_id, created_at, updated_at
            FROM project_artifacts
            WHERE {where}
            ORDER BY stage, created_at DESC
            """,
            params,
        ).fetchall()

    # Group by stage
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        d = _row_to_dict(r)
        d["payload"] = _parse_json_field(d.pop("payload_json", None), {})
        d["metadata"] = _parse_json_field(d.pop("metadata_json", None), {})
        grouped.setdefault(d["stage"], []).append(d)

    return {"project_id": project_id, "artifacts_by_stage": grouped}


@app.get("/api/projects/{project_id}/events")
def list_project_events(project_id: int):
    with get_db() as conn:
        proj = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not proj:
            raise HTTPException(
                status_code=404, detail=f"Project {project_id} not found"
            )

        rows = conn.execute(
            """
            SELECT e.*
            FROM orchestrator_stage_events e
            JOIN orchestrator_runs r ON r.id = e.run_id
            WHERE r.project_id = ?
            ORDER BY e.created_at DESC
            """,
            (project_id,),
        ).fetchall()

    events = []
    for r in rows:
        d = _row_to_dict(r)
        d["payload"] = _parse_json_field(d.pop("payload_json", None), {})
        events.append(d)

    return {"project_id": project_id, "events": events}


# ---------------------------------------------------------------------------
# Stats / Dashboard
# ---------------------------------------------------------------------------


@app.get("/api/stats", response_model=DashboardStats)
def dashboard_stats():
    with get_db() as conn:
        total_papers = conn.execute("SELECT COUNT(*) AS c FROM papers").fetchone()["c"]
        total_topics = conn.execute("SELECT COUNT(*) AS c FROM topics").fetchone()["c"]
        total_projects = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()[
            "c"
        ]
        total_artifacts = conn.execute(
            "SELECT COUNT(*) AS c FROM project_artifacts"
        ).fetchone()["c"]
        total_provenance = conn.execute(
            "SELECT COUNT(*) AS c FROM provenance_records"
        ).fetchone()["c"]
        papers_with_pdf = conn.execute(
            "SELECT COUNT(*) AS c FROM papers WHERE pdf_path IS NOT NULL AND pdf_path != ''"
        ).fetchone()["c"]

        recent_papers = conn.execute(
            """
            SELECT id, title, venue, year, status, created_at
            FROM papers
            ORDER BY created_at DESC
            LIMIT 10
            """
        ).fetchall()

        recent_events = conn.execute(
            """
            SELECT e.id, e.project_id, e.from_stage, e.to_stage,
                   e.event_type, e.status, e.actor, e.created_at
            FROM orchestrator_stage_events e
            ORDER BY e.created_at DESC
            LIMIT 10
            """
        ).fetchall()

    return DashboardStats(
        total_papers=total_papers,
        total_topics=total_topics,
        total_projects=total_projects,
        total_artifacts=total_artifacts,
        total_provenance_records=total_provenance,
        papers_with_pdf=papers_with_pdf,
        recent_papers=_rows_to_list(recent_papers),
        recent_events=_rows_to_list(recent_events),
    )


@app.get("/api/provenance/summary", response_model=ProvenanceSummary)
def provenance_summary():
    with get_db() as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*) AS total_records,
                   COALESCE(SUM(cost_usd), 0.0) AS total_cost,
                   COALESCE(SUM(prompt_tokens), 0) AS total_prompt,
                   COALESCE(SUM(completion_tokens), 0) AS total_completion
            FROM provenance_records
            """
        ).fetchone()

        by_backend = conn.execute(
            """
            SELECT backend,
                   model_used,
                   COUNT(*) AS call_count,
                   COALESCE(SUM(cost_usd), 0.0) AS total_cost,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens
            FROM provenance_records
            GROUP BY backend, model_used
            ORDER BY total_cost DESC
            """
        ).fetchall()

        by_primitive = conn.execute(
            """
            SELECT primitive,
                   COUNT(*) AS call_count,
                   COALESCE(SUM(cost_usd), 0.0) AS total_cost,
                   SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
                   SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failure_count
            FROM provenance_records
            GROUP BY primitive
            ORDER BY call_count DESC
            LIMIT 30
            """
        ).fetchall()

        recent = conn.execute(
            """
            SELECT id, primitive, backend, model_used, cost_usd,
                   prompt_tokens, completion_tokens, success, created_at
            FROM provenance_records
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()

    return ProvenanceSummary(
        total_records=totals["total_records"],
        total_cost_usd=round(totals["total_cost"], 4),
        total_prompt_tokens=totals["total_prompt"] or 0,
        total_completion_tokens=totals["total_completion"] or 0,
        by_backend=_rows_to_list(by_backend),
        by_primitive=_rows_to_list(by_primitive),
        recent_records=_rows_to_list(recent),
    )


# ---------------------------------------------------------------------------
# Review Issues
# ---------------------------------------------------------------------------


@app.get("/api/projects/{project_id}/issues")
def list_project_issues(
    project_id: int,
    status: str | None = Query(
        None, description="Filter: open, in_progress, resolved, wontfix"
    ),
    blocking_only: bool = Query(False),
):
    with get_db() as conn:
        proj = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not proj:
            raise HTTPException(
                status_code=404, detail=f"Project {project_id} not found"
            )

        conditions = ["project_id = ?"]
        params: list[Any] = [project_id]

        if status:
            conditions.append("status = ?")
            params.append(status)

        if blocking_only:
            conditions.append("blocking = 1")

        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""
            SELECT *
            FROM review_issues
            WHERE {where}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()

    return {"project_id": project_id, "issues": _rows_to_list(rows)}


# ===========================================================================
# WRITE / ACTION ENDPOINTS
# ===========================================================================
#
# These endpoints mutate state — either via raw SQL INSERT or by delegating
# to MCP tool handlers through execute_tool(name, arguments).
# ---------------------------------------------------------------------------


def _run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call execute_tool and translate errors into HTTP 500."""
    try:
        return execute_tool(name, arguments)
    except Exception as exc:
        logger.error(
            "execute_tool(%s) failed: %s\n%s", name, exc, traceback.format_exc()
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Topic creation
# ---------------------------------------------------------------------------


class CreateTopicRequest(BaseModel):
    name: str
    description: str = ""
    target_venue: str = ""
    deadline: str = ""


@app.post("/api/topics")
def create_topic(body: CreateTopicRequest):
    """Create a new research topic."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO topics (name, description, status, target_venue, deadline, created_at)
            VALUES (?, ?, 'active', ?, ?, ?)
            """,
            (body.name, body.description, body.target_venue, body.deadline, now),
        )
        conn.commit()
        topic_id = cur.lastrowid
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Project creation
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    topic_id: int
    name: str
    description: str = ""
    target_venue: str = ""
    deadline: str = ""


@app.post("/api/projects")
def create_project(body: CreateProjectRequest):
    """Create a new project and bootstrap its orchestrator run."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        # Verify topic exists
        topic = conn.execute(
            "SELECT id FROM topics WHERE id = ?", (body.topic_id,)
        ).fetchone()
        if not topic:
            raise HTTPException(
                status_code=404, detail=f"Topic {body.topic_id} not found"
            )

        cur = conn.execute(
            """
            INSERT INTO projects (topic_id, name, description, status, target_venue, deadline,
                                  created_at, updated_at)
            VALUES (?, ?, ?, 'planning', ?, ?, ?, ?)
            """,
            (
                body.topic_id,
                body.name,
                body.description,
                body.target_venue,
                body.deadline,
                now,
                now,
            ),
        )
        conn.commit()
        project_id = cur.lastrowid

    # Bootstrap orchestrator run
    orch_result = _run_tool(
        "orchestrator_resume",
        {"project_id": project_id, "topic_id": body.topic_id},
    )

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT p.*, t.name AS topic_name,
                   o.current_stage, o.stage_status, o.gate_status
            FROM projects p
            JOIN topics t ON t.id = p.topic_id
            LEFT JOIN orchestrator_runs o ON o.project_id = p.id
            WHERE p.id = ?
            """,
            (project_id,),
        ).fetchone()

    result = _row_to_dict(row)
    result["orchestrator"] = orch_result
    return result


# ---------------------------------------------------------------------------
# Paper operations
# ---------------------------------------------------------------------------


class PaperSearchRequest(BaseModel):
    query: str
    topic_id: int | None = None
    max_results: int = Field(default=50, ge=1, le=200)


@app.post("/api/papers/search")
def search_papers(body: PaperSearchRequest):
    """Search for papers via configured providers."""
    args: dict[str, Any] = {"query": body.query, "max_results": body.max_results}
    if body.topic_id is not None:
        args["topic_id"] = body.topic_id
    return _run_tool("paper_search", args)


class PaperIngestRequest(BaseModel):
    source: str  # arxiv ID, DOI, or URL
    topic_id: int | None = None
    relevance: str = "medium"


@app.post("/api/papers/ingest")
def ingest_paper(body: PaperIngestRequest):
    """Ingest a paper by arxiv ID, DOI, or URL."""
    args: dict[str, Any] = {"source": body.source, "relevance": body.relevance}
    if body.topic_id is not None:
        args["topic_id"] = body.topic_id
    return _run_tool("paper_ingest", args)


# ---------------------------------------------------------------------------
# Orchestrator actions
# ---------------------------------------------------------------------------


class AdvanceRequest(BaseModel):
    actor: str = "web_ui"


@app.post("/api/projects/{project_id}/advance")
def advance_project(project_id: int, body: AdvanceRequest):
    """Advance the project to the next orchestrator stage."""
    return _run_tool(
        "orchestrator_advance", {"project_id": project_id, "actor": body.actor}
    )


@app.get("/api/projects/{project_id}/gate")
def check_gate(project_id: int):
    """Check the gate for the current orchestrator stage."""
    return _run_tool("orchestrator_gate_check", {"project_id": project_id})


# ---------------------------------------------------------------------------
# Analysis operations
# ---------------------------------------------------------------------------


class GapDetectRequest(BaseModel):
    focus: str | None = None


@app.post("/api/topics/{topic_id}/gaps")
def detect_gaps(topic_id: int, body: GapDetectRequest):
    """Detect research gaps in a topic's literature."""
    args: dict[str, Any] = {"topic_id": topic_id}
    if body.focus:
        args["focus"] = body.focus
    return _run_tool("gap_detect", args)


class ClaimExtractRequest(BaseModel):
    paper_ids: list[int]
    focus: str | None = None


@app.post("/api/topics/{topic_id}/claims")
def extract_claims(topic_id: int, body: ClaimExtractRequest):
    """Extract research claims from papers within a topic."""
    args: dict[str, Any] = {"topic_id": topic_id, "paper_ids": body.paper_ids}
    if body.focus:
        args["focus"] = body.focus
    return _run_tool("claim_extract", args)


class DirectionRankingRequest(BaseModel):
    focus: str | None = None


@app.post("/api/topics/{topic_id}/directions")
def rank_directions(topic_id: int, body: DirectionRankingRequest):
    """Rank candidate research directions by novelty x feasibility x impact."""
    args: dict[str, Any] = {"topic_id": topic_id}
    if body.focus:
        args["focus"] = body.focus
    return _run_tool("direction_ranking", args)


# ---------------------------------------------------------------------------
# Writing operations
# ---------------------------------------------------------------------------


class OutlineGenerateRequest(BaseModel):
    topic_id: int
    template: str = "neurips"


@app.post("/api/projects/{project_id}/outline")
def generate_outline(project_id: int, body: OutlineGenerateRequest):
    """Generate a paper outline from contributions and evidence."""
    return _run_tool(
        "outline_generate",
        {
            "topic_id": body.topic_id,
            "project_id": project_id,
            "template": body.template,
        },
    )


class SectionDraftRequest(BaseModel):
    section: str
    outline: str | None = None
    max_words: int = 0


@app.post("/api/topics/{topic_id}/section-draft")
def draft_section(topic_id: int, body: SectionDraftRequest):
    """Draft a paper section using linked evidence."""
    args: dict[str, Any] = {"section": body.section, "topic_id": topic_id}
    if body.outline:
        args["outline"] = body.outline
    if body.max_words > 0:
        args["max_words"] = body.max_words
    return _run_tool("section_draft", args)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    # Restrict reload watcher to the Python package so web/node_modules and other
    # large trees don't trigger spurious reloads when running alongside the
    # Next.js dashboard.
    _package_dir = str(Path(__file__).resolve().parent)

    uvicorn.run(
        "research_harness_mcp.http_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[_package_dir],
    )
