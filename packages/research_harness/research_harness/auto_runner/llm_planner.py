"""LLM Planner — generates stage_context parameters via one LLM call per stage.

Before each stage's tools execute, the planner reads topic metadata and
previous-stage artifacts from DB, then asks an LLM to produce the correct
parameters for the current stage's tools (as a JSON dict).

Design constraints:
  - One LLM call per stage (cost control)
  - Routes via the medium tier (`LLM_ROUTE_MEDIUM` env override)
  - Idempotent: same DB state → same output
  - Fail-safe: planner error → returns {} without blocking execution
  - init stage skipped (parameters already known)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..orchestrator.service import OrchestratorService
from ..storage.db import Database

logger = logging.getLogger(__name__)


def plan_stage(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    """Generate enriched stage_context for the current stage via LLM.

    Returns a dict to merge into checkpoint_data["stage_context"].
    Returns {} on failure or for stages that don't need planning.
    """
    if stage == "init":
        meta = _gather_topic_meta(db, topic_id)
        return {
            "topic_description": meta["description"] or meta["name"],
            "query": meta["description"][:200] or meta["name"],
            "topic_id": topic_id,
        }

    planners = {
        "build": _plan_build,
        "analyze": _plan_analyze,
        "propose": _plan_propose,
        "experiment": _plan_experiment,
        "write": _plan_write,
    }

    planner_fn = planners.get(stage)
    if planner_fn is None:
        logger.debug("No planner registered for stage '%s'", stage)
        return {}

    try:
        result = planner_fn(
            db=db,
            svc=svc,
            topic_id=topic_id,
            checkpoint_data=checkpoint_data,
        )
        if not isinstance(result, dict):
            return {}
        result["topic_id"] = topic_id
        return result
    except Exception as exc:
        logger.warning("Planner failed for stage '%s': %s", stage, exc)
        return {}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _gather_topic_meta(db: Database, topic_id: int) -> dict[str, str]:
    """Read topic name, description, target_venue from DB."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT name, description, target_venue FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"name": "", "description": "", "target_venue": ""}
    return {
        "name": row["name"] or "",
        "description": row["description"] or "",
        "target_venue": row["target_venue"] or "",
    }


def _gather_artifact_payload(
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    artifact_type: str,
) -> dict[str, Any]:
    """Load the latest artifact payload for a given stage+type."""
    art = svc.get_latest_artifact(topic_id, stage, artifact_type)
    if art is None:
        return {}
    payload = art.payload_json if hasattr(art, "payload_json") else ""
    if not payload:
        return {}
    try:
        return json.loads(payload) if isinstance(payload, str) else payload
    except (json.JSONDecodeError, TypeError):
        return {}


def _get_paper_count(db: Database, topic_id: int) -> int:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM paper_topics WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def _get_top_papers(
    db: Database, topic_id: int, limit: int = 50
) -> list[dict[str, Any]]:
    """Get top papers by relevance and citation count."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT p.id, p.title, p.year, p.venue, p.citation_count,
                      pt.relevance
               FROM papers p
               JOIN paper_topics pt ON p.id = pt.paper_id
               WHERE pt.topic_id = ?
               ORDER BY
                 CASE pt.relevance WHEN 'high' THEN 0
                                   WHEN 'medium' THEN 1 ELSE 2 END,
                 COALESCE(p.citation_count, 0) DESC
               LIMIT ?""",
            (topic_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_search_queries(db: Database, topic_id: int) -> list[str]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT query FROM search_queries WHERE topic_id = ?",
            (topic_id,),
        ).fetchall()
        return [r["query"] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _get_contributions(db: Database, topic_id: int) -> str:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT contributions FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
        return (row["contributions"] or "") if row else ""
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# LLM call wrapper
# ---------------------------------------------------------------------------


def _call_planner_llm(prompt: str) -> dict[str, Any]:
    """Call LLM with planner prompt, parse JSON response."""
    from ..execution.llm_primitives import _client_chat, _get_client, _parse_json

    client = _get_client(tier="medium", task_name="stage_planner")
    raw = _client_chat(client, prompt)
    return _parse_json(raw, primitive="stage_planner")


# ---------------------------------------------------------------------------
# Per-stage planners
# ---------------------------------------------------------------------------


def _plan_build(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    meta = _gather_topic_meta(db, topic_id)
    paper_count = _get_paper_count(db, topic_id)
    existing_queries = _get_search_queries(db, topic_id)

    prompt = f"""You are a paper retrieval planner. Given a research topic, generate a search strategy.

Topic: {meta["name"]}
Description: {meta["description"]}
Current paper count: {paper_count}
Existing queries: {json.dumps(existing_queries[:10], ensure_ascii=False)}

Return a JSON object with these fields:
- "query": primary search query string for paper_search
- "additional_queries": list of 3-5 alternative search queries
- "auto_ingest": true
- "max_results": 500
- "seed_top_n": 10
- "forward_limit": 50
- "backward_limit": 50
- "topic_description": a concise summary of the topic (1-2 sentences)

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    if not result.get("query"):
        result["query"] = meta["description"][:200] or meta["name"]
    result.setdefault("auto_ingest", True)
    result.setdefault("max_results", 500)
    result.setdefault("seed_top_n", 10)
    result.setdefault("forward_limit", 50)
    result.setdefault("backward_limit", 50)
    result.setdefault("topic_description", meta["description"][:200])
    return result


def _plan_analyze(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    meta = _gather_topic_meta(db, topic_id)
    papers = _get_top_papers(db, topic_id, limit=50)
    paper_count = len(papers)

    papers_table = "\n".join(
        f"  {p['id']} | {p['title'][:60]} | {p.get('year', '?')} | "
        f"{p.get('venue', '?')[:20]} | cites={p.get('citation_count', 0)}"
        for p in papers[:30]
    )

    prompt = f"""You are a paper analysis planner. Select papers for deep analysis and define the research focus.

Topic: {meta["name"]} — {meta["description"]}
Paper pool ({paper_count} papers, showing top 30):
{papers_table}

Return a JSON object with:
- "paper_ids": list of 20-30 paper IDs (integers) to analyze via claim_extract
- "focus": a specific research focus string (1-2 sentences) for gap_detect and baseline_identify

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    if not result.get("paper_ids"):
        result["paper_ids"] = [p["id"] for p in papers[:25]]
    if not result.get("focus"):
        result["focus"] = meta["description"][:200]
    return result


def _plan_propose(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    gaps = _gather_artifact_payload(svc, topic_id, "analyze", "gap_detect")
    # direction_ranking is not in analyze's tool list; fall back to
    # direction_proposal (auto-recorded by analyze from gap_detect output)
    # or evidence_pack as additional context.
    directions = _gather_artifact_payload(
        svc, topic_id, "analyze", "direction_ranking"
    )
    if not directions:
        directions = _gather_artifact_payload(
            svc, topic_id, "analyze", "direction_proposal"
        )
    baselines = _gather_artifact_payload(
        svc, topic_id, "analyze", "baseline_identify"
    )
    meta = _gather_topic_meta(db, topic_id)

    prompt = f"""You are a research direction planner. Synthesize gaps, directions, and baselines into a proposal.

Gaps: {json.dumps(gaps, ensure_ascii=False, default=str)[:2000]}
Directions: {json.dumps(directions, ensure_ascii=False, default=str)[:2000]}
Baselines: {json.dumps(baselines, ensure_ascii=False, default=str)[:1000]}

Return a JSON object with:
- "artifact_type": "direction_proposal"
- "artifact_title": a short title for the research direction
- "artifact_payload": object with keys "direction", "motivation", "baselines", "gaps_addressed", "research_question" (REQUIRED: a concise research question this direction answers)
- "focus": the chosen research focus string
- "study_spec": a brief study design specification (datasets, metrics, baselines, experiment groups)

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    result.setdefault("artifact_type", "direction_proposal")
    result.setdefault("artifact_title", "Research direction proposal")
    # Ensure research_question exists in payload (required by orchestrator invariant)
    payload = result.get("artifact_payload", {})
    if isinstance(payload, dict) and "research_question" not in payload:
        payload["research_question"] = payload.get(
            "direction", "What is the optimal approach?"
        )
    result["artifact_payload"] = payload
    # P0-4: study_spec must be non-empty for the artifact to be recorded.
    # Synthesize from direction if LLM returned empty.
    if not result.get("study_spec"):
        direction = payload.get("direction", "") if isinstance(payload, dict) else ""
        rq = payload.get("research_question", "") if isinstance(payload, dict) else ""
        result["study_spec"] = (
            f"Evaluate the proposed approach ({direction or rq or meta['name']}) "
            f"against baselines on standard benchmarks. "
            f"Metrics: accuracy, efficiency, ablation over key components."
        )
    return result


def _plan_experiment(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    proposal = _gather_artifact_payload(
        svc, topic_id, "propose", "direction_proposal"
    )
    study_spec = _gather_artifact_payload(svc, topic_id, "propose", "study_spec")

    prompt = f"""You are an experiment planner. Design an experiment based on the research direction.

Direction proposal: {json.dumps(proposal, ensure_ascii=False, default=str)[:2000]}
Existing study spec: {json.dumps(study_spec, ensure_ascii=False, default=str)[:1000] or "None yet"}

Return a JSON object with:
- "study_spec": a complete experiment design description (what to implement, datasets, metrics, baselines)
- "primary_metric": the main evaluation metric name (e.g. "accuracy", "f1", "regret")

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    result.setdefault("study_spec", "")
    result.setdefault("primary_metric", "")
    return result


def _plan_write(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    meta = _gather_topic_meta(db, topic_id)
    contributions = _get_contributions(db, topic_id)
    experiment = _gather_artifact_payload(
        svc, topic_id, "experiment", "experiment_result"
    )
    proposal = _gather_artifact_payload(
        svc, topic_id, "propose", "direction_proposal"
    )

    prompt = f"""You are a paper writing planner. Plan the structure and parameters for drafting a research paper.

Topic: {meta["name"]}
Target venue: {meta["target_venue"] or "top AI conference"}
Contributions: {contributions[:1000] or "Not yet defined"}
Experiment results: {json.dumps(experiment, ensure_ascii=False, default=str)[:1500] or "None"}
Direction: {json.dumps(proposal, ensure_ascii=False, default=str)[:1000] or "None"}

Return a JSON object with:
- "venue": target venue name
- "contributions": the paper's contribution statement
- "outline": a brief paper outline (section titles and key points)
- "sections_to_draft": ordered list of section names to write ["introduction", "related_work", "method", "experiments", "conclusion"]
- "evidence_ids": list of evidence/claim IDs to cite (can be empty)

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    result.setdefault("venue", meta["target_venue"] or "NeurIPS")
    result.setdefault("contributions", contributions)
    result.setdefault(
        "sections_to_draft",
        [
            "introduction",
            "related_work",
            "method",
            "experiments",
            "conclusion",
        ],
    )
    return result
