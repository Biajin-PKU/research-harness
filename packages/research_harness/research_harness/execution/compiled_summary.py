"""Compiled summary cache: per-paper structured summaries and topic-level overviews.

This module addresses the RAG anti-pattern where every LLM primitive call
rebuilds context from scratch. Instead, we compile a structured JSON summary
per paper (eager, at annotation time) and cache topic overviews (lazy, on
first access). Both layers use hash/count-based invalidation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from ..storage.db import Database
from . import prompts

logger = logging.getLogger(__name__)

# JSON schema fields expected in compiled_summary
COMPILED_FIELDS = (
    "overview",
    "methods",
    "claims",
    "limitations",
    "metrics",
    "relations",
)

# Contradiction signal keywords for topic sampling
_CONTRADICTION_KEYWORDS = (
    "revisit",
    "fail",
    "contrary",
    "challenge",
    "contradict",
    "rethink",
    "pitfall",
    "does not",
    "limitation of",
)

_TOP_K = 20
_CONTRADICTION_BUDGET = 5
_MIN_ABSTRACT_LEN = 100


def _compute_source_hash(conn: Any, paper_id: int) -> str:
    """Compute SHA-256 of all source material for a paper's compiled summary."""
    # 1. Paper annotations
    annotations = conn.execute(
        "SELECT section, content FROM paper_annotations "
        "WHERE paper_id = ? AND COALESCE(content, '') != '' "
        "ORDER BY section",
        (paper_id,),
    ).fetchall()
    ann_dict = {row["section"]: row["content"] for row in annotations}

    # 2. Paper card (from artifacts)
    card_data: dict | None = None
    artifact = conn.execute(
        "SELECT path FROM paper_artifacts "
        "WHERE paper_id = ? AND artifact_type = 'paperindex_card'",
        (paper_id,),
    ).fetchone()
    if artifact:
        card_path = Path(artifact["path"])
        if card_path.exists():
            try:
                card_data = json.loads(card_path.read_text())
            except Exception:
                pass

    # 3. Abstract
    row = conn.execute(
        "SELECT abstract FROM papers WHERE id = ?",
        (paper_id,),
    ).fetchone()
    abstract = (row["abstract"] or "") if row else ""

    source = {
        "annotations": ann_dict,
        "card": card_data,
        "abstract": abstract,
    }
    blob = json.dumps(source, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _build_source_text(conn: Any, paper_id: int) -> str:
    """Build the source text fed to the compilation prompt."""
    parts: list[str] = []

    # Annotations (priority order)
    for section in (
        "summary",
        "methodology",
        "experiments",
        "limitations",
        "deep_reading",
        "equations",
        "reproduction_notes",
    ):
        row = conn.execute(
            "SELECT content FROM paper_annotations "
            "WHERE paper_id = ? AND section = ? AND COALESCE(content, '') != ''",
            (paper_id, section),
        ).fetchone()
        if row:
            parts.append(f"[{section}]\n{row['content']}")

    # Paper card fields (if available)
    artifact = conn.execute(
        "SELECT path FROM paper_artifacts "
        "WHERE paper_id = ? AND artifact_type = 'paperindex_card'",
        (paper_id,),
    ).fetchone()
    if artifact:
        card_path = Path(artifact["path"])
        if card_path.exists():
            try:
                card = json.loads(card_path.read_text())
                card_parts = []
                for key in (
                    "core_idea",
                    "method_summary",
                    "contributions",
                    "key_results",
                    "limitations",
                    "assumptions",
                ):
                    val = card.get(key)
                    if val:
                        if isinstance(val, list):
                            val = "; ".join(str(v) for v in val)
                        card_parts.append(f"{key}: {val}")
                if card_parts:
                    parts.append("[paper_card]\n" + "\n".join(card_parts))
            except Exception:
                pass

    # Abstract fallback
    if not parts:
        row = conn.execute(
            "SELECT abstract FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()
        if row and row["abstract"]:
            parts.append(f"[abstract]\n{row['abstract']}")

    return "\n\n".join(parts)


def ensure_compiled_summary(db: Database, paper_id: int) -> dict:
    """Return compiled summary for a paper, compiling via LLM if stale/missing.

    Returns a dict with keys: overview, methods, claims, limitations, metrics,
    relations. Returns {} if there's no source data or compilation fails.
    """
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT compiled_summary, compiled_from_hash, title FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()
        if row is None:
            return {}

        title = row["title"] or f"Paper #{paper_id}"
        current_hash = _compute_source_hash(conn, paper_id)

        # Cache hit
        existing = row["compiled_summary"] or ""
        existing_hash = row["compiled_from_hash"] or ""
        if existing and existing_hash == current_hash:
            try:
                return json.loads(existing)
            except json.JSONDecodeError:
                pass  # corrupted cache, recompile

        # Check if we have enough source material
        source_text = _build_source_text(conn, paper_id)
        if not source_text or len(source_text.strip()) < _MIN_ABSTRACT_LEN:
            return {}

        # Compile via LLM (light tier)
        from . import llm_primitives as _llm

        client = _llm._get_client(tier="light", task_name="compiled_summary")
        prompt = prompts.compiled_summary_prompt(title, source_text)
        raw = _llm._client_chat(client, prompt)
        result = _llm._parse_json(raw, primitive="compiled_summary", context=title)

        if not result or "overview" not in result:
            logger.warning(
                "Compiled summary LLM returned invalid output for paper %d", paper_id
            )
            return {}

        # Normalize: ensure all expected fields exist
        normalized = {}
        for field in COMPILED_FIELDS:
            normalized[field] = result.get(field, [] if field != "overview" else "")

        # Store
        conn.execute(
            "UPDATE papers SET compiled_summary = ?, compiled_from_hash = ? WHERE id = ?",
            (json.dumps(normalized, ensure_ascii=False), current_hash, paper_id),
        )
        conn.commit()
        return normalized
    except Exception:
        logger.debug(
            "ensure_compiled_summary failed for paper %d", paper_id, exc_info=True
        )
        return {}
    finally:
        conn.close()


def format_compiled_as_text(compiled: dict) -> str:
    """Format compiled summary JSON into [Section] text for _get_paper_text compatibility."""
    if not compiled:
        return ""
    parts: list[str] = []

    overview = compiled.get("overview", "")
    if overview:
        parts.append(f"[Overview]\n{overview}")

    methods = compiled.get("methods", [])
    if methods:
        parts.append("[Methods]\n" + "\n".join(f"- {m}" for m in methods))

    claims = compiled.get("claims", [])
    if claims:
        claim_lines = []
        for c in claims:
            if isinstance(c, dict):
                claim_lines.append(
                    f"- {c.get('claim', '')} "
                    f"(evidence: {c.get('evidence', 'N/A')}, "
                    f"strength: {c.get('strength', 'unknown')})"
                )
            else:
                claim_lines.append(f"- {c}")
        parts.append("[Claims]\n" + "\n".join(claim_lines))

    limitations = compiled.get("limitations", [])
    if limitations:
        parts.append("[Limitations]\n" + "\n".join(f"- {item}" for item in limitations))

    metrics = compiled.get("metrics", [])
    if metrics:
        metric_lines = []
        for m in metrics:
            if isinstance(m, dict):
                metric_lines.append(
                    f"- {m.get('dataset', '?')}/{m.get('metric', '?')}: "
                    f"{m.get('value', '?')} (baseline: {m.get('baseline', 'N/A')})"
                )
            else:
                metric_lines.append(f"- {m}")
        parts.append("[Metrics]\n" + "\n".join(metric_lines))

    relations = compiled.get("relations", [])
    if relations:
        parts.append("[Relations]\n" + "\n".join(f"- {r}" for r in relations))

    return "\n\n".join(parts)


def format_compiled_for_context(compiled: dict, title: str = "") -> str:
    """Shorter format for topic-level sampling context (~400 chars)."""
    if not compiled:
        return ""
    parts: list[str] = []
    overview = compiled.get("overview", "")
    if overview:
        parts.append(overview[:300])

    claims = compiled.get("claims", [])
    for c in claims[:2]:
        if isinstance(c, dict):
            parts.append(f"Claim: {c.get('claim', '')[:100]}")
        elif isinstance(c, str):
            parts.append(f"Claim: {c[:100]}")

    return " | ".join(parts)


def get_topic_summary_cached(
    db: Database,
    topic_id: int,
) -> tuple[str, list[int]]:
    """Return topic overview, using cache if fresh. Compiles from top-K sampling if stale.

    Returns (summary_text, paper_ids_used).
    """
    conn = db.connect()
    try:
        # Count current non-dismissed papers
        count_row = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            """,
            (topic_id,),
        ).fetchone()
        current_count = count_row["cnt"] if count_row else 0

        # Check cache
        cached = conn.execute(
            "SELECT summary, paper_count, paper_ids_json FROM topic_summaries WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        if cached and cached["paper_count"] == current_count and cached["summary"]:
            try:
                ids = json.loads(cached["paper_ids_json"])
                return (cached["summary"], ids)
            except (json.JSONDecodeError, TypeError):
                pass

        if current_count == 0:
            return ("(no papers in topic)", [])

        # Sample top-K by citation count + recency
        top_rows = conn.execute(
            """
            SELECT p.id, p.title, p.year, p.venue, p.citation_count
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY COALESCE(p.citation_count, 0) DESC, p.year DESC
            LIMIT ?
            """,
            (topic_id, _TOP_K),
        ).fetchall()
        sampled_ids = {int(r["id"]) for r in top_rows}
        sampled = list(top_rows)

        # Add contradiction candidates
        if current_count > _TOP_K:
            like_clauses = " OR ".join(
                "LOWER(p.title) LIKE ?" for _ in _CONTRADICTION_KEYWORDS
            )
            params: list[Any] = [topic_id]
            params.extend(f"%{kw}%" for kw in _CONTRADICTION_KEYWORDS)
            if sampled_ids:
                exclude = ",".join(str(i) for i in sampled_ids)
                exclude_clause = f"AND p.id NOT IN ({exclude})"
            else:
                exclude_clause = ""

            contra_rows = conn.execute(
                f"""
                SELECT p.id, p.title, p.year, p.venue, p.citation_count
                FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                  AND ({like_clauses})
                  {exclude_clause}
                  AND NOT EXISTS (
                      SELECT 1 FROM topic_paper_notes tpn
                      WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                        AND tpn.note_type = 'user_dismissed'
                  )
                ORDER BY p.year DESC
                LIMIT ?
                """,
                (*params, _CONTRADICTION_BUDGET),
            ).fetchall()
            for r in contra_rows:
                if int(r["id"]) not in sampled_ids:
                    sampled.append(r)
                    sampled_ids.add(int(r["id"]))
    finally:
        conn.close()

    # Build context from compiled summaries
    entries: list[str] = []
    paper_ids: list[int] = []
    for row in sampled:
        pid = int(row["id"])
        paper_ids.append(pid)

        compiled = ensure_compiled_summary(db, pid)
        context = format_compiled_for_context(compiled)

        header = f"- [{pid}] {row['title'] or f'Paper #{pid}'}"
        if row["year"]:
            header += f" ({row['year']})"
        if row["venue"]:
            header += f" [{row['venue']}]"
        if context:
            entries.append(f"{header}\n  {context}")
        else:
            entries.append(header)

    if not entries:
        return ("(no papers in topic)", [])

    # Compile topic overview via LLM (medium tier)
    from . import llm_primitives as _llm

    papers_text = "\n".join(entries)
    client = _llm._get_client(tier="medium", task_name="topic_overview")
    prompt = prompts.topic_overview_prompt(papers_text, current_count)
    raw = _llm._client_chat(client, prompt)
    result = _llm._parse_json(raw, primitive="topic_overview")
    overview = result.get("overview", papers_text[:2000])

    # Cache
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO topic_summaries
            (topic_id, summary, paper_count, paper_ids_json, compiled_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (topic_id, overview, current_count, json.dumps(paper_ids)),
        )
        conn.commit()
    finally:
        conn.close()

    return (overview, paper_ids)
