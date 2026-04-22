from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable

from .core.circuit_breaker import CircuitBreakerConfig, get_breaker
from .paper_sources import PDFCandidate, PaperRecord, SearchProvider, SearchQuery

# S2 gets a lenient breaker: 429 is rate-limiting (expected), not an outage.
# 8 failures before trip (vs default 3), shorter recovery (30s vs 60s).
_S2_BREAKER_CONFIG = CircuitBreakerConfig(
    failure_threshold=8,
    initial_recovery_sec=30.0,
    max_recovery_sec=300.0,
    backoff_multiplier=2.0,
)

logger = logging.getLogger(__name__)

JsonFetcher = Callable[[str, dict[str, str]], Any]
TextFetcher = Callable[[str, dict[str, str]], str]

_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_BACKOFF_SECS = 1.0


class ProviderConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    enabled: bool
    reason: str = ""


def _fetch_with_retry(
    url: str,
    headers: dict[str, str],
    parse: Callable[[bytes], Any],
    max_retries: int = _MAX_RETRIES,
    base_backoff: float = _BASE_BACKOFF_SECS,
    *,
    data: bytes | None = None,
    method: str | None = None,
    timeout: int = 30,
) -> Any:
    """Fetch a URL with exponential backoff on transient errors.

    Supports both GET and POST requests. For POST, pass *data* and optionally *method*.
    Respects Retry-After header on 429/503 responses.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            request = urllib.request.Request(
                url, headers=headers, data=data, method=method
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return parse(response.read())
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in _RETRYABLE_HTTP_CODES or attempt == max_retries:
                raise
            wait = _parse_retry_after(exc, base_backoff * (2**attempt))
            logger.warning(
                "HTTP %d from %s, retrying in %.1fs (attempt %d/%d)",
                exc.code,
                url,
                wait,
                attempt + 1,
                max_retries,
            )
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt == max_retries:
                raise
            wait = base_backoff * (2**attempt)
            logger.warning(
                "Network error from %s: %s, retrying in %.1fs (attempt %d/%d)",
                url,
                exc,
                wait,
                attempt + 1,
                max_retries,
            )
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def _parse_retry_after(exc: urllib.error.HTTPError, default: float) -> float:
    """Extract wait time from Retry-After header, falling back to *default*."""
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after is None:
        return default
    try:
        return max(float(retry_after), 0.5)
    except ValueError:
        return default


def default_json_fetcher(url: str, headers: dict[str, str]) -> Any:
    return _fetch_with_retry(
        url, headers, lambda data: json.loads(data.decode("utf-8"))
    )


def default_text_fetcher(url: str, headers: dict[str, str]) -> str:
    return _fetch_with_retry(url, headers, lambda data: data.decode("utf-8"))


class HTTPProvider(SearchProvider):
    name: str

    def __init__(self, fetcher: JsonFetcher | None = None):
        self._fetcher = fetcher or default_json_fetcher

    def _fetch_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        breaker = get_breaker(self.name)
        return breaker.call(self._fetcher, url, headers or {})


class GoogleScholarProvider(HTTPProvider):
    name = "google_scholar"

    def __init__(
        self, api_url: str, api_key: str = "", fetcher: JsonFetcher | None = None
    ):
        super().__init__(fetcher=fetcher)
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        params = {"q": query.query, "num": str(query.limit)}
        if query.year_from is not None:
            params["as_ylo"] = str(query.year_from)
        if query.year_to is not None:
            params["as_yhi"] = str(query.year_to)
        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        payload = self._fetch_json(url, headers)
        items = (
            payload.get("organic_results")
            or payload.get("results")
            or payload.get("papers")
            or []
        )
        records: list[PaperRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            pdf_candidates: list[PDFCandidate] = []
            resources = item.get("resources") or item.get("pdfs") or []
            if isinstance(resources, list):
                for resource in resources:
                    if isinstance(resource, dict) and resource.get("link"):
                        pdf_candidates.append(
                            PDFCandidate(
                                url=str(resource["link"]),
                                source_type="open_access_pdf",
                                provider=self.name,
                                confidence=0.75,
                            )
                        )
            if item.get("pdf_url"):
                pdf_candidates.append(
                    PDFCandidate(
                        url=str(item["pdf_url"]),
                        source_type="open_access_pdf",
                        provider=self.name,
                        confidence=0.8,
                    )
                )
            records.append(
                PaperRecord(
                    title=str(item.get("title") or ""),
                    authors=_coerce_authors(
                        item.get("publication_info") or item.get("authors")
                    ),
                    year=_coerce_year(item.get("year") or item.get("publication_year")),
                    venue=str(item.get("publication") or item.get("venue") or ""),
                    abstract=str(item.get("snippet") or item.get("abstract") or ""),
                    doi=str(item.get("doi") or ""),
                    url=str(item.get("link") or item.get("url") or ""),
                    provider=self.name,
                    citation_count=_coerce_int(
                        item.get("cited_by_count")
                        or item.get("inline_links", {}).get("cited_by", {}).get("total")
                    ),
                    pdf_candidates=pdf_candidates,
                )
            )
        return records


class OpenAlexProvider(HTTPProvider):
    name = "openalex"

    def __init__(
        self,
        api_key: str = "",
        email: str | None = None,
        fetcher: JsonFetcher | None = None,
    ):
        super().__init__(fetcher=fetcher)
        self.api_key = api_key
        self.email = email or ""

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        params = {"search": query.query, "per-page": str(query.limit)}
        filters: list[str] = []
        if query.year_from is not None:
            filters.append(f"from_publication_date:{query.year_from}-01-01")
        if query.year_to is not None:
            filters.append(f"to_publication_date:{query.year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if self.email:
            params["mailto"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}"
        payload = self._fetch_json(url, {"Accept": "application/json"})
        results = payload.get("results") or []
        records: list[PaperRecord] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            pdf_candidates = _openalex_pdf_candidates(item)
            primary_location = item.get("primary_location") or {}
            landing = primary_location.get("landing_page_url") or item.get("doi") or ""
            records.append(
                PaperRecord(
                    title=str(item.get("title") or ""),
                    authors=[
                        author.get("author", {}).get("display_name", "")
                        for author in item.get("authorships") or []
                        if isinstance(author, dict)
                        and author.get("author", {}).get("display_name")
                    ],
                    affiliations=_openalex_affiliations(item),
                    year=_coerce_year(item.get("publication_year")),
                    venue=str(
                        (primary_location.get("source") or {}).get("display_name") or ""
                    ),
                    abstract=_openalex_abstract(item),
                    doi=_normalize_doi(str(item.get("doi") or "")),
                    openalex_id=str(item.get("id") or "").rsplit("/", 1)[-1],
                    url=str(landing),
                    provider=self.name,
                    citation_count=_coerce_int(item.get("cited_by_count")),
                    pdf_candidates=pdf_candidates,
                    concepts=_openalex_concepts(item),
                )
            )
        return records

    def _common_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.email:
            params["mailto"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def get_work(self, openalex_id: str) -> PaperRecord | None:
        """Fetch a single work by OpenAlex ID with full metadata."""
        oa_id = openalex_id if openalex_id.startswith("W") else f"W{openalex_id}"
        params = self._common_params()
        url = f"https://api.openalex.org/works/{oa_id}"
        if params:
            url += f"?{urllib.parse.urlencode(params)}"
        try:
            _item = self._fetch_json(url, {"Accept": "application/json"})
        except Exception:
            return None

    def resolve_doi(self, doi: str) -> str | None:
        """Resolve a DOI to an OpenAlex Work ID (W...)."""
        clean = (
            doi.strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
        )
        if not clean:
            return None
        params = self._common_params()
        url = f"https://api.openalex.org/works/doi:{clean}"
        if params:
            url += f"?{urllib.parse.urlencode(params)}"
        try:
            item = self._fetch_json(url, {"Accept": "application/json"})
        except Exception:
            return None
        if not isinstance(item, dict):
            return None
        oa_url = str(item.get("id") or "")
        return oa_url.rsplit("/", 1)[-1] if oa_url else None
        if not isinstance(item, dict) or not item.get("id"):
            return None
        pdf_candidates = _openalex_pdf_candidates(item)
        primary_location = item.get("primary_location") or {}
        landing = primary_location.get("landing_page_url") or item.get("doi") or ""
        return PaperRecord(
            title=str(item.get("title") or ""),
            authors=[
                a.get("author", {}).get("display_name", "")
                for a in item.get("authorships") or []
                if isinstance(a, dict) and a.get("author", {}).get("display_name")
            ],
            affiliations=_openalex_affiliations(item),
            year=_coerce_year(item.get("publication_year")),
            venue=str((primary_location.get("source") or {}).get("display_name") or ""),
            abstract=_openalex_abstract(item),
            doi=_normalize_doi(str(item.get("doi") or "")),
            openalex_id=str(item.get("id") or "").rsplit("/", 1)[-1],
            url=str(landing),
            provider=self.name,
            citation_count=_coerce_int(item.get("cited_by_count")),
            pdf_candidates=pdf_candidates,
            concepts=_openalex_concepts(item),
        )

    def cited_by(self, openalex_id: str, limit: int = 100) -> list[PaperRecord]:
        """Fetch papers that cite the given work, paginating up to limit."""
        oa_id = openalex_id if openalex_id.startswith("W") else f"W{openalex_id}"
        per_page = 50
        results: list[PaperRecord] = []
        page = 1
        while len(results) < limit:
            params = self._common_params()
            params["filter"] = f"cites:{oa_id}"
            params["per-page"] = str(per_page)
            params["sort"] = "cited_by_count:desc"
            params["page"] = str(page)
            url = f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}"
            try:
                payload = self._fetch_json(url, {"Accept": "application/json"})
            except Exception:
                break
            batch = self._parse_results(payload.get("results") or [])
            if not batch:
                break
            results.extend(batch)
            page += 1
        return results[:limit]

    def venue_papers(
        self,
        venue_name: str,
        year_from: int | None = None,
        limit: int = 25,
    ) -> list[PaperRecord]:
        """Fetch recent papers from a specific venue."""
        # First resolve venue name to source ID
        v_params = self._common_params()
        v_params["search"] = venue_name
        v_url = f"https://api.openalex.org/sources?{urllib.parse.urlencode(v_params)}"
        try:
            v_payload = self._fetch_json(v_url, {"Accept": "application/json"})
        except Exception:
            return []
        sources = v_payload.get("results") or []
        if not sources:
            return []
        source_id = str(sources[0].get("id") or "").rsplit("/", 1)[-1]
        if not source_id:
            return []

        # Fetch papers from that source
        params = self._common_params()
        filters = [f"primary_location.source.id:{source_id}"]
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        params["filter"] = ",".join(filters)
        params["per-page"] = str(min(limit, 50))
        params["sort"] = "cited_by_count:desc"
        url = f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}"
        try:
            payload = self._fetch_json(url, {"Accept": "application/json"})
        except Exception:
            return []
        return self._parse_results(payload.get("results") or [])

    def _parse_results(self, results: list) -> list[PaperRecord]:
        records: list[PaperRecord] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            pdf_candidates = _openalex_pdf_candidates(item)
            primary_location = item.get("primary_location") or {}
            landing = primary_location.get("landing_page_url") or item.get("doi") or ""
            records.append(
                PaperRecord(
                    title=str(item.get("title") or ""),
                    authors=[
                        a.get("author", {}).get("display_name", "")
                        for a in item.get("authorships") or []
                        if isinstance(a, dict)
                        and a.get("author", {}).get("display_name")
                    ],
                    affiliations=_openalex_affiliations(item),
                    year=_coerce_year(item.get("publication_year")),
                    venue=str(
                        (primary_location.get("source") or {}).get("display_name") or ""
                    ),
                    abstract=_openalex_abstract(item),
                    doi=_normalize_doi(str(item.get("doi") or "")),
                    openalex_id=str(item.get("id") or "").rsplit("/", 1)[-1],
                    url=str(landing),
                    provider=self.name,
                    citation_count=_coerce_int(item.get("cited_by_count")),
                    pdf_candidates=pdf_candidates,
                    concepts=_openalex_concepts(item),
                )
            )
        return records


class SemanticScholarProvider(HTTPProvider):
    """Semantic Scholar provider with built-in rate limiter.

    Free tier: ~1 req/s.  Keyed tier: ~10 req/s.
    The rate limiter sleeps *before* each request to prevent 429s,
    which is cheaper than hitting 429 → backoff → circuit breaker trip.
    """

    name = "semantic_scholar"

    FIELDS = ",".join(
        [
            "paperId",
            "title",
            "authors",
            "authors.affiliations",
            "year",
            "venue",
            "abstract",
            "externalIds",
            "url",
            "citationCount",
            "openAccessPdf",
        ]
    )

    # Monotonic timestamp of the last S2 request (shared across instances)
    _last_request_time: float = 0.0

    def __init__(self, api_key: str = "", fetcher: JsonFetcher | None = None):
        super().__init__(fetcher=fetcher)
        self.api_key = api_key
        # Free tier: 1 req/s; keyed tier: relax to 0.15s
        self._min_interval = 0.15 if api_key else 1.05

    def _rate_limited_fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> Any:
        """Fetch with pre-request rate limiting to prevent 429s."""
        now = time.monotonic()
        elapsed = now - SemanticScholarProvider._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        SemanticScholarProvider._last_request_time = time.monotonic()
        # Use a more lenient circuit breaker for S2 (429 = rate limit, not outage)
        breaker = get_breaker(self.name, _S2_BREAKER_CONFIG)
        return breaker.call(self._fetcher, url, headers or {})

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        params = {
            "query": query.query,
            "limit": str(query.limit),
            "fields": self.FIELDS,
        }
        if query.year_from is not None or query.year_to is not None:
            start = query.year_from or 1900
            end = query.year_to or 2100
            params["year"] = f"{start}-{end}"
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        payload = self._rate_limited_fetch(url, headers)
        data = payload.get("data") or []
        records: list[PaperRecord] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            open_access = item.get("openAccessPdf") or {}
            pdf_candidates: list[PDFCandidate] = []
            if isinstance(open_access, dict) and open_access.get("url"):
                pdf_candidates.append(
                    PDFCandidate(
                        url=str(open_access["url"]),
                        source_type="open_access_pdf",
                        provider=self.name,
                        confidence=0.9,
                    )
                )
            external_ids = item.get("externalIds") or {}
            records.append(
                PaperRecord(
                    title=str(item.get("title") or ""),
                    authors=[
                        author.get("name", "")
                        for author in item.get("authors") or []
                        if isinstance(author, dict) and author.get("name")
                    ],
                    affiliations=_s2_affiliations(item.get("authors") or []),
                    year=_coerce_year(item.get("year")),
                    venue=str(item.get("venue") or ""),
                    abstract=str(item.get("abstract") or ""),
                    doi=str(external_ids.get("DOI") or ""),
                    arxiv_id=str(external_ids.get("ArXiv") or ""),
                    s2_id=str(item.get("paperId") or ""),
                    url=str(item.get("url") or ""),
                    provider=self.name,
                    citation_count=_coerce_int(item.get("citationCount")),
                    pdf_candidates=pdf_candidates,
                )
            )
        return records

    def get_references(self, paper_id: str, limit: int = 50) -> list[PaperRecord]:
        """Fetch papers referenced by this paper (backward expansion)."""
        fields = "paperId,title,authors,year,venue,abstract,externalIds,citationCount,openAccessPdf"
        params = {"fields": fields, "limit": str(min(limit, 1000))}
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            payload = self._rate_limited_fetch(url, headers)
        except Exception:
            return []
        return [
            self._cited_paper_to_record(item.get("citedPaper") or {})
            for item in payload.get("data") or []
            if item.get("citedPaper")
        ]

    def get_citations(self, paper_id: str, limit: int = 50) -> list[PaperRecord]:
        """Fetch papers that cite this paper (forward expansion)."""
        fields = "paperId,title,authors,year,venue,abstract,externalIds,citationCount,openAccessPdf"
        params = {"fields": fields, "limit": str(min(limit, 1000))}
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            payload = self._rate_limited_fetch(url, headers)
        except Exception:
            return []
        return [
            self._cited_paper_to_record(item.get("citingPaper") or {})
            for item in payload.get("data") or []
            if item.get("citingPaper")
        ]

    def _cited_paper_to_record(self, item: dict) -> PaperRecord:
        if not isinstance(item, dict):
            return PaperRecord()
        external_ids = item.get("externalIds") or {}
        open_access = item.get("openAccessPdf") or {}
        pdf_candidates: list[PDFCandidate] = []
        if isinstance(open_access, dict) and open_access.get("url"):
            pdf_candidates.append(
                PDFCandidate(
                    url=str(open_access["url"]),
                    source_type="open_access_pdf",
                    provider=self.name,
                    confidence=0.9,
                )
            )
        return PaperRecord(
            title=str(item.get("title") or ""),
            authors=[
                a.get("name", "")
                for a in item.get("authors") or []
                if isinstance(a, dict) and a.get("name")
            ],
            affiliations=_s2_affiliations(item.get("authors") or []),
            year=_coerce_year(item.get("year")),
            venue=str(item.get("venue") or ""),
            abstract=str(item.get("abstract") or ""),
            doi=str(external_ids.get("DOI") or ""),
            arxiv_id=str(external_ids.get("ArXiv") or ""),
            s2_id=str(item.get("paperId") or ""),
            provider=self.name,
            citation_count=_coerce_int(item.get("citationCount")),
            pdf_candidates=pdf_candidates,
        )


class OpenReviewProvider(HTTPProvider):
    name = "openreview"

    def __init__(
        self,
        base_url: str = "https://api2.openreview.net",
        access_token: str = "",
        fetcher: JsonFetcher | None = None,
    ):
        super().__init__(fetcher=fetcher)
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        params = {
            "query": query.query,
            "content": "title",
            "limit": str(query.limit),
            "source": "forum",
        }
        url = f"{self.base_url}/notes/search?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        payload = self._fetch_json(url, headers)
        notes = payload.get("notes") or []
        records: list[PaperRecord] = []
        for item in notes:
            if not isinstance(item, dict):
                continue
            content = item.get("content") or {}
            openreview_id = str(item.get("id") or item.get("forum") or "")
            title = _content_text(content.get("title"))
            abstract = _content_text(content.get("abstract"))
            authors = _content_list(content.get("authors"))
            venue = _content_text(content.get("venue"))
            pdf_candidates = []
            if openreview_id:
                pdf_candidates.append(
                    PDFCandidate(
                        url=f"https://openreview.net/pdf?id={openreview_id}",
                        source_type="openreview_pdf",
                        provider=self.name,
                        confidence=0.9,
                    )
                )
            records.append(
                PaperRecord(
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    venue=venue,
                    year=_coerce_year(
                        item.get("pdate") or item.get("cdate") or item.get("odate")
                    ),
                    openreview_id=openreview_id,
                    url=f"https://openreview.net/forum?id={openreview_id}"
                    if openreview_id
                    else "",
                    provider=self.name,
                    pdf_candidates=pdf_candidates,
                )
            )
        return records


class ArxivProvider:
    name = "arxiv"

    def __init__(self, fetcher: TextFetcher | None = None):
        self._fetcher = fetcher or default_text_fetcher

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        params = {
            "search_query": f"all:{query.query}",
            "start": "0",
            "max_results": str(query.limit),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        url = f"https://export.arxiv.org/api/query?{urllib.parse.urlencode(params)}"
        breaker = get_breaker(self.name)
        payload = breaker.call(self._fetcher, url, {"Accept": "application/atom+xml"})
        root = ET.fromstring(payload)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        records: list[PaperRecord] = []
        for entry in root.findall("atom:entry", ns):
            title = _xml_text(entry.find("atom:title", ns))
            abstract = _xml_text(entry.find("atom:summary", ns))
            published = _xml_text(entry.find("atom:published", ns))
            year = _coerce_year(published[:4]) if published else None
            if query.year_from is not None and (year is None or year < query.year_from):
                continue
            if query.year_to is not None and (year is None or year > query.year_to):
                continue
            authors = [
                _xml_text(item.find("atom:name", ns))
                for item in entry.findall("atom:author", ns)
            ]
            authors = [item for item in authors if item]
            entry_id = _xml_text(entry.find("atom:id", ns))
            arxiv_id = entry_id.rsplit("/abs/", 1)[-1] if "/abs/" in entry_id else ""
            doi = _xml_text(entry.find("arxiv:doi", ns))
            pdf_candidates: list[PDFCandidate] = []
            for link in entry.findall("atom:link", ns):
                href = link.attrib.get("href", "")
                title_attr = link.attrib.get("title", "")
                if href and (title_attr == "pdf" or href.endswith(".pdf")):
                    pdf_candidates.append(
                        PDFCandidate(
                            url=href,
                            source_type="arxiv_pdf",
                            provider=self.name,
                            confidence=0.98,
                        )
                    )
            records.append(
                PaperRecord(
                    title=title,
                    authors=authors,
                    year=year,
                    venue="arXiv",
                    abstract=abstract,
                    doi=doi,
                    arxiv_id=arxiv_id,
                    url=entry_id,
                    provider=self.name,
                    pdf_candidates=pdf_candidates,
                )
            )
        return records


class PASAProvider:
    """PASA (Paper Search Agent) — public preprint search via pasa-agent.ai.

    Async polling API: submit query, poll for results. Placed last in the
    provider suite as a high-recall fallback for preprints.
    """

    name = "pasa"

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 30.0,
        poll_interval: float = 2.0,
        max_polls: int = 30,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("PASA_BASE_URL", "https://pasa-agent.ai")
        ).rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self._submit_path = "/paper-agent/api/v1/single_paper_agent"
        self._result_path = "/paper-agent/api/v1/single_get_result"

    def search(self, query: SearchQuery) -> list[PaperRecord]:
        import time
        import random

        session_id = f"{int(time.time() * 1000)}{random.randint(100000, 999999)}"
        # Submit query
        submit_payload = {
            "user_query": query.query,
            "session_id": session_id,
            "top_k": query.limit,
        }
        try:
            self._post_json(self._submit_path, submit_payload)
        except Exception:
            return []

        # Poll for results
        all_items: dict[str, dict] = {}
        stable_polls = 0

        for _ in range(self.max_polls):
            try:
                response = self._post_json(
                    self._result_path, {"session_id": session_id}
                )
            except Exception:
                break

            items = self._extract_items(response)
            if items:
                prev_count = len(all_items)
                for item in items:
                    key = self._item_key(item)
                    all_items.setdefault(key, item)
                stable_polls = 0 if len(all_items) > prev_count else stable_polls + 1
                finished = self._is_finished(response)
                if finished or (all_items and stable_polls >= 1):
                    break
            time.sleep(self.poll_interval)

        records: list[PaperRecord] = []
        for item in all_items.values():
            record = self._to_paper_record(item)
            if record.title:
                if query.year_from and record.year and record.year < query.year_from:
                    continue
                if query.year_to and record.year and record.year > query.year_to:
                    continue
                records.append(record)
        return records[: query.limit]

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        breaker = get_breaker(self.name)
        return breaker.call(
            _fetch_with_retry,
            url,
            {"Content-Type": "application/json", "Accept": "application/json"},
            lambda raw: json.loads(raw.decode("utf-8")),
            data=data,
            method="POST",
            timeout=self.timeout,
        )

    def _extract_items(self, response: Any) -> list[dict]:
        if not isinstance(response, dict):
            return []
        for key in ("papers", "paper_list", "results", "items", "data"):
            value = response.get(key)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(value, dict) and value:
                return [v for v in value.values() if isinstance(v, dict)]
            if isinstance(value, list) and value:
                return [v for v in value if isinstance(v, dict)]
        return []

    @staticmethod
    def _is_finished(response: Any) -> bool:
        if not isinstance(response, dict):
            return False
        if response.get("finish") is True:
            return True
        status = str(response.get("status", "")).strip().lower()
        return status in {"done", "completed", "complete", "finished", "success"}

    @staticmethod
    def _item_key(item: dict) -> str:
        title = str(item.get("title") or item.get("paper_title") or "").strip().lower()
        link = str(
            item.get("link") or item.get("url") or item.get("paper_url") or ""
        ).strip()
        return f"{title}||{link}"

    def _to_paper_record(self, item: dict) -> PaperRecord:
        # Unpack nested json_result if present
        json_result = item.get("json_result")
        if isinstance(json_result, str):
            try:
                json_result = json.loads(json_result)
            except (json.JSONDecodeError, TypeError):
                json_result = None
        if isinstance(json_result, dict):
            item = {**item, **json_result}

        title = str(
            item.get("title") or item.get("paper_title") or item.get("name") or ""
        ).strip()
        authors_raw = (
            item.get("authors") or item.get("author_list") or item.get("creator")
        )
        abstract = str(item.get("abstract") or item.get("summary") or "").strip()
        venue = str(
            item.get("venue") or item.get("journal") or item.get("conference") or ""
        ).strip()
        year = _coerce_year(
            item.get("year") or item.get("published_year") or item.get("publish_time")
        )
        doi = str(item.get("doi") or "").strip()
        arxiv_id = str(item.get("arxiv_id") or item.get("arxiv") or "").strip()

        # Try to extract arxiv_id from URL
        if not arxiv_id:
            for url_key in ("link", "url", "paper_url"):
                link = str(item.get(url_key) or "").strip()
                if "/abs/" in link:
                    arxiv_id = link.split("/abs/", 1)[1].rstrip("/")
                    break

        paper_url = str(
            item.get("paper_url") or item.get("url") or item.get("link") or ""
        ).strip()

        pdf_candidates: list[PDFCandidate] = []
        pdf_url = str(item.get("pdf_url") or item.get("pdf") or "").strip()
        if pdf_url:
            pdf_candidates.append(
                PDFCandidate(
                    url=pdf_url,
                    source_type="open_access_pdf",
                    provider=self.name,
                    confidence=0.7,
                )
            )
        if arxiv_id:
            clean_id = arxiv_id.removesuffix(".pdf").strip("/")
            pdf_candidates.append(
                PDFCandidate(
                    url=f"https://arxiv.org/pdf/{clean_id}.pdf",
                    source_type="arxiv_pdf",
                    provider=self.name,
                    confidence=0.95,
                )
            )

        return PaperRecord(
            title=title,
            authors=_coerce_authors(authors_raw),
            year=year,
            venue=venue,
            abstract=abstract,
            doi=doi,
            arxiv_id=arxiv_id,
            url=paper_url,
            provider=self.name,
            pdf_candidates=pdf_candidates,
        )


def build_provider_suite(fetcher: JsonFetcher | None = None) -> list[SearchProvider]:
    providers: list[SearchProvider] = [ArxivProvider()]
    google_url = os.environ.get("GOOGLE_SCHOLAR_API_URL", "").strip()
    openalex_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    semantic_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()

    if google_url:
        providers.append(
            GoogleScholarProvider(
                api_url=google_url,
                api_key=os.environ.get("GOOGLE_SCHOLAR_API_KEY", ""),
                fetcher=fetcher,
            )
        )
    if openalex_key:
        providers.append(
            OpenAlexProvider(
                api_key=openalex_key,
                email=os.environ.get("OPENALEX_MAILTO", ""),
                fetcher=fetcher,
            )
        )
    # S2 is always enabled (free tier works without key, just rate-limited to ~1 req/s)
    providers.append(SemanticScholarProvider(api_key=semantic_key, fetcher=fetcher))
    if os.environ.get("OPENREVIEW_ENABLE", "").strip().lower() in {"1", "true", "yes"}:
        providers.append(
            OpenReviewProvider(
                access_token=os.environ.get("OPENREVIEW_ACCESS_TOKEN", ""),
                fetcher=fetcher,
            )
        )

    # PASA as last-resort fallback (preprints, lower priority)
    pasa_enabled = os.environ.get("PASA_ENABLE", "").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if pasa_enabled:
        providers.append(PASAProvider())

    return providers


def available_provider_specs() -> list[ProviderSpec]:
    google_url = os.environ.get("GOOGLE_SCHOLAR_API_URL", "").strip()
    openalex_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    semantic_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    openreview_enabled = os.environ.get("OPENREVIEW_ENABLE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    pasa_disabled = os.environ.get("PASA_ENABLE", "").strip().lower() in {
        "0",
        "false",
        "no",
    }
    return [
        ProviderSpec("arxiv", True, "built-in"),
        ProviderSpec(
            "google_scholar",
            bool(google_url),
            "configured" if google_url else "set GOOGLE_SCHOLAR_API_URL",
        ),
        ProviderSpec(
            "openalex",
            bool(openalex_key),
            "configured" if openalex_key else "set OPENALEX_API_KEY",
        ),
        ProviderSpec(
            "semantic_scholar",
            True,
            "configured (keyed)"
            if semantic_key
            else "enabled (free tier, rate-limited)",
        ),
        ProviderSpec(
            "openreview",
            openreview_enabled,
            "configured" if openreview_enabled else "set OPENREVIEW_ENABLE=1",
        ),
        ProviderSpec(
            "pasa",
            not pasa_disabled,
            "enabled (fallback)" if not pasa_disabled else "disabled via PASA_ENABLE=0",
        ),
    ]


def _openalex_pdf_candidates(item: dict[str, Any]) -> list[PDFCandidate]:
    candidates: list[PDFCandidate] = []
    ids = str(item.get("id") or "").rsplit("/", 1)
    if ids and ids[-1]:
        candidates.append(
            PDFCandidate(
                url=f"https://content.openalex.org/works/{ids[-1]}.pdf",
                source_type="openalex_content",
                provider="openalex",
                confidence=0.85,
            )
        )
    best_oa = item.get("best_oa_location") or {}
    for location in [
        best_oa,
        item.get("primary_location") or {},
        *(item.get("locations") or []),
    ]:
        if not isinstance(location, dict):
            continue
        pdf_url = location.get("pdf_url") or ""
        landing_url = location.get("landing_page_url") or ""
        if pdf_url:
            candidates.append(
                PDFCandidate(
                    url=str(pdf_url),
                    source_type="open_access_pdf",
                    provider="openalex",
                    confidence=0.95,
                )
            )
        elif landing_url and location.get("is_oa"):
            candidates.append(
                PDFCandidate(
                    url=str(landing_url),
                    source_type="publisher_pdf",
                    provider="openalex",
                    confidence=0.7,
                )
            )
    return _dedupe_pdf_candidates(candidates)


def _s2_affiliations(authors: list[Any]) -> list[str]:
    """Extract unique affiliations from Semantic Scholar author list."""
    seen: set[str] = set()
    result: list[str] = []
    for author in authors:
        if not isinstance(author, dict):
            continue
        for aff in author.get("affiliations") or []:
            name = (aff if isinstance(aff, str) else "").strip()
            if name and name not in seen:
                seen.add(name)
                result.append(name)
    return result


def _openalex_affiliations(item: dict[str, Any]) -> list[str]:
    """Extract unique institution names from an OpenAlex work's authorships."""
    seen: set[str] = set()
    result: list[str] = []
    for authorship in item.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        for inst in authorship.get("institutions") or []:
            if not isinstance(inst, dict):
                continue
            name = (inst.get("display_name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                result.append(name)
    return result


def _openalex_concepts(item: dict[str, Any]) -> list[dict]:
    """Extract hierarchical concept tags from an OpenAlex work.

    Returns a list of dicts with keys: display_name, level, score.
    Level 0 = broadest (e.g. "Computer Science"), higher = more specific.
    """
    raw = item.get("concepts") or item.get("topics") or []
    concepts: list[dict] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        name = c.get("display_name") or ""
        if not name:
            continue
        concepts.append(
            {
                "display_name": name,
                "level": c.get("level", 0),
                "score": round(c.get("score", 0.0), 3),
            }
        )
    return concepts


def _openalex_abstract(item: dict[str, Any]) -> str:
    inverted = item.get("abstract_inverted_index") or {}
    if not inverted:
        return ""
    size = (
        max(
            (max(positions) for positions in inverted.values() if positions), default=-1
        )
        + 1
    )
    if size <= 0:
        return ""
    tokens = [""] * size
    for token, positions in inverted.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int) and 0 <= pos < size:
                tokens[pos] = token
    return " ".join(token for token in tokens if token)


def _normalize_doi(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("https://doi.org/"):
        return cleaned.removeprefix("https://doi.org/")
    return cleaned


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        inner = value.get("value")
        if isinstance(inner, str):
            return inner
    return ""


def _content_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, dict):
        inner = value.get("value")
        if isinstance(inner, list):
            return [str(item) for item in inner if str(item).strip()]
    return []


def _coerce_authors(value: Any) -> list[str]:
    if isinstance(value, list):
        return [
            str(item.get("name") or item) if isinstance(item, dict) else str(item)
            for item in value
            if str(item.get("name") if isinstance(item, dict) else item).strip()
        ]
    if isinstance(value, dict):
        authors = value.get("authors")
        if isinstance(authors, list):
            return [str(item) for item in authors if str(item).strip()]
        summary = value.get("summary")
        if isinstance(summary, str):
            return [item.strip() for item in summary.split(",") if item.strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _coerce_year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 9999 else None
    text = str(value)
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        return year if 1000 <= year <= 9999 else None
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe_pdf_candidates(items: list[PDFCandidate]) -> list[PDFCandidate]:
    merged: dict[tuple[str, str], PDFCandidate] = {}
    for item in items:
        key = (item.url, item.source_type)
        current = merged.get(key)
        if current is None or item.confidence > current.confidence:
            merged[key] = item
    return list(merged.values())


def _xml_text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()
