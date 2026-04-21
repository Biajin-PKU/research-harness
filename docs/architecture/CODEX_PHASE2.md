# CODEX Phase 2: Kimi-Backed ResearchHarnessBackend

## Objective

Implement a working `ResearchHarnessBackend` that routes LLM primitives through Kimi
(via the existing `LLMClient` in `paperindex/llm/client.py`), enabling end-to-end
research workflow execution. Non-LLM primitives delegate to `LocalBackend`.

## Critical: Read Before Coding

1. Run `pytest packages/ -q --tb=short` — must show `125 passed`. Stop if not.
2. Read these files completely before writing any code:
   - `packages/paperindex/paperindex/llm/client.py` (existing LLM client — REUSE this)
   - `packages/research_harness/research_harness/execution/backend.py` (Protocol)
   - `packages/research_harness/research_harness/execution/local.py` (reference impl)
   - `packages/research_harness/research_harness/execution/harness.py` (stub to replace)
   - `packages/research_harness/research_harness/execution/factory.py` (registration)
   - `packages/research_harness/research_harness/primitives/types.py` (all I/O types)
   - `packages/research_harness/research_harness/primitives/registry.py` (9 specs)
   - `packages/research_harness/research_harness/primitives/impls.py` (existing local impls)

## Architecture Constraint

- DO NOT create a new LLM client. Import and use `paperindex.llm.client.LLMClient` and `resolve_llm_config`.
- DO NOT modify any existing file except `harness.py`, `factory.py`, and `__init__.py` in the execution package.
- All new code goes in NEW files under `packages/research_harness/research_harness/execution/`.

## Step-by-Step Implementation

### Step 1: Create `execution/prompts.py`

Prompt templates for each LLM primitive. Each function takes typed input + context,
returns a single prompt string.

```python
"""Prompt templates for LLM-backed research primitives."""
from __future__ import annotations
from typing import Any


def paper_summarize_prompt(paper_title: str, paper_text: str, focus: str = "") -> str:
    focus_line = f"\nFocus area: {focus}" if focus else ""
    return f"""You are a research paper analyst.

Summarize the following paper concisely (200-300 words).{focus_line}

Paper: {paper_title}

Text:
{paper_text[:8000]}

Return your response as JSON:
{{"summary": "<your summary>", "confidence": <0.0-1.0>}}"""


def claim_extract_prompt(papers_text: str, focus: str = "") -> str:
    focus_line = f"\nFocus on: {focus}" if focus else ""
    return f"""You are a research claim extractor.{focus_line}

Extract distinct research claims from the following papers.
For each claim, assess confidence (0.0-1.0) and identify the evidence type
(empirical, theoretical, methodological, survey-based).

Papers:
{papers_text[:12000]}

Return JSON:
{{"claims": [{{"content": "<claim text>", "evidence_type": "<type>", "confidence": <float>}}]}}"""


def gap_detect_prompt(literature_summary: str, focus: str = "") -> str:
    focus_line = f"\nFocus on: {focus}" if focus else ""
    return f"""You are a research gap analyst.{focus_line}

Based on the following literature summary, identify research gaps.
Classify each gap as: methodological, empirical, theoretical, or application.
Rate severity: low, medium, high.

Literature:
{literature_summary[:10000]}

Return JSON:
{{"gaps": [{{"description": "<gap>", "gap_type": "<type>", "severity": "<level>"}}]}}"""


def baseline_identify_prompt(literature_summary: str, focus: str = "") -> str:
    focus_line = f"\nFocus on: {focus}" if focus else ""
    return f"""You are a research baseline analyst.{focus_line}

Identify the key baseline methods/systems that papers in this area compare against.
For each baseline, note which metrics are commonly reported.

Literature:
{literature_summary[:10000]}

Return JSON:
{{"baselines": [{{"name": "<method name>", "metrics": {{"<metric>": "<typical value or range>"}}, "notes": "<why this is a common baseline>"}}]}}"""


def section_draft_prompt(
    section: str, outline: str, evidence_text: str, max_words: int = 2000
) -> str:
    return f"""You are an academic writer drafting a paper section.

Section: {section}
{"Outline: " + outline if outline else ""}
Maximum words: {max_words}

Evidence and sources:
{evidence_text[:10000]}

Write the section in academic style. Use [N] citation markers where you reference evidence.

Return JSON:
{{"content": "<section text>", "citations_used": [<list of evidence indices referenced>], "word_count": <int>}}"""


def consistency_check_prompt(sections_text: str) -> str:
    return f"""You are a paper consistency reviewer.

Review the following paper sections for:
1. Contradictory claims between sections
2. Undefined terms used before introduction
3. Citation gaps (claims without evidence)
4. Logical flow issues
5. Notation inconsistencies

Sections:
{sections_text[:15000]}

Return JSON:
{{"issues": [{{"issue_type": "<type>", "severity": "<low|medium|high>", "location": "<which section>", "description": "<what's wrong>", "suggestion": "<how to fix>"}}]}}"""
```

### Step 2: Create `execution/llm_primitives.py`

Implementation of all 6 LLM primitives. Each function:
- Takes `db: Database` and typed kwargs
- Builds prompt via `prompts.py`
- Calls `LLMClient.chat()`
- Parses JSON response into the correct output dataclass
- Handles parse failures gracefully (returns partial result, never crashes)

```python
"""LLM-backed primitive implementations using Kimi/Anthropic/OpenAI."""
from __future__ import annotations

import json
import logging
from typing import Any

from paperindex.llm.client import LLMClient, resolve_llm_config

from ..primitives.types import (
    Baseline, BaselineIdentifyOutput,
    Claim, ClaimExtractOutput,
    ConsistencyCheckOutput, ConsistencyIssue,
    DraftText, SectionDraftOutput,
    Gap, GapDetectOutput,
    SummaryOutput,
)
from ..storage.db import Database
from . import prompts

logger = logging.getLogger(__name__)


def _get_client(model_override: str | None = None) -> LLMClient:
    """Create LLMClient from environment. Caller can override model."""
    config = resolve_llm_config(
        {"model": model_override} if model_override else None
    )
    return LLMClient(config)


def _parse_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from LLM response."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown code block
    for marker in ("```json", "```"):
        if marker in text:
            start = text.index(marker) + len(marker)
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass
    return {}


def _get_paper_text(db: Database, paper_id: int) -> tuple[str, str]:
    """Retrieve paper title and best available text from DB."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT title, abstract FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            return (f"Paper #{paper_id}", "")
        title = row["title"] or f"Paper #{paper_id}"
        text = row["abstract"] or ""
        # Try to get more text from notes or sections if abstract is short
        if len(text) < 200:
            note_row = conn.execute(
                "SELECT content FROM paper_notes WHERE paper_id = ? ORDER BY id LIMIT 1",
                (paper_id,),
            ).fetchone()
            if note_row and note_row["content"]:
                text = text + "\n" + note_row["content"]
        return (title, text)
    finally:
        conn.close()


def _get_topic_literature_summary(db: Database, topic_id: int) -> str:
    """Build a literature summary from papers in a topic."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT p.title, p.abstract, p.year, p.venue
               FROM papers p
               JOIN paper_topics pt ON p.id = pt.paper_id
               WHERE pt.topic_id = ?
               ORDER BY p.year DESC""",
            (topic_id,),
        ).fetchall()
        parts = []
        for row in rows:
            entry = f"- {row['title'] or 'Untitled'}"
            if row["year"]:
                entry += f" ({row['year']})"
            if row["venue"]:
                entry += f" [{row['venue']}]"
            if row["abstract"]:
                entry += f"\n  {row['abstract'][:300]}"
            parts.append(entry)
        return "\n".join(parts) if parts else "(no papers in topic)"
    finally:
        conn.close()


def paper_summarize(
    *, db: Database, paper_id: int, focus: str = "",
    _model: str | None = None, **_: Any,
) -> SummaryOutput:
    title, text = _get_paper_text(db, paper_id)
    if not text:
        return SummaryOutput(
            paper_id=paper_id, summary="(no text available for summarization)",
            focus=focus, confidence=0.0, model_used="none",
        )
    client = _get_client(_model)
    prompt = prompts.paper_summarize_prompt(title, text, focus)
    raw = client.chat(prompt)
    parsed = _parse_json(raw)
    return SummaryOutput(
        paper_id=paper_id,
        summary=parsed.get("summary", raw[:2000]),
        focus=focus,
        confidence=float(parsed.get("confidence", 0.5)),
        model_used=client.model,
    )


def claim_extract(
    *, db: Database, paper_ids: list[int], topic_id: int, focus: str = "",
    _model: str | None = None, **_: Any,
) -> ClaimExtractOutput:
    texts = []
    for pid in paper_ids:
        title, text = _get_paper_text(db, pid)
        texts.append(f"[Paper {pid}] {title}\n{text}")
    combined = "\n\n".join(texts)
    client = _get_client(_model)
    prompt = prompts.claim_extract_prompt(combined, focus)
    raw = client.chat(prompt)
    parsed = _parse_json(raw)
    claims = []
    for item in parsed.get("claims", []):
        if isinstance(item, dict) and item.get("content"):
            claims.append(Claim(
                claim_id="",  # auto-generated by __post_init__
                content=item["content"],
                paper_ids=paper_ids,
                evidence_type=item.get("evidence_type", ""),
                confidence=float(item.get("confidence", 0.5)),
            ))
    return ClaimExtractOutput(claims=claims, papers_processed=len(paper_ids))


def gap_detect(
    *, db: Database, topic_id: int, focus: str = "",
    _model: str | None = None, **_: Any,
) -> GapDetectOutput:
    summary = _get_topic_literature_summary(db, topic_id)
    client = _get_client(_model)
    prompt = prompts.gap_detect_prompt(summary, focus)
    raw = client.chat(prompt)
    parsed = _parse_json(raw)
    gaps = []
    for item in parsed.get("gaps", []):
        if isinstance(item, dict) and item.get("description"):
            gaps.append(Gap(
                gap_id="",
                description=item["description"],
                gap_type=item.get("gap_type", ""),
                severity=item.get("severity", "medium"),
            ))
    return GapDetectOutput(gaps=gaps, papers_analyzed=summary.count("- "))


def baseline_identify(
    *, db: Database, topic_id: int, focus: str = "",
    _model: str | None = None, **_: Any,
) -> BaselineIdentifyOutput:
    summary = _get_topic_literature_summary(db, topic_id)
    client = _get_client(_model)
    prompt = prompts.baseline_identify_prompt(summary, focus)
    raw = client.chat(prompt)
    parsed = _parse_json(raw)
    baselines = []
    for item in parsed.get("baselines", []):
        if isinstance(item, dict) and item.get("name"):
            baselines.append(Baseline(
                name=item["name"],
                metrics=item.get("metrics", {}),
                notes=item.get("notes", ""),
            ))
    return BaselineIdentifyOutput(baselines=baselines)


def section_draft(
    *, db: Database, section: str, topic_id: int,
    evidence_ids: list[str] | None = None, outline: str = "",
    max_words: int = 2000, _model: str | None = None, **_: Any,
) -> SectionDraftOutput:
    summary = _get_topic_literature_summary(db, topic_id)
    client = _get_client(_model)
    prompt = prompts.section_draft_prompt(section, outline, summary, max_words)
    raw = client.chat(prompt)
    parsed = _parse_json(raw)
    content = parsed.get("content", raw[:max_words * 6])
    return SectionDraftOutput(draft=DraftText(
        section=section,
        content=content,
        citations_used=parsed.get("citations_used", []),
        evidence_ids=evidence_ids or [],
        word_count=parsed.get("word_count", len(content.split())),
    ))


def consistency_check(
    *, db: Database, topic_id: int, sections: list[str] | None = None,
    _model: str | None = None, **_: Any,
) -> ConsistencyCheckOutput:
    # For now, use literature summary as proxy for sections content
    summary = _get_topic_literature_summary(db, topic_id)
    sections_text = f"Topic literature (topic_id={topic_id}):\n{summary}"
    client = _get_client(_model)
    prompt = prompts.consistency_check_prompt(sections_text)
    raw = client.chat(prompt)
    parsed = _parse_json(raw)
    issues = []
    for item in parsed.get("issues", []):
        if isinstance(item, dict) and item.get("description"):
            issues.append(ConsistencyIssue(
                issue_type=item.get("issue_type", "unknown"),
                severity=item.get("severity", "medium"),
                location=item.get("location", ""),
                description=item["description"],
                suggestion=item.get("suggestion", ""),
            ))
    return ConsistencyCheckOutput(
        issues=issues,
        sections_checked=sections or [],
    )
```

### Step 3: Rewrite `execution/harness.py`

Replace the stub with a working implementation:

```python
"""ResearchHarnessBackend — LLM-powered research primitive execution."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from paperindex.llm.client import resolve_llm_config

from ..primitives.registry import get_primitive_spec, list_primitives
from ..primitives.types import PrimitiveResult
from ..storage.db import Database
from .backend import BackendInfo
from . import llm_primitives


# Maps primitive name -> implementation function in llm_primitives
_LLM_DISPATCH: dict[str, Any] = {
    "paper_summarize": llm_primitives.paper_summarize,
    "claim_extract": llm_primitives.claim_extract,
    "gap_detect": llm_primitives.gap_detect,
    "baseline_identify": llm_primitives.baseline_identify,
    "section_draft": llm_primitives.section_draft,
    "consistency_check": llm_primitives.consistency_check,
}

# Non-LLM primitives delegate to local implementations
_LOCAL_DISPATCH: dict[str, Any] = {}


def _load_local_dispatch() -> None:
    """Lazy-load local primitive implementations."""
    if _LOCAL_DISPATCH:
        return
    from ..primitives.registry import get_primitive_impl
    for name in ("paper_search", "paper_ingest", "evidence_link"):
        impl = get_primitive_impl(name)
        if impl is not None:
            _LOCAL_DISPATCH[name] = impl


class ResearchHarnessBackend:
    """Execution backend that routes LLM primitives through Kimi/Anthropic/OpenAI."""

    def __init__(self, db: Database | None = None, **_: Any) -> None:
        self._db = db
        llm_config = resolve_llm_config()
        self._provider = llm_config.provider
        self._model = llm_config.model
        self._has_api_key = bool(llm_config.api_key)

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        spec = get_primitive_spec(primitive)
        if spec is None:
            return PrimitiveResult(
                primitive=primitive, success=False, output=None,
                error=f"Unknown primitive: {primitive}",
                backend="research_harness",
            )

        started = datetime.now(timezone.utc).isoformat()

        # Route: LLM primitives go through llm_primitives, others through local
        if spec.requires_llm:
            if primitive not in _LLM_DISPATCH:
                return PrimitiveResult(
                    primitive=primitive, success=False, output=None,
                    error=f"LLM primitive '{primitive}' not implemented yet",
                    backend="research_harness", started_at=started,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
            if not self._has_api_key:
                return PrimitiveResult(
                    primitive=primitive, success=False, output=None,
                    error="No API key configured. Set KIMI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY.",
                    backend="research_harness", started_at=started,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
            impl = _LLM_DISPATCH[primitive]
        else:
            _load_local_dispatch()
            impl = _LOCAL_DISPATCH.get(primitive)
            if impl is None:
                return PrimitiveResult(
                    primitive=primitive, success=False, output=None,
                    error=f"No local implementation for: {primitive}",
                    backend="research_harness", started_at=started,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )

        try:
            output = impl(db=self._db, **kwargs)
            finished = datetime.now(timezone.utc).isoformat()
            model_used = "none"
            if hasattr(output, "model_used") and output.model_used:
                model_used = output.model_used
            elif spec.requires_llm:
                model_used = self._model
            return PrimitiveResult(
                primitive=primitive, success=True, output=output,
                started_at=started, finished_at=finished,
                backend="research_harness", model_used=model_used,
            )
        except Exception as exc:
            finished = datetime.now(timezone.utc).isoformat()
            return PrimitiveResult(
                primitive=primitive, success=False, output=None,
                error=str(exc), started_at=started, finished_at=finished,
                backend="research_harness", model_used=self._model,
            )

    def get_info(self) -> BackendInfo:
        supported = list(_LLM_DISPATCH.keys())
        _load_local_dispatch()
        supported.extend(_LOCAL_DISPATCH.keys())
        return BackendInfo(
            name="research_harness",
            supported_primitives=sorted(supported),
            requires_api_key=True,
            description=f"LLM-powered research primitives via {self._provider}/{self._model}",
        )

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        spec = get_primitive_spec(primitive)
        if spec is None or not spec.requires_llm:
            return 0.0
        # Rough estimate based on Kimi pricing (~$0.001/1k tokens)
        return 0.005  # ~5k tokens average per primitive call

    def supports(self, primitive: str) -> bool:
        if primitive in _LLM_DISPATCH:
            return True
        _load_local_dispatch()
        return primitive in _LOCAL_DISPATCH
```

### Step 4: Update `execution/factory.py`

The factory's `create_backend` passes `**kwargs` to constructors. Ensure
`ResearchHarnessBackend` receives `db=` when created. No change needed to factory.py
itself — the caller (cli.py) already passes `db=` via `**kwargs`.

Verify this by reading `cli.py` to confirm `db` is passed. If NOT, add `db=` to the
`create_backend` call site in `cli.py`.

### Step 5: Update `execution/__init__.py`

Add exports:
```python
from .harness import ResearchHarnessBackend
```
(This should already be exported. Verify.)

### Step 6: Tests — `tests/test_harness_backend.py` (NEW FILE)

Write tests that work WITHOUT a real API key (mock the LLMClient):

```python
"""Tests for ResearchHarnessBackend with mocked LLM calls."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from research_harness.execution.harness import ResearchHarnessBackend
from research_harness.primitives.types import PrimitiveCategory


@pytest.fixture
def harness(db):
    """Create harness backend with mocked API key."""
    with patch("research_harness.execution.harness.resolve_llm_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(
            provider="kimi", model="kimi-test", api_key="fake-key"
        )
        backend = ResearchHarnessBackend(db=db)
    return backend


class TestHarnessInfo:
    def test_info_name(self, harness):
        info = harness.get_info()
        assert info.name == "research_harness"

    def test_supports_llm_primitives(self, harness):
        assert harness.supports("paper_summarize")
        assert harness.supports("claim_extract")
        assert harness.supports("gap_detect")
        assert harness.supports("baseline_identify")
        assert harness.supports("section_draft")
        assert harness.supports("consistency_check")

    def test_supports_local_primitives(self, harness):
        assert harness.supports("paper_search")
        assert harness.supports("paper_ingest")

    def test_cost_estimate(self, harness):
        assert harness.estimate_cost("paper_summarize") > 0
        assert harness.estimate_cost("paper_search") == 0.0


class TestHarnessLocalExecution:
    def test_paper_search_via_harness(self, harness, db):
        """Non-LLM primitives should work without API key."""
        result = harness.execute("paper_search", query="test", db=db)
        assert result.success
        assert result.backend == "research_harness"

    def test_unknown_primitive(self, harness):
        result = harness.execute("nonexistent_primitive")
        assert not result.success
        assert "Unknown" in result.error


class TestHarnessLLMExecution:
    @patch("research_harness.execution.llm_primitives._get_client")
    def test_paper_summarize(self, mock_get_client, harness, db):
        # Insert a paper first
        conn = db.connect()
        conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            ("Test Paper", "This paper studies attention mechanisms in transformers."),
        )
        conn.commit()
        paper_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "summary": "This paper studies attention.",
            "confidence": 0.85,
        })
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute("paper_summarize", paper_id=paper_id, db=db)
        assert result.success
        assert result.backend == "research_harness"
        assert "attention" in result.output.summary.lower()
        assert result.output.confidence == 0.85

    @patch("research_harness.execution.llm_primitives._get_client")
    def test_claim_extract(self, mock_get_client, harness, db):
        conn = db.connect()
        conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            ("Paper A", "We show that method X outperforms Y by 10%."),
        )
        conn.commit()
        paper_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # Create a topic and link
        conn.execute("INSERT INTO topics (name) VALUES (?)", ("test-topic",))
        conn.commit()
        topic_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
            (paper_id, topic_id),
        )
        conn.commit()
        conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "claims": [
                {"content": "Method X outperforms Y by 10%", "evidence_type": "empirical", "confidence": 0.9}
            ]
        })
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute(
            "claim_extract", paper_ids=[paper_id], topic_id=topic_id, db=db
        )
        assert result.success
        assert len(result.output.claims) == 1
        assert "outperforms" in result.output.claims[0].content

    @patch("research_harness.execution.llm_primitives._get_client")
    def test_gap_detect(self, mock_get_client, harness, db):
        conn = db.connect()
        conn.execute("INSERT INTO topics (name) VALUES (?)", ("gaps-topic",))
        conn.commit()
        topic_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "gaps": [
                {"description": "No study on domain X", "gap_type": "empirical", "severity": "high"}
            ]
        })
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute("gap_detect", topic_id=topic_id, db=db)
        assert result.success
        assert len(result.output.gaps) == 1

    def test_no_api_key_error(self, db):
        """Without API key, LLM primitives should fail gracefully."""
        with patch("research_harness.execution.harness.resolve_llm_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                provider="kimi", model="kimi-test", api_key=""
            )
            backend = ResearchHarnessBackend(db=db)
        result = backend.execute("paper_summarize", paper_id=1, db=db)
        assert not result.success
        assert "API key" in result.error

    @patch("research_harness.execution.llm_primitives._get_client")
    def test_llm_error_handled(self, mock_get_client, harness, db):
        """LLM errors should not crash — return failed PrimitiveResult."""
        conn = db.connect()
        conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            ("Err Paper", "Some text."),
        )
        conn.commit()
        paper_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("API timeout")
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute("paper_summarize", paper_id=paper_id, db=db)
        assert not result.success
        assert "timeout" in result.error.lower()

    @patch("research_harness.execution.llm_primitives._get_client")
    def test_malformed_json_handled(self, mock_get_client, harness, db):
        """LLM returning non-JSON should still produce a result."""
        conn = db.connect()
        conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            ("Bad JSON Paper", "Abstract text here."),
        )
        conn.commit()
        paper_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = "This is not JSON, just a plain summary."
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        result = harness.execute("paper_summarize", paper_id=paper_id, db=db)
        assert result.success
        # Should fall back to using raw text as summary
        assert "plain summary" in result.output.summary


class TestHarnessWithTracked:
    @patch("research_harness.execution.llm_primitives._get_client")
    def test_provenance_recorded(self, mock_get_client, harness, db):
        """Verify TrackedBackend works with harness."""
        from research_harness.execution.tracked import TrackedBackend
        from research_harness.provenance.recorder import ProvenanceRecorder

        conn = db.connect()
        conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            ("Tracked Paper", "Some abstract."),
        )
        conn.commit()
        paper_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "summary": "Tracked summary.", "confidence": 0.7,
        })
        mock_client.model = "kimi-test"
        mock_get_client.return_value = mock_client

        recorder = ProvenanceRecorder(db)
        tracked = TrackedBackend(harness, recorder)
        result = tracked.execute("paper_summarize", paper_id=paper_id, db=db)
        assert result.success

        records = recorder.list_records(backend="research_harness")
        assert len(records) == 1
        assert records[0].primitive == "paper_summarize"
```

### Step 7: Integration test — `tests/test_harness_e2e.py` (NEW FILE)

A test that exercises the REAL Kimi API (skipped when `KIMI_API_KEY` is not set):

```python
"""End-to-end test with real Kimi API — skipped without KIMI_API_KEY."""
from __future__ import annotations

import os

import pytest

from research_harness.execution.harness import ResearchHarnessBackend


requires_kimi = pytest.mark.skipif(
    not os.environ.get("KIMI_API_KEY"),
    reason="KIMI_API_KEY not set",
)


@requires_kimi
class TestHarnessE2EKimi:
    def test_paper_summarize_real(self, db):
        """Summarize a paper using real Kimi API."""
        conn = db.connect()
        conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            (
                "Attention Is All You Need",
                "The dominant sequence transduction models are based on complex "
                "recurrent or convolutional neural networks that include an encoder "
                "and a decoder. The best performing models also connect the encoder "
                "and decoder through an attention mechanism. We propose a new simple "
                "network architecture, the Transformer, based solely on attention "
                "mechanisms, dispensing with recurrence and convolutions entirely.",
            ),
        )
        conn.commit()
        paper_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        backend = ResearchHarnessBackend(db=db)
        result = backend.execute("paper_summarize", paper_id=paper_id, db=db)

        assert result.success, f"Failed: {result.error}"
        assert result.backend == "research_harness"
        assert len(result.output.summary) > 50
        assert result.output.model_used != "none"
        print(f"\n[E2E] Model: {result.output.model_used}")
        print(f"[E2E] Summary: {result.output.summary[:200]}")

    def test_claim_extract_real(self, db):
        """Extract claims using real Kimi API."""
        conn = db.connect()
        conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            (
                "BERT: Pre-training of Deep Bidirectional Transformers",
                "We introduce BERT, which obtains new state-of-the-art results "
                "on eleven natural language processing tasks, including pushing "
                "the GLUE score to 80.5%, MultiNLI accuracy to 86.7%, and "
                "SQuAD v1.1 question answering F1 to 93.2%.",
            ),
        )
        conn.commit()
        paper_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO topics (name) VALUES (?)", ("e2e-test",))
        conn.commit()
        topic_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
            (paper_id, topic_id),
        )
        conn.commit()
        conn.close()

        backend = ResearchHarnessBackend(db=db)
        result = backend.execute(
            "claim_extract", paper_ids=[paper_id], topic_id=topic_id, db=db
        )

        assert result.success, f"Failed: {result.error}"
        assert len(result.output.claims) >= 1
        print(f"\n[E2E] Claims extracted: {len(result.output.claims)}")
        for claim in result.output.claims:
            print(f"  - {claim.content[:100]}")
```

### Step 8: Verify

1. `pytest packages/ -q --tb=short` — all existing 125 tests + new tests pass
2. `pytest packages/research_harness/tests/test_harness_backend.py -v` — all harness tests pass
3. If `KIMI_API_KEY` is set: `pytest packages/research_harness/tests/test_harness_e2e.py -v -s` — real API test passes
4. `python -m research_harness.cli backend info --backend research_harness` — shows all 9 supported primitives

### Step 9: Update `session_handoff.md`

Record what was done:
- ResearchHarnessBackend now functional with 6 LLM + 3 local primitives
- Prompt templates in `execution/prompts.py`
- LLM implementations in `execution/llm_primitives.py`
- Mocked tests in `test_harness_backend.py`
- E2E test in `test_harness_e2e.py` (skipped without API key)
- Provider auto-detected from env: KIMI_API_KEY → Kimi, ANTHROPIC_API_KEY → Anthropic, OPENAI_API_KEY → OpenAI

## Safety Rules

1. **Never modify** files outside `packages/research_harness/research_harness/execution/` and `packages/research_harness/tests/` unless explicitly told to above.
2. **Never delete** existing test files.
3. **Run tests after every file creation** — `pytest packages/ -q --tb=short`. Stop and fix if any test fails.
4. **Do not install new packages** — use only stdlib + what's already importable.
5. `harness.py` is the ONLY existing file you rewrite. All other changes are NEW files.
6. Every `PrimitiveResult` must have `backend="research_harness"` — never empty.
7. LLM errors MUST be caught and returned as `PrimitiveResult(success=False)` — never let exceptions propagate.

## File Creation Order

Execute in this exact order, running tests after each:

1. `execution/prompts.py` (new) → run tests
2. `execution/llm_primitives.py` (new) → run tests
3. `execution/harness.py` (rewrite) → run tests
4. `tests/test_harness_backend.py` (new) → run tests (all should pass)
5. `tests/test_harness_e2e.py` (new) → run tests (e2e skipped without key)
6. Update `docs/session_handoff.md`
