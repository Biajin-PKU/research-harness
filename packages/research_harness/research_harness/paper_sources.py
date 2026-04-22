from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable, Protocol


_TITLE_TOKEN_RE = re.compile(r"[^a-z0-9]+")

SEARCH_PROVIDER_PRIORITY: dict[str, int] = {
    "google_scholar": 120,
    "openalex": 115,
    "semantic_scholar": 110,
    "openreview": 105,
    "arxiv": 100,
    "crossref": 95,
    "dblp": 90,
    "pasa": 50,
    "manual": 200,
}

METADATA_FIELD_PRIORITY: dict[str, int] = {
    "manual": 200,
    "openalex": 130,
    "crossref": 125,
    "arxiv": 120,
    "openreview": 118,
    "semantic_scholar": 112,
    "dblp": 105,
    "google_scholar": 95,
}

PDF_SOURCE_PRIORITY: dict[str, int] = {
    "manual_pdf": 220,
    "local_file": 210,
    "openalex_content": 200,
    "open_access_pdf": 190,
    "arxiv_pdf": 185,
    "openreview_pdf": 180,
    "publisher_pdf": 130,
    "doi_landing": 80,
    "browser_session": 70,
}


@dataclass(frozen=True)
class SearchQuery:
    query: str
    topic: str = ""
    year_from: int | None = None
    year_to: int | None = None
    limit: int = 50


@dataclass(frozen=True)
class PDFCandidate:
    url: str
    source_type: str
    provider: str
    requires_browser: bool = False
    confidence: float = 0.5
    license_hint: str = ""

    @property
    def priority(self) -> int:
        return PDF_SOURCE_PRIORITY.get(self.source_type, 0)


@dataclass
class ProviderError:
    provider: str
    error_type: str
    message: str


@dataclass
class SearchOutcome:
    results: list[PaperRecord]
    provider_errors: list[ProviderError] = field(default_factory=list)


@dataclass
class PaperRecord:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    abstract: str = ""
    doi: str = ""
    arxiv_id: str = ""
    s2_id: str = ""
    openalex_id: str = ""
    openreview_id: str = ""
    url: str = ""
    provider: str = ""
    citation_count: int | None = None
    pdf_candidates: list[PDFCandidate] = field(default_factory=list)
    concepts: list[dict] = field(default_factory=list)  # OpenAlex concept tags
    source_rank: int = 0

    def fingerprint(self) -> str:
        for value in (
            self.doi,
            self.arxiv_id,
            self.openreview_id,
            self.s2_id,
            self.openalex_id,
        ):
            cleaned = (value or "").strip().lower()
            if cleaned:
                return cleaned
        normalized_title = normalize_title(self.title)
        normalized_year = str(self.year or "")
        return f"title:{normalized_title}:{normalized_year}"


class SearchProvider(Protocol):
    name: str

    def search(self, query: SearchQuery) -> list[PaperRecord]: ...


def normalize_title(value: str) -> str:
    lowered = value.strip().lower()
    lowered = _TITLE_TOKEN_RE.sub(" ", lowered)
    return " ".join(lowered.split())


def title_year_key(record: PaperRecord) -> str:
    return f"{normalize_title(record.title)}::{record.year or ''}"


def provider_priority(provider: str, table: dict[str, int]) -> int:
    return table.get(provider, 0)


class SearchAggregator:
    def __init__(self, providers: Iterable[SearchProvider]):
        self.providers = list(providers)

    def search(
        self, query: SearchQuery, *, output_limit: int | None = None
    ) -> SearchOutcome:
        """Search all providers and merge results.

        Each provider is queried with ``query.limit`` (per-provider cap).
        The merged output is capped at ``output_limit`` when provided, otherwise
        all unique merged results are returned so callers can apply their own cap.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        merged: dict[str, PaperRecord] = {}
        title_index: dict[str, str] = {}
        provider_errors: list[ProviderError] = []

        if not self.providers:
            return SearchOutcome(results=[], provider_errors=[])

        def _query_one(
            provider: SearchProvider,
        ) -> tuple[SearchProvider, list[PaperRecord]]:
            return provider, provider.search(query)

        with ThreadPoolExecutor(max_workers=len(self.providers)) as pool:
            futures = {pool.submit(_query_one, p): p for p in self.providers}
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    _, records = future.result()
                except Exception as exc:
                    provider_errors.append(
                        ProviderError(
                            provider=getattr(
                                provider, "name", provider.__class__.__name__
                            ),
                            error_type=exc.__class__.__name__,
                            message=str(exc),
                        )
                    )
                    continue
                for record in records:
                    provider_name = record.provider or provider.name
                    record.provider = provider_name
                    record.source_rank = provider_priority(
                        provider_name, SEARCH_PROVIDER_PRIORITY
                    )
                    key = record.fingerprint()
                    title_key = title_year_key(record)
                    existing_key = key if key in merged else title_index.get(title_key)
                    if existing_key is not None:
                        merged_record = merge_records(merged[existing_key], record)
                        canonical_key = merged_record.fingerprint()
                        if canonical_key != existing_key:
                            del merged[existing_key]
                        merged[canonical_key] = merged_record
                        title_index[title_key] = canonical_key
                    else:
                        merged[key] = clone_record(record)
                        title_index[title_key] = key
        ranked = sorted(
            merged.values(),
            key=lambda record: rank_record(record, query.query),
            reverse=True,
        )
        cap = output_limit if output_limit is not None else len(ranked)
        return SearchOutcome(results=ranked[:cap], provider_errors=provider_errors)


class PDFResolver:
    def plan(self, record: PaperRecord) -> list[PDFCandidate]:
        merged: dict[tuple[str, str], PDFCandidate] = {}
        for candidate in record.pdf_candidates:
            key = (candidate.url.strip(), candidate.source_type)
            if not key[0]:
                continue
            current = merged.get(key)
            if current is None or rank_pdf_candidate(candidate) > rank_pdf_candidate(
                current
            ):
                merged[key] = candidate

        if record.arxiv_id:
            arxiv_url = (
                f"https://arxiv.org/pdf/{record.arxiv_id.removeprefix('arXiv:')}.pdf"
            )
            candidate = PDFCandidate(
                url=arxiv_url,
                source_type="arxiv_pdf",
                provider="arxiv",
                confidence=0.98,
            )
            key = (candidate.url, candidate.source_type)
            merged.setdefault(key, candidate)

        if record.openreview_id:
            openreview_url = f"https://openreview.net/pdf?id={record.openreview_id}"
            candidate = PDFCandidate(
                url=openreview_url,
                source_type="openreview_pdf",
                provider="openreview",
                confidence=0.9,
            )
            key = (candidate.url, candidate.source_type)
            merged.setdefault(key, candidate)

        if record.doi:
            doi_url = f"https://doi.org/{record.doi}"
            candidate = PDFCandidate(
                url=doi_url,
                source_type="doi_landing",
                provider="crossref",
                confidence=0.6,
            )
            key = (candidate.url, candidate.source_type)
            merged.setdefault(key, candidate)

        return sorted(merged.values(), key=rank_pdf_candidate, reverse=True)


def merge_records(base: PaperRecord, incoming: PaperRecord) -> PaperRecord:
    result = clone_record(base)
    result.pdf_candidates = list(base.pdf_candidates)
    result.source_rank = max(base.source_rank, incoming.source_rank)

    _merge_scalar(result, incoming, "title")
    _merge_scalar(result, incoming, "venue")
    _merge_scalar(result, incoming, "abstract")
    _merge_scalar(result, incoming, "doi")
    _merge_scalar(result, incoming, "arxiv_id")
    _merge_scalar(result, incoming, "s2_id")
    _merge_scalar(result, incoming, "openalex_id")
    _merge_scalar(result, incoming, "openreview_id")
    _merge_scalar(result, incoming, "url")
    _merge_numeric(result, incoming, "year")
    _merge_numeric(result, incoming, "citation_count")

    if incoming.authors and (
        not result.authors
        or provider_priority(incoming.provider, METADATA_FIELD_PRIORITY)
        >= provider_priority(base.provider, METADATA_FIELD_PRIORITY)
    ):
        result.authors = list(dict.fromkeys(incoming.authors))

    if incoming.affiliations and (
        not result.affiliations
        or provider_priority(incoming.provider, METADATA_FIELD_PRIORITY)
        >= provider_priority(base.provider, METADATA_FIELD_PRIORITY)
    ):
        result.affiliations = list(dict.fromkeys(incoming.affiliations))

    existing_urls = {(item.url, item.source_type) for item in result.pdf_candidates}
    for candidate in incoming.pdf_candidates:
        key = (candidate.url, candidate.source_type)
        if candidate.url and key not in existing_urls:
            result.pdf_candidates.append(candidate)
            existing_urls.add(key)
    return result


def clone_record(record: PaperRecord) -> PaperRecord:
    return PaperRecord(
        title=record.title,
        authors=list(record.authors),
        affiliations=list(record.affiliations),
        year=record.year,
        venue=record.venue,
        abstract=record.abstract,
        doi=record.doi,
        arxiv_id=record.arxiv_id,
        s2_id=record.s2_id,
        openalex_id=record.openalex_id,
        openreview_id=record.openreview_id,
        url=record.url,
        provider=record.provider,
        citation_count=record.citation_count,
        pdf_candidates=list(record.pdf_candidates),
        concepts=list(record.concepts),
        source_rank=record.source_rank,
    )


def _merge_scalar(result: PaperRecord, incoming: PaperRecord, field_name: str) -> None:
    existing_value = getattr(result, field_name)
    incoming_value = getattr(incoming, field_name)
    if not incoming_value:
        return
    if not existing_value or provider_priority(
        incoming.provider, METADATA_FIELD_PRIORITY
    ) >= provider_priority(result.provider, METADATA_FIELD_PRIORITY):
        setattr(result, field_name, incoming_value)
        if field_name != "title":
            result.provider = incoming.provider


def _merge_numeric(result: PaperRecord, incoming: PaperRecord, field_name: str) -> None:
    incoming_value = getattr(incoming, field_name)
    if incoming_value is None:
        return
    existing_value = getattr(result, field_name)
    if existing_value is None or provider_priority(
        incoming.provider, METADATA_FIELD_PRIORITY
    ) >= provider_priority(result.provider, METADATA_FIELD_PRIORITY):
        setattr(result, field_name, incoming_value)


def rank_record(
    record: PaperRecord, query_text: str = ""
) -> tuple[int, int, int, int, int, str]:
    title_match = query_title_match_score(record, query_text)
    pdf_bonus = (
        1 if record.pdf_candidates or record.arxiv_id or record.openreview_id else 0
    )
    citation_score = record.citation_count or 0
    id_bonus = sum(
        1
        for item in (
            record.doi,
            record.arxiv_id,
            record.s2_id,
            record.openalex_id,
            record.openreview_id,
        )
        if item
    )
    return (
        record.source_rank,
        title_match,
        pdf_bonus,
        citation_score,
        id_bonus,
        normalize_title(record.title),
    )


def query_title_match_score(record: PaperRecord, query_text: str) -> int:
    if not query_text.strip():
        return 0
    normalized_query = normalize_title(query_text)
    normalized_title = normalize_title(record.title)
    if normalized_title == normalized_query:
        return 3
    if normalized_query and normalized_query in normalized_title:
        return 2
    query_tokens = set(normalized_query.split())
    title_tokens = set(normalized_title.split())
    if query_tokens and query_tokens.issubset(title_tokens):
        return 1
    return 0


def rank_pdf_candidate(candidate: PDFCandidate) -> tuple[int, float, int, str]:
    browser_penalty = 0 if not candidate.requires_browser else -1
    return (candidate.priority, candidate.confidence, browser_penalty, candidate.url)
