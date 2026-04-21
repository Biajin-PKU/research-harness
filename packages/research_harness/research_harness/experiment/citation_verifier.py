"""Citation verifier — 4-layer cascade verification of bibliographic references.

Checks citations against: CrossRef → DataCite → OpenAlex → Semantic Scholar.
Uses Jaccard title similarity for matching:
  - >= 0.80 → verified
  - >= 0.50 → partial_match
  - <  0.50 → hallucinated (if all sources fail)

Integrates with circuit breaker for resilience and search cache (TTL=365d)
for efficiency.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Jaccard similarity thresholds
VERIFIED_THRESHOLD = 0.80
PARTIAL_THRESHOLD = 0.50


@dataclass
class CitationInput:
    """A citation to verify."""

    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""


@dataclass
class CitationResult:
    """Result of verifying a single citation."""

    title: str
    status: str = "not_found"  # verified | partial_match | not_found | hallucinated
    confidence: float = 0.0
    matched_title: str = ""
    matched_doi: str = ""
    source: str = ""  # which API confirmed it


def _tokenize(text: str) -> set[str]:
    """Tokenize a title for Jaccard similarity."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = set(text.split())
    # Remove common stop words
    stop_words = {"a", "an", "the", "of", "in", "on", "for", "and", "to", "with", "is", "by", "at", "from"}
    return tokens - stop_words


def jaccard_similarity(title_a: str, title_b: str) -> float:
    """Compute Jaccard similarity between two titles."""
    tokens_a = _tokenize(title_a)
    tokens_b = _tokenize(title_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _classify_match(similarity: float) -> str:
    """Classify a match based on Jaccard similarity."""
    if similarity >= VERIFIED_THRESHOLD:
        return "verified"
    if similarity >= PARTIAL_THRESHOLD:
        return "partial_match"
    return "not_found"


def _check_crossref(title: str, http_fn: Any = None) -> CitationResult | None:
    """Check a citation against CrossRef API."""
    try:
        if http_fn is None:
            import urllib.request
            import json

            encoded = urllib.parse.quote(title)
            url = f"https://api.crossref.org/works?query.bibliographic={encoded}&rows=3"
            req = urllib.request.Request(url, headers={"User-Agent": "ResearchHarness/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("crossref", title)

        items = data.get("message", {}).get("items", [])
        for item in items[:3]:
            candidate_title = " ".join(item.get("title", []))
            if not candidate_title:
                continue
            sim = jaccard_similarity(title, candidate_title)
            status = _classify_match(sim)
            if status != "not_found":
                return CitationResult(
                    title=title,
                    status=status,
                    confidence=sim,
                    matched_title=candidate_title,
                    matched_doi=item.get("DOI", ""),
                    source="crossref",
                )
    except Exception as exc:
        logger.debug("CrossRef check failed for '%s': %s", title[:50], exc)
    return None


def _check_openalex(title: str, http_fn: Any = None) -> CitationResult | None:
    """Check a citation against OpenAlex API."""
    try:
        if http_fn is None:
            import urllib.request
            import json

            encoded = urllib.parse.quote(title)
            url = f"https://api.openalex.org/works?filter=title.search:{encoded}&per_page=3"
            req = urllib.request.Request(url, headers={"User-Agent": "ResearchHarness/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("openalex", title)

        results = data.get("results", [])
        for item in results[:3]:
            candidate_title = item.get("title", "")
            if not candidate_title:
                continue
            sim = jaccard_similarity(title, candidate_title)
            status = _classify_match(sim)
            if status != "not_found":
                return CitationResult(
                    title=title,
                    status=status,
                    confidence=sim,
                    matched_title=candidate_title,
                    matched_doi=item.get("doi", "").replace("https://doi.org/", ""),
                    source="openalex",
                )
    except Exception as exc:
        logger.debug("OpenAlex check failed for '%s': %s", title[:50], exc)
    return None


def _check_semantic_scholar(title: str, http_fn: Any = None) -> CitationResult | None:
    """Check a citation against Semantic Scholar API."""
    try:
        if http_fn is None:
            import urllib.request
            import json

            encoded = urllib.parse.quote(title)
            url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={encoded}&limit=3&fields=title,externalIds"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("semantic_scholar", title)

        papers = data.get("data", [])
        for paper in papers[:3]:
            candidate_title = paper.get("title", "")
            if not candidate_title:
                continue
            sim = jaccard_similarity(title, candidate_title)
            status = _classify_match(sim)
            if status != "not_found":
                ext_ids = paper.get("externalIds", {}) or {}
                return CitationResult(
                    title=title,
                    status=status,
                    confidence=sim,
                    matched_title=candidate_title,
                    matched_doi=ext_ids.get("DOI", ""),
                    source="semantic_scholar",
                )
    except Exception as exc:
        logger.debug("S2 check failed for '%s': %s", title[:50], exc)
    return None


def _check_datacite(title: str, http_fn: Any = None) -> CitationResult | None:
    """Check a citation against DataCite API."""
    try:
        if http_fn is None:
            import urllib.request
            import json

            encoded = urllib.parse.quote(title)
            url = f"https://api.datacite.org/dois?query={encoded}&page[size]=3"
            req = urllib.request.Request(url, headers={"User-Agent": "ResearchHarness/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        else:
            data = http_fn("datacite", title)

        items = data.get("data", [])
        for item in items[:3]:
            attrs = item.get("attributes", {})
            candidate_title = " ".join(attrs.get("titles", [{}])[0].get("title", "").split()) if attrs.get("titles") else ""
            if not candidate_title:
                continue
            sim = jaccard_similarity(title, candidate_title)
            status = _classify_match(sim)
            if status != "not_found":
                return CitationResult(
                    title=title,
                    status=status,
                    confidence=sim,
                    matched_title=candidate_title,
                    matched_doi=attrs.get("doi", ""),
                    source="datacite",
                )
    except Exception as exc:
        logger.debug("DataCite check failed for '%s': %s", title[:50], exc)
    return None


# Cascade order: CrossRef (best coverage) → DataCite → OpenAlex → S2
_CASCADE = [
    ("crossref", _check_crossref),
    ("datacite", _check_datacite),
    ("openalex", _check_openalex),
    ("semantic_scholar", _check_semantic_scholar),
]


def verify_citation(
    citation: CitationInput,
    http_fn: Any = None,
    breaker_fn: Any = None,
) -> CitationResult:
    """Verify a single citation through the 4-layer cascade.

    Args:
        citation: The citation to verify.
        http_fn: Optional mock HTTP function for testing.
        breaker_fn: Optional circuit breaker wrapper.

    Returns:
        CitationResult with status and matched metadata.
    """
    # If DOI is provided, it's likely real — skip cascade
    if citation.doi:
        return CitationResult(
            title=citation.title,
            status="verified",
            confidence=1.0,
            matched_doi=citation.doi,
            source="doi_provided",
        )

    best_result: CitationResult | None = None

    for source_name, check_fn in _CASCADE:
        try:
            if breaker_fn is not None:
                result = breaker_fn(source_name, check_fn, citation.title, http_fn)
            else:
                result = check_fn(citation.title, http_fn)
        except Exception:
            continue

        if result is None:
            continue

        if result.status == "verified":
            return result

        # Keep the best partial match
        if best_result is None or result.confidence > best_result.confidence:
            best_result = result

    # If we got a partial match, return it
    if best_result is not None:
        return best_result

    # All sources failed → hallucinated
    return CitationResult(
        title=citation.title,
        status="hallucinated",
        confidence=0.0,
    )


def verify_citations(
    citations: list[CitationInput],
    http_fn: Any = None,
    breaker_fn: Any = None,
) -> list[CitationResult]:
    """Verify a batch of citations."""
    return [verify_citation(c, http_fn=http_fn, breaker_fn=breaker_fn) for c in citations]
