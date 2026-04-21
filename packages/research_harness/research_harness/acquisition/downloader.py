"""PDF downloader with multi-candidate fallback and paywall detection."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx

from ..pdf_download import (
    PaperDownloadCandidate,
    build_candidate_urls,
    is_pdf_bytes,
    preferred_filename,
)

logger = logging.getLogger(__name__)

PAYWALL_DOMAINS = frozenset({
    "sciencedirect.com",
    "springer.com",
    "link.springer.com",
    "wiley.com",
    "onlinelibrary.wiley.com",
    "tandfonline.com",
    "ieeexplore.ieee.org",
    "dl.acm.org",
    "nature.com",
    "science.org",
    "jstor.org",
    "emerald.com",
    "sagepub.com",
    "cambridge.org",
    "oxford.org",
    "oup.com",
})

DOWNLOAD_TIMEOUT = 30.0
MAX_CONCURRENCY = 5
MIN_PDF_BYTES = 10_000


@dataclass(frozen=True)
class DownloadResult:
    paper_id: int
    status: Literal["success", "failed", "needs_manual"]
    path: Path | None = None
    provider: str | None = None
    failure_reason: str | None = None


def _is_paywall_domain(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith(f".{d}") for d in PAYWALL_DOMAINS)


def _classify_http_error(status_code: int, url: str) -> Literal["skip", "paywall", "transient"]:
    if status_code == 404:
        return "skip"
    if status_code in (403, 401):
        if _is_paywall_domain(url):
            return "paywall"
        return "skip"
    if status_code in (429, 500, 502, 503, 504):
        return "transient"
    return "skip"


async def download_single(
    candidate: PaperDownloadCandidate,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> DownloadResult:
    urls = build_candidate_urls(candidate)
    if not urls:
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="failed",
            failure_reason="no candidate URLs",
        )

    filename = preferred_filename(candidate)
    output_path = output_dir / filename
    saw_paywall = False

    async with semaphore:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(DOWNLOAD_TIMEOUT, connect=10.0),
            headers={"User-Agent": "research-harness/0.1 (academic-bot)"},
        ) as client:
            for url in urls:
                try:
                    resp = await client.get(url)
                except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.DecodingError) as exc:
                    logger.debug("Timeout/connect error for %s: %s", url, exc)
                    continue

                if resp.status_code != 200:
                    category = _classify_http_error(resp.status_code, url)
                    if category == "paywall":
                        saw_paywall = True
                    logger.debug("HTTP %d for %s (category=%s)", resp.status_code, url, category)
                    continue

                content = resp.content
                # Sci-Hub returns HTML with embedded PDF — extract direct link
                if not is_pdf_bytes(content) and _is_scihub_domain(url):
                    pdf_url = _extract_scihub_pdf_url(content)
                    if pdf_url:
                        # Resolve relative URLs against the Sci-Hub mirror
                        if pdf_url.startswith("/"):
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            pdf_url = f"{parsed.scheme}://{parsed.netloc}{pdf_url}"
                        try:
                            pdf_resp = await client.get(pdf_url)
                            if pdf_resp.status_code == 200 and is_pdf_bytes(pdf_resp.content):
                                content = pdf_resp.content
                        except Exception as exc:
                            logger.debug("PDF link %s failed: %s", pdf_url, exc)

                if not is_pdf_bytes(content) or len(content) < MIN_PDF_BYTES:
                    logger.debug("Not a valid PDF from %s (%d bytes)", url, len(content))
                    continue

                output_path.write_bytes(content)
                logger.info("Downloaded paper %d from %s (%d bytes)", candidate.paper_id, url, len(content))
                return DownloadResult(
                    paper_id=candidate.paper_id,
                    status="success",
                    path=output_path,
                    provider=url,
                )

    if saw_paywall:
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="needs_manual",
            failure_reason="paywall detected",
        )
    return DownloadResult(
        paper_id=candidate.paper_id,
        status="failed",
        failure_reason="all candidate URLs failed",
    )


def _is_scihub_domain(url: str) -> bool:
    """Check if URL points to a Sci-Hub mirror."""
    import os
    raw = os.environ.get("SCIHUB_MIRRORS", "")
    if not raw:
        return False
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    for mirror in raw.split(","):
        mirror_host = urlparse(mirror.strip()).netloc.lower()
        if mirror_host and host == mirror_host:
            return True
    return False


def _extract_scihub_pdf_url(html_bytes: bytes) -> str | None:
    """Extract direct PDF URL from Sci-Hub HTML response.

    Sci-Hub embeds PDFs using various methods across mirror versions:
      - Legacy: <iframe src="..."> or <embed src="...">
      - Current (2024+): <object data="...pdf"> or <meta name="citation_pdf_url">
    """
    import re
    try:
        text = html_bytes.decode("utf-8", errors="ignore")
    except Exception:
        return None

    def _normalize(url: str) -> str | None:
        if url.startswith("//"):
            url = "https:" + url
        if ".pdf" in url.lower() or "download" in url.lower() or "/storage/" in url.lower():
            return url
        return None

    # Pattern 1: <object data="...pdf#..."> (current sci-hub.st/ru)
    match = re.search(r'<object[^>]+data=["\']([^"\']+\.pdf[^"\']*)["\']', text, re.IGNORECASE)
    if match:
        result = _normalize(match.group(1).split("#")[0])
        if result:
            return result

    # Pattern 2: <meta name="citation_pdf_url" content="...">
    match = re.search(r'<meta\s+name=["\']citation_pdf_url["\']\s+content=["\']([^"\']+)["\']', text, re.IGNORECASE)
    if match:
        result = _normalize(match.group(1))
        if result:
            return result

    # Pattern 3: Legacy <iframe src="..."> or <embed src="...">
    for pattern in (
        r'<(?:iframe|embed)[^>]+src=["\']([^"\']+\.pdf[^"\']*)["\']',
        r'<(?:iframe|embed)[^>]+src=["\']([^"\']+)["\']',
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result = _normalize(match.group(1))
            if result:
                return result

    return None


async def download_batch(
    candidates: list[PaperDownloadCandidate],
    output_dir: Path,
    max_concurrency: int = MAX_CONCURRENCY,
) -> list[DownloadResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = [download_single(c, output_dir, semaphore) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    final: list[DownloadResult] = []
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            logger.warning("Download task %d failed: %s", i, r)
            final.append(DownloadResult(paper_id=candidates[i].paper_id, status="failed", failure_reason=str(r)))
        else:
            final.append(r)
    return final
