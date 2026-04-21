# 01 Research Primitives

## 设计目标

定义 research-harness 的**研究操作词汇表** — 一组类型安全、可审计、后端无关的研究原语。这些原语是 ExecutionBackend 的操作单元，也是 Provenance 系统的记录粒度。

## 设计逻辑

### 为什么需要 Research Primitives？

当前 research-harness 的操作分散在 CLI 命令和 PaperPool 方法中，没有统一的"研究操作"抽象。引入 Primitives 的好处：

1. **后端无关** — 相同的 primitive 可以在 Claude Code 或 Research Harness 上执行
2. **可审计** — 每次 primitive 调用都有标准化的输入/输出类型，方便 provenance 追踪
3. **可路由** — Research Harness 的 task-aware router 按 primitive 类型选择模型
4. **可测试** — 每个 primitive 有明确的 input/output contract

### 与现有系统的关系

```
现有:
  CLI (click commands) → PaperPool / ProjectManager / PaperIndexAdapter → DB

加入 Primitives 后:
  CLI → ExecutionBackend.execute_primitive() → Primitive 实现 → PaperPool / ... → DB
       ↕                                       ↕
  Provenance 自动记录                     可被 Research Harness 替换
```

CLI 仍然是用户入口，但核心操作经过 Primitive 层，使得后端可替换、操作可追踪。

---

## 数据类型定义

### 文件: `packages/research_harness/research_harness/primitives/types.py`

```python
"""Research primitive types — input/output contracts for all research operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PrimitiveCategory(str, Enum):
    """Task taxonomy for model routing.

    Each category maps to a default model tier in the Research Harness router.
    Categories are derived empirically (see docs/research_harness_design.md § Task Taxonomy).
    """

    RETRIEVAL = "retrieval"          # paper_search, keyword expansion
    COMPREHENSION = "comprehension"  # paper_summarize, section extract
    EXTRACTION = "extraction"        # claim_extract, baseline_identify, evidence_link
    ANALYSIS = "analysis"            # gap_detect, method_compare
    SYNTHESIS = "synthesis"          # hypothesis_gen, cross-paper synthesis
    GENERATION = "generation"        # section_draft, outline_gen
    VERIFICATION = "verification"    # consistency_check, novelty_assess


@dataclass(frozen=True)
class PrimitiveSpec:
    """Metadata for a registered research primitive."""

    name: str
    category: PrimitiveCategory
    description: str
    input_schema: dict[str, Any]   # JSON Schema of expected kwargs
    output_type: str               # fully qualified class name of output dataclass
    requires_llm: bool = True      # whether this primitive needs an LLM call
    idempotent: bool = False       # safe to retry without side effects


# ─── Primitive Input / Output Types ─────────────────────────────────

@dataclass(frozen=True)
class PaperRef:
    """Lightweight paper reference returned by search."""

    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    arxiv_id: str = ""
    s2_id: str = ""
    relevance_score: float = 0.0
    snippet: str = ""


@dataclass(frozen=True)
class PaperSearchInput:
    query: str
    topic_id: int | None = None
    max_results: int = 20
    year_from: int | None = None
    year_to: int | None = None
    venue_filter: str = ""


@dataclass(frozen=True)
class PaperSearchOutput:
    papers: list[PaperRef] = field(default_factory=list)
    provider: str = ""         # which search provider was used
    query_used: str = ""       # actual query after expansion


@dataclass(frozen=True)
class PaperIngestInput:
    source: str                # arxiv_id, doi, pdf_path, or URL
    topic_id: int | None = None
    relevance: str = "medium"  # high, medium, low


@dataclass(frozen=True)
class PaperIngestOutput:
    paper_id: int
    title: str
    status: str                # "new" or "existing"
    merged_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SummaryOutput:
    paper_id: int
    summary: str
    focus: str = ""
    confidence: float = 0.0
    model_used: str = ""


@dataclass(frozen=True)
class Claim:
    """An extracted research claim with evidence linkage."""

    claim_id: str              # deterministic hash of content
    content: str
    paper_ids: list[int] = field(default_factory=list)
    evidence_type: str = ""    # empirical, theoretical, survey
    confidence: float = 0.0
    source_section: str = ""

    def __post_init__(self):
        if not self.claim_id:
            h = hashlib.sha256(self.content.encode()).hexdigest()[:12]
            object.__setattr__(self, "claim_id", f"claim_{h}")


@dataclass(frozen=True)
class ClaimExtractInput:
    paper_ids: list[int]
    topic_id: int
    focus: str = ""            # optional focus area


@dataclass(frozen=True)
class ClaimExtractOutput:
    claims: list[Claim] = field(default_factory=list)
    papers_processed: int = 0


@dataclass(frozen=True)
class EvidenceLink:
    """Link between a claim and its supporting evidence."""

    claim_id: str
    source_type: str           # "paper", "experiment", "dataset"
    source_id: str             # paper_id, experiment name, etc.
    strength: str = "moderate" # strong, moderate, weak
    notes: str = ""


@dataclass(frozen=True)
class EvidenceLinkInput:
    claim_id: str
    source_type: str
    source_id: str
    strength: str = "moderate"
    notes: str = ""


@dataclass(frozen=True)
class EvidenceLinkOutput:
    link: EvidenceLink
    created: bool = True


@dataclass(frozen=True)
class Gap:
    """A detected research gap."""

    gap_id: str
    description: str
    gap_type: str = ""         # methodology, data, theory, application
    severity: str = "medium"   # high, medium, low
    related_paper_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class GapDetectInput:
    topic_id: int
    focus: str = ""


@dataclass(frozen=True)
class GapDetectOutput:
    gaps: list[Gap] = field(default_factory=list)
    papers_analyzed: int = 0


@dataclass(frozen=True)
class Baseline:
    """An identified baseline method/system for comparison."""

    name: str
    paper_ids: list[int] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class BaselineIdentifyInput:
    topic_id: int
    focus: str = ""


@dataclass(frozen=True)
class BaselineIdentifyOutput:
    baselines: list[Baseline] = field(default_factory=list)


@dataclass(frozen=True)
class DraftText:
    """A drafted section of text with citation tracking."""

    section: str               # introduction, related_work, method, etc.
    content: str
    citations_used: list[int] = field(default_factory=list)  # paper_ids
    evidence_ids: list[str] = field(default_factory=list)     # claim_ids
    word_count: int = 0


@dataclass(frozen=True)
class SectionDraftInput:
    section: str
    topic_id: int
    evidence_ids: list[str] = field(default_factory=list)
    outline: str = ""
    max_words: int = 2000


@dataclass(frozen=True)
class SectionDraftOutput:
    draft: DraftText | None = None


@dataclass(frozen=True)
class ConsistencyIssue:
    """An issue found during consistency checking."""

    issue_type: str            # contradiction, missing_citation, logic_gap, style
    severity: str              # high, medium, low
    location: str              # section name or "cross-section"
    description: str
    suggestion: str = ""


@dataclass(frozen=True)
class ConsistencyCheckInput:
    topic_id: int
    sections: list[str] = field(default_factory=list)  # empty = check all


@dataclass(frozen=True)
class ConsistencyCheckOutput:
    issues: list[ConsistencyIssue] = field(default_factory=list)
    sections_checked: list[str] = field(default_factory=list)


# ─── Primitive Result Envelope ──────────────────────────────────────

@dataclass(frozen=True)
class PrimitiveResult:
    """Standard envelope wrapping every primitive execution result."""

    primitive: str             # primitive name
    success: bool
    output: Any                # one of the *Output dataclasses above
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    backend: str = ""          # "claude_code" or "research_harness"
    model_used: str = ""
    cost_usd: float = 0.0

    @property
    def duration_seconds(self) -> float:
        if not self.started_at or not self.finished_at:
            return 0.0
        t0 = datetime.fromisoformat(self.started_at)
        t1 = datetime.fromisoformat(self.finished_at)
        return (t1 - t0).total_seconds()

    def input_hash(self, input_data: Any) -> str:
        """SHA256 of JSON-serialized input for provenance."""
        raw = json.dumps(input_data, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def output_hash(self) -> str:
        """SHA256 of JSON-serialized output for provenance."""
        raw = json.dumps(self.output, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

---

## Primitive Registry

### 文件: `packages/research_harness/research_harness/primitives/registry.py`

```python
"""Primitive registry — maps primitive names to specs and implementations."""

from __future__ import annotations

from typing import Callable, Any

from .types import PrimitiveCategory, PrimitiveSpec


# ─── Registry ───────────────────────────────────────────────────────

PRIMITIVE_REGISTRY: dict[str, PrimitiveSpec] = {}

# Decorator for registering primitive implementations
_IMPLEMENTATIONS: dict[str, Callable[..., Any]] = {}


def register_primitive(spec: PrimitiveSpec):
    """Register a primitive spec. Use as decorator on implementation function."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        PRIMITIVE_REGISTRY[spec.name] = spec
        _IMPLEMENTATIONS[spec.name] = fn
        return fn
    return decorator


def get_primitive_spec(name: str) -> PrimitiveSpec | None:
    return PRIMITIVE_REGISTRY.get(name)


def get_primitive_impl(name: str) -> Callable[..., Any] | None:
    return _IMPLEMENTATIONS.get(name)


def list_primitives() -> list[PrimitiveSpec]:
    return list(PRIMITIVE_REGISTRY.values())


def list_by_category(category: PrimitiveCategory) -> list[PrimitiveSpec]:
    return [s for s in PRIMITIVE_REGISTRY.values() if s.category == category]


# ─── Built-in Primitive Specs ───────────────────────────────────────

PAPER_SEARCH_SPEC = PrimitiveSpec(
    name="paper_search",
    category=PrimitiveCategory.RETRIEVAL,
    description="Search for papers by query across configured providers",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "topic_id": {"type": "integer"},
            "max_results": {"type": "integer", "default": 20},
            "year_from": {"type": "integer"},
            "year_to": {"type": "integer"},
            "venue_filter": {"type": "string"},
        },
        "required": ["query"],
    },
    output_type="PaperSearchOutput",
    requires_llm=False,
    idempotent=True,
)

PAPER_INGEST_SPEC = PrimitiveSpec(
    name="paper_ingest",
    category=PrimitiveCategory.RETRIEVAL,
    description="Ingest a paper into the pool by arxiv_id, doi, or pdf_path",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "topic_id": {"type": "integer"},
            "relevance": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["source"],
    },
    output_type="PaperIngestOutput",
    requires_llm=False,
    idempotent=True,
)

PAPER_SUMMARIZE_SPEC = PrimitiveSpec(
    name="paper_summarize",
    category=PrimitiveCategory.COMPREHENSION,
    description="Generate a focused summary of a paper",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["paper_id"],
    },
    output_type="SummaryOutput",
    requires_llm=True,
)

CLAIM_EXTRACT_SPEC = PrimitiveSpec(
    name="claim_extract",
    category=PrimitiveCategory.EXTRACTION,
    description="Extract research claims from papers within a topic",
    input_schema={
        "type": "object",
        "properties": {
            "paper_ids": {"type": "array", "items": {"type": "integer"}},
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["paper_ids", "topic_id"],
    },
    output_type="ClaimExtractOutput",
    requires_llm=True,
)

EVIDENCE_LINK_SPEC = PrimitiveSpec(
    name="evidence_link",
    category=PrimitiveCategory.EXTRACTION,
    description="Link a claim to supporting evidence",
    input_schema={
        "type": "object",
        "properties": {
            "claim_id": {"type": "string"},
            "source_type": {"type": "string"},
            "source_id": {"type": "string"},
            "strength": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["claim_id", "source_type", "source_id"],
    },
    output_type="EvidenceLinkOutput",
    requires_llm=False,
    idempotent=True,
)

GAP_DETECT_SPEC = PrimitiveSpec(
    name="gap_detect",
    category=PrimitiveCategory.ANALYSIS,
    description="Detect research gaps in a topic's literature",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["topic_id"],
    },
    output_type="GapDetectOutput",
    requires_llm=True,
)

BASELINE_IDENTIFY_SPEC = PrimitiveSpec(
    name="baseline_identify",
    category=PrimitiveCategory.EXTRACTION,
    description="Identify baseline methods for comparison in a topic",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["topic_id"],
    },
    output_type="BaselineIdentifyOutput",
    requires_llm=True,
)

SECTION_DRAFT_SPEC = PrimitiveSpec(
    name="section_draft",
    category=PrimitiveCategory.GENERATION,
    description="Draft a paper section using linked evidence",
    input_schema={
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "topic_id": {"type": "integer"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "outline": {"type": "string"},
            "max_words": {"type": "integer", "default": 2000},
        },
        "required": ["section", "topic_id"],
    },
    output_type="SectionDraftOutput",
    requires_llm=True,
)

CONSISTENCY_CHECK_SPEC = PrimitiveSpec(
    name="consistency_check",
    category=PrimitiveCategory.VERIFICATION,
    description="Check consistency across drafted sections",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "sections": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["topic_id"],
    },
    output_type="ConsistencyCheckOutput",
    requires_llm=True,
)
```

---

## Primitive 实现（骨架）

### 文件: `packages/research_harness/research_harness/primitives/impls.py`

Phase 1 只需要实现 `paper_search` 和 `paper_ingest`（不依赖 LLM 的 primitives）。LLM-dependent primitives 在 Phase 2 通过 ExecutionBackend 委派。

```python
"""Built-in primitive implementations — non-LLM operations only in Phase 1."""

from __future__ import annotations

from .registry import register_primitive, PAPER_SEARCH_SPEC, PAPER_INGEST_SPEC
from .types import (
    PaperSearchInput, PaperSearchOutput, PaperRef,
    PaperIngestInput, PaperIngestOutput,
)


@register_primitive(PAPER_SEARCH_SPEC)
def paper_search(*, db, query: str, topic_id: int | None = None,
                 max_results: int = 20, **kwargs) -> PaperSearchOutput:
    """Search local paper pool. External search (arxiv/s2) is via ExecutionBackend."""
    conn = db.connect()
    sql = "SELECT id, title, authors, year, venue, doi, arxiv_id, s2_id FROM papers"
    params: list = []

    if topic_id is not None:
        sql += """
            WHERE id IN (SELECT paper_id FROM paper_topics WHERE topic_id = ?)
        """
        params.append(topic_id)

    rows = conn.execute(sql, params).fetchall()

    # Simple keyword match for local search
    query_lower = query.lower()
    tokens = query_lower.split()
    results = []
    for row in rows:
        title = (row[1] or "").lower()
        score = sum(1 for t in tokens if t in title) / max(len(tokens), 1)
        if score > 0:
            results.append(PaperRef(
                title=row[1] or "",
                authors=_parse_authors(row[2]),
                year=row[3],
                venue=row[4] or "",
                doi=row[5] or "",
                arxiv_id=row[6] or "",
                s2_id=row[7] or "",
                relevance_score=score,
            ))

    results.sort(key=lambda r: r.relevance_score, reverse=True)
    return PaperSearchOutput(
        papers=results[:max_results],
        provider="local",
        query_used=query,
    )


@register_primitive(PAPER_INGEST_SPEC)
def paper_ingest(*, db, source: str, topic_id: int | None = None,
                 relevance: str = "medium", **kwargs) -> PaperIngestOutput:
    """Ingest paper into pool. Delegates to PaperPool for dedup logic."""
    from ..core.paper_pool import PaperPool
    from ..storage.models import Paper

    pool = PaperPool(db)

    # Determine source type
    paper_kwargs: dict = {}
    if source.startswith("10."):  # DOI
        paper_kwargs["doi"] = source
    elif "/" not in source and len(source) < 20:  # arxiv-like
        paper_kwargs["arxiv_id"] = source
    else:
        paper_kwargs["title"] = source

    paper = Paper(id=0, title=paper_kwargs.get("title", ""), **{
        k: v for k, v in paper_kwargs.items() if k != "title"
    })
    result = pool.ingest(paper, topic_id=topic_id, relevance=relevance)

    return PaperIngestOutput(
        paper_id=result["paper_id"],
        title=result.get("title", ""),
        status=result.get("status", "new"),
        merged_fields=result.get("merged_fields", []),
    )


def _parse_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        import json
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [a.strip() for a in raw.split(",") if a.strip()]
```

---

## 包初始化

### 文件: `packages/research_harness/research_harness/primitives/__init__.py`

```python
"""Research primitives — typed operations for research workflows."""

from .types import (
    PrimitiveCategory,
    PrimitiveSpec,
    PrimitiveResult,
    PaperRef,
    PaperSearchInput, PaperSearchOutput,
    PaperIngestInput, PaperIngestOutput,
    SummaryOutput,
    Claim, ClaimExtractInput, ClaimExtractOutput,
    EvidenceLink, EvidenceLinkInput, EvidenceLinkOutput,
    Gap, GapDetectInput, GapDetectOutput,
    Baseline, BaselineIdentifyInput, BaselineIdentifyOutput,
    DraftText, SectionDraftInput, SectionDraftOutput,
    ConsistencyIssue, ConsistencyCheckInput, ConsistencyCheckOutput,
)
from .registry import (
    PRIMITIVE_REGISTRY,
    get_primitive_spec,
    get_primitive_impl,
    list_primitives,
    list_by_category,
)

# Import implementations to trigger registration
from . import impls as _impls  # noqa: F401

__all__ = [
    "PrimitiveCategory", "PrimitiveSpec", "PrimitiveResult",
    "PaperRef",
    "PaperSearchInput", "PaperSearchOutput",
    "PaperIngestInput", "PaperIngestOutput",
    "SummaryOutput",
    "Claim", "ClaimExtractInput", "ClaimExtractOutput",
    "EvidenceLink", "EvidenceLinkInput", "EvidenceLinkOutput",
    "Gap", "GapDetectInput", "GapDetectOutput",
    "Baseline", "BaselineIdentifyInput", "BaselineIdentifyOutput",
    "DraftText", "SectionDraftInput", "SectionDraftOutput",
    "ConsistencyIssue", "ConsistencyCheckInput", "ConsistencyCheckOutput",
    "PRIMITIVE_REGISTRY", "get_primitive_spec", "get_primitive_impl",
    "list_primitives", "list_by_category",
]
```

---

## 测试要求

### 文件: `packages/research_harness/tests/test_primitives.py`

Codex 需要实现以下测试：

```python
"""Tests for research primitives."""

# 1. test_primitive_registry_has_all_specs
#    - 验证 PRIMITIVE_REGISTRY 包含 9 个 primitive
#    - 验证每个 spec 有 name, category, description, input_schema, output_type

# 2. test_list_by_category
#    - RETRIEVAL 类别包含 paper_search, paper_ingest
#    - EXTRACTION 类别包含 claim_extract, evidence_link, baseline_identify
#    - ANALYSIS 包含 gap_detect
#    - GENERATION 包含 section_draft
#    - VERIFICATION 包含 consistency_check
#    - COMPREHENSION 包含 paper_summarize

# 3. test_paper_search_local
#    - 插入 3 篇 paper，搜索关键词，验证返回匹配结果
#    - 验证 PaperSearchOutput 字段

# 4. test_paper_search_with_topic_filter
#    - 搜索时限定 topic_id，只返回该 topic 下的 papers

# 5. test_paper_ingest_new
#    - ingest 新 paper，验证 status="new"

# 6. test_paper_ingest_duplicate
#    - ingest 已有 doi 的 paper，验证 status="existing"

# 7. test_primitive_result_hashing
#    - 验证 PrimitiveResult.input_hash() 和 output_hash() 返回一致的 hash

# 8. test_claim_id_generation
#    - 验证 Claim 自动生成 claim_id (SHA256 of content)

# 9. test_frozen_dataclasses
#    - 验证所有 output types 是 frozen (不可变)
```

---

## Codex 实现注意事项

1. **`impls.py` 中的 `paper_ingest` 需要适配现有 `PaperPool.ingest()` 的返回格式** — 目前 PaperPool.ingest 返回 paper_id (int)，需要包装成 dict 或修改 PaperPool
2. **不要在 Phase 1 实现 LLM-dependent primitives** — 只注册 spec，不提供实现。这些在 Phase 2 由 ExecutionBackend 的具体后端实现
3. **所有 dataclass 必须 frozen=True** — 不可变是核心设计原则
4. **input_schema 使用 JSON Schema 格式** — 与 MCP tool definition 兼容，为未来 MCP 集成做准备
