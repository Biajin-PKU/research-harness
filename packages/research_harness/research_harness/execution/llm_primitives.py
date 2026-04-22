"""LLM-backed primitive implementations using the shared paperindex client."""

from __future__ import annotations

import collections
import json
import logging
import re
import threading as _threading
from typing import Any

from paperindex.llm.client import (
    LLMClient,
    TaskTier,
    get_last_usage,
    is_joy_gpt_task,
    is_joy_kimi_task,
    joy_gpt_route,
    joy_kimi_route,
    resolve_llm_config,
)

from ..primitives.types import (
    AlgorithmCandidateGenerateOutput,
    AlgorithmDesignLoopOutput,
    AlgorithmDesignRefineOutput,
    Baseline,
    BaselineIdentifyOutput,
    Claim,
    ClaimExtractOutput,
    CodeGenerationOutput,
    CompetitiveLearningOutput,
    ConsistencyCheckOutput,
    ConsistencyIssue,
    ContradictionDetectOutput,
    CoverageCheckOutput,
    CoverageItem,
    CrossPaperLink,
    DeepReadingNote,
    DeepReadingOutput,
    DesignBriefOutput,
    DesignGapProbeOutput,
    DeterministicCheck,
    DirectionRankingOutput,
    DraftText,
    EvidenceMatrixOutput,
    FigureGenerateOutput,
    FigureInterpretOutput,
    FigurePlanOutput,
    Gap,
    GapDetectOutput,
    IndustrialFeasibility,
    IterativeRetrievalLoopOutput,
    LessonExtractOutput,
    MethodLayerExpansionOutput,
    MethodQuery,
    MethodTaxonomyOutput,
    OriginalityBoundaryCheckOutput,
    OutlineGenerateOutput,
    OutlineSectionItem,
    QueryCandidate,
    QueryRefineOutput,
    RankedDirection,
    RebuttalFormatOutput,
    RetrievalRoundRecord,
    ReviewDimension,
    SectionDraftOutput,
    SectionPlan,
    SectionReviewOutput,
    SectionReviseOutput,
    SummaryOutput,
    TableExtractOutput,
    TopicFramingOutput,
    WritingArchitectureOutput,
    WritingPattern,
    WritingPatternExtractOutput,
)
from ..storage.db import Database
from . import prompts

logger = logging.getLogger(__name__)

_SUMMARY_SECTIONS = ("summary", "methodology", "experiments", "limitations")

# Task tier mapping: each primitive gets a complexity tier for auto-routing
_PRIMITIVE_TIERS: dict[str, TaskTier] = {
    "paper_summarize": "light",
    "claim_extract": "medium",
    "gap_detect": "medium",
    "paper_coverage_check": "medium",
    "baseline_identify": "medium",
    "query_refine": "light",
    "section_draft": "medium",
    "consistency_check": "heavy",
    "deep_read_pass1": "medium",
    "deep_read_pass2": "heavy",
    "outline_generate": "medium",
    "section_review": "medium",
    "section_revise": "medium",
    "compiled_summary": "light",
    "topic_overview": "medium",
    "method_taxonomy": "medium",
    "evidence_matrix": "medium",
    "contradiction_detect": "medium",
    "table_extract": "medium",
    "figure_interpret": "medium",
    "competitive_learning": "medium",
    "topic_framing": "medium",
    "direction_ranking": "medium",
    "method_layer_expansion": "medium",
    "writing_architecture": "medium",
    "writing_pattern_extract": "light",
    "rebuttal_format": "medium",
    "lesson_extract": "light",
    "strategy_distill": "light",
    "strategy_quality_gate": "medium",
    "design_brief_expand": "medium",
    "design_gap_probe": "light",
    "algorithm_candidate_generate": "heavy",
    "originality_boundary_check": "heavy",
    "algorithm_design_refine": "heavy",
    "algorithm_design_loop": "heavy",
}

# RED LINE: primitives that must NEVER use Anthropic API.
# These are bulk paper-reading tasks where basic models suffice.
# The blocklist in client.py enforces at routing level; this set
# is used for assertion-level defense in _get_client.
_ANTHROPIC_BLOCKED_PRIMITIVES: frozenset[str] = frozenset(
    {
        "paper_summarize",
        "claim_extract",
        "gap_detect",
        "paper_coverage_check",
        "baseline_identify",
        "deep_read_pass1",
        "compiled_summary",
        "method_taxonomy",
        "evidence_matrix",
        "table_extract",
        "figure_interpret",
        "lesson_extract",
        "strategy_distill",
        "writing_pattern_extract",
    }
)


def _get_client(
    model_override: str | None = None, tier: TaskTier | None = None, task_name: str = ""
) -> LLMClient:
    # joy_kimi override for single-paper reading tasks (light/medium tier)
    if task_name and not model_override and is_joy_kimi_task(task_name):
        prov, mdl = joy_kimi_route()
        client = LLMClient(resolve_llm_config({"provider": prov, "model": mdl}))
        client._default_tier = None  # type: ignore[attr-defined]
        return client
    # joy_gpt override for heavy-tier paper analysis tasks
    if task_name and not model_override and is_joy_gpt_task(task_name):
        prov, mdl = joy_gpt_route()
        client = LLMClient(resolve_llm_config({"provider": prov, "model": mdl}))
        client._default_tier = None  # type: ignore[attr-defined]
        return client
    overrides = {"model": model_override} if model_override else None
    client = LLMClient(resolve_llm_config(overrides))
    # Store tier so chat() can use it
    client._default_tier = tier  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Per-primitive token accumulator (thread-local).
#
# A single primitive may call ``_client_chat`` multiple times (e.g. deep_read
# runs two passes, claim_extract may chunk over snippets). The backend resets
# the accumulator before dispatching the primitive impl and reads the totals
# after it returns, then injects them into the emitted ``PrimitiveResult``.
# ---------------------------------------------------------------------------

_token_acc_local = _threading.local()


def _get_project_contributions(db: Database, project_id: int) -> str:
    """Return stored ``projects.contributions`` for a project_id, or empty.

    Used by writing primitives (outline_generate, writing_architecture,
    figure_plan, competitive_learning) as a fallback when the caller omits
    the ``contributions`` argument. Makes contributions a project-level
    config rather than a repeated per-call parameter.
    """
    if not project_id:
        return ""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT contributions FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return ""
    return (row["contributions"] or "").strip()


def _get_topic_latest_project_contributions(db: Database, topic_id: int) -> str:
    """Return contributions from the most recently updated project of a topic.

    Used when the primitive only has ``topic_id`` (no ``project_id``), e.g.
    writing_architecture / figure_plan / competitive_learning — they operate
    at the topic layer but the contributions live on the project.
    """
    if not topic_id:
        return ""
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT contributions FROM projects
            WHERE topic_id = ?
              AND contributions IS NOT NULL AND contributions != ''
            ORDER BY datetime(updated_at) DESC, id DESC
            LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return ""
    return (row["contributions"] or "").strip()


def _reset_token_accumulator() -> None:
    _token_acc_local.prompt = 0
    _token_acc_local.completion = 0
    _token_acc_local.observed = False


def _accumulated_tokens() -> tuple[int | None, int | None]:
    """Return (prompt, completion) summed across all LLM calls since reset.

    Returns (None, None) if no provider reported usage, so callers cannot tell
    between "zero observed tokens" and "provider does not expose usage".
    """
    if not getattr(_token_acc_local, "observed", False):
        return (None, None)
    return (
        int(getattr(_token_acc_local, "prompt", 0)),
        int(getattr(_token_acc_local, "completion", 0)),
    )


def _client_chat(client: LLMClient, prompt: str) -> str:
    """Call client.chat with tier if available and accumulate token usage."""
    tier = getattr(client, "_default_tier", None)
    text = client.chat(prompt, tier=tier)
    usage = get_last_usage()
    if usage is not None and (
        usage.prompt_tokens is not None or usage.completion_tokens is not None
    ):
        _token_acc_local.prompt = getattr(_token_acc_local, "prompt", 0) + (
            usage.prompt_tokens or 0
        )
        _token_acc_local.completion = getattr(_token_acc_local, "completion", 0) + (
            usage.completion_tokens or 0
        )
        _token_acc_local.observed = True
    return text


def _parse_json(text: str, *, primitive: str = "", context: str = "") -> dict[str, Any]:
    candidate = text.strip()
    if not candidate:
        return {}
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    fenced_markers = ("```json", "```")
    for marker in fenced_markers:
        start = candidate.find(marker)
        if start < 0:
            continue
        start += len(marker)
        end = candidate.find("```", start)
        block = candidate[start:] if end < 0 else candidate[start:end]
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            continue
    logger.warning(
        "JSON parse failed for %s [%s]: %.200s",
        primitive or "unknown",
        context or "no context",
        candidate,
    )
    return {}


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _paper_label(paper_id: int, title: str) -> str:
    return title or f"Paper #{paper_id}"


def _get_paper_text(db: Database, paper_id: int) -> tuple[str, str]:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id, title, compiled_summary FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()
        if row is None:
            return (f"Paper #{paper_id}", "")

        title = row["title"] or f"Paper #{paper_id}"

        # Fast path: use compiled summary if available
        compiled_raw = row["compiled_summary"] or ""
        if compiled_raw:
            try:
                from .compiled_summary import format_compiled_as_text

                compiled = json.loads(compiled_raw)
                text = format_compiled_as_text(compiled)
                if text:
                    return (title, text)
            except Exception:
                logger.debug(
                    "compiled_summary unusable for paper %s; falling back to annotations",
                    paper_id,
                    exc_info=True,
                )

        parts: list[str] = []

        annotations = conn.execute(
            """
            SELECT section, content
            FROM paper_annotations
            WHERE paper_id = ? AND COALESCE(content, '') != ''
            ORDER BY CASE section
                WHEN 'summary' THEN 0
                WHEN 'methodology' THEN 1
                WHEN 'experiments' THEN 2
                WHEN 'limitations' THEN 3
                ELSE 99
            END, id
            """,
            (paper_id,),
        ).fetchall()
        for annotation in annotations:
            section = annotation["section"] or "note"
            content = (annotation["content"] or "").strip()
            if content:
                parts.append(f"[{section}]\n{content}")

        if not parts:
            notes = conn.execute(
                """
                SELECT note_type, content
                FROM topic_paper_notes
                WHERE paper_id = ? AND COALESCE(content, '') != ''
                ORDER BY id
                """,
                (paper_id,),
            ).fetchall()
            for note in notes:
                note_type = note["note_type"] or "note"
                content = (note["content"] or "").strip()
                if content:
                    parts.append(f"[{note_type}]\n{content}")

        return (title, "\n\n".join(parts).strip())
    finally:
        conn.close()


TASK_QUERIES: dict[str, str] = {
    "gap_detect": "limitations, future work, open problems, challenges, shortcomings",
    "claim_extract": "contributions, key findings, we propose, we show, our method achieves",
    "baseline_identify": "baseline, comparison, benchmark, state-of-the-art, competing methods",
    "section_draft": "methodology, approach, results, contributions, related work",
    "consistency_check": "claims, results, methodology, conclusions",
    "deep_read": "methodology, algorithm, limitations, reproducibility, novelty",
}

MAX_SNIPPETS_PER_PAPER = 3
MAX_SNIPPET_CHARS = 600


def _get_paperindex_context(db: Database, paper_id: int, task_type: str) -> str | None:
    """Try to retrieve task-relevant snippets from paperindex for a paper."""
    conn = db.connect()
    try:
        artifact = conn.execute(
            """
            SELECT path FROM paper_artifacts
            WHERE paper_id = ? AND artifact_type = 'paperindex_structure'
            """,
            (paper_id,),
        ).fetchone()
        if artifact is None:
            return None
    finally:
        conn.close()

    try:
        query = TASK_QUERIES.get(task_type, "methodology, results, contributions")

        structure_path = artifact["path"]
        from pathlib import Path

        if not Path(structure_path).exists():
            return None

        import json as _json

        structure_data = _json.loads(Path(structure_path).read_text())
        from paperindex.types import SectionNode, StructureResult

        structure = StructureResult(
            doc_name=structure_data.get("doc_name", ""),
            tree=[
                SectionNode.from_dict(n) for n in structure_data.get("structure", [])
            ],
            pdf_hash=structure_data.get("pdf_hash", ""),
            page_count=int(structure_data.get("page_count", 0) or 0),
            raw=structure_data.get("raw", {}),
        )

        from paperindex.retrieval.search import find_structure_matches
        from paperindex.types import PaperRecord as PIRecord

        record = PIRecord(
            paper_id=f"paper_{paper_id}",
            title="",
            doc_name="",
            pdf_hash=structure.pdf_hash,
            page_count=structure.page_count,
            structure=structure,
            sections={},
            card=None,
            source_path="",
            indexed_at="",
        )
        matches = find_structure_matches(record, query, limit=MAX_SNIPPETS_PER_PAPER)

        if not matches:
            return None

        parts: list[str] = []
        for match in matches:
            snippet = (match.snippet or "")[:MAX_SNIPPET_CHARS]
            if snippet:
                parts.append(f"[Section: {match.title}] {snippet}")
        return "\n".join(parts) if parts else None
    except Exception:
        logger.debug("paperindex lookup failed for paper %d", paper_id, exc_info=True)
        return None


def _get_topic_literature_summary(
    db: Database,
    topic_id: int,
    task_type: str = "",
) -> tuple[str, list[int]]:
    """Build topic literature summary using compiled summary cache.

    Uses top-K sampling + contradiction candidates instead of iterating all
    papers. Falls back to per-paper annotation joining for uncached papers.
    """
    from .compiled_summary import get_topic_summary_cached

    try:
        return get_topic_summary_cached(db, topic_id)
    except Exception:
        logger.warning(
            "Compiled topic summary failed for topic %d, falling back to legacy",
            topic_id,
            exc_info=True,
        )

    # Legacy fallback: iterate all papers (original behavior)
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.year, p.venue
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY p.year DESC, p.id DESC
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    paper_ids: list[int] = []
    entries: list[str] = []
    for row in rows:
        paper_id = int(row["id"])
        header = f"- {_paper_label(paper_id, row['title'] or f'Paper #{paper_id}')}"
        if row["year"]:
            header += f" ({row['year']})"
        if row["venue"]:
            header += f" [{row['venue']}]"

        context = None
        if task_type:
            try:
                context = _get_paperindex_context(db, paper_id, task_type)
            except Exception:
                logger.debug("paperindex context failed for paper %d", paper_id)

        if context:
            entry = f"{header}\n  {context}"
        else:
            try:
                title, text = _get_paper_text(db, paper_id)
            except Exception:
                logger.warning("Skipping paper %d: corrupted or unreadable", paper_id)
                continue
            if text:
                entry = f"{header}\n  {text[:500]}"
            else:
                entry = header

        paper_ids.append(paper_id)
        entries.append(entry)

    if not entries:
        return ("(no papers in topic)", [])
    return ("\n".join(entries), paper_ids)


def _parse_authors_for_display(raw: str) -> list[str]:
    """Parse DB authors field for display in evidence prompts.

    Reuses ``parse_authors_field`` from latex_compiler to handle all
    four DB format variants ([], "", JSON array, double-escaped JSON).
    """
    from research_harness.execution.latex_compiler import parse_authors_field

    return parse_authors_field(raw)


def _build_numbered_evidence(
    db: Database,
    topic_id: int,
    max_papers: int = 50,
    task_type: str = "",
) -> tuple[str, list[int]]:
    """Build a numbered evidence list for citation injection.

    Returns ``(evidence_text, paper_ids)`` where evidence_text lists each paper
    prefixed with ``[N]`` so the LLM can use ``[N]`` markers consistently.
    Enforces a minimum of 30 papers when available, up to ``max_papers``.

    Ordering: high-relevance papers first, then by citation count, then by year.
    """
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.year, p.venue, p.authors, p.abstract,
                   p.citation_count, pt.relevance
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY
                CASE pt.relevance WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                COALESCE(p.citation_count, 0) DESC,
                p.year DESC,
                p.id DESC
            LIMIT ?
            """,
            (topic_id, max_papers),
        ).fetchall()
    finally:
        conn.close()

    paper_ids: list[int] = []
    lines: list[str] = []
    for i, row in enumerate(rows, start=1):
        paper_id = int(row["id"])
        title = row["title"] or f"Paper #{paper_id}"
        year = row["year"] or "n.d."
        venue = row["venue"] or ""
        authors_raw = row["authors"] or ""
        authors_list = _parse_authors_for_display(authors_raw)
        authors = authors_list[0] if authors_list else "Unknown"
        citation_key = f"ref{i}"

        header = f'[{i}] {authors} et al. "{title}" ({year})'
        if venue and venue not in ("arXiv.org", "arXiv"):
            header += f" — {venue}"
        header += f"  [cite key: {citation_key}, paper_id={paper_id}]"

        abstract = (row["abstract"] or "").strip()
        if abstract:
            header += f"\n    Abstract: {abstract[:400]}"

        lines.append(header)
        paper_ids.append(paper_id)

    if not lines:
        return ("(no papers in topic)", [])

    return ("\n\n".join(lines), paper_ids)


def _audit_draft_citations(content: str, evidence_count: int) -> list[str]:
    """Check [N] citation markers in drafted text against evidence pool size.

    Returns a list of warning strings for out-of-range or suspicious citations.
    """
    if evidence_count <= 0:
        return []

    warnings: list[str] = []
    seen: set[int] = set()

    for m in re.finditer(r"\[(\d+)\]", content):
        n = int(m.group(1))
        if n < 1 or n > evidence_count:
            warnings.append(
                f"[{n}] is out of range (evidence pool has [{1}]-[{evidence_count}])"
            )
        seen.add(n)

    return warnings


def _load_writing_lessons(
    db: Database,
    topic_id: int,
    stage: str = "section_draft",
) -> str:
    """Load recent writing lessons and format as prompt overlay.

    Returns empty string if no lessons or DB lacks lessons table.
    """
    try:
        from ..evolution.store import DBLessonStore

        store = DBLessonStore(db)
        overlay = store.build_overlay(stage, top_k=5, topic_id=topic_id)
        return overlay
    except Exception:
        return ""


def _record_writing_lessons_from_draft(
    db: Database,
    topic_id: int,
    section: str,
    content: str,
    audit_warnings: list[str],
    target_words: int = 0,
) -> None:
    """Run deterministic writing checks on drafted content and record failures as lessons.

    This is the "discover problems" wire of the self-evolution loop: every time
    section_draft produces output, we automatically detect quality issues and
    persist them so future drafts can learn from past mistakes.

    V2 path: routes through ExperienceStore.ingest(source_kind="self_review")
    which internally bridges to V1 DBLessonStore. Falls back to V1 direct path
    if V2 is unavailable.
    """
    try:
        from .writing_checks import run_all_checks
    except Exception:
        return

    issues: list[str] = []

    try:
        check_results = run_all_checks(content, section, target_words)
        for c in check_results:
            if not c.passed:
                issues.append(f"[{section}] Check '{c.check_name}' failed: {c.details}")
    except Exception as exc:
        logger.debug("Writing checks unavailable: %s", exc)

    for w in audit_warnings:
        issues.append(f"[{section}] Citation audit: {w}")

    if not issues:
        return

    # V2 path: unified experience pipeline
    try:
        from ..evolution.experience import ExperienceRecord, ExperienceStore

        store = ExperienceStore(db)
        for issue in issues[:10]:
            store.ingest(
                ExperienceRecord(
                    source_kind="self_review",
                    stage="section_draft",
                    section=section,
                    diff_summary=issue,
                    topic_id=topic_id,
                    metadata={"auto_review": True},
                )
            )
        logger.info(
            "Recorded %d experience(s) for section '%s' via V2 pipeline",
            min(len(issues), 10),
            section,
        )
        return
    except Exception as exc:
        logger.debug("V2 experience pipeline unavailable (%s), falling back to V1", exc)

    # V1 fallback
    try:
        from ..evolution.store import DBLessonStore, Lesson

        store_v1 = DBLessonStore(db)
        for issue in issues[:10]:
            store_v1.append(
                Lesson(
                    stage="section_draft",
                    content=issue,
                    lesson_type="failure",
                    tags=["auto_review", section],
                ),
                source="auto_review",
                topic_id=topic_id,
            )
        logger.info(
            "Recorded %d writing lesson(s) for section '%s'",
            min(len(issues), 10),
            section,
        )
    except Exception as exc:
        logger.debug("Could not record writing lessons: %s", exc)


_STOPWORDS = {
    "about",
    "above",
    "across",
    "after",
    "again",
    "against",
    "algorithm",
    "algorithms",
    "among",
    "and",
    "approach",
    "approaches",
    "are",
    "based",
    "between",
    "beyond",
    "budget",
    "bidding",
    "channel",
    "channels",
    "data",
    "deep",
    "for",
    "from",
    "into",
    "learning",
    "method",
    "methods",
    "model",
    "models",
    "multi",
    "neural",
    "online",
    "paper",
    "papers",
    "research",
    "results",
    "study",
    "system",
    "systems",
    "that",
    "the",
    "their",
    "these",
    "this",
    "through",
    "using",
    "with",
}


def _tokenize_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text.lower())
    return [token for token in tokens if token not in _STOPWORDS]


def _collect_topic_query_context(
    db: Database,
    topic_id: int,
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.title, p.abstract, p.authors, p.venue
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
        query_rows = conn.execute(
            "SELECT query FROM search_query_registry WHERE topic_id = ? ORDER BY created_at",
            (topic_id,),
        ).fetchall()
        artifact_rows = conn.execute(
            """
            SELECT payload_json FROM project_artifacts
            WHERE topic_id = ? AND artifact_type IN ('gap_analysis', 'evidence_pack', 'claim_candidate_set')
              AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 6
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    keyword_counter: collections.Counter[str] = collections.Counter()
    author_counter: collections.Counter[str] = collections.Counter()
    venue_counter: collections.Counter[str] = collections.Counter()

    for row in rows:
        text = " ".join(
            part for part in (row["title"] or "", row["abstract"] or "") if part
        )
        keyword_counter.update(_tokenize_keywords(text))
        venue = str(row["venue"] or "").strip()
        if venue:
            venue_counter.update([venue])
        try:
            authors = json.loads(row["authors"]) if row["authors"] else []
        except (TypeError, json.JSONDecodeError):
            authors = []
        for author in authors[:8]:
            name = str(author).strip()
            if name:
                author_counter.update([name])

    gaps: list[str] = []
    for row in artifact_rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        for gap in payload.get("gaps", []):
            if isinstance(gap, dict) and gap.get("description"):
                gaps.append(str(gap["description"]).strip())

    known_queries = [str(row["query"]).strip() for row in query_rows if row["query"]]
    return (
        [term for term, _ in keyword_counter.most_common(12)],
        [author for author, _ in author_counter.most_common(6)],
        [venue for venue, _ in venue_counter.most_common(6)],
        known_queries,
        gaps[:10],
    )


def paper_summarize(
    *,
    db: Database,
    paper_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> SummaryOutput:
    title, text = _get_paper_text(db, paper_id)
    if not text:
        return SummaryOutput(
            paper_id=paper_id,
            summary="(no text available for summarization)",
            focus=focus,
            confidence=0.0,
            model_used="none",
        )

    client = _get_client(
        _model,
        tier=_PRIMITIVE_TIERS.get("paper_summarize"),
        task_name="paper_summarize",
    )
    raw = _client_chat(client, prompts.paper_summarize_prompt(title, text, focus))
    parsed = _parse_json(raw, primitive="paper_summarize")
    return SummaryOutput(
        paper_id=paper_id,
        summary=str(parsed.get("summary") or raw[:2000]).strip(),
        focus=focus,
        confidence=_coerce_float(parsed.get("confidence"), 0.5),
        model_used=client.model,
    )


def claim_extract(
    *,
    db: Database,
    paper_ids: list[int],
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> ClaimExtractOutput:
    del topic_id
    snippets: list[str] = []
    skipped: list[int] = []
    for paper_id in paper_ids:
        try:
            title, text = _get_paper_text(db, paper_id)
            # Try paperindex for richer context
            pi_context = _get_paperindex_context(db, paper_id, "claim_extract")
            if pi_context:
                snippets.append(
                    f"[Paper {paper_id}] {_paper_label(paper_id, title)}\n{pi_context}"
                )
            else:
                snippets.append(
                    f"[Paper {paper_id}] {_paper_label(paper_id, title)}\n{text}"
                )
        except Exception:
            logger.warning(
                "Skipping paper %d in claim_extract: corrupted or unreadable", paper_id
            )
            skipped.append(paper_id)
            continue

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("claim_extract"))
    raw = _client_chat(
        client, prompts.claim_extract_prompt("\n\n".join(snippets), focus)
    )
    parsed = _parse_json(raw, primitive="claim_extract")

    claims: list[Claim] = []
    for item in parsed.get("claims", []):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        claims.append(
            Claim(
                claim_id="",
                content=content,
                paper_ids=paper_ids,
                evidence_type=str(item.get("evidence_type", "")).strip(),
                confidence=_coerce_float(item.get("confidence"), 0.5),
            )
        )

    return ClaimExtractOutput(claims=claims, papers_processed=len(paper_ids))


def gap_detect(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> GapDetectOutput:
    summary, related_paper_ids = _get_topic_literature_summary(
        db, topic_id, task_type="gap_detect"
    )
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("gap_detect"))
    raw = _client_chat(client, prompts.gap_detect_prompt(summary, focus))
    parsed = _parse_json(raw, primitive="gap_detect")

    gaps: list[Gap] = []
    for item in parsed.get("gaps", []):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        if not description:
            continue
        gaps.append(
            Gap(
                gap_id="",
                description=description,
                gap_type=str(item.get("gap_type", "")).strip(),
                severity=str(item.get("severity", "medium")).strip() or "medium",
                related_paper_ids=related_paper_ids,
            )
        )

    # Persist to DB so direction_ranking / query_refine can consume.
    # INSERT OR IGNORE keeps (topic_id, description) unique — re-running
    # gap_detect on the same topic won't create duplicates.
    if gaps:
        conn = db.connect()
        try:
            related_ids_json = json.dumps(related_paper_ids)
            for gap in gaps:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO gaps
                        (topic_id, description, gap_type, severity, related_paper_ids, focus)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        topic_id,
                        gap.description,
                        gap.gap_type,
                        gap.severity,
                        related_ids_json,
                        focus,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    return GapDetectOutput(gaps=gaps, papers_analyzed=len(related_paper_ids))


def query_refine(
    *,
    db: Database,
    topic_id: int,
    max_candidates: int = 8,
    _model: str | None = None,
    **_: Any,
) -> QueryRefineOutput:
    summary, _ = _get_topic_literature_summary(db, topic_id, task_type="gap_detect")
    top_keywords, frequent_authors, venues, known_queries, gaps = (
        _collect_topic_query_context(db, topic_id)
    )

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("query_refine"))
    raw = _client_chat(
        client,
        prompts.query_refine_prompt(
            topic_summary=summary,
            top_keywords=top_keywords,
            frequent_authors=frequent_authors,
            venues=venues,
            known_queries=known_queries,
            gaps=gaps,
            max_candidates=max_candidates,
        ),
    )
    parsed = _parse_json(raw, primitive="query_refine")

    candidates: list[QueryCandidate] = []
    seen_queries = {query.casefold() for query in known_queries}
    for item in parsed.get("candidates", []):
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        if not query:
            continue
        lowered = query.casefold()
        if lowered in seen_queries:
            continue
        seen_queries.add(lowered)
        candidates.append(
            QueryCandidate(
                query=query,
                rationale=str(item.get("rationale", "")).strip(),
                coverage_direction=str(item.get("coverage_direction", "")).strip(),
                priority=str(item.get("priority", "medium")).strip() or "medium",
            )
        )

    return QueryRefineOutput(
        topic_id=topic_id,
        candidates=candidates[:max_candidates],
        top_keywords=top_keywords,
        frequent_authors=frequent_authors,
        venue_distribution=venues,
        known_queries=known_queries,
        gaps_considered=gaps,
        model_used=client.model,
    )


def paper_coverage_check(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> CoverageCheckOutput:
    conn = db.connect()
    try:
        # Fetch topic context
        topic_row = conn.execute(
            "SELECT name, description FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        topic_context = ""
        if topic_row:
            name = topic_row["name"] or ""
            desc = topic_row["description"] or ""
            topic_context = f"{name}\n{desc}".strip()

        # Fetch all papers for this topic (excluding already-dismissed ones)
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.arxiv_id, p.doi, p.url, p.pdf_path, p.status
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY p.id
            """,
            (topic_id,),
        ).fetchall()

        # Check which papers have abstract annotations
        abstract_by_paper: dict[int, str] = {}
        for row in rows:
            pid = row["id"]
            ann = conn.execute(
                """
                SELECT content FROM paper_annotations
                WHERE paper_id = ? AND section IN ('abstract', 'summary')
                  AND COALESCE(content, '') != ''
                LIMIT 1
                """,
                (pid,),
            ).fetchone()
            if ann:
                abstract_by_paper[pid] = (ann["content"] or "").strip()

        # Fetch past dismissal reasons to calibrate LLM scoring
        dismissed_rows = conn.execute(
            """
            SELECT p.title, tpn.content as reason
            FROM topic_paper_notes tpn
            JOIN papers p ON p.id = tpn.paper_id
            WHERE tpn.topic_id = ? AND tpn.note_type = 'user_dismissed'
              AND COALESCE(tpn.content, '') != ''
            ORDER BY tpn.created_at DESC
            LIMIT 20
            """,
            (topic_id,),
        ).fetchall()
        dismissal_history = [(r["title"], r["reason"]) for r in dismissed_rows]

    finally:
        conn.close()

    # Filter to papers without PDF (meta_only or no pdf_path)
    meta_papers = [r for r in rows if not r["pdf_path"] or r["status"] == "meta_only"]

    if not meta_papers:
        return CoverageCheckOutput(items=[], total_meta_only=0, high_necessity_count=0)

    # Build prompt input: id | title | has_abstract | snippet
    lines = []
    for r in meta_papers:
        pid = r["id"]
        title = r["title"] or f"Paper #{pid}"
        has_abs = pid in abstract_by_paper
        snippet = abstract_by_paper.get(pid, "")[:200] if has_abs else "(no abstract)"
        lines.append(f"{pid} | {title} | {'yes' if has_abs else 'no'} | {snippet}")
    papers_text = "\n".join(lines)

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("paper_coverage_check"))
    raw = _client_chat(
        client,
        prompts.paper_coverage_check_prompt(
            topic_context, papers_text, focus, dismissal_history
        ),
    )
    parsed = _parse_json(raw, primitive="paper_coverage_check")

    # Build necessity lookup from LLM response
    necessity_map: dict[int, tuple[str, str]] = {}
    for item in parsed.get("assessments", []):
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item["paper_id"])
        except (KeyError, ValueError, TypeError):
            continue
        level = str(item.get("necessity_level", "medium")).strip() or "medium"
        reason = str(item.get("reason", "")).strip()
        necessity_map[pid] = (level, reason)

    # Build download hints and CoverageItems
    items: list[CoverageItem] = []
    for r in meta_papers:
        pid = r["id"]
        arxiv_id = r["arxiv_id"] or ""
        doi = r["doi"] or ""
        url = r["url"] or ""

        if arxiv_id:
            hint = f"https://arxiv.org/abs/{arxiv_id}"
        elif doi:
            hint = f"https://doi.org/{doi}"
        elif url:
            hint = url
        else:
            hint = ""

        necessity_level, reason = necessity_map.get(pid, ("medium", ""))
        items.append(
            CoverageItem(
                paper_id=pid,
                title=r["title"] or f"Paper #{pid}",
                has_abstract=pid in abstract_by_paper,
                has_pdf=bool(r["pdf_path"]),
                necessity_level=necessity_level,
                reason=reason,
                download_hint=hint,
                arxiv_id=arxiv_id,
                doi=doi,
            )
        )

    # Sort: high first, then medium, then low
    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: (order.get(x.necessity_level, 1), x.paper_id))

    high_count = sum(1 for it in items if it.necessity_level == "high")
    return CoverageCheckOutput(
        items=items,
        total_meta_only=len(meta_papers),
        high_necessity_count=high_count,
    )


def baseline_identify(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> BaselineIdentifyOutput:
    summary, related_paper_ids = _get_topic_literature_summary(
        db, topic_id, task_type="baseline_identify"
    )
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("baseline_identify"))
    raw = _client_chat(client, prompts.baseline_identify_prompt(summary, focus))
    parsed = _parse_json(raw, primitive="baseline_identify")

    baselines: list[Baseline] = []
    for item in parsed.get("baselines", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        baselines.append(
            Baseline(
                name=name,
                paper_ids=related_paper_ids,
                metrics=metrics,
                notes=str(item.get("notes", "")).strip(),
            )
        )

    return BaselineIdentifyOutput(baselines=baselines)


# ---------------------------------------------------------------------------
# Venue writing profiles — persistent competitive_learning cache
# ---------------------------------------------------------------------------

_VENUE_PROFILE_MAX_AGE_DAYS = 180


def _load_cached_venue_profiles(
    db: Database, venue: str
) -> CompetitiveLearningOutput | None:
    """Return cached CompetitiveLearningOutput if venue profiles are fresh enough."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT dimension, top_pattern, examples, paper_count, updated_at
               FROM venue_writing_profiles
               WHERE venue = ?
               ORDER BY dimension""",
            (venue,),
        ).fetchall()
    except Exception:
        return None
    finally:
        conn.close()
    if not rows:
        return None
    # Check freshness: all rows share roughly the same updated_at
    from datetime import datetime, timedelta, timezone

    try:
        oldest = min(datetime.fromisoformat(r["updated_at"]) for r in rows)
    except (ValueError, TypeError):
        return None
    if datetime.now(timezone.utc).replace(tzinfo=None) - oldest > timedelta(
        days=_VENUE_PROFILE_MAX_AGE_DAYS
    ):
        return None
    patterns: list[WritingPattern] = []
    for r in rows:
        patterns.append(
            WritingPattern(
                dimension=r["dimension"],
                pattern=r["top_pattern"],
                example="",
                source_paper="",
            )
        )
    return CompetitiveLearningOutput(
        venue=venue,
        exemplar_count=rows[0]["paper_count"] if rows else 0,
        patterns=patterns,
        model_used="cache",
    )


def _persist_venue_profiles(
    db: Database,
    venue: str,
    patterns: list[WritingPattern],
    paper_count: int,
) -> None:
    """Upsert venue writing profiles from competitive_learning results."""
    if not patterns:
        return
    conn = db.connect()
    try:
        for p in patterns:
            conn.execute(
                """INSERT INTO venue_writing_profiles
                   (venue, dimension, top_pattern, paper_count, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(venue, dimension) DO UPDATE SET
                     top_pattern = excluded.top_pattern,
                     paper_count = excluded.paper_count,
                     updated_at = excluded.updated_at""",
                (venue, p.dimension, p.pattern, paper_count),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed to persist venue profiles for %s: %s", venue, exc)
    finally:
        conn.close()


def competitive_learning(
    *,
    db: Database,
    topic_id: int,
    venue: str,
    paper_ids: list[int] | None = None,
    contributions: str = "",
    _model: str | None = None,
    **_: Any,
) -> CompetitiveLearningOutput:
    """Analyze exemplar papers from a venue to extract writing patterns.

    If paper_ids is provided, uses those specific papers as exemplars.
    Otherwise, selects the highest-cited recent papers from the topic pool
    that match the target venue.

    ``contributions`` is optional: if omitted, auto-loaded from the most
    recently updated project's ``projects.contributions`` for this topic.
    """
    if not contributions.strip():
        contributions = _get_topic_latest_project_contributions(db, topic_id)

    # Check freshness cache: skip LLM if venue profiles are < 180 days old
    cached = _load_cached_venue_profiles(db, venue)
    if cached is not None:
        return cached

    conn = db.connect()
    try:
        # Select exemplar papers: user-specified or auto-selected by venue + citations
        if paper_ids:
            placeholders = ",".join("?" * len(paper_ids))
            rows = conn.execute(
                f"SELECT id, title, abstract, venue, year FROM papers WHERE id IN ({placeholders})",
                paper_ids,
            ).fetchall()
        else:
            # Auto-select: recent high-cited papers matching venue keyword
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.abstract, p.venue, p.year
                FROM papers p
                JOIN paper_topics pt ON p.id = pt.paper_id
                WHERE pt.topic_id = ?
                  AND p.year >= strftime('%Y', 'now', '-2 years')
                  AND (p.venue LIKE ? OR p.venue LIKE ?)
                ORDER BY p.citation_count DESC NULLS LAST
                LIMIT 8
                """,
                (topic_id, f"%{venue}%", f"%{venue.split()[0]}%"),
            ).fetchall()

        if not rows:
            # Fallback 2: OpenAlex venue_papers for real venue exemplars
            try:
                from ..paper_source_clients import OpenAlexProvider

                oa = OpenAlexProvider()
                oa_records = oa.venue_papers(venue, limit=8)
                if oa_records:
                    rows = [
                        {
                            "id": 0,
                            "title": r.title,
                            "abstract": r.abstract,
                            "venue": r.venue,
                            "year": r.year,
                        }
                        for r in oa_records
                    ]
            except Exception as exc:
                logger.debug("OpenAlex venue_papers fallback failed: %s", exc)

        if not rows:
            # Fallback 3: just pick top-cited recent papers from topic
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.abstract, p.venue, p.year
                FROM papers p
                JOIN paper_topics pt ON p.id = pt.paper_id
                WHERE pt.topic_id = ?
                  AND p.year >= strftime('%Y', 'now', '-2 years')
                ORDER BY p.citation_count DESC NULLS LAST
                LIMIT 5
                """,
                (topic_id,),
            ).fetchall()
    finally:
        conn.close()

    # Build exemplar text block
    exemplar_parts: list[str] = []
    for r in rows:
        parts = [
            f"### {r['title']} ({r['venue'] or 'unknown venue'}, {r['year'] or '?'})"
        ]
        if r["abstract"]:
            parts.append(f"Abstract: {r['abstract'][:800]}")
        exemplar_parts.append("\n".join(parts))

    exemplar_text = "\n\n".join(exemplar_parts)
    if not exemplar_text.strip():
        return CompetitiveLearningOutput(venue=venue, exemplar_count=0)

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("competitive_learning"))
    raw = _client_chat(
        client,
        prompts.competitive_learning_prompt(venue, exemplar_text, contributions),
    )
    parsed = _parse_json(raw, primitive="competitive_learning")

    patterns: list[WritingPattern] = []
    for item in parsed.get("patterns", []):
        if not isinstance(item, dict):
            continue
        dim = str(item.get("dimension", "")).strip()
        pat = str(item.get("pattern", "")).strip()
        if dim and pat:
            patterns.append(
                WritingPattern(
                    dimension=dim,
                    pattern=pat,
                    example=str(item.get("example", "")).strip(),
                    source_paper=str(item.get("source_paper", "")).strip(),
                )
            )

    section_norms = parsed.get("section_length_norms", {})
    if not isinstance(section_norms, dict):
        section_norms = {}
    section_norms = {
        str(k): int(v) for k, v in section_norms.items() if isinstance(v, (int, float))
    }

    result = CompetitiveLearningOutput(
        venue=venue,
        exemplar_count=len(rows),
        patterns=patterns,
        section_length_norms=section_norms,
        narrative_guidance=str(parsed.get("narrative_guidance", "")).strip(),
        model_used=client.model,
    )

    _persist_venue_profiles(db, venue, patterns, len(rows))

    return result


_DEFAULT_WORD_TARGETS: dict[str, int] = {
    "abstract": 220,
    "introduction": 1500,
    "related_work": 2500,
    "related work": 2500,
    "method": 3000,
    "methodology": 3000,
    "experiments": 3500,
    "experiment": 3500,
    "results": 1500,
    "discussion": 900,
    "conclusion": 350,
    "conclusions": 350,
    "limitations": 350,
    "appendix": 3000,
}


def _default_citation_quota(section: str) -> int:
    from .writing_checks import SECTION_CITATION_QUOTA

    return SECTION_CITATION_QUOTA.get(section.lower().strip(), 0)


def section_draft(
    *,
    db: Database,
    section: str,
    topic_id: int,
    evidence_ids: list[str] | None = None,
    outline: str = "",
    writing_patterns: str = "",
    max_words: int = 0,
    citation_quota: int = -1,
    _model: str | None = None,
    **_: Any,
) -> SectionDraftOutput:
    sec_lower = section.lower().strip()

    # Use richer numbered evidence list (citation-aware) instead of legacy summary
    evidence_text, _paper_ids = _build_numbered_evidence(
        db,
        topic_id,
        max_papers=50,
        task_type="section_draft",
    )
    if not evidence_text or evidence_text == "(no papers in topic)":
        # fallback to legacy
        evidence_text, _ = _get_topic_literature_summary(
            db, topic_id, task_type="section_draft"
        )

    # Default word target if caller did not specify
    if max_words <= 0:
        max_words = _DEFAULT_WORD_TARGETS.get(sec_lower, 2000)

    # Default citation quota if caller did not specify
    if citation_quota < 0:
        citation_quota = _default_citation_quota(section)

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("section_draft"))

    # Auto-inject Universal Writing Skill guidance for this section
    section_guidance = ""
    try:
        from ..evolution.writing_skill import WritingSkillAggregator

        aggregator = WritingSkillAggregator(db)
        section_guidance = aggregator.get_section_guidance(sec_lower.replace(" ", "_"))
    except Exception as exc:
        logger.debug("Writing skill guidance unavailable: %s", exc)

    # Wire 1: Auto-inject writing lessons from previous runs
    lesson_overlay = _load_writing_lessons(db, topic_id, stage="section_draft")
    if lesson_overlay:
        section_guidance = (
            f"{section_guidance}\n\n{lesson_overlay}"
            if section_guidance
            else lesson_overlay
        )

    # Dispatch to section-specific prompt (intro/related_work/experiments use custom prompts)
    prompt_text = prompts.build_section_draft_prompt(
        section=section,
        outline=outline,
        evidence_text=evidence_text,
        max_words=max_words,
        section_guidance=section_guidance,
        citation_quota=citation_quota,
        writing_patterns=writing_patterns,
        evidence_count=len(_paper_ids),
    )
    raw = _client_chat(client, prompt_text)

    parsed = _parse_json(raw, primitive="section_draft", context=section)
    content = str(parsed.get("content") or raw[: max_words * 8]).strip()

    # Post-draft citation audit: flag out-of-range [N] markers
    audit_warnings = _audit_draft_citations(content, len(_paper_ids))
    if audit_warnings:
        logger.warning(
            "Citation audit for section '%s': %d issue(s) — %s",
            section,
            len(audit_warnings),
            "; ".join(audit_warnings[:5]),
        )

    # Wire 2: Run deterministic checks and record failures as writing lessons
    _record_writing_lessons_from_draft(
        db, topic_id, section, content, audit_warnings, max_words
    )

    return SectionDraftOutput(
        draft=DraftText(
            section=section,
            content=content,
            citations_used=_coerce_int_list(parsed.get("citations_used")),
            evidence_ids=evidence_ids or [],
            word_count=_coerce_int(parsed.get("word_count"), len(content.split())),
        )
    )


def draft_with_review_loop(
    *,
    db: Database,
    section: str,
    topic_id: int,
    evidence_ids: list[str] | None = None,
    outline: str = "",
    writing_patterns: str = "",
    max_words: int = 0,
    citation_quota: int = -1,
    max_revisions: int = 2,
    _model: str | None = None,
    **_: Any,
) -> SectionDraftOutput:
    """Draft a section with automatic review-revise loop.

    This is the "self-correct" wire of the self-evolution loop:
    1. Draft via section_draft
    2. Run deterministic checks
    3. If checks fail, build feedback and revise (up to max_revisions times)
    4. Return the best version

    Lessons are recorded automatically by section_draft (Wire 2).
    """
    from .writing_checks import run_all_checks

    # Initial draft
    result = section_draft(
        db=db,
        section=section,
        topic_id=topic_id,
        evidence_ids=evidence_ids,
        outline=outline,
        writing_patterns=writing_patterns,
        max_words=max_words,
        citation_quota=citation_quota,
        _model=_model,
    )
    content = result.draft.content

    for revision_round in range(max_revisions):
        # Run deterministic review checks
        check_results = run_all_checks(content, section, max_words)
        failed = [c for c in check_results if not c.passed]

        if not failed:
            logger.info(
                "Section '%s' passed all checks after %d revision(s)",
                section,
                revision_round,
            )
            break

        # Build feedback from failed checks
        feedback_lines = [f"- {c.check_name}: {c.details}" for c in failed]
        feedback = (
            f"Revision round {revision_round + 1}/{max_revisions}. "
            f"The following checks failed:\n" + "\n".join(feedback_lines)
        )

        logger.info(
            "Section '%s' has %d failed check(s), starting revision %d/%d",
            section,
            len(failed),
            revision_round + 1,
            max_revisions,
        )

        # Revise
        client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("section_revise"))
        revise_prompt = (
            f"You are revising the {section} section of an academic paper.\n\n"
            f"## Review feedback\n{feedback}\n\n"
            f"## Current content\n{content}\n\n"
            f"Fix ALL flagged issues. Return the revised section in the same "
            f"LaTeX format. Preserve all citation markers [N] and equations. "
            f"Target ~{max_words} words.\n\n"
            f'Return JSON: {{"content": "...", "changes_made": ["..."]}}'
        )

        raw = _client_chat(client, revise_prompt)
        parsed = _parse_json(raw, primitive="section_revise", context=section)
        revised = str(parsed.get("content") or raw[: max_words * 8]).strip()
        if revised:
            content = revised
    else:
        logger.warning(
            "Section '%s' still has issues after %d revision(s)",
            section,
            max_revisions,
        )

    return SectionDraftOutput(
        draft=DraftText(
            section=section,
            content=content,
            citations_used=result.draft.citations_used,
            evidence_ids=evidence_ids or [],
            word_count=len(content.split()),
        )
    )


def outline_generate(
    *,
    db: Database,
    topic_id: int,
    project_id: int,
    template: str = "neurips",
    contributions: str = "",
    _model: str | None = None,
    **_: Any,
) -> OutlineGenerateOutput:
    """Generate paper outline from topic literature, claims, and contributions.

    ``contributions`` fallback order:
      1. Explicit argument (caller-provided).
      2. ``projects.contributions`` for this project_id (project-level config).
      3. Latest ``writing_architecture`` artifact for this project+topic.
    If none of the above yield a non-empty string, this primitive REFUSES to
    run rather than letting the LLM invent a paper from topic literature.
    """
    summary, _ = _get_topic_literature_summary(db, topic_id, task_type="section_draft")

    # Fallback 2: project-level config
    if not contributions.strip():
        contributions = _get_project_contributions(db, project_id)

    # Gather claims if available
    conn = db.connect()
    try:
        claims_rows = conn.execute(
            """
            SELECT content FROM topic_paper_notes
            WHERE topic_id = ? AND note_type = 'claim'
            ORDER BY id DESC LIMIT 30
            """,
            (topic_id,),
        ).fetchall()
        # Fallback 3: read from writing_architecture artifact if still empty.
        if not contributions.strip():
            arch_rows = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE project_id = ? AND topic_id = ?
                  AND artifact_type = 'writing_architecture'
                  AND status = 'active'
                ORDER BY created_at DESC LIMIT 1
                """,
                (project_id, topic_id),
            ).fetchall()
            if arch_rows:
                try:
                    payload = json.loads(arch_rows[0]["payload_json"])
                    parts: list[str] = []
                    title = str(payload.get("paper_title", "")).strip()
                    if title:
                        parts.append(f"Paper title: {title}")
                    narr = str(payload.get("narrative_strategy", "")).strip()
                    if narr:
                        parts.append(f"Narrative strategy: {narr}")
                    for sec in payload.get("sections", []) or []:
                        if not isinstance(sec, dict):
                            continue
                        arg = str(sec.get("argument_strategy", "")).strip()
                        if arg:
                            parts.append(f"- {sec.get('section', '?')}: {arg}")
                    if parts:
                        contributions = "\n".join(parts)
                except (json.JSONDecodeError, TypeError):
                    pass
    finally:
        conn.close()
    claims_text = (
        "\n".join(r["content"] for r in claims_rows if r["content"])
        if claims_rows
        else "(no claims extracted yet)"
    )

    if not contributions.strip():
        raise ValueError(
            "outline_generate requires paper contributions but none were found. "
            "Resolution order checked: (1) `contributions` argument, "
            f"(2) projects.contributions for project_id={project_id}, "
            "(3) writing_architecture artifact. "
            "Fix by calling `project_set_contributions(project_id, contributions=...)` "
            "or running `writing_architecture` first, or pass contributions explicitly. "
            "Refusing to generate to avoid hallucinating an unrelated paper from topic literature."
        )

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("outline_generate"))
    raw = _client_chat(
        client,
        prompts.outline_generate_prompt(summary, claims_text, template, contributions),
    )
    parsed = _parse_json(raw, primitive="outline_generate")

    sections: list[OutlineSectionItem] = []
    for item in parsed.get("sections", []):
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("section", "")).strip()
        if not section_id:
            continue
        sections.append(
            OutlineSectionItem(
                section=section_id,
                title=str(item.get("title", section_id)).strip(),
                target_words=_coerce_int(item.get("target_words"), 800),
                key_points=[str(p) for p in (item.get("key_points") or []) if p],
                evidence_ids=[str(e) for e in (item.get("evidence_ids") or []) if e],
            )
        )

    # Fallback to default sections if LLM returned empty
    if not sections:
        sections = [
            OutlineSectionItem(
                section="introduction", title="Introduction", target_words=1500
            ),
            OutlineSectionItem(
                section="related_work", title="Related Work", target_words=2500
            ),
            OutlineSectionItem(section="method", title="Method", target_words=3000),
            OutlineSectionItem(
                section="experiments", title="Experiments", target_words=3500
            ),
            OutlineSectionItem(
                section="discussion", title="Discussion", target_words=900
            ),
            OutlineSectionItem(
                section="conclusion", title="Conclusion", target_words=350
            ),
            OutlineSectionItem(
                section="limitations", title="Limitations", target_words=350
            ),
            OutlineSectionItem(section="appendix", title="Appendix", target_words=3000),
        ]

    total = sum(s.target_words for s in sections)
    return OutlineGenerateOutput(
        title=str(parsed.get("title", "")).strip(),
        abstract_draft=str(parsed.get("abstract_draft", "")).strip(),
        sections=sections,
        total_target_words=total,
        model_used=client.model,
    )


def section_review(
    *,
    db: Database,
    section: str,
    content: str,
    target_words: int = 0,
    _model: str | None = None,
    **_: Any,
) -> SectionReviewOutput:
    """Review a paper section: LLM 10-dim scoring + deterministic checks."""
    from ..execution.writing_checks import REVIEW_DIMENSIONS as DIM_NAMES
    from ..execution.writing_checks import run_all_checks

    # 1. Run deterministic checks
    check_results = run_all_checks(content, section, target_words)
    deterministic_checks = [
        DeterministicCheck(
            check_name=c.check_name,
            passed=c.passed,
            details=c.details,
            items_found=c.items_found,
        )
        for c in check_results
    ]

    # 2. LLM scoring
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("section_review"))
    raw = _client_chat(
        client, prompts.section_review_prompt(section, content, target_words)
    )
    parsed = _parse_json(raw, primitive="section_review", context=section)

    # Parse dimensions from LLM response
    dim_map: dict[str, tuple[float, str]] = {}
    for item in parsed.get("dimensions", []):
        if not isinstance(item, dict):
            continue
        dim_name = str(item.get("dimension", "")).strip()
        if dim_name:
            dim_map[dim_name] = (
                _coerce_float(item.get("score"), 0.0),
                str(item.get("comment", "")).strip(),
            )

    # Build dimension list — use LLM scores where available, 0.0 otherwise
    dimensions: list[ReviewDimension] = []
    for dim_name in DIM_NAMES:
        score, comment = dim_map.get(dim_name, (0.0, ""))
        dimensions.append(
            ReviewDimension(dimension=dim_name, score=score, comment=comment)
        )

    # Calculate overall score
    overall = _coerce_float(parsed.get("overall_score"), 0.0)
    if overall == 0.0 and dimensions:
        scores = [d.score for d in dimensions if d.score > 0]
        overall = sum(scores) / len(scores) if scores else 0.0

    # Suggestions from LLM + deterministic failures
    suggestions: list[str] = [str(s) for s in (parsed.get("suggestions") or []) if s]
    failed_checks = [c for c in check_results if not c.passed]
    for c in failed_checks:
        suggestions.append(f"[{c.check_name}] {c.details}")

    needs_revision = overall < 0.6 or len(failed_checks) > 0

    return SectionReviewOutput(
        section=section,
        overall_score=round(overall, 3),
        dimensions=dimensions,
        deterministic_checks=deterministic_checks,
        suggestions=suggestions,
        needs_revision=needs_revision,
        model_used=client.model,
    )


def section_revise(
    *,
    db: Database,
    section: str,
    content: str,
    review_feedback: str,
    target_words: int = 0,
    _model: str | None = None,
    **_: Any,
) -> SectionReviseOutput:
    """Revise a paper section based on review feedback using LLM."""
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("section_revise"))
    raw = _client_chat(
        client,
        prompts.section_revise_prompt(section, content, review_feedback, target_words),
    )
    parsed = _parse_json(raw, primitive="section_revise", context=section)

    revised = str(parsed.get("revised_content") or raw[: len(content) * 2]).strip()
    changes = [str(c) for c in (parsed.get("changes_made") or []) if c]
    if not changes:
        changes = ["LLM revision applied"]

    word_count = _coerce_int(parsed.get("word_count"), len(revised.split()))

    return SectionReviseOutput(
        section=section,
        revised_content=revised,
        changes_made=changes,
        word_count=word_count,
        model_used=client.model,
    )


def consistency_check(
    *,
    db: Database,
    topic_id: int,
    sections: list[str] | None = None,
    _model: str | None = None,
    **_: Any,
) -> ConsistencyCheckOutput:
    summary, _ = _get_topic_literature_summary(
        db, topic_id, task_type="consistency_check"
    )
    requested_sections = sections or []
    sections_label = (
        ", ".join(requested_sections) if requested_sections else f"topic {topic_id}"
    )
    prompt_input = f"Sections under review: {sections_label}\n\n{summary}"

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("consistency_check"))
    raw = _client_chat(client, prompts.consistency_check_prompt(prompt_input))
    parsed = _parse_json(raw, primitive="consistency_check")

    issues: list[ConsistencyIssue] = []
    for item in parsed.get("issues", []):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        if not description:
            continue
        issues.append(
            ConsistencyIssue(
                issue_type=str(item.get("issue_type", "unknown")).strip() or "unknown",
                severity=str(item.get("severity", "medium")).strip() or "medium",
                location=str(item.get("location", "")).strip(),
                description=description,
                suggestion=str(item.get("suggestion", "")).strip(),
            )
        )

    return ConsistencyCheckOutput(
        issues=issues,
        sections_checked=requested_sections,
    )


def deep_read(
    *,
    db: Database,
    paper_id: int,
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> DeepReadingOutput:
    """Two-pass deep reading: extraction (medium) then critical analysis (heavy)."""
    title, text = _get_paper_text(db, paper_id)
    if not text:
        return DeepReadingOutput(
            paper_id=paper_id,
            note=DeepReadingNote(),
            model_used="none",
            confidence=0.0,
        )

    # --- Pass 1: deep extraction (medium tier, or joy_kimi for single-paper reading) ---
    client1 = _get_client(
        _model,
        tier=_PRIMITIVE_TIERS.get("deep_read_pass1"),
        task_name="deep_read_pass1",
    )
    raw1 = _client_chat(client1, prompts.deep_read_pass1_prompt(title, text, focus))
    p1 = _parse_json(raw1, primitive="deep_read", context="pass1")
    pass1_model = client1.model

    # --- Pass 2: critical analysis (heavy tier) ---
    topic_summary, _ = _get_topic_literature_summary(
        db, topic_id, task_type="deep_read"
    )
    pass1_json = json.dumps(p1, ensure_ascii=False)

    client2 = _get_client(
        _model,
        tier=_PRIMITIVE_TIERS.get("deep_read_pass2"),
        task_name="deep_read_pass2",
    )
    raw2 = _client_chat(
        client2,
        prompts.deep_read_pass2_prompt(title, pass1_json, text, topic_summary, focus),
    )
    p2 = _parse_json(raw2, primitive="deep_read", context="pass2")
    pass2_model = client2.model

    # Parse industrial feasibility
    feas_raw = p2.get("industrial_feasibility", {})
    if not isinstance(feas_raw, dict):
        feas_raw = {}
    feasibility = IndustrialFeasibility(
        viability=str(feas_raw.get("viability", "")).strip(),
        latency_constraints=str(feas_raw.get("latency_constraints", "")).strip(),
        data_requirements=str(feas_raw.get("data_requirements", "")).strip(),
        engineering_challenges=[
            str(c) for c in (feas_raw.get("engineering_challenges") or []) if c
        ],
        deployment_prerequisites=[
            str(p) for p in (feas_raw.get("deployment_prerequisites") or []) if p
        ],
    )

    # Parse cross-paper links
    links: list[CrossPaperLink] = []
    for item in p2.get("cross_paper_links", []):
        if not isinstance(item, dict):
            continue
        links.append(
            CrossPaperLink(
                target_paper_id=_coerce_int(item.get("target_paper_id"), 0),
                relation_type=str(item.get("relation_type", "")).strip(),
                evidence=str(item.get("evidence", "")).strip(),
            )
        )

    note = DeepReadingNote(
        algorithm_walkthrough=str(p1.get("algorithm_walkthrough", "")).strip(),
        limitation_analysis=str(p1.get("limitation_analysis", "")).strip(),
        reproducibility_assessment=str(
            p1.get("reproducibility_assessment", "")
        ).strip(),
        critical_assessment=str(p2.get("critical_assessment", "")).strip(),
        industrial_feasibility=feasibility,
        research_implications=[
            str(r) for r in (p2.get("research_implications") or []) if r
        ],
        cross_paper_links=links,
    )

    # --- Side effect: store in paper_annotations ---
    from dataclasses import asdict

    from ..storage.models import PaperAnnotation

    conn = db.connect()
    try:
        from ..core.paper_pool import PaperPool

        pool = PaperPool(conn)
        pool.upsert_annotation(
            PaperAnnotation(
                paper_id=paper_id,
                section="deep_reading",
                content=json.dumps(asdict(note), ensure_ascii=False),
                source=f"{pass1_model}+{pass2_model}",
                confidence=0.85,
                extractor_version="v1",
            )
        )
    finally:
        conn.close()

    return DeepReadingOutput(
        paper_id=paper_id,
        note=note,
        model_used=f"{pass1_model}+{pass2_model}",
        pass1_model=pass1_model,
        pass2_model=pass2_model,
        confidence=0.85,
    )


def code_generate(
    *,
    db: Database,
    topic_id: int,
    study_spec: str,
    iteration: int = 0,
    previous_code: str = "",
    previous_metrics: dict[str, Any] | None = None,
    feedback: str = "",
    _model: str | None = None,
    **_: Any,
) -> CodeGenerationOutput:
    """Generate experiment code from study spec and topic context."""
    summary, _ = _get_topic_literature_summary(db, topic_id, task_type="section_draft")
    metrics_str = json.dumps(previous_metrics or {})

    client = _get_client(_model, tier="heavy")
    raw = _client_chat(
        client,
        prompts.code_generate_prompt(
            study_spec=study_spec,
            topic_summary=summary,
            iteration=iteration,
            previous_code=previous_code,
            previous_metrics=metrics_str,
            feedback=feedback,
        ),
    )
    parsed = _parse_json(raw, primitive="code_generate", context=f"iter{iteration}")

    files = parsed.get("files", {})
    if not isinstance(files, dict):
        files = {}
    # Fallback: if LLM returned code directly without JSON wrapper
    if not files and raw.strip():
        files = {"main.py": raw.strip()}

    return CodeGenerationOutput(
        files=files,
        entry_point=str(parsed.get("entry_point", "main.py")),
        description=str(parsed.get("description", "")),
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Phase 2: Cross-paper analysis LLM primitives
# ---------------------------------------------------------------------------


def method_taxonomy(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    **_: Any,
) -> "MethodTaxonomyOutput":
    """Build method taxonomy from compiled summaries via LLM."""
    from ..primitives.types import MethodTaxonomyOutput, TaxonomyNode
    from .compiled_summary import ensure_compiled_summary, format_compiled_for_context

    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.year FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            ORDER BY COALESCE(p.citation_count, 0) DESC
            LIMIT 50
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return MethodTaxonomyOutput()

    # Build context from compiled summaries
    entries: list[str] = []
    for row in rows:
        pid = int(row["id"])
        compiled = ensure_compiled_summary(db, pid)
        ctx = format_compiled_for_context(compiled)
        header = f"[{pid}] {row['title'] or f'Paper #{pid}'}"
        if row["year"]:
            header += f" ({row['year']})"
        entries.append(f"{header}: {ctx}" if ctx else header)

    papers_text = "\n".join(entries)
    client = _get_client(tier="medium", task_name="method_taxonomy")
    prompt = prompts.method_taxonomy_prompt(papers_text, focus)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="method_taxonomy")
    nodes_raw = parsed.get("nodes", [])

    # Store to DB
    conn = db.connect()
    try:
        result_nodes: list[TaxonomyNode] = []
        node_name_to_id: dict[str, int] = {}

        # First pass: create all nodes
        for n in nodes_raw:
            name = n.get("name", "")
            if not name:
                continue
            aliases = n.get("aliases", [])
            desc = n.get("description", "")

            import json as _json

            conn.execute(
                """
                INSERT OR REPLACE INTO taxonomy_nodes (topic_id, name, description, aliases)
                VALUES (?, ?, ?, ?)
                """,
                (topic_id, name, desc, _json.dumps(aliases, ensure_ascii=False)),
            )
            nid_row = conn.execute(
                "SELECT id FROM taxonomy_nodes WHERE topic_id = ? AND name = ?",
                (topic_id, name),
            ).fetchone()
            nid = nid_row["id"] if nid_row else 0
            node_name_to_id[name] = nid

        # Second pass: set parent_id
        for n in nodes_raw:
            name = n.get("name", "")
            parent = n.get("parent")
            if parent and parent in node_name_to_id and name in node_name_to_id:
                conn.execute(
                    "UPDATE taxonomy_nodes SET parent_id = ? WHERE id = ?",
                    (node_name_to_id[parent], node_name_to_id[name]),
                )

        # Third pass: create assignments
        assignments = 0
        for n in nodes_raw:
            name = n.get("name", "")
            if name not in node_name_to_id:
                continue
            nid = node_name_to_id[name]
            for pid in n.get("paper_ids", []):
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO taxonomy_assignments (paper_id, node_id, confidence) VALUES (?, ?, 0.7)",
                        (int(pid), nid),
                    )
                    assignments += 1
                except Exception as exc:
                    logger.debug(
                        "Taxonomy assignment failed for paper %s → node %s: %s",
                        pid,
                        nid,
                        exc,
                    )

        conn.commit()

        # Build output
        for n in nodes_raw:
            name = n.get("name", "")
            if name not in node_name_to_id:
                continue
            parent_name = n.get("parent")
            result_nodes.append(
                TaxonomyNode(
                    node_id=node_name_to_id[name],
                    name=name,
                    parent_id=node_name_to_id.get(parent_name) if parent_name else None,
                    description=n.get("description", ""),
                    aliases=n.get("aliases", []),
                    paper_count=len(n.get("paper_ids", [])),
                )
            )
    finally:
        conn.close()

    return MethodTaxonomyOutput(
        nodes=result_nodes,
        assignments_count=assignments,
        papers_processed=len(rows),
    )


def evidence_matrix(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    **_: Any,
) -> "EvidenceMatrixOutput":
    """Build evidence matrix: query existing claims, normalize via LLM, store."""
    from ..primitives.types import EvidenceMatrixOutput, NormalizedClaim

    conn = db.connect()
    try:
        # Step 1: Gather claims from compiled summaries
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.compiled_summary FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND p.compiled_summary IS NOT NULL AND p.compiled_summary != ''
            ORDER BY COALESCE(p.citation_count, 0) DESC
            LIMIT 50
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return EvidenceMatrixOutput()

    import json as _json

    # Build claims context from compiled summaries
    claim_entries: list[str] = []
    for row in rows:
        pid = int(row["id"])
        try:
            compiled = _json.loads(row["compiled_summary"])
        except (TypeError, _json.JSONDecodeError):
            continue
        claims = compiled.get("claims", [])
        metrics = compiled.get("metrics", [])

        paper_claims: list[str] = []
        for c in claims:
            if isinstance(c, dict):
                paper_claims.append(c.get("claim", str(c)))
            elif isinstance(c, str):
                paper_claims.append(c)
        for m in metrics:
            if isinstance(m, dict):
                paper_claims.append(
                    f"{m.get('metric', '?')} on {m.get('dataset', '?')}: {m.get('value', '?')}"
                )

        if paper_claims:
            claim_entries.append(
                f"[Paper {pid}] {row['title'] or f'Paper #{pid}'}\n"
                + "\n".join(f"  - {c}" for c in paper_claims[:10])
            )

    if not claim_entries:
        return EvidenceMatrixOutput(papers_processed=len(rows))

    claims_text = "\n\n".join(claim_entries)
    client = _get_client(tier="medium", task_name="evidence_matrix")
    prompt = prompts.evidence_matrix_prompt(claims_text, focus)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="evidence_matrix")
    norm_claims_raw = parsed.get("normalized_claims", [])

    # Step 2: Store in DB
    conn = db.connect()
    result_claims: list[NormalizedClaim] = []
    methods_set: set[str] = set()
    datasets_set: set[str] = set()

    try:
        for nc in norm_claims_raw:
            paper_id = nc.get("paper_id", 0)
            claim_text = nc.get("claim_text", "")
            method = nc.get("method", "")
            dataset = nc.get("dataset", "")
            metric = nc.get("metric", "")
            task = nc.get("task", "")
            value = str(nc.get("value", ""))
            direction = nc.get("direction", "qualitative")
            confidence = float(nc.get("confidence", 0.5))

            if method:
                methods_set.add(method)
            if dataset:
                datasets_set.add(dataset)

            conn.execute(
                """
                INSERT INTO normalized_claims
                (topic_id, paper_id, claim_text, method, dataset, metric, task, value, direction, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic_id,
                    paper_id,
                    claim_text,
                    method,
                    dataset,
                    metric,
                    task,
                    value,
                    direction,
                    confidence,
                ),
            )
            cid_row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
            cid = cid_row["id"] if cid_row else 0

            result_claims.append(
                NormalizedClaim(
                    claim_id=cid,
                    paper_id=paper_id,
                    claim_text=claim_text,
                    method=method,
                    dataset=dataset,
                    metric=metric,
                    task=task,
                    value=value,
                    direction=direction,
                    confidence=confidence,
                )
            )

        conn.commit()
    finally:
        conn.close()

    return EvidenceMatrixOutput(
        claims=result_claims,
        methods=sorted(methods_set),
        datasets=sorted(datasets_set),
        papers_processed=len(rows),
    )


def contradiction_detect(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> "ContradictionDetectOutput":
    """Detect contradictions between normalized claims."""
    from ..primitives.types import (
        ContradictionCandidate,
        ContradictionDetectOutput,
        NormalizedClaim,
    )

    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, paper_id, claim_text, method, dataset, metric, task, value, direction, confidence
            FROM normalized_claims WHERE topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    if len(rows) < 2:
        return ContradictionDetectOutput(claims_analyzed=len(rows))

    # Build claims context
    claims_map: dict[int, NormalizedClaim] = {}
    lines: list[str] = []
    for r in rows:
        nc = NormalizedClaim(
            claim_id=int(r["id"]),
            paper_id=int(r["paper_id"]),
            claim_text=r["claim_text"],
            method=r["method"],
            dataset=r["dataset"],
            metric=r["metric"],
            task=r["task"],
            value=r["value"],
            direction=r["direction"],
            confidence=float(r["confidence"]),
        )
        claims_map[nc.claim_id] = nc
        lines.append(
            f"[{nc.claim_id}] paper={nc.paper_id} method={nc.method} "
            f"dataset={nc.dataset} metric={nc.metric} task={nc.task} "
            f"value={nc.value} direction={nc.direction}"
        )

    claims_text = "\n".join(lines)
    client = _get_client(tier="medium", task_name="contradiction_detect")
    prompt = prompts.contradiction_detect_prompt(claims_text)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="contradiction_detect")
    contras_raw = parsed.get("contradictions", [])

    # Store in DB
    conn = db.connect()
    results: list[ContradictionCandidate] = []
    try:
        for c in contras_raw:
            a_id = c.get("claim_a_id", 0)
            b_id = c.get("claim_b_id", 0)
            if a_id not in claims_map or b_id not in claims_map:
                continue

            conn.execute(
                """
                INSERT INTO contradictions
                (topic_id, claim_a_id, claim_b_id, same_task, same_dataset, same_metric, confidence, conflict_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic_id,
                    a_id,
                    b_id,
                    int(c.get("same_task", False)),
                    int(c.get("same_dataset", False)),
                    int(c.get("same_metric", False)),
                    float(c.get("confidence", 0.5)),
                    c.get("conflict_reason", ""),
                ),
            )
            cid_row = conn.execute("SELECT last_insert_rowid() as id").fetchone()

            results.append(
                ContradictionCandidate(
                    contradiction_id=cid_row["id"] if cid_row else 0,
                    claim_a=claims_map.get(a_id),
                    claim_b=claims_map.get(b_id),
                    same_task=bool(c.get("same_task", False)),
                    same_dataset=bool(c.get("same_dataset", False)),
                    same_metric=bool(c.get("same_metric", False)),
                    confidence=float(c.get("confidence", 0.5)),
                    conflict_reason=c.get("conflict_reason", ""),
                )
            )

        conn.commit()
    finally:
        conn.close()

    return ContradictionDetectOutput(
        contradictions=results,
        claims_analyzed=len(rows),
    )


# ---------------------------------------------------------------------------
# Phase 3: Quantitative extraction LLM primitives
# ---------------------------------------------------------------------------


def table_extract(
    *,
    db: Database,
    paper_id: int,
    **_: Any,
) -> "TableExtractOutput":
    """Extract structured tables from a paper via LLM."""
    from ..primitives.types import ExtractedTable, TableExtractOutput

    title, text = _get_paper_text(db, paper_id)
    if not text:
        return TableExtractOutput(paper_id=paper_id)

    client = _get_client(tier="medium", task_name="table_extract")
    prompt = prompts.table_extract_prompt(title, text)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="table_extract", context=title)
    tables_raw = parsed.get("tables", [])

    import json as _json

    conn = db.connect()
    result_tables: list[ExtractedTable] = []
    try:
        for t in tables_raw:
            headers = t.get("headers", [])
            rows = t.get("rows", [])
            table_num = t.get("table_number", 0)
            caption = t.get("caption", "")
            source_page = t.get("source_page")

            conn.execute(
                """
                INSERT INTO extracted_tables
                (paper_id, table_number, caption, headers, rows, source_page, confidence)
                VALUES (?, ?, ?, ?, ?, ?, 0.7)
                """,
                (
                    paper_id,
                    table_num,
                    caption,
                    _json.dumps(headers, ensure_ascii=False),
                    _json.dumps(rows, ensure_ascii=False),
                    source_page,
                ),
            )
            tid_row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
            tid = tid_row["id"] if tid_row else 0

            result_tables.append(
                ExtractedTable(
                    table_id=tid,
                    paper_id=paper_id,
                    table_number=table_num,
                    caption=caption,
                    headers=headers,
                    rows=rows,
                    source_page=source_page,
                    confidence=0.7,
                )
            )
        conn.commit()
    finally:
        conn.close()

    return TableExtractOutput(tables=result_tables, paper_id=paper_id)


def figure_interpret(
    *,
    db: Database,
    paper_id: int,
    **_: Any,
) -> "FigureInterpretOutput":
    """Interpret figures from a paper via LLM."""
    from ..primitives.types import ExtractedFigure, FigureInterpretOutput

    title, text = _get_paper_text(db, paper_id)
    if not text:
        return FigureInterpretOutput(paper_id=paper_id)

    client = _get_client(tier="medium", task_name="figure_interpret")
    prompt = prompts.figure_interpret_prompt(title, text)
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="figure_interpret", context=title)
    figures_raw = parsed.get("figures", [])

    import json as _json

    conn = db.connect()
    result_figures: list[ExtractedFigure] = []
    try:
        for f in figures_raw:
            fig_num = f.get("figure_number", 0)
            caption = f.get("caption", "")
            interp = f.get("interpretation", "")
            key_pts = f.get("key_data_points", [])
            fig_type = f.get("figure_type", "")
            source_page = f.get("source_page")

            conn.execute(
                """
                INSERT INTO extracted_figures
                (paper_id, figure_number, caption, interpretation, key_data_points, figure_type, source_page)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    fig_num,
                    caption,
                    interp,
                    _json.dumps(key_pts, ensure_ascii=False),
                    fig_type,
                    source_page,
                ),
            )
            fid_row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
            fid = fid_row["id"] if fid_row else 0

            result_figures.append(
                ExtractedFigure(
                    figure_id=fid,
                    paper_id=paper_id,
                    figure_number=fig_num,
                    caption=caption,
                    interpretation=interp,
                    key_data_points=key_pts,
                    figure_type=fig_type,
                    source_page=source_page,
                )
            )
        conn.commit()
    finally:
        conn.close()

    return FigureInterpretOutput(figures=result_figures, paper_id=paper_id)


# ---------------------------------------------------------------------------
# Phase 4: Workflow primitives
# ---------------------------------------------------------------------------


def rebuttal_format(
    *,
    db: Database,
    project_id: int,
    **_: Any,
) -> "RebuttalFormatOutput":
    """Format a rebuttal letter from review issues and author responses."""
    from ..primitives.types import RebuttalFormatOutput

    conn = db.connect()
    try:
        # Gather review issues
        issues = conn.execute(
            """
            SELECT ri.severity, ri.category, ri.summary, ri.details, ri.recommended_action
            FROM review_issues ri
            WHERE ri.project_id = ? AND ri.status != 'resolved'
            ORDER BY
                CASE ri.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                ri.created_at
            """,
            (project_id,),
        ).fetchall()

        # Gather responses
        responses = conn.execute(
            """
            SELECT rr.response_type, rr.response_text, ri.summary as issue_summary
            FROM review_responses rr
            JOIN review_issues ri ON ri.id = rr.issue_id
            WHERE rr.project_id = ?
            ORDER BY rr.created_at
            """,
            (project_id,),
        ).fetchall()
    finally:
        conn.close()

    if not issues:
        return RebuttalFormatOutput(
            rebuttal_text="No review issues found for this project.",
            issues_addressed=0,
            project_id=project_id,
        )

    # Build issue text
    issue_lines: list[str] = []
    for i in issues:
        line = f"[{i['severity'].upper()}] {i['category']}: {i['summary']}"
        if i["details"]:
            line += f"\n  Details: {i['details']}"
        if i["recommended_action"]:
            line += f"\n  Recommended: {i['recommended_action']}"
        issue_lines.append(line)

    # Build response text
    resp_lines: list[str] = []
    for r in responses:
        resp_lines.append(
            f"Re: {r['issue_summary']}\n  [{r['response_type']}] {r['response_text']}"
        )

    issues_text = "\n\n".join(issue_lines)
    responses_text = (
        "\n\n".join(resp_lines) if resp_lines else "(no responses recorded)"
    )

    client = _get_client(tier="medium", task_name="rebuttal_format")
    prompt = prompts.rebuttal_draft_prompt(issues_text, responses_text)
    rebuttal = _client_chat(client, prompt)

    return RebuttalFormatOutput(
        rebuttal_text=rebuttal.strip(),
        issues_addressed=len(issues),
        project_id=project_id,
    )


# ---------------------------------------------------------------------------
# Evolution primitives (LLM-powered)
# ---------------------------------------------------------------------------


def lesson_extract(
    *,
    db: Database,
    stage: str,
    stage_summary: str,
    issues_encountered: list[str] | None = None,
    session_id: str = "",
    **_: Any,
) -> "LessonExtractOutput":
    """Extract structured lessons from a stage execution using LLM.

    Analyses trajectory data (if available) plus the stage summary and
    issues to produce structured lessons that feed into strategy distillation.
    """
    from ..primitives.types import LessonExtractOutput, LessonItem

    issues = issues_encountered or []

    # Build trajectory context if session_id provided
    trajectory_text = ""
    if session_id:
        try:
            from ..evolution.trajectory import TrajectoryRecorder

            events = TrajectoryRecorder.get_stage_trajectories(
                db,
                stage,
                limit=30,
            )
            trajectory_text = TrajectoryRecorder.format_trajectory_text(events)
        except Exception:
            trajectory_text = "(trajectory data unavailable)"

    # Build the extraction prompt
    prompt_parts = [
        "You are a research workflow analyst. Extract structured lessons "
        "from the following stage execution data.\n",
        f"## Stage: {stage}\n",
        f"## Summary\n{stage_summary}\n",
    ]
    if issues:
        prompt_parts.append(
            "## Issues Encountered\n" + "\n".join(f"- {i}" for i in issues) + "\n"
        )
    if trajectory_text:
        prompt_parts.append(f"## Tool Execution Trajectory\n{trajectory_text}\n")

    prompt_parts.append(
        "\n## Task\n"
        "Extract 3-8 lessons from this execution. For each lesson, provide:\n"
        '- "stage": the workflow stage\n'
        '- "content": concise lesson text (1-2 sentences)\n'
        '- "lesson_type": one of "observation", "success", "failure", "tip"\n'
        '- "tags": 1-3 relevant tags\n\n'
        "Focus on:\n"
        "1. What strategies worked well (success)\n"
        "2. What failed and why (failure)\n"
        "3. Useful patterns worth repeating (tip)\n"
        "4. Non-obvious observations (observation)\n\n"
        'Return JSON: {"lessons": [...]}'
    )

    prompt = "\n".join(prompt_parts)
    client = _get_client(
        tier=_PRIMITIVE_TIERS.get("lesson_extract"), task_name="lesson_extract"
    )
    raw = _client_chat(client, prompt)
    parsed = _parse_json(raw, primitive="lesson_extract", context=stage)

    lessons: list[LessonItem] = []
    for item in parsed.get("lessons", []):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        lessons.append(
            LessonItem(
                stage=stage,
                content=content,
                lesson_type=str(item.get("lesson_type", "observation")).strip()
                or "observation",
                tags=[str(t) for t in (item.get("tags") or []) if t],
            )
        )

    # Fallback: if LLM returned nothing useful, use the old stub logic
    if not lessons:
        for issue in issues:
            lessons.append(
                LessonItem(
                    stage=stage, content=issue, lesson_type="failure", tags=[stage]
                )
            )
        if stage_summary:
            lessons.append(
                LessonItem(
                    stage=stage,
                    content=stage_summary,
                    lesson_type="observation",
                    tags=[stage],
                )
            )

    return LessonExtractOutput(
        lessons=lessons,
        stage=stage,
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Iterative retrieval loop
#
# Multi-round paper_search → overlap check → paper_ingest loop. Stops when
# the paper pool has converged (mean overlap ≥ threshold AND new papers added
# < floor) for `window` consecutive rounds, or when the optional
# cost-per-new-paper budget is exceeded.
# ---------------------------------------------------------------------------


def _paper_identity_key(ref: Any) -> str | None:
    """Pick a stable identifier for de-duplication: arxiv_id > doi > s2_id.

    Falls back to ``None`` when no strong identifier is present — those rows
    are discarded from the overlap calculation because title-based matching
    is known to be unreliable (see PASA bug fix history).
    """
    arxiv = str(getattr(ref, "arxiv_id", "") or "").strip().lower()
    if arxiv:
        return f"arxiv:{arxiv}"
    doi = str(getattr(ref, "doi", "") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    s2 = str(getattr(ref, "s2_id", "") or "").strip().lower()
    if s2:
        return f"s2:{s2}"
    return None


def _paper_in_pool(
    db: Database, *, arxiv_id: str = "", doi: str = "", s2_id: str = ""
) -> bool:
    """Check whether a paper already exists in the local pool."""
    arxiv_id = (arxiv_id or "").strip()
    doi = (doi or "").strip()
    s2_id = (s2_id or "").strip()
    if not (arxiv_id or doi or s2_id):
        return False
    conn = db.connect()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if arxiv_id:
            clauses.append("LOWER(COALESCE(arxiv_id,'')) = ?")
            params.append(arxiv_id.lower())
        if doi:
            clauses.append("LOWER(COALESCE(doi,'')) = ?")
            params.append(doi.lower())
        if s2_id:
            clauses.append("LOWER(COALESCE(s2_id,'')) = ?")
            params.append(s2_id.lower())
        where = " OR ".join(clauses)
        row = conn.execute(
            f"SELECT id FROM papers WHERE {where} LIMIT 1", params
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _ingest_source_from_ref(ref: Any) -> str | None:
    """Best identifier to hand to paper_ingest. Prefers arxiv over doi over url."""
    arxiv = str(getattr(ref, "arxiv_id", "") or "").strip()
    if arxiv:
        return arxiv
    doi = str(getattr(ref, "doi", "") or "").strip()
    if doi:
        return doi
    s2 = str(getattr(ref, "s2_id", "") or "").strip()
    if s2:
        return s2
    url = str(getattr(ref, "url", "") or "").strip()
    if url:
        return url
    return None


def _record_retrieval_round_to_db(
    db: Database,
    *,
    topic_id: int,
    query: str,
    round_index: int,
    record: RetrievalRoundRecord,
    cost_usd: float,
) -> None:
    """Upsert the round metrics into search_query_registry."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT id FROM search_query_registry WHERE topic_id = ? AND query = ?",
            (topic_id, query),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO search_query_registry
                    (topic_id, query, source, last_searched_at,
                     round_index, total_hits, dedup_hits, existing_hits,
                     new_papers_added, overlap_ratio, seed_gap, last_round_cost_usd)
                VALUES (?, ?, 'iterative_loop', datetime('now'),
                        ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic_id,
                    query,
                    round_index,
                    record.total_hits,
                    record.dedup_hits,
                    record.existing_hits,
                    record.new_papers_added,
                    record.overlap_ratio,
                    record.seed_gap,
                    cost_usd,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE search_query_registry
                SET last_searched_at = datetime('now'),
                    round_index = ?,
                    total_hits = ?,
                    dedup_hits = ?,
                    existing_hits = ?,
                    new_papers_added = ?,
                    overlap_ratio = ?,
                    seed_gap = ?,
                    last_round_cost_usd = ?
                WHERE id = ?
                """,
                (
                    round_index,
                    record.total_hits,
                    record.dedup_hits,
                    record.existing_hits,
                    record.new_papers_added,
                    record.overlap_ratio,
                    record.seed_gap,
                    cost_usd,
                    int(row["id"]),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def iterative_retrieval_loop(
    *,
    db: Database,
    topic_id: int,
    max_rounds: int = 5,
    convergence_threshold: float = 0.8,
    window: int = 2,
    new_paper_floor: int = 5,
    queries_per_round: int = 4,
    max_results_per_query: int = 30,
    budget_per_new_paper_usd: float | None = None,
    ingest_relevance: str = "medium",
    **_: Any,
) -> IterativeRetrievalLoopOutput:
    """Run multi-round retrieval until the paper pool converges.

    Each round:
      1. Calls query_refine for fresh candidate queries.
      2. Filters out queries already executed by this loop (or registered).
      3. Runs paper_search for each fresh query (auto_ingest=False), dedupes
         hits on (arxiv_id, doi, s2_id), computes overlap with the existing
         pool, and ingests only the new papers.
      4. Records per-query round metrics in search_query_registry and an
         in-memory RetrievalRoundRecord.

    Stop when either:
      • Mean overlap ≥ convergence_threshold AND round new_papers < new_paper_floor
        for `window` consecutive rounds.
      • Optional: cost_per_new_paper exceeds budget_per_new_paper_usd.
      • No fresh queries can be generated (query exhaustion).
      • max_rounds reached (hard cap).
    """
    # Lazy imports to avoid cycle — paper_search / paper_ingest live in the
    # local primitives module and do not require an LLM backend.
    from ..primitives.impls import paper_ingest as _paper_ingest_impl
    from ..primitives.impls import paper_search as _paper_search_impl

    rounds: list[RetrievalRoundRecord] = []
    per_round_mean_overlap: list[float] = []
    per_round_new_papers: list[int] = []

    # Load previously-registered queries so we don't replay them inside the loop.
    conn = db.connect()
    try:
        known = {
            str(row["query"]).strip().casefold()
            for row in conn.execute(
                "SELECT query FROM search_query_registry WHERE topic_id = ?",
                (topic_id,),
            ).fetchall()
            if row["query"]
        }
    finally:
        conn.close()

    total_new_papers = 0
    total_fresh_queries = 0
    converged_run = 0
    stop_reason = "max_rounds_reached"
    convergence_reached = False
    model_used = ""

    for round_idx in range(1, max_rounds + 1):
        refine = query_refine(
            db=db, topic_id=topic_id, max_candidates=queries_per_round * 3
        )
        model_used = refine.model_used or model_used

        fresh_candidates: list[QueryCandidate] = []
        for cand in refine.candidates:
            q_key = cand.query.strip().casefold()
            if not q_key or q_key in known:
                continue
            known.add(q_key)
            fresh_candidates.append(cand)
            if len(fresh_candidates) >= queries_per_round:
                break

        if not fresh_candidates:
            stop_reason = "query_refine_exhausted"
            break

        round_records: list[RetrievalRoundRecord] = []
        round_new_papers = 0
        round_effective_queries = 0  # queries that returned at least 1 hit

        for cand in fresh_candidates:
            total_fresh_queries += 1
            try:
                search_out = _paper_search_impl(
                    db=db,
                    query=cand.query,
                    topic_id=topic_id,
                    max_results=max_results_per_query,
                    auto_ingest=False,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("paper_search failed for %r: %s", cand.query, exc)
                continue

            # Dedup on strong identifier; drop rows without one.
            seen_keys: set[str] = set()
            deduped: list[Any] = []
            for paper_ref in search_out.papers:
                key = _paper_identity_key(paper_ref)
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped.append(paper_ref)

            total_hits = len(search_out.papers)
            dedup_hits = len(deduped)

            # Count how many are already in the pool, ingest the rest.
            existing_hits = 0
            new_added = 0
            ingest_errors: list[str] = []
            for paper_ref in deduped:
                if _paper_in_pool(
                    db,
                    arxiv_id=getattr(paper_ref, "arxiv_id", ""),
                    doi=getattr(paper_ref, "doi", ""),
                    s2_id=getattr(paper_ref, "s2_id", ""),
                ):
                    existing_hits += 1
                    continue
                source = _ingest_source_from_ref(paper_ref)
                if not source:
                    continue
                try:
                    _paper_ingest_impl(
                        db=db,
                        source=source,
                        topic_id=topic_id,
                        relevance=ingest_relevance,
                    )
                    new_added += 1
                except Exception as exc:  # pragma: no cover - defensive
                    ingest_errors.append(f"{source}: {exc}")

            # Exclude empty-result queries from overlap computation to avoid
            # LLM-hallucinated terms trivially showing 0% overlap.
            if dedup_hits == 0:
                overlap_ratio = 0.0
            else:
                overlap_ratio = existing_hits / dedup_hits
                round_effective_queries += 1

            record = RetrievalRoundRecord(
                round_index=round_idx,
                query=cand.query,
                total_hits=total_hits,
                dedup_hits=dedup_hits,
                existing_hits=existing_hits,
                new_papers_added=new_added,
                overlap_ratio=overlap_ratio,
                seed_gap=cand.coverage_direction or cand.rationale,
                ingest_errors=ingest_errors,
                providers_queried=list(search_out.providers_queried),
            )
            round_records.append(record)

            # Persist the round for dashboards / gating.
            try:
                _record_retrieval_round_to_db(
                    db,
                    topic_id=topic_id,
                    query=cand.query,
                    round_index=round_idx,
                    record=record,
                    cost_usd=0.0,  # per-round cost is charged at loop level
                )
            except Exception as exc:  # pragma: no cover - logging only
                logger.warning(
                    "Failed to persist retrieval round record for %r: %s",
                    cand.query,
                    exc,
                )

            round_new_papers += new_added

        rounds.extend(round_records)
        if round_effective_queries == 0:
            mean_overlap = 0.0
        else:
            mean_overlap = (
                sum(r.overlap_ratio for r in round_records if r.dedup_hits > 0)
                / round_effective_queries
            )

        per_round_mean_overlap.append(mean_overlap)
        per_round_new_papers.append(round_new_papers)
        total_new_papers += round_new_papers

        # Cost-aware stop (requires observed token → cost estimation). The
        # accumulator is read by the backend after this impl returns; here we
        # read the current snapshot to decide mid-loop.
        if budget_per_new_paper_usd is not None and round_new_papers > 0:
            prompt_so_far, completion_so_far = _accumulated_tokens()
            if prompt_so_far is not None or completion_so_far is not None:
                # Crude cost estimate: $0.005 per primitive call already baked
                # into estimate_cost. Use accumulated token count as proxy:
                # assume $0.5 per million tokens in + $1.5 per million out
                # (matches joy_gpt rough pricing tier).
                est_cost = ((prompt_so_far or 0) / 1_000_000) * 0.5 + (
                    (completion_so_far or 0) / 1_000_000
                ) * 1.5
                if total_new_papers > 0:
                    cost_per_paper = est_cost / max(total_new_papers, 1)
                    if cost_per_paper > budget_per_new_paper_usd:
                        stop_reason = "cost_budget_exceeded"
                        break

        # Dual-condition convergence check
        if mean_overlap >= convergence_threshold and round_new_papers < new_paper_floor:
            converged_run += 1
            if converged_run >= window:
                convergence_reached = True
                stop_reason = "converged"
                break
        else:
            converged_run = 0

    final_mean_overlap = per_round_mean_overlap[-1] if per_round_mean_overlap else 0.0

    prompt_tokens_total, completion_tokens_total = _accumulated_tokens()
    # Crude cost reflection (ties into per-primitive estimate_cost baseline)
    total_cost_usd = 0.0
    if prompt_tokens_total is not None or completion_tokens_total is not None:
        total_cost_usd = ((prompt_tokens_total or 0) / 1_000_000) * 0.5 + (
            (completion_tokens_total or 0) / 1_000_000
        ) * 1.5
    cost_per_new_paper: float | None = None
    if total_new_papers > 0 and total_cost_usd > 0:
        cost_per_new_paper = total_cost_usd / total_new_papers

    return IterativeRetrievalLoopOutput(
        topic_id=topic_id,
        rounds_run=len(per_round_mean_overlap),
        total_new_papers=total_new_papers,
        total_fresh_queries=total_fresh_queries,
        final_mean_overlap=final_mean_overlap,
        convergence_reached=convergence_reached,
        stop_reason=stop_reason,
        rounds=rounds,
        per_round_mean_overlap=per_round_mean_overlap,
        per_round_new_papers=per_round_new_papers,
        total_prompt_tokens=prompt_tokens_total,
        total_completion_tokens=completion_tokens_total,
        total_cost_usd=total_cost_usd,
        cost_per_new_paper=cost_per_new_paper,
        model_used=model_used,
    )


# ---------------------------------------------------------------------------
# Topic framing (init stage)
# ---------------------------------------------------------------------------


def topic_framing(
    *,
    db: Database,
    context: str = "",
    _model: str | None = None,
    **_: Any,
) -> TopicFramingOutput:
    """Analyze project context and generate a structured topic definition."""
    if not context.strip():
        return TopicFramingOutput()

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("topic_framing"))
    raw = _client_chat(client, prompts.topic_framing_prompt(context))
    parsed = _parse_json(raw, primitive="topic_framing")

    return TopicFramingOutput(
        topic_name=str(parsed.get("topic_name", "")).strip(),
        description=str(parsed.get("description", "")).strip(),
        search_queries=[str(q) for q in (parsed.get("search_queries") or []) if q],
        scope_keywords=[str(k) for k in (parsed.get("scope_keywords") or []) if k],
        target_venue=str(parsed.get("target_venue", "")).strip(),
        year_from=_coerce_int(parsed.get("year_from"), 0),
        exclusions=[str(e) for e in (parsed.get("exclusions") or []) if e],
        seed_papers=[str(s) for s in (parsed.get("seed_papers") or []) if s],
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Research direction ranking (analyze stage)
# ---------------------------------------------------------------------------


def direction_ranking(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    _model: str | None = None,
    **_: Any,
) -> DirectionRankingOutput:
    """Rank candidate research directions by novelty × feasibility × impact."""
    summary, related_paper_ids = _get_topic_literature_summary(
        db, topic_id, task_type="direction_ranking"
    )

    # Gather existing gaps
    conn = db.connect()
    try:
        gap_rows = conn.execute(
            """SELECT description, gap_type, severity FROM gaps
               WHERE topic_id = ? ORDER BY rowid""",
            (topic_id,),
        ).fetchall()
        gaps_text = (
            "\n".join(f"- [{r['severity']}] {r['description']}" for r in gap_rows)
            or "No gaps detected yet."
        )

        claim_rows = conn.execute(
            """SELECT claim_text, method, dataset, metric FROM normalized_claims
               WHERE topic_id = ? ORDER BY rowid LIMIT 30""",
            (topic_id,),
        ).fetchall()
        claims_text = (
            "\n".join(
                f"- {r['claim_text']}" + (f" [{r['method']}]" if r["method"] else "")
                for r in claim_rows
            )
            or "No claims extracted yet."
        )
    finally:
        conn.close()

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("direction_ranking"))
    raw = _client_chat(
        client,
        prompts.direction_ranking_prompt(gaps_text, claims_text, summary),
    )
    parsed = _parse_json(raw, primitive="direction_ranking")

    directions: list[RankedDirection] = []
    for item in parsed.get("directions", []):
        if not isinstance(item, dict):
            continue
        direction = str(item.get("direction", "")).strip()
        if not direction:
            continue
        directions.append(
            RankedDirection(
                direction=direction,
                description=str(item.get("description", "")).strip(),
                novelty=_coerce_float(item.get("novelty"), 0.0),
                feasibility=_coerce_float(item.get("feasibility"), 0.0),
                impact=_coerce_float(item.get("impact"), 0.0),
                composite_score=_coerce_float(item.get("composite_score"), 0.0),
                supporting_gaps=[
                    str(g) for g in (item.get("supporting_gaps") or []) if g
                ],
                risks=[str(r) for r in (item.get("risks") or []) if r],
            )
        )

    # Sort by composite score descending
    directions.sort(key=lambda d: d.composite_score, reverse=True)

    return DirectionRankingOutput(
        directions=directions,
        recommendation=str(parsed.get("recommendation", "")).strip(),
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Method layer expansion (propose stage)
# ---------------------------------------------------------------------------


def method_layer_expansion(
    *,
    db: Database,
    topic_id: int,
    proposal: str,
    _model: str | None = None,
    **_: Any,
) -> MethodLayerExpansionOutput:
    """Extract method keywords from a proposal and generate cross-domain search queries."""
    summary, _ = _get_topic_literature_summary(
        db, topic_id, task_type="method_layer_expansion"
    )

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("method_layer_expansion"))
    raw = _client_chat(
        client,
        prompts.method_layer_expansion_prompt(proposal, summary),
    )
    parsed = _parse_json(raw, primitive="method_layer_expansion")

    queries: list[MethodQuery] = []
    for item in parsed.get("queries", []):
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        if query:
            queries.append(
                MethodQuery(
                    query=query,
                    category=str(item.get("category", "")).strip(),
                    rationale=str(item.get("rationale", "")).strip(),
                )
            )

    return MethodLayerExpansionOutput(
        method_keywords=[str(k) for k in (parsed.get("method_keywords") or []) if k],
        queries=queries,
        cross_domain_venues=[
            str(v) for v in (parsed.get("cross_domain_venues") or []) if v
        ],
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Writing architecture (write stage)
# ---------------------------------------------------------------------------


def writing_architecture(
    *,
    db: Database,
    topic_id: int,
    contributions: str = "",
    writing_patterns: str = "",
    outline: str = "",
    _model: str | None = None,
    **_: Any,
) -> WritingArchitectureOutput:
    """Design optimal paper structure based on contributions and venue patterns.

    ``contributions`` is optional: if omitted, auto-loaded from the most
    recently updated project's ``projects.contributions`` for this topic.
    """
    if not contributions.strip():
        contributions = _get_topic_latest_project_contributions(db, topic_id)
    if not contributions.strip():
        raise ValueError(
            "writing_architecture requires contributions either passed "
            "explicitly or set on the project via project_set_contributions."
        )
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("writing_architecture"))
    raw = _client_chat(
        client,
        prompts.writing_architecture_prompt(contributions, writing_patterns, outline),
    )
    parsed = _parse_json(raw, primitive="writing_architecture")

    sections: list[SectionPlan] = []
    for item in parsed.get("sections", []):
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("section", "")).strip()
        if section_id:
            sections.append(
                SectionPlan(
                    section=section_id,
                    title=str(item.get("title", section_id)).strip(),
                    target_words=_coerce_int(item.get("target_words"), 500),
                    argument_strategy=str(item.get("argument_strategy", "")).strip(),
                    key_evidence=[
                        str(e) for e in (item.get("key_evidence") or []) if e
                    ],
                )
            )

    return WritingArchitectureOutput(
        paper_title=str(parsed.get("paper_title", "")).strip(),
        narrative_strategy=str(parsed.get("narrative_strategy", "")).strip(),
        sections=sections,
        total_words=_coerce_int(
            parsed.get("total_words"), sum(s.target_words for s in sections)
        ),
        strengths=[str(s) for s in (parsed.get("strengths") or []) if s],
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Figure planning
# ---------------------------------------------------------------------------


def figure_plan(
    *,
    db: Database,
    topic_id: int,
    contributions: str = "",
    outline: str = "",
    target_venue: str = "",
    _model: str | None = None,
    **_: Any,
) -> "FigurePlanOutput":
    """Plan figures and tables for a paper.

    ``contributions`` is optional: if omitted, auto-loaded from the most
    recently updated project's ``projects.contributions`` for this topic.
    """
    from ..primitives.types import FigurePlanItem, FigurePlanOutput

    if not contributions.strip():
        contributions = _get_topic_latest_project_contributions(db, topic_id)
    if not contributions.strip():
        raise ValueError(
            "figure_plan requires contributions either passed explicitly "
            "or set on the project via project_set_contributions."
        )

    evidence_text, _ = _build_numbered_evidence(
        db, topic_id, max_papers=15, task_type="figure_plan"
    )
    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("writing_architecture"))
    raw = _client_chat(
        client,
        prompts.figure_plan_prompt(contributions, outline, evidence_text, target_venue),
    )
    parsed = _parse_json(raw, primitive="figure_plan")

    items: list[FigurePlanItem] = []
    for entry in parsed.get("items", []):
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "figure")).strip().lower()
        if kind not in ("figure", "table"):
            kind = "figure"
        items.append(
            FigurePlanItem(
                figure_id=str(entry.get("figure_id", "")).strip(),
                kind=kind,
                title=str(entry.get("title", "")).strip(),
                caption=str(entry.get("caption", "")).strip(),
                section=str(entry.get("section", "")).strip(),
                purpose=str(entry.get("purpose", "")).strip(),
                data_source=str(entry.get("data_source", "")).strip(),
                suggested_layout=str(entry.get("suggested_layout", "")).strip(),
                placement_hint=str(entry.get("placement_hint", "")).strip(),
            )
        )

    figs = sum(1 for it in items if it.kind == "figure")
    tabs = sum(1 for it in items if it.kind == "table")
    return FigurePlanOutput(
        items=items,
        total_items=len(items),
        figures_count=figs,
        tables_count=tabs,
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Figure generation (via fal.ai — external image API)
# ---------------------------------------------------------------------------


def figure_generate(
    *,
    db: Database,
    topic_id: int,
    items: list[dict[str, Any]],
    output_dir: str,
    model: str = "recraft",
    _model: str | None = None,
    **_: Any,
) -> "FigureGenerateOutput":
    """Generate academic figure images from figure_plan items via fal.ai."""
    from ..primitives.types import FigureGenerateItem, FigureGenerateOutput
    from .fal_image_client import (
        build_image_prompt,
        choose_dimensions,
        classify_figure_style,
        figure_id_to_filename,
        generate_image,
    )

    figure_items = [
        it
        for it in items
        if isinstance(it, dict) and it.get("kind", "figure") == "figure"
    ]

    results: list[FigureGenerateItem] = []
    for item in figure_items:
        figure_id = str(item.get("figure_id", "")).strip()
        title = str(item.get("title", "")).strip()
        caption = str(item.get("caption", "")).strip()
        purpose = str(item.get("purpose", "")).strip()
        data_source = str(item.get("data_source", "")).strip()
        suggested_layout = str(item.get("suggested_layout", "")).strip()
        section = str(item.get("section", "")).strip()

        prompt = build_image_prompt(
            title=title,
            purpose=purpose,
            caption=caption,
            data_source=data_source,
            suggested_layout=suggested_layout,
            section=section,
        )
        style = classify_figure_style(purpose, suggested_layout, title)
        dimensions = choose_dimensions(suggested_layout, purpose)
        filename = figure_id_to_filename(figure_id)

        try:
            gen_result = generate_image(
                prompt=prompt,
                model=model,
                style=style,
                dimensions=dimensions,
                output_dir=output_dir,
                filename=filename,
            )
        except Exception as exc:
            results.append(
                FigureGenerateItem(
                    figure_id=figure_id,
                    filename=filename,
                    success=False,
                    error=str(exc),
                    prompt_used=prompt,
                    model_used=model,
                )
            )
            continue

        results.append(
            FigureGenerateItem(
                figure_id=figure_id,
                filename=filename,
                path=gen_result.local_path if gen_result.success else "",
                success=gen_result.success,
                error=gen_result.error,
                prompt_used=prompt,
                model_used=gen_result.model_id,
                width=gen_result.width,
                height=gen_result.height,
            )
        )

    generated = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    primary_model = results[0].model_used if results else model

    return FigureGenerateOutput(
        items=results,
        total_requested=len(figure_items),
        total_generated=generated,
        total_failed=failed,
        output_dir=output_dir,
        model_used=primary_model,
    )


# ---------------------------------------------------------------------------
# Universal Writing Skill: pattern extraction
# ---------------------------------------------------------------------------


def writing_pattern_extract(
    *,
    db: Database,
    paper_id: int,
    _model: str | None = None,
    **_: Any,
) -> "WritingPatternExtractOutput":
    """Extract structural writing patterns from a deeply-read paper."""
    from ..primitives.types import (
        ALL_WRITING_DIMENSIONS,
        WRITING_SKILL_DIMENSIONS,
        WritingObservation,
        WritingPatternExtractOutput,
    )

    title, text = _get_paper_text(db, paper_id)
    if not text:
        return WritingPatternExtractOutput(paper_id=paper_id)

    # Get paper metadata for venue/year
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT venue, year FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
    finally:
        conn.close()
    venue = (row["venue"] or "") if row else ""
    year = (row["year"] or 0) if row else 0

    # Determine venue tier (rough heuristic)
    venue_tier = ""
    top_venues = {
        "neurips",
        "nips",
        "icml",
        "iclr",
        "kdd",
        "aaai",
        "ijcai",
        "acl",
        "emnlp",
        "naacl",
        "cvpr",
        "iccv",
        "eccv",
    }
    if venue:
        venue_lower = venue.lower()
        for v in top_venues:
            if v in venue_lower:
                venue_tier = "A"
                break

    client = _get_client(_model, tier=_PRIMITIVE_TIERS.get("paper_summarize"))
    raw = _client_chat(
        client,
        prompts.writing_pattern_extract_prompt(title, text, venue),
    )
    parsed = _parse_json(raw, primitive="writing_pattern_extract", context=title)

    # Build dimension→section lookup
    dim_to_section: dict[str, str] = {}
    for sec, dims in WRITING_SKILL_DIMENSIONS.items():
        for d in dims:
            dim_to_section[d] = sec

    observations: list[WritingObservation] = []
    for item in parsed.get("observations", []):
        if not isinstance(item, dict):
            continue
        dim = str(item.get("dimension", "")).strip()
        if dim not in ALL_WRITING_DIMENSIONS:
            continue
        obs = WritingObservation(
            paper_id=paper_id,
            dimension=dim,
            section=dim_to_section.get(dim, str(item.get("section", "")).strip()),
            observation=str(item.get("observation", "")).strip(),
            example_text=str(item.get("example_text", "")).strip()[:1000],
            paper_venue=venue,
            paper_venue_tier=venue_tier,
            paper_year=year,
        )
        observations.append(obs)

    # Persist to DB
    conn = db.connect()
    try:
        for obs in observations:
            conn.execute(
                """INSERT INTO writing_observations
                   (paper_id, dimension, section, observation, example_text,
                    paper_venue, paper_venue_tier, paper_year, extractor_model)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    obs.paper_id,
                    obs.dimension,
                    obs.section,
                    obs.observation,
                    obs.example_text,
                    obs.paper_venue,
                    obs.paper_venue_tier,
                    obs.paper_year,
                    client.model,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return WritingPatternExtractOutput(
        paper_id=paper_id,
        observations=observations,
        dimensions_extracted=len(observations),
        model_used=client.model,
    )


# ---------------------------------------------------------------------------
# Algorithm design subsystem (propose stage)
# ---------------------------------------------------------------------------


def design_brief_expand(
    *,
    db: Database,
    topic_id: int,
    direction: str,
    constraints: list[str] | None = None,
    _model: str | None = None,
    **_: Any,
) -> "DesignBriefOutput":
    """Expand a research direction into a formal design brief with method slots."""
    from ..primitives.types import DesignBriefOutput

    summary, _paper_ids = _get_topic_literature_summary(
        db, topic_id, task_type="design_brief_expand"
    )

    conn = db.connect()
    try:
        gap_rows = conn.execute(
            "SELECT description, gap_type, severity FROM gaps WHERE topic_id = ? ORDER BY rowid",
            (topic_id,),
        ).fetchall()
        gap_context = (
            "\n".join(f"- [{r['severity']}] {r['description']}" for r in gap_rows) or ""
        )

        tax_rows = conn.execute(
            """SELECT method_name, category, aliases, paper_count
               FROM method_taxonomy WHERE topic_id = ? ORDER BY paper_count DESC LIMIT 30""",
            (topic_id,),
        ).fetchall()
        method_taxonomy = (
            "\n".join(
                f"- {r['method_name']} ({r['category'] or 'uncategorized'}, {r['paper_count'] or 0} papers)"
                for r in tax_rows
            )
            or ""
        )
    except Exception:
        gap_context = ""
        method_taxonomy = ""
    finally:
        conn.close()

    constraints_text = "\n".join(f"- {c}" for c in (constraints or []))

    client = _get_client(_model, tier="medium")
    raw = _client_chat(
        client,
        prompts.design_brief_expand_prompt(
            direction=direction,
            gap_context=gap_context,
            method_taxonomy=method_taxonomy,
            constraints=constraints_text,
        ),
    )
    parsed = _parse_json(raw, primitive="design_brief_expand")

    return DesignBriefOutput(
        problem_definition=str(parsed.get("problem_definition", "")).strip(),
        constraints=[str(c) for c in (parsed.get("constraints") or [])],
        method_slots=[
            s for s in (parsed.get("method_slots") or []) if isinstance(s, dict)
        ],
        blocking_questions=[str(q) for q in (parsed.get("blocking_questions") or [])],
        model_used=client.model,
    )


def design_gap_probe(
    *,
    db: Database,
    topic_id: int,
    brief: dict[str, Any],
    method_inventory: list[dict[str, Any]] | None = None,
    _model: str | None = None,
    **_: Any,
) -> "DesignGapProbeOutput":
    """Probe a design brief for knowledge gaps requiring targeted search/reading."""
    from ..primitives.types import DesignGapProbeOutput

    conn = db.connect()
    try:
        tax_rows = conn.execute(
            """SELECT method_name, category, aliases, paper_count
               FROM method_taxonomy WHERE topic_id = ? ORDER BY paper_count DESC LIMIT 30""",
            (topic_id,),
        ).fetchall()
        inv_text = (
            "\n".join(
                f"- {r['method_name']} ({r['category'] or 'uncategorized'})"
                for r in tax_rows
            )
            or ""
        )

        paper_rows = conn.execute(
            """SELECT p.id, p.title, p.year, p.venue
               FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
               WHERE pt.topic_id = ? AND pt.relevance IN ('high', 'medium')
               ORDER BY p.year DESC LIMIT 20""",
            (topic_id,),
        ).fetchall()
        papers_summary = (
            "\n".join(
                f"- [Paper {r['id']}] {r['title']}"
                + (f" ({r['year']})" if r["year"] else "")
                for r in paper_rows
            )
            or ""
        )
    except Exception:
        inv_text = ""
        papers_summary = ""
    finally:
        conn.close()

    if method_inventory:
        inv_text = "\n".join(
            f"- {m.get('method_name', m.get('name', '?'))} ({m.get('category', '?')})"
            for m in method_inventory
        )

    brief_text = json.dumps(brief, indent=2, default=str)

    client = _get_client(_model, tier="light")
    raw = _client_chat(
        client,
        prompts.design_gap_probe_prompt(
            brief=brief_text,
            method_inventory=inv_text,
            existing_papers_summary=papers_summary,
        ),
    )
    parsed = _parse_json(raw, primitive="design_gap_probe")

    return DesignGapProbeOutput(
        knowledge_gaps=[
            g for g in (parsed.get("knowledge_gaps") or []) if isinstance(g, dict)
        ],
        recommended_actions=[str(a) for a in (parsed.get("recommended_actions") or [])],
        deep_read_targets=[
            int(t)
            for t in (parsed.get("deep_read_targets") or [])
            if isinstance(t, (int, float))
        ],
        model_used=client.model,
    )


def algorithm_candidate_generate(
    *,
    db: Database,
    topic_id: int,
    brief: dict[str, Any],
    gap_probe: dict[str, Any] | None = None,
    deep_read_notes: list[dict[str, Any]] | None = None,
    _model: str | None = None,
    **_: Any,
) -> "AlgorithmCandidateGenerateOutput":
    """Generate 2-3 algorithm candidates with provenance-tagged components."""
    from ..primitives.types import AlgorithmCandidate, AlgorithmCandidateGenerateOutput

    conn = db.connect()
    try:
        tax_rows = conn.execute(
            """SELECT method_name, category, aliases, paper_count
               FROM method_taxonomy WHERE topic_id = ? ORDER BY paper_count DESC LIMIT 30""",
            (topic_id,),
        ).fetchall()
        method_inventory = (
            "\n".join(
                f"- {r['method_name']} ({r['category'] or 'uncategorized'}, {r['paper_count'] or 0} papers)"
                for r in tax_rows
            )
            or ""
        )
    except Exception:
        method_inventory = ""
    finally:
        conn.close()

    # Collect deep reading notes if available
    dr_text = ""
    if deep_read_notes:
        dr_text = "\n\n".join(
            f"### Paper {n.get('paper_id', '?')}: {n.get('title', '?')}\n{n.get('summary', n.get('notes', ''))}"
            for n in deep_read_notes
        )

    brief_text = json.dumps(brief, indent=2, default=str)
    gap_text = json.dumps(gap_probe, indent=2, default=str) if gap_probe else ""

    client = _get_client(_model, tier="heavy")
    raw = _client_chat(
        client,
        prompts.algorithm_candidate_generate_prompt(
            brief=brief_text,
            method_inventory=method_inventory,
            gap_probe=gap_text,
            deep_read_notes=dr_text,
        ),
    )
    parsed = _parse_json(raw, primitive="algorithm_candidate_generate")

    candidates: list[AlgorithmCandidate] = []
    for item in parsed.get("candidates", []):
        if not isinstance(item, dict):
            continue
        components = [c for c in (item.get("components") or []) if isinstance(c, dict)]
        provenance_tags = [str(c.get("provenance_tag", "unknown")) for c in components]
        candidates.append(
            AlgorithmCandidate(
                name=str(item.get("name", "")).strip(),
                architecture_description=str(
                    item.get("architecture_description", "")
                ).strip(),
                components=components,
                novelty_statement=str(item.get("novelty_statement", "")).strip(),
                feasibility_notes=str(item.get("feasibility_notes", "")).strip(),
                provenance_tags=provenance_tags,
            )
        )

    return AlgorithmCandidateGenerateOutput(
        candidates=candidates,
        method_inventory_used=_coerce_int(parsed.get("method_inventory_used"), 0),
        model_used=client.model,
    )


def originality_boundary_check(
    *,
    db: Database,
    topic_id: int,
    candidate: dict[str, Any],
    _model: str | None = None,
    **_: Any,
) -> "OriginalityBoundaryCheckOutput":
    """Check candidate novelty against prior art in the paper pool."""
    from ..primitives.types import OriginalityBoundaryCheckOutput

    candidate_name = str(candidate.get("name", "")).strip()

    # Gather papers that might be near-matches
    conn = db.connect()
    try:
        paper_rows = conn.execute(
            """SELECT p.id, p.title, p.year, p.venue, p.compiled_summary
               FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
               WHERE pt.topic_id = ? AND pt.relevance IN ('high', 'medium')
               ORDER BY p.year DESC LIMIT 30""",
            (topic_id,),
        ).fetchall()

        near_papers = []
        for r in paper_rows:
            summary = r["compiled_summary"] or ""
            near_papers.append(
                f"### [Paper {r['id']}] {r['title']} ({r['year'] or '?'})\n{summary[:500]}"
            )
        near_papers_text = "\n\n".join(near_papers) if near_papers else ""
    finally:
        conn.close()

    candidate_text = json.dumps(candidate, indent=2, default=str)

    client = _get_client(_model, tier="heavy")
    raw = _client_chat(
        client,
        prompts.originality_boundary_check_prompt(
            candidate=candidate_text,
            near_papers_summaries=near_papers_text,
        ),
    )
    parsed = _parse_json(raw, primitive="originality_boundary_check")

    return OriginalityBoundaryCheckOutput(
        candidate_name=str(parsed.get("candidate_name", candidate_name)).strip(),
        near_matches=[
            m for m in (parsed.get("near_matches") or []) if isinstance(m, dict)
        ],
        novelty_verdict=str(parsed.get("novelty_verdict", "")).strip().lower(),
        novelty_score=_coerce_float(parsed.get("novelty_score"), 0.0),
        recommended_modifications=[
            str(m) for m in (parsed.get("recommended_modifications") or [])
        ],
        model_used=client.model,
    )


def algorithm_design_refine(
    *,
    db: Database,
    topic_id: int,
    candidate: dict[str, Any],
    originality_result: dict[str, Any] | None = None,
    feedback: str = "",
    constraints: list[str] | None = None,
    _model: str | None = None,
    **_: Any,
) -> "AlgorithmDesignRefineOutput":
    """Refine best candidate into a publication-ready research proposal."""
    from ..primitives.types import AlgorithmDesignRefineOutput

    candidate_text = json.dumps(candidate, indent=2, default=str)
    originality_text = (
        json.dumps(originality_result, indent=2, default=str)
        if originality_result
        else ""
    )
    constraints_text = "\n".join(f"- {c}" for c in (constraints or []))

    client = _get_client(_model, tier="heavy")
    raw = _client_chat(
        client,
        prompts.algorithm_design_refine_prompt(
            candidate=candidate_text,
            originality_result=originality_text,
            feedback=feedback,
            constraints=constraints_text,
        ),
    )
    parsed = _parse_json(raw, primitive="algorithm_design_refine")

    components = [c for c in (parsed.get("components") or []) if isinstance(c, dict)]
    provenance_summary = [
        p for p in (parsed.get("provenance_summary") or []) if isinstance(p, dict)
    ]

    return AlgorithmDesignRefineOutput(
        proposal_title=str(parsed.get("proposal_title", "")).strip(),
        problem_formulation=str(parsed.get("problem_formulation", "")).strip(),
        algorithm_description=str(parsed.get("algorithm_description", "")).strip(),
        components=components,
        novelty_statement=str(parsed.get("novelty_statement", "")).strip(),
        experiment_hooks=[str(h) for h in (parsed.get("experiment_hooks") or [])],
        provenance_summary=provenance_summary,
        model_used=client.model,
    )


def algorithm_design_loop(
    *,
    db: Database,
    topic_id: int,
    project_id: int,
    direction: str,
    max_rounds: int = 3,
    constraints: list[str] | None = None,
    _model: str | None = None,
    **_: Any,
) -> "AlgorithmDesignLoopOutput":
    """Iterative design loop: brief -> gap -> candidates -> originality -> refine.

    Stops when:
      - Best candidate achieves novelty_verdict == "novel" and no critical gaps.
      - max_rounds reached.
    """
    from ..primitives.types import AlgorithmDesignLoopOutput

    briefs: list[Any] = []
    gap_probes: list[Any] = []
    candidates_history: list[Any] = []
    originality_checks: list[Any] = []
    papers_read = 0
    convergence_reason = "max_rounds_reached"
    final_proposal = None

    for round_idx in range(1, max_rounds + 1):
        brief_out = design_brief_expand(
            db=db,
            topic_id=topic_id,
            direction=direction,
            constraints=constraints,
            _model=_model,
        )
        briefs.append(brief_out)
        brief_dict: dict[str, Any] = {
            "problem_definition": brief_out.problem_definition,
            "constraints": list(brief_out.constraints),
            "method_slots": list(brief_out.method_slots),
            "blocking_questions": list(brief_out.blocking_questions),
        }

        gap_out = design_gap_probe(
            db=db,
            topic_id=topic_id,
            brief=brief_dict,
            _model=_model,
        )
        gap_probes.append(gap_out)

        if gap_out.deep_read_targets:
            papers_read += len(gap_out.deep_read_targets)

        deep_read_notes: list[dict[str, Any]] = []
        if gap_out.deep_read_targets:
            conn = db.connect()
            try:
                for pid in gap_out.deep_read_targets[:5]:
                    row = conn.execute(
                        "SELECT paper_id, pass1_summary, pass2_critical "
                        "FROM paper_annotations WHERE paper_id = ?",
                        (pid,),
                    ).fetchone()
                    if row:
                        deep_read_notes.append(
                            {
                                "paper_id": row["paper_id"],
                                "pass1": row["pass1_summary"] or "",
                                "pass2": row["pass2_critical"] or "",
                            }
                        )
            except Exception as exc:
                logger.debug("Deep reading notes unavailable: %s", exc)
            finally:
                conn.close()

        gap_dict: dict[str, Any] = {
            "knowledge_gaps": list(gap_out.knowledge_gaps),
            "recommended_actions": list(gap_out.recommended_actions),
            "deep_read_targets": list(gap_out.deep_read_targets),
        }

        cand_out = algorithm_candidate_generate(
            db=db,
            topic_id=topic_id,
            brief=brief_dict,
            gap_probe=gap_dict,
            deep_read_notes=deep_read_notes,
            _model=_model,
        )
        candidates_history.append(cand_out)

        if not cand_out.candidates:
            convergence_reason = "no_candidates_generated"
            break

        best = cand_out.candidates[0]
        best_dict: dict[str, Any] = {
            "name": best.name,
            "architecture_description": best.architecture_description,
            "components": list(best.components),
            "novelty_statement": best.novelty_statement,
            "feasibility_notes": best.feasibility_notes,
            "provenance_tags": list(best.provenance_tags),
        }

        orig_out = originality_boundary_check(
            db=db,
            topic_id=topic_id,
            candidate=best_dict,
            _model=_model,
        )
        originality_checks.append(orig_out)

        has_critical_gaps = any(
            isinstance(g, dict) and g.get("severity") in ("critical", "high")
            for g in gap_out.knowledge_gaps
        )
        is_novel = orig_out.novelty_verdict == "novel"

        if is_novel and not has_critical_gaps:
            orig_dict: dict[str, Any] = {
                "candidate_name": orig_out.candidate_name,
                "near_matches": list(orig_out.near_matches),
                "novelty_verdict": orig_out.novelty_verdict,
                "novelty_score": orig_out.novelty_score,
                "recommended_modifications": list(orig_out.recommended_modifications),
            }
            refine_out = algorithm_design_refine(
                db=db,
                topic_id=topic_id,
                candidate=best_dict,
                originality_result=orig_dict,
                constraints=constraints,
                _model=_model,
            )
            return AlgorithmDesignLoopOutput(
                final_proposal=refine_out,
                rounds_completed=round_idx,
                convergence_reason="novel_and_no_critical_gaps",
                briefs=briefs,
                gap_probes=gap_probes,
                candidates_history=candidates_history,
                originality_checks=originality_checks,
                papers_read_during_loop=papers_read,
                model_used=_model or "",
            )

        feedback_parts: list[str] = []
        if not is_novel:
            mods = orig_out.recommended_modifications
            feedback_parts.append(
                f"Novelty verdict: {orig_out.novelty_verdict} (score={orig_out.novelty_score:.2f}). "
                f"Modifications needed: {'; '.join(mods) if mods else 'unspecified'}"
            )
        if has_critical_gaps:
            critical = [
                g
                for g in gap_out.knowledge_gaps
                if isinstance(g, dict) and g.get("severity") in ("critical", "high")
            ]
            feedback_parts.append(
                f"Critical gaps remain: {'; '.join(str(g.get('slot', '?')) for g in critical)}"
            )

        orig_dict = {
            "candidate_name": orig_out.candidate_name,
            "novelty_verdict": orig_out.novelty_verdict,
            "novelty_score": orig_out.novelty_score,
            "recommended_modifications": list(orig_out.recommended_modifications),
        }
        refine_out = algorithm_design_refine(
            db=db,
            topic_id=topic_id,
            candidate=best_dict,
            originality_result=orig_dict,
            feedback="\n".join(feedback_parts),
            constraints=constraints,
            _model=_model,
        )
        final_proposal = refine_out

        direction = (
            f"{direction}\n\n[Round {round_idx} refinement] "
            f"{refine_out.novelty_statement}"
        )

    return AlgorithmDesignLoopOutput(
        final_proposal=final_proposal,
        rounds_completed=max_rounds
        if convergence_reason == "max_rounds_reached"
        else len(briefs),
        convergence_reason=convergence_reason,
        briefs=briefs,
        gap_probes=gap_probes,
        candidates_history=candidates_history,
        originality_checks=originality_checks,
        papers_read_during_loop=papers_read,
        model_used=_model or "",
    )
