"""Verification primitive implementations — Sprint 3.

paper_verify_numbers, citation_verify, evidence_trace.
All non-LLM operations.
"""

from __future__ import annotations

import logging
from typing import Any

from ..experiment.citation_verifier import (
    CitationInput,
    verify_citations,
)
from ..experiment.paper_verifier import verify_paper_numbers
from ..experiment.verified_registry import build_registry_from_metrics
from ..storage.db import Database
from .registry import (
    CITATION_VERIFY_SPEC,
    EVIDENCE_TRACE_SPEC,
    PAPER_VERIFY_NUMBERS_SPEC,
    register_primitive,
)
from .types import (
    CitationVerifyItem,
    CitationVerifyOutput,
    EvidenceTraceLink,
    EvidenceTraceOutput,
    PaperVerifyIssue,
    PaperVerifyOutput,
)

logger = logging.getLogger(__name__)


@register_primitive(PAPER_VERIFY_NUMBERS_SPEC)
def paper_verify_numbers(
    *,
    db: Database,
    topic_id: int,
    text: str,
    section: str = "",
    tolerance: float = 0.01,
    **_: Any,
) -> PaperVerifyOutput:
    """Verify numbers in paper text against the topic's verified registry."""
    # Load registry from DB
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT number_original, source FROM verified_numbers WHERE topic_id = ?",
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    registry = build_registry_from_metrics({})
    for row in rows:
        registry.add_value(row["number_original"], row["source"])

    result = verify_paper_numbers(text, registry, section=section, tolerance=tolerance)

    issues = [
        PaperVerifyIssue(
            severity=i.severity,
            number=i.number,
            raw_text=i.raw_text,
            section=i.section,
            message=i.message,
            line_number=i.line_number,
        )
        for i in result.issues
    ]

    return PaperVerifyOutput(
        total_numbers=result.total_numbers,
        verified_count=result.verified_count,
        always_allowed_count=result.always_allowed_count,
        unverified_count=result.unverified_count,
        pass_rate=result.pass_rate,
        ok=result.ok,
        issues=issues,
    )


@register_primitive(CITATION_VERIFY_SPEC)
def citation_verify(
    *,
    citations: list[dict[str, Any]],
    **_: Any,
) -> CitationVerifyOutput:
    """Verify citations against external databases."""
    inputs = [
        CitationInput(
            title=c.get("title", ""),
            authors=c.get("authors", []),
            year=c.get("year"),
            venue=c.get("venue", ""),
            doi=c.get("doi", ""),
        )
        for c in citations
    ]

    results = verify_citations(inputs)

    items = [
        CitationVerifyItem(
            title=r.title,
            status=r.status,
            confidence=r.confidence,
            matched_title=r.matched_title,
            matched_doi=r.matched_doi,
            source=r.source,
        )
        for r in results
    ]

    verified = sum(1 for r in results if r.status == "verified")
    partial = sum(1 for r in results if r.status == "partial_match")
    not_found = sum(1 for r in results if r.status == "not_found")
    hallucinated = sum(1 for r in results if r.status == "hallucinated")
    total = len(results)
    pass_rate = (verified + partial) / total if total > 0 else 1.0

    return CitationVerifyOutput(
        total=total,
        verified=verified,
        partial=partial,
        not_found=not_found,
        hallucinated=hallucinated,
        items=items,
        pass_rate=pass_rate,
    )


@register_primitive(EVIDENCE_TRACE_SPEC)
def evidence_trace(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> EvidenceTraceOutput:
    """Trace claims → evidence_links → papers → verified_numbers.

    Computes coverage_ratio = fully_traced / total_claims.
    """
    conn = db.connect()
    try:
        # Get all claims for this topic
        claims = conn.execute(
            """
            SELECT DISTINCT pa.payload_json
            FROM project_artifacts pa
            WHERE pa.topic_id = ? AND pa.artifact_type = 'claims' AND pa.status = 'active'
            """,
            (topic_id,),
        ).fetchall()

        # Get all evidence links
        evidence_links = conn.execute(
            """
            SELECT DISTINCT pa.payload_json
            FROM project_artifacts pa
            WHERE pa.topic_id = ? AND pa.artifact_type = 'evidence_links' AND pa.status = 'active'
            """,
            (topic_id,),
        ).fetchall()

        # Get papers with verified numbers
        rows = conn.execute(
            "SELECT DISTINCT topic_id FROM verified_numbers WHERE topic_id = ?",
            (topic_id,),
        ).fetchall()
        has_verified = len(rows) > 0

        # Get paper IDs in this topic
        paper_rows = conn.execute(
            """
            SELECT p.id, p.title FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
        paper_map = {row["id"]: row["title"] for row in paper_rows}

    finally:
        conn.close()

    # Parse claims from artifacts
    import json

    all_claim_ids: list[str] = []
    for row in claims:
        try:
            payload = json.loads(row["payload_json"] or "{}")
            for claim in payload.get("claims", []):
                cid = claim.get("claim_id", "")
                if cid:
                    all_claim_ids.append(cid)
        except (json.JSONDecodeError, TypeError):
            continue

    # Parse evidence links
    link_map: dict[str, list[dict]] = {}  # claim_id → [link_data]
    for row in evidence_links:
        try:
            payload = json.loads(row["payload_json"] or "{}")
            links = payload.get("links", [payload]) if isinstance(payload, dict) else []
            for link in links:
                cid = link.get("claim_id", "")
                if cid:
                    link_map.setdefault(cid, []).append(link)
        except (json.JSONDecodeError, TypeError):
            continue

    # Build traces
    traces: list[EvidenceTraceLink] = []
    traced = 0
    fully_traced = 0

    for claim_id in all_claim_ids:
        links = link_map.get(claim_id, [])
        if not links:
            traces.append(EvidenceTraceLink(claim_id=claim_id))
            continue

        traced += 1
        for link in links:
            source_type = link.get("source_type", "")
            source_id = link.get("source_id", "")
            paper_id = 0
            paper_title = ""

            if source_type == "paper":
                try:
                    paper_id = int(source_id)
                    paper_title = paper_map.get(paper_id, "")
                except (ValueError, TypeError):
                    pass

            chain_complete = bool(paper_id and has_verified)
            if chain_complete:
                fully_traced += 1

            traces.append(
                EvidenceTraceLink(
                    claim_id=claim_id,
                    evidence_link_id=f"{claim_id}:{source_type}:{source_id}",
                    paper_id=paper_id,
                    paper_title=paper_title,
                    has_verified_numbers=has_verified,
                    chain_complete=chain_complete,
                )
            )

    total = len(all_claim_ids) if all_claim_ids else 0
    coverage = fully_traced / total if total > 0 else 0.0

    return EvidenceTraceOutput(
        total_claims=total,
        traced_claims=traced,
        fully_traced=fully_traced,
        coverage_ratio=coverage,
        traces=traces,
    )
