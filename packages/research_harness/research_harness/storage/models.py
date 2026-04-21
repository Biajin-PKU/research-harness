"""Pure data models for research hub storage."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Topic:
    id: int | None = None
    name: str = ""
    description: str = ""
    status: str = "active"
    target_venue: str = ""
    deadline: str = ""
    created_at: str = ""
    last_search_at: str = ""
    freshness_warn_days: int = 7
    freshness_stale_days: int = 30


@dataclass
class Project:
    id: int | None = None
    topic_id: int = 0
    name: str = ""
    description: str = ""
    status: str = "planning"
    target_venue: str = ""
    deadline: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Paper:
    id: int | None = None
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    abstract: str = ""
    doi: str = ""
    arxiv_id: str = ""
    s2_id: str = ""
    url: str = ""
    pdf_path: str = ""
    pdf_hash: str = ""
    affiliations: list[str] = field(default_factory=list)
    status: str = "meta_only"
    created_at: str = ""
    bibtex_auto: str = ""
    concepts_json: str = ""


@dataclass
class PaperAnnotation:
    id: int | None = None
    paper_id: int = 0
    section: str = ""
    content: str = ""
    source: str = ""
    confidence: float = 1.0
    extractor_version: str = ""
    pdf_hash_at_extraction: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class TopicPaperNote:
    id: int | None = None
    paper_id: int = 0
    topic_id: int = 0
    note_type: str = ""
    content: str = ""
    source: str = ""
    created_at: str = ""


@dataclass
class BibEntry:
    paper_id: int = 0
    bibtex_key: str = ""
    bibtex: str = ""
    source: str = ""
    verified_by: str = ""
    verified_at: str = ""


@dataclass
class Task:
    id: int | None = None
    topic_id: int | None = None
    project_id: int | None = None
    title: str = ""
    description: str = ""
    status: str = "pending"
    priority: str = "medium"
    blocker: str = ""
    output_path: str = ""
    due_date: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Review:
    id: int | None = None
    project_id: int = 0
    gate: str = ""
    reviewer: str = ""
    verdict: str = ""
    score: float | None = None
    findings: str = ""
    created_at: str = ""


@dataclass
class SearchRun:
    id: int | None = None
    topic_id: int | None = None
    query: str = ""
    provider: str = ""
    result_count: int = 0
    ingested_count: int = 0
    created_at: str = ""


@dataclass
class SearchQuery:
    """Registered query for per-query freshness tracking."""

    id: int | None = None
    topic_id: int = 0
    query: str = ""
    source: str = "user"  # user / auto_generated / method_expansion
    last_searched_at: str = ""
    created_at: str = ""


@dataclass
class DecisionLogEntry:
    """Record of a human decision at a checkpoint."""

    id: int | None = None
    project_id: int = 0
    topic_id: int = 0
    stage: str = ""
    checkpoint: str = ""  # e.g. 'direction_selection', 'proposal_approval'
    choice: str = ""
    reasoning: str = ""
    params_snapshot: str = "{}"  # JSON: parameters at this point
    created_at: str = ""
