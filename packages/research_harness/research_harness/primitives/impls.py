"""Built-in primitive implementations — non-LLM operations only in Phase 1."""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..core.paper_pool import PaperPool
from ..core.search_cache import cache_get, cache_put
from ..paper_source_clients import build_provider_suite
from ..paper_sources import PaperRecord, SearchAggregator
from ..paper_sources import SearchQuery as AggSearchQuery
from ..paper_sources import normalize_title
from ..storage.db import Database
from ..storage.models import Paper
from .registry import (
    COLD_START_RUN_SPEC,
    EXPAND_CITATIONS_SPEC,
    PAPER_ACQUIRE_SPEC,
    PAPER_INGEST_SPEC,
    PAPER_SEARCH_SPEC,
    TOPIC_GET_CONTRIBUTIONS_SPEC,
    TOPIC_SET_CONTRIBUTIONS_SPEC,
    SELECT_SEEDS_SPEC,
    register_primitive,
)
from .types import (
    ExpandCandidatePaper,
    ExpandCitationsOutput,
    PaperAcquireOutput,
    PaperIngestOutput,
    PaperRef,
    PaperSearchOutput,
    TopicSetContributionsOutput,
    SeedPaper,
    SelectSeedsOutput,
    UnableToAcquireItem,
)
from .venue_tiers import (
    meets_tier_threshold,
    venue_tier_label,
    venue_tier_score,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# paper_search — multi-provider with venue tier ranking
# ---------------------------------------------------------------------------


@register_primitive(PAPER_SEARCH_SPEC)
def paper_search(
    *,
    db: Database,
    query: str,
    topic_id: int | None = None,
    max_results: int = 500,
    year_from: int | None = None,
    year_to: int | None = None,
    venue_filter: str = "",
    tier_filter: str = "",
    auto_ingest: bool = False,
    **_: Any,
) -> PaperSearchOutput:
    """Search papers across local pool + external providers with venue tier ranking."""

    current_year = datetime.now(timezone.utc).year

    # Phase 1: Local DB search
    local_refs = _local_db_search(
        db=db,
        query=query,
        topic_id=topic_id,
        year_from=year_from,
        year_to=year_to,
        venue_filter=venue_filter,
        max_results=max_results * 3,
    )

    # Phase 2: External provider fan-out (with cache)
    providers_queried: list[str] = ["local"]
    provider_errors: list[str] = []
    external_refs: list[PaperRef] = []

    cache_params = {"year_from": year_from, "year_to": year_to, "limit": 50}
    cached = cache_get(db, query, "aggregated", cache_params)
    if cached is not None:
        providers_queried.append("cache")
        for rec_dict in cached:
            external_refs.append(_dict_to_ref(rec_dict))
    else:
        try:
            providers = build_provider_suite()
            if providers:
                ext_year_from = year_from if year_from is not None else current_year - 5
                agg_query = AggSearchQuery(
                    query=query,
                    year_from=ext_year_from,
                    year_to=year_to,
                    limit=50,  # per-provider cap: each source returns top 50
                )
                aggregator = SearchAggregator(providers)
                outcome = aggregator.search(agg_query, output_limit=max_results)
                for p in providers:
                    providers_queried.append(getattr(p, "name", p.__class__.__name__))
                for err in outcome.provider_errors:
                    provider_errors.append(f"{err.provider}: {err.message}")
                for record in outcome.results:
                    external_refs.append(_record_to_ref(record, query))
                # Cache the results
                cache_put(
                    db,
                    query,
                    "aggregated",
                    [_ref_to_dict(r) for r in external_refs],
                    cache_params,
                )
        except Exception as exc:
            logger.warning("External provider fan-out failed: %s", exc)
            provider_errors.append(f"fan-out: {exc}")
            # Stale cache fallback
            stale = cache_get(db, query, "aggregated", cache_params, allow_stale=True)
            if stale:
                providers_queried.append("stale_cache")
                for rec_dict in stale:
                    external_refs.append(_dict_to_ref(rec_dict))

    # Phase 3: Merge, dedup, filter, rank
    all_refs = _merge_and_dedup(local_refs, external_refs)
    total_before_filter = len(all_refs)

    # Enrich with venue tier info
    all_refs = [_enrich_venue_tier(ref) for ref in all_refs]

    # Apply filters
    if venue_filter:
        all_refs = [r for r in all_refs if venue_filter.lower() in r.venue.lower()]
    if tier_filter:
        all_refs = [r for r in all_refs if meets_tier_threshold(r.venue, tier_filter)]

    # Rank
    all_refs.sort(key=lambda r: _composite_rank(r, query, current_year), reverse=True)
    final = all_refs[:max_results]

    # Phase 4: Auto-ingest
    ingested_count = 0
    if auto_ingest and final:
        ingested_count = _auto_ingest_refs(db, final, topic_id)

    provider_label = "multi" if len(providers_queried) > 1 else "local"

    # Log to search_runs so MCP callers also get audit trail
    try:
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO search_runs (topic_id, query, provider, result_count, ingested_count) VALUES (?, ?, ?, ?, ?)",
                (topic_id, query, provider_label, len(final), ingested_count),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to log search_run: %s", exc)

    return PaperSearchOutput(
        papers=final,
        provider=provider_label,
        query_used=query,
        providers_queried=providers_queried,
        provider_errors=provider_errors,
        total_before_filter=total_before_filter,
        ingested_count=ingested_count,
    )


def _local_db_search(
    *,
    db: Database,
    query: str,
    topic_id: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    venue_filter: str = "",
    max_results: int = 60,
) -> list[PaperRef]:
    """Search the local SQLite paper pool."""
    conn = db.connect()
    try:
        sql = "SELECT id, title, authors, affiliations, year, venue, doi, arxiv_id, s2_id, url FROM papers"
        clauses: list[str] = []
        params: list[Any] = []

        if topic_id is not None:
            clauses.append(
                "id IN (SELECT paper_id FROM paper_topics WHERE topic_id = ?)"
            )
            params.append(topic_id)
        if year_from is not None:
            clauses.append("year >= ?")
            params.append(year_from)
        if year_to is not None:
            clauses.append("year <= ?")
            params.append(year_to)
        if venue_filter:
            clauses.append("LOWER(COALESCE(venue, '')) LIKE ?")
            params.append(f"%{venue_filter.lower()}%")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        rows = conn.execute(sql, params).fetchall()
        tokens = [token for token in query.lower().split() if token]
        results: list[PaperRef] = []
        for row in rows:
            title = (row["title"] or "").lower()
            score = (
                0.0
                if not tokens
                else sum(1 for token in tokens if token in title) / len(tokens)
            )
            if score <= 0:
                continue
            results.append(
                PaperRef(
                    title=row["title"] or "",
                    authors=_parse_authors(row["authors"]),
                    affiliations=_parse_authors(row["affiliations"])
                    if row["affiliations"]
                    else [],
                    year=row["year"],
                    venue=row["venue"] or "",
                    doi=row["doi"] or "",
                    arxiv_id=row["arxiv_id"] or "",
                    s2_id=row["s2_id"] or "",
                    url=row["url"] or "",
                    relevance_score=score,
                )
            )
        results.sort(key=lambda item: (-item.relevance_score, item.title))
        return results[:max_results]
    finally:
        conn.close()


def _record_to_ref(record: PaperRecord, query: str) -> PaperRef:
    """Convert a PaperRecord from SearchAggregator to PaperRef."""
    tokens = [t for t in query.lower().split() if t]
    title_lower = normalize_title(record.title)
    score = 0.0
    if tokens:
        score = sum(1 for t in tokens if t in title_lower) / len(tokens)

    return PaperRef(
        title=record.title,
        authors=list(record.authors),
        affiliations=list(record.affiliations),
        year=record.year,
        venue=record.venue,
        doi=record.doi,
        arxiv_id=record.arxiv_id,
        s2_id=record.s2_id,
        url=record.url,
        relevance_score=score,
        snippet=record.abstract[:300] if record.abstract else "",
        citation_count=record.citation_count,
    )


def _ref_to_dict(ref: PaperRef) -> dict[str, Any]:
    """Serialize PaperRef to a JSON-safe dict for caching."""
    return {
        "title": ref.title,
        "authors": ref.authors,
        "affiliations": ref.affiliations,
        "year": ref.year,
        "venue": ref.venue,
        "doi": ref.doi,
        "arxiv_id": ref.arxiv_id,
        "s2_id": ref.s2_id,
        "url": ref.url,
        "relevance_score": ref.relevance_score,
        "snippet": ref.snippet,
        "venue_tier": ref.venue_tier,
        "citation_count": ref.citation_count,
    }


def _dict_to_ref(d: dict[str, Any]) -> PaperRef:
    """Deserialize a cached dict back to PaperRef."""
    return PaperRef(
        title=d.get("title", ""),
        authors=d.get("authors", []),
        affiliations=d.get("affiliations", []),
        year=d.get("year"),
        venue=d.get("venue", ""),
        doi=d.get("doi", ""),
        arxiv_id=d.get("arxiv_id", ""),
        s2_id=d.get("s2_id", ""),
        url=d.get("url", ""),
        relevance_score=d.get("relevance_score", 0.0),
        snippet=d.get("snippet", ""),
        venue_tier=d.get("venue_tier", ""),
        citation_count=d.get("citation_count"),
    )


def _ref_fingerprint(ref: PaperRef) -> str:
    """Generate a dedup fingerprint for a PaperRef."""
    for value in (ref.doi, ref.arxiv_id, ref.s2_id):
        cleaned = value.strip().lower()
        if cleaned:
            return cleaned
    return f"title:{normalize_title(ref.title)}:{ref.year or ''}"


def _merge_and_dedup(local: list[PaperRef], external: list[PaperRef]) -> list[PaperRef]:
    """Merge local and external results, deduplicating by fingerprint."""
    merged: dict[str, PaperRef] = {}
    # Local results first (they have pool membership)
    for ref in local:
        fp = _ref_fingerprint(ref)
        merged[fp] = ref
    # External results — prefer richer metadata when deduplicating
    for ref in external:
        fp = _ref_fingerprint(ref)
        existing = merged.get(fp)
        if existing is None:
            merged[fp] = ref
        else:
            merged[fp] = _pick_richer(existing, ref)
    return list(merged.values())


def _pick_richer(a: PaperRef, b: PaperRef) -> PaperRef:
    """Pick the PaperRef with richer metadata, merging missing fields."""

    # Prefer the one with more filled fields
    def _richness(r: PaperRef) -> int:
        count = 0
        if r.venue:
            count += 1
        if r.doi:
            count += 1
        if r.arxiv_id:
            count += 1
        if r.s2_id:
            count += 1
        if r.citation_count is not None:
            count += 1
        if r.snippet:
            count += 1
        if r.authors:
            count += 1
        return count

    base, other = (a, b) if _richness(a) >= _richness(b) else (b, a)
    # Merge missing fields from other into base
    return PaperRef(
        title=base.title or other.title,
        authors=base.authors or other.authors,
        affiliations=base.affiliations or other.affiliations,
        year=base.year or other.year,
        venue=base.venue or other.venue,
        doi=base.doi or other.doi,
        arxiv_id=base.arxiv_id or other.arxiv_id,
        s2_id=base.s2_id or other.s2_id,
        url=base.url or other.url,
        relevance_score=max(base.relevance_score, other.relevance_score),
        snippet=base.snippet or other.snippet,
        venue_tier=base.venue_tier or other.venue_tier,
        citation_count=base.citation_count
        if base.citation_count is not None
        else other.citation_count,
    )


def _enrich_venue_tier(ref: PaperRef) -> PaperRef:
    """Add venue tier label to a PaperRef."""
    label = venue_tier_label(ref.venue)
    if label == ref.venue_tier:
        return ref
    return PaperRef(
        title=ref.title,
        authors=ref.authors,
        year=ref.year,
        venue=ref.venue,
        doi=ref.doi,
        arxiv_id=ref.arxiv_id,
        s2_id=ref.s2_id,
        url=ref.url,
        relevance_score=ref.relevance_score,
        snippet=ref.snippet,
        venue_tier=label,
        citation_count=ref.citation_count,
    )


def _composite_rank(
    ref: PaperRef, query: str, current_year: int
) -> tuple[float, float, float, float]:
    """Produce a ranking tuple (higher is better)."""
    # 1. Venue tier score (0.0 - 1.0)
    tier_score = venue_tier_score(ref.venue) / 100.0

    # 2. Recency score
    if ref.year is not None and ref.year >= current_year - 4:
        recency = 1.0
    elif ref.year is not None and ref.year >= current_year - 8:
        recency = 0.5
    else:
        recency = 0.2

    # 3. Title relevance
    relevance = ref.relevance_score

    # 4. Citation score (log-scaled)
    citation = math.log1p(ref.citation_count or 0) / 15.0

    return (tier_score, recency, relevance, citation)


def _auto_ingest_refs(db: Database, refs: list[PaperRef], topic_id: int | None) -> int:
    """Auto-ingest PaperRefs into the local pool."""
    conn = db.connect()
    count = 0
    try:
        pool = PaperPool(conn)
        for ref in refs:
            source = ref.doi or ref.arxiv_id or ref.title
            if not source:
                continue
            paper = Paper(
                title=ref.title,
                doi=ref.doi,
                arxiv_id=ref.arxiv_id,
                s2_id=ref.s2_id,
                year=ref.year,
                venue=ref.venue,
                url=ref.url,
                authors=json.dumps(ref.authors) if ref.authors else "",
            )
            try:
                pool.ingest(paper, topic_id=topic_id, relevance="medium")
                count += 1
            except Exception as exc:
                logger.debug(
                    "Ingest failed for ref '%s': %s",
                    ref.title[:60] if ref.title else "?",
                    exc,
                )
                continue
        return count
    finally:
        conn.close()


@register_primitive(SELECT_SEEDS_SPEC)
def select_seeds(
    *,
    db: Database,
    topic_id: int,
    top_n: int = 10,
    min_relevance: str = "medium",
    **_: Any,
) -> SelectSeedsOutput:
    """Rank and return top citation-expansion seeds from the paper pool."""
    _RELEVANCE_WEIGHT = {"high": 1.0, "medium": 0.5, "low": 0.1}
    _RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2}
    min_order = _RELEVANCE_ORDER.get(min_relevance, 1)

    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.venue, p.year, p.citation_count,
                   p.s2_id, p.arxiv_id, p.doi, pt.relevance
            FROM papers p
            JOIN paper_topics pt ON p.id = pt.paper_id
            WHERE pt.topic_id = ? AND p.status != 'deleted'
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    total_pool = len(rows)
    candidates: list[SeedPaper] = []

    for row in rows:
        relevance = _normalize_relevance(row["relevance"] or "low")
        if _RELEVANCE_ORDER.get(relevance, 2) > min_order:
            continue

        venue = row["venue"] or ""
        tier = venue_tier_label(venue)
        tier_score = venue_tier_score(venue) / 100.0

        citations = row["citation_count"]
        citation_score = math.log1p(citations or 0) / math.log1p(10000)

        relevance_score = _RELEVANCE_WEIGHT.get(relevance, 0.1)

        composite = tier_score * 0.4 + citation_score * 0.3 + relevance_score * 0.3

        candidates.append(
            SeedPaper(
                paper_id=row["id"],
                title=row["title"] or "",
                venue=venue,
                venue_tier=tier,
                year=row["year"],
                citation_count=citations,
                relevance=relevance,
                seed_score=round(composite, 4),
                s2_id=row["s2_id"] or "",
                arxiv_id=row["arxiv_id"] or "",
                doi=row["doi"] or "",
            )
        )

    candidates.sort(key=lambda s: s.seed_score, reverse=True)
    return SelectSeedsOutput(
        seeds=candidates[:top_n],
        topic_id=topic_id,
        total_pool=total_pool,
    )


@register_primitive(EXPAND_CITATIONS_SPEC)
def expand_citations(
    *,
    db: Database,
    topic_id: int,
    seed_paper_ids: list[int] | None = None,
    forward_limit: int = 50,
    backward_limit: int = 50,
    **_: Any,
) -> ExpandCitationsOutput:
    """Expand paper pool via S2 citation graph on seed papers (both directions)."""
    from ..paper_source_clients import SemanticScholarProvider

    # Resolve seeds: use provided IDs or fall back to auto-select top 5
    if seed_paper_ids:
        seeds = _load_seed_papers(db, topic_id, seed_paper_ids)
    else:
        seeds_out = select_seeds(
            db=db, topic_id=topic_id, top_n=5, min_relevance="medium"
        )
        seeds = list(seeds_out.seeds)

    if not seeds:
        return ExpandCitationsOutput(
            topic_id=topic_id,
            seeds_used=0,
            decision_guidance=(
                "No seeds found for this topic. Run paper_search + paper_ingest first, "
                "then retry expand_citations."
            ),
        )

    s2 = SemanticScholarProvider()
    candidates: list[ExpandCandidatePaper] = []
    forward_count = 0
    backward_count = 0

    for seed in seeds:
        # Determine best identifier for S2 API
        # S2 needs ARXIV: prefix for arxiv IDs; strip version suffix (e.g. v1)
        if seed.s2_id:
            s2_id = seed.s2_id
        elif seed.arxiv_id:
            raw = seed.arxiv_id.replace("arxiv:", "").replace("ARXIV:", "")
            # Strip version suffix (e.g. 2308.09066v1 → 2308.09066)
            import re

            raw = re.sub(r"v\d+$", "", raw)
            s2_id = f"ARXIV:{raw}"
        elif seed.doi:
            s2_id = seed.doi
        else:
            s2_id = None
        if not s2_id:
            continue

        # Forward: papers that CITE this seed
        try:
            fwd_records = s2.get_citations(s2_id, limit=forward_limit)
            for rec in fwd_records:
                candidates.append(
                    _record_to_expand_candidate(rec, seed.paper_id, "forward")
                )
            forward_count += len(fwd_records)
        except Exception as exc:
            logger.warning(
                "S2 get_citations failed for seed %d (%s): %s",
                seed.paper_id,
                s2_id,
                exc,
            )

        # Backward: papers cited BY this seed (references)
        try:
            bwd_records = s2.get_references(s2_id, limit=backward_limit)
            for rec in bwd_records:
                candidates.append(
                    _record_to_expand_candidate(rec, seed.paper_id, "backward")
                )
            backward_count += len(bwd_records)
        except Exception as exc:
            logger.warning(
                "S2 get_references failed for seed %d (%s): %s",
                seed.paper_id,
                s2_id,
                exc,
            )

    # Supplement with OpenAlex cited_by for seeds that have a DOI
    try:
        from ..paper_source_clients import OpenAlexProvider

        oa = OpenAlexProvider()
        for seed in seeds:
            if not seed.doi:
                continue
            oa_id = oa.resolve_doi(seed.doi)
            if not oa_id:
                continue
            try:
                oa_records = oa.cited_by(oa_id, limit=forward_limit)
                for rec in oa_records:
                    candidates.append(
                        _record_to_expand_candidate(rec, seed.paper_id, "forward")
                    )
                forward_count += len(oa_records)
            except Exception as exc:
                logger.warning(
                    "OA cited_by failed for seed %d (%s): %s", seed.paper_id, oa_id, exc
                )
    except Exception as exc:
        logger.debug("OpenAlex cited_by integration skipped: %s", exc)

    # Dedup by fingerprint (same paper may appear from multiple seeds)
    seen: set[str] = set()
    deduped: list[ExpandCandidatePaper] = []
    for c in candidates:
        fp = (
            c.doi.strip().lower()
            or c.arxiv_id.strip().lower()
            or c.s2_id.strip().lower()
            or f"title:{c.title.lower()}"
        )
        if fp not in seen:
            seen.add(fp)
            deduped.append(c)

    # Sort by composite score: venue_tier × 0.4 + log_citation × 0.3 (no relevance known yet)
    deduped.sort(key=_candidate_rank, reverse=True)

    guidance = _build_expand_guidance(deduped, topic_id)

    return ExpandCitationsOutput(
        topic_id=topic_id,
        seeds_used=len(seeds),
        forward_count=forward_count,
        backward_count=backward_count,
        candidates=deduped,
        decision_guidance=guidance,
    )


def _load_seed_papers(
    db: Database, topic_id: int, paper_ids: list[int]
) -> list[SeedPaper]:
    """Load SeedPaper objects for the given paper IDs in a topic."""
    conn = db.connect()
    try:
        placeholders = ",".join("?" * len(paper_ids))
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, p.venue, p.year, p.citation_count,
                   p.s2_id, p.arxiv_id, p.doi, pt.relevance
            FROM papers p
            JOIN paper_topics pt ON p.id = pt.paper_id
            WHERE pt.topic_id = ? AND p.id IN ({placeholders})
            """,
            [topic_id, *paper_ids],
        ).fetchall()
    finally:
        conn.close()

    result: list[SeedPaper] = []
    for row in rows:
        venue = row["venue"] or ""
        result.append(
            SeedPaper(
                paper_id=row["id"],
                title=row["title"] or "",
                venue=venue,
                venue_tier=venue_tier_label(venue),
                year=row["year"],
                citation_count=row["citation_count"],
                relevance=row["relevance"] or "low",
                seed_score=0.0,
                s2_id=row["s2_id"] or "",
                arxiv_id=row["arxiv_id"] or "",
                doi=row["doi"] or "",
            )
        )
    return result


def _record_to_expand_candidate(
    record: "PaperRecord", seed_paper_id: int, direction: str
) -> ExpandCandidatePaper:
    """Convert a PaperRecord from S2 citation graph to an ExpandCandidatePaper."""
    venue = record.venue or ""
    return ExpandCandidatePaper(
        title=record.title or "",
        doi=record.doi or "",
        arxiv_id=record.arxiv_id or "",
        s2_id=record.s2_id or "",
        year=record.year,
        venue=venue,
        venue_tier=venue_tier_label(venue),
        citation_count=record.citation_count,
        abstract=(record.abstract or "")[:300],
        direction=direction,
        seed_paper_id=seed_paper_id,
    )


def _candidate_rank(c: ExpandCandidatePaper) -> tuple[float, float]:
    """Sort key for expand candidates: venue tier + log citation."""
    tier = venue_tier_score(c.venue) / 100.0
    cite = math.log1p(c.citation_count or 0) / math.log1p(10000)
    return (tier * 0.4 + cite * 0.3, c.year or 0)


def _build_expand_guidance(
    candidates: list[ExpandCandidatePaper], topic_id: int
) -> str:
    """Build model guidance text based on candidate pool quality."""
    if not candidates:
        return (
            "No expansion candidates found. The seeds may lack S2 identifiers. "
            "Try enriching seeds via paper_ingest before retrying."
        )

    top_tier = [
        c for c in candidates if "CCF-A" in c.venue_tier or "Q1" in c.venue_tier
    ]
    high_cite = [c for c in candidates if (c.citation_count or 0) >= 50]

    parts = [
        f"Found {len(candidates)} unique candidates ({len(top_tier)} from top-tier venues, "
        f"{len(high_cite)} with ≥50 citations).",
        "Decision guidance:",
        "  • PRIORITIZE ingestion of papers with: top-tier venue (CCF-A*/A, CAS-Q1) "
        "AND citation_count ≥ 50 AND year ≥ 2019.",
        "  • For additional rounds: re-run expand_citations with the newly ingested papers "
        "as seed_paper_ids if the top-tier / high-citation pool is still sparse (<10 papers).",
        "  • SKIP candidates with: unknown venue, citation_count < 5, year < 2015 "
        "(unless they appear highly relevant to the topic).",
        f"  • Use paper_ingest for each selected candidate, then paper_search topic_id={topic_id} "
        "to confirm pool coverage before moving to analyze stage.",
    ]
    return "\n".join(parts)


def _normalize_relevance(value: str) -> str:
    """Normalize relevance to categorical label (high/medium/low).

    Handles float-like strings (e.g. "0.67") by mapping to buckets:
      >= 0.7 → "high", >= 0.4 → "medium", else → "low"
    """
    value = value.strip().lower()
    if value in ("high", "medium", "low"):
        return value
    # Also accept core/peripheral as aliases
    if value == "core":
        return "high"
    if value == "peripheral":
        return "low"
    # Try parsing as float
    try:
        score = float(value)
        if score >= 0.7:
            return "high"
        elif score >= 0.4:
            return "medium"
        else:
            return "low"
    except (ValueError, TypeError):
        return "medium"


@register_primitive(PAPER_INGEST_SPEC)
def paper_ingest(
    *,
    db: Database,
    source: str,
    topic_id: int | None = None,
    relevance: str = "medium",
    url: str = "",
    **_: Any,
) -> PaperIngestOutput:
    """Ingest a paper into the local pool without changing PaperPool semantics."""

    import time

    relevance = _normalize_relevance(relevance)

    conn = db.connect()
    try:
        pool = PaperPool(conn)
        existing = _find_existing_source(conn, source)
        paper = _paper_from_source(source, url=url)
        paper_id = pool.ingest(paper, topic_id=topic_id, relevance=relevance)

        # Auto-enrich metadata from Semantic Scholar (with retry on incomplete)
        enriched_fields: dict[str, str] = {}
        for attempt in range(2):
            try:
                enriched_fields = pool.enrich_metadata(paper_id)
                if "error" in enriched_fields:
                    logger.debug(
                        "S2 enrichment note for paper %d: %s",
                        paper_id,
                        enriched_fields.pop("error"),
                    )
                time.sleep(1.05)  # S2 rate limit: 1 req/s
            except Exception as exc:
                logger.warning(
                    "S2 enrichment failed for paper %d (attempt %d): %s",
                    paper_id,
                    attempt + 1,
                    exc,
                )
                time.sleep(1.05)
                continue

            # Verify completeness — retry if title still empty
            stored = pool.get(paper_id)
            if stored is not None and stored.title and stored.title != source:
                break
            if attempt == 0:
                time.sleep(1.05)

        stored = pool.get(paper_id)
        title = stored.title if stored is not None else paper.title
        metadata_complete = bool(title and title != source)

        # Duplicate detection (by title similarity)
        dup_candidates: list[dict[str, object]] = []
        if title and existing is None:
            try:
                dup_candidates = _find_duplicate_candidates(
                    conn,
                    title,
                    exclude_id=paper_id,
                    topic_id=topic_id,
                )
            except Exception:
                logger.debug(
                    "Duplicate detection failed for paper %d", paper_id, exc_info=True
                )

        # Survey detection
        if title and topic_id is not None:
            try:
                _detect_survey_paper(conn, paper_id, title, topic_id=topic_id)
            except Exception:
                logger.debug(
                    "Survey detection failed for paper %d", paper_id, exc_info=True
                )

        return PaperIngestOutput(
            paper_id=paper_id,
            title=title,
            status="existing" if existing is not None else "new",
            merged_fields=["metadata_incomplete"] if not metadata_complete else [],
            enriched_fields=enriched_fields,
            duplicate_candidates=dup_candidates,
        )
    finally:
        conn.close()


def _normalize_title(title: str) -> str:
    """Normalize a title for fuzzy comparison: lowercase, strip punctuation/whitespace."""
    import re

    t = title.lower().strip()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _title_similarity(a: str, b: str) -> float:
    """Character-level overlap ratio between two normalized titles."""
    if not a or not b:
        return 0.0
    a_set = set(a.split())
    b_set = set(b.split())
    if not a_set or not b_set:
        return 0.0
    intersection = a_set & b_set
    return len(intersection) / max(len(a_set), len(b_set))


_DUPLICATE_THRESHOLD = 0.75

_SURVEY_KEYWORDS = (
    "survey",
    "review",
    "meta-analysis",
    "meta analysis",
    "systematic review",
    "literature review",
    "overview of",
    "a comprehensive",
    "tutorial",
)


def _find_duplicate_candidates(
    conn: sqlite3.Connection,
    title: str,
    exclude_id: int | None = None,
    topic_id: int | None = None,
) -> list[dict[str, object]]:
    """Find papers with similar titles. Returns list of {id, title, similarity}."""
    if not title or len(title) < 10:
        return []

    norm = _normalize_title(title)
    if not norm:
        return []

    # Query candidate papers (same topic if specified, otherwise all)
    if topic_id is not None:
        rows = conn.execute(
            """
            SELECT p.id, p.title FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ? AND p.title IS NOT NULL AND p.title != ''
            """,
            (topic_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title FROM papers WHERE title IS NOT NULL AND title != ''",
        ).fetchall()

    candidates = []
    for row in rows:
        if exclude_id is not None and int(row["id"]) == exclude_id:
            continue
        other_norm = _normalize_title(row["title"])
        sim = _title_similarity(norm, other_norm)
        if sim >= _DUPLICATE_THRESHOLD:
            candidates.append(
                {
                    "id": int(row["id"]),
                    "title": row["title"],
                    "similarity": round(sim, 3),
                }
            )

    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    return candidates[:5]


def _detect_survey_paper(
    conn: sqlite3.Connection,
    paper_id: int,
    title: str,
    topic_id: int | None = None,
) -> bool:
    """Flag paper as survey if title matches survey keywords. Returns True if flagged."""
    if not title:
        return False
    lower = title.lower()
    is_survey = any(kw in lower for kw in _SURVEY_KEYWORDS)
    if not is_survey:
        return False

    if topic_id is None:
        return is_survey

    # Check if already flagged
    existing = conn.execute(
        "SELECT 1 FROM topic_paper_notes WHERE paper_id = ? AND topic_id = ? AND note_type = 'survey_flag'",
        (paper_id, topic_id),
    ).fetchone()
    if existing:
        return True

    conn.execute(
        "INSERT INTO topic_paper_notes (paper_id, topic_id, note_type, content) VALUES (?, ?, 'survey_flag', 'Auto-detected survey paper')",
        (paper_id, topic_id),
    )
    conn.commit()
    return True


def _find_existing_source(conn: sqlite3.Connection, source: str) -> int | None:
    if source.startswith("10."):
        row = conn.execute("SELECT id FROM papers WHERE doi = ?", (source,)).fetchone()
    elif "/" not in source and len(source) < 20:
        row = conn.execute(
            "SELECT id FROM papers WHERE arxiv_id = ?", (source,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM papers WHERE title = ?", (source,)
        ).fetchone()
    if row is None:
        return None
    return int(row["id"])


def _paper_from_source(source: str, url: str = "") -> Paper:
    if source.startswith("10."):
        return Paper(doi=source, url=url)
    if "/" not in source and len(source) < 20:
        return Paper(arxiv_id=source, url=url)
    return Paper(title=source, url=url)


@register_primitive(PAPER_ACQUIRE_SPEC)
def paper_acquire(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> PaperAcquireOutput:
    """Download PDFs, enrich metadata, annotate, and produce unable-to-acquire list."""
    import time
    from pathlib import Path

    from ..acquisition.pipeline import acquire_papers

    # Step 1: Batch-enrich metadata for meta_only papers
    conn = db.connect()
    enriched = 0
    try:
        pool = PaperPool(conn)
        meta_papers = pool.list_papers(topic_id=topic_id, status="meta_only")
        for paper in meta_papers:
            if paper.id is None:
                continue
            needs_enrichment = (
                not paper.title
                or not paper.abstract
                or paper.title.startswith(("doi:", "s2:", "pdf:"))
            )
            if not needs_enrichment:
                continue
            has_id = bool(paper.arxiv_id or paper.doi or paper.s2_id)
            if not has_id:
                continue
            try:
                result = pool.enrich_metadata(paper.id)
                if result and "error" not in result:
                    enriched += 1
                time.sleep(1.05)
            except Exception as exc:
                logger.debug("Venue refresh failed for paper %d: %s", paper.id, exc)
    finally:
        conn.close()

    # Step 2: Run existing acquisition pipeline (download + annotate)
    db_path = db.path
    download_dir = Path(db_path).parent / "papers"
    artifacts_root = Path(db_path).parent / "artifacts"
    report = acquire_papers(
        db, topic_id, download_dir=download_dir, artifacts_root=artifacts_root
    )

    # Step 3: Build priority-sorted unable-to-acquire list
    unable = _build_unable_to_acquire_list(db, topic_id)

    return PaperAcquireOutput(
        topic_id=topic_id,
        total=report.total_papers,
        downloaded=report.downloaded,
        annotated=report.annotated,
        enriched=enriched,
        failed=report.failed,
        needs_manual=report.needs_manual,
        unable_to_acquire=unable,
    )


def _build_unable_to_acquire_list(
    db: Database, topic_id: int
) -> list[UnableToAcquireItem]:
    """Build a priority-sorted list of papers still missing PDFs after acquisition."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.doi, p.arxiv_id, p.status,
                   pt.relevance
            FROM papers p
            JOIN paper_topics pt ON p.id = pt.paper_id
            WHERE pt.topic_id = ? AND (p.pdf_path IS NULL OR p.pdf_path = '')
              AND p.status != 'deleted'
            ORDER BY
                CASE pt.relevance WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                p.title
            """,
            (topic_id,),
        ).fetchall()

        items: list[UnableToAcquireItem] = []
        for r in rows:
            doi = r["doi"] or ""
            arxiv_id = r["arxiv_id"] or ""
            hint = ""
            reason = "no downloadable URL found"
            if arxiv_id:
                hint = f"https://arxiv.org/pdf/{arxiv_id.removeprefix('arxiv:')}.pdf"
                reason = "download attempted but failed"
            elif doi:
                hint = f"https://doi.org/{doi}"
                reason = "likely paywalled"
            items.append(
                UnableToAcquireItem(
                    paper_id=r["id"],
                    title=r["title"] or "",
                    relevance=r["relevance"] or "medium",
                    doi=doi,
                    arxiv_id=arxiv_id,
                    failure_reason=reason,
                    download_hint=hint,
                )
            )
        return items
    finally:
        conn.close()


def _parse_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        parsed = [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


# ---------------------------------------------------------------------------
# topic_set_contributions / topic_get_contributions — topic-level config
# ---------------------------------------------------------------------------
# Writing primitives (writing_architecture, outline_generate, figure_plan,
# competitive_learning) read this as a fallback, eliminating the need to pass
# the contributions string to every call.


@register_primitive(TOPIC_SET_CONTRIBUTIONS_SPEC)
def topic_set_contributions(
    *,
    db: Database,
    topic_id: int,
    contributions: str,
    **_: Any,
) -> TopicSetContributionsOutput:
    """Persist topic-level contributions. Overwrites any prior value."""
    text = (contributions or "").strip()
    conn = db.connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"topic_id={topic_id} not found")
        conn.execute(
            """UPDATE topics
               SET contributions = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (text, topic_id),
        )
        conn.commit()
    finally:
        conn.close()
    return TopicSetContributionsOutput(
        topic_id=topic_id, contributions=text, updated=True
    )


@register_primitive(TOPIC_GET_CONTRIBUTIONS_SPEC)
def topic_get_contributions(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> TopicSetContributionsOutput:
    """Read topic-level contributions. Returns empty string if unset."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT contributions FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError(f"topic_id={topic_id} not found")
    return TopicSetContributionsOutput(
        topic_id=topic_id,
        contributions=(row["contributions"] or "").strip(),
        updated=False,
    )


# ---------------------------------------------------------------------------
# Cold Start Protocol
# ---------------------------------------------------------------------------


@register_primitive(COLD_START_RUN_SPEC)
def cold_start_run(*, db, topic_id, gold_papers=None, **_):
    from ..evolution.cold_start_protocol import ColdStartProtocol

    protocol = ColdStartProtocol(db=db, topic_id=topic_id, gold_papers=gold_papers)
    return protocol.check_all()
