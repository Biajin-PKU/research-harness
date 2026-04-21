from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

MIN_PDF_BYTES = 10_000


@dataclass(frozen=True)
class PaperDownloadCandidate:
    paper_id: int
    title: str
    year: int | None = None
    venue: str = ""
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""


def is_pdf_bytes(payload: bytes) -> bool:
    return payload.startswith(b"%PDF")


def sanitize_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned[:80] or "paper"


def preferred_filename(candidate: PaperDownloadCandidate) -> str:
    return f"{candidate.paper_id}_{sanitize_filename(candidate.title)}.pdf"


def build_candidate_urls(candidate: PaperDownloadCandidate, manual_urls: Iterable[str] | None = None) -> list[str]:
    """Build prioritized list of candidate download URLs.

    Priority order:
      1. Manual URLs (user-provided)
      2. Paper's stored URL (often S2 openAccessPdf from enrichment)
      3. arXiv direct PDF
      4. Unpaywall OA PDF
      5. Sci-Hub (if SCIHUB_MIRRORS configured)
      6. Publisher-specific URLs (ACM, IEEE, Elsevier, Springer, etc.)
      7. doi.org redirect (often hits paywall)
    """
    # Phase 1: High-priority OA sources
    oa_urls: list[str] = []
    oa_urls.extend((manual_urls or []))
    if candidate.url:
        oa_urls.append(candidate.url)

    # arXiv direct PDF
    arxiv_id = (candidate.arxiv_id or "").strip()
    if arxiv_id:
        normalized_arxiv = arxiv_id.removeprefix("arXiv:").strip()
        oa_urls.append(f"https://arxiv.org/pdf/{normalized_arxiv}.pdf")

    # Unpaywall OA
    doi = (candidate.doi or "").strip()
    if doi:
        oa_url = _unpaywall_oa_url(doi)
        if oa_url:
            oa_urls.append(oa_url)

    # Phase 2: Sci-Hub (after OA, before publisher paywall URLs)
    if doi:
        scihub_url = _scihub_url(doi)
        if scihub_url:
            oa_urls.append(scihub_url)

    # Phase 3: Publisher-specific URLs (may be paywalled)
    publisher_urls = _publisher_urls_from_doi(doi, (candidate.venue or "").lower(), candidate.year)

    all_urls = oa_urls + publisher_urls
    return _dedupe(_normalize_urls(all_urls))


def _publisher_urls_from_doi(doi: str, venue: str, year: int | None = None) -> list[str]:
    """Generate publisher-specific download URLs from DOI."""
    if not doi:
        return []

    urls: list[str] = []
    encoded_doi = quote(doi, safe="/")

    # ACM Digital Library
    if doi.startswith("10.1145/"):
        urls.append(f"https://dl.acm.org/doi/pdf/{encoded_doi}")

    # INFORMS journals
    if doi.startswith("10.1287/") or "msom" in venue or "informs" in venue:
        urls.append(f"https://pubsonline.informs.org/doi/pdf/{encoded_doi}")

    # Springer
    if doi.startswith("10.1007/"):
        urls.append(f"https://link.springer.com/content/pdf/{encoded_doi}.pdf")

    # IEEE Xplore — extract arnumber from DOI suffix
    if doi.startswith("10.1109/"):
        parts = doi.split(".")
        if parts and parts[-1].isdigit():
            arnumber = parts[-1]
            urls.append(
                f"https://ieeexplore.ieee.org/stamp/stamp.jsp?{urlencode({'tp': '', 'arnumber': arnumber})}"
            )

    # Elsevier / ScienceDirect
    if doi.startswith("10.1016/"):
        urls.append(f"https://www.sciencedirect.com/science/article/pii/{encoded_doi}")

    # doi.org redirect (last — often hits paywall landing page)
    urls.append(f"https://doi.org/{encoded_doi}")

    return urls


# ---------------------------------------------------------------------------
# Unpaywall OA lookup
# ---------------------------------------------------------------------------

def _unpaywall_oa_url(doi: str) -> str | None:
    """Query Unpaywall API for best open-access PDF URL.

    Returns the OA PDF URL if available, None otherwise.
    Uses a 10s timeout and catches all errors gracefully.
    """
    import urllib.request
    import urllib.error

    email = os.environ.get("UNPAYWALL_EMAIL", "research-harness@academic-tools.org")
    encoded_doi = quote(doi, safe="/")
    api_url = f"https://api.unpaywall.org/v2/{encoded_doi}?email={email}"

    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "research-harness/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None

    # Try best_oa_location first, then iterate oa_locations
    best = data.get("best_oa_location") or {}
    pdf_url = (best.get("url_for_pdf") or "").strip()
    if pdf_url:
        return pdf_url

    # Fallback: scan all OA locations for a PDF URL
    for loc in data.get("oa_locations") or []:
        pdf_url = (loc.get("url_for_pdf") or "").strip()
        if pdf_url:
            return pdf_url

    return None


# ---------------------------------------------------------------------------
# Sci-Hub fallback (opt-in via SCIHUB_MIRRORS env var)
# ---------------------------------------------------------------------------

def _scihub_url(doi: str) -> str | None:
    """Build a Sci-Hub URL from DOI if mirrors are configured.

    Disabled by default. Set SCIHUB_MIRRORS env var to enable:
        export SCIHUB_MIRRORS="https://sci-hub.se,https://sci-hub.st"

    Returns the first mirror URL, or None if not configured.
    """
    raw = os.environ.get("SCIHUB_MIRRORS", "")
    mirrors = [m.strip().rstrip("/") for m in raw.split(",") if m.strip()]
    if not mirrors:
        return None
    encoded_doi = quote(doi, safe="/")
    return f"{mirrors[0]}/{encoded_doi}"


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

def _normalize_urls(urls: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for raw_url in urls:
        raw_url = (raw_url or "").strip()
        if not raw_url:
            continue
        normalized.extend(_expand_url(raw_url))
    return _dedupe(normalized)


def _expand_url(url: str) -> list[str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path
    query = parse_qs(parsed.query, keep_blank_values=True)

    if host.endswith("arxiv.org"):
        if path.startswith("/abs/"):
            arxiv_id = path.split("/abs/", 1)[1]
            return [f"https://arxiv.org/pdf/{arxiv_id}.pdf", url]
        if path.startswith("/pdf/") and not path.endswith(".pdf"):
            return [f"https://{host}{path}.pdf"]

    if "ieeexplore.ieee.org" in host:
        arnumber = query.get("arnumber", [None])[0]
        if "/document/" in path:
            arnumber = path.rstrip("/").split("/")[-1]
        if arnumber:
            return [
                f"https://ieeexplore.ieee.org/stamp/stamp.jsp?{urlencode({'tp': '', 'arnumber': arnumber})}",
                f"https://ieeexplore.ieee.org/document/{arnumber}",
                url,
            ]

    if host.endswith("kns.cnki.net") and "/article/abstract" in path:
        pdf_path = path.replace("/article/abstract", "/article/pdf")
        return [urlunparse(parsed._replace(path=pdf_path)), url]

    return [url]


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output
