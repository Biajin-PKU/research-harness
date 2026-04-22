from __future__ import annotations

from research_harness.execution.local import LocalBackend
from research_harness.execution.tracked import TrackedBackend
from research_harness.primitives.types import PaperSearchOutput, PrimitiveResult
from research_harness.provenance import ProvenanceRecorder


def _result(
    primitive: str = "paper_search",
    success: bool = True,
    backend: str = "local",
    cost_usd: float = 0.0,
    started_at: str = "2026-04-03T00:00:00+00:00",
    finished_at: str = "2026-04-03T00:00:01+00:00",
) -> PrimitiveResult:
    return PrimitiveResult(
        primitive=primitive,
        success=success,
        output=PaperSearchOutput(),
        error="" if success else "boom",
        started_at=started_at,
        finished_at=finished_at,
        backend=backend,
        model_used="none",
        cost_usd=cost_usd,
    )


def test_record_and_retrieve(db) -> None:
    recorder = ProvenanceRecorder(db)
    record_id = recorder.record(_result(), {"query": "attention"}, topic_id=None)

    record = recorder.get(record_id)
    assert record is not None
    assert record.id == record_id
    assert record.primitive == "paper_search"
    assert record.backend == "local"


def test_list_with_filters(db) -> None:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('topic-a')")
        topic_id = int(
            conn.execute("SELECT id FROM topics WHERE name = 'topic-a'").fetchone()[
                "id"
            ]
        )
        conn.commit()
    finally:
        conn.close()

    recorder = ProvenanceRecorder(db)
    recorder.record(
        _result(primitive="paper_search", backend="local"),
        {"query": "a"},
        topic_id=topic_id,
    )
    recorder.record(
        _result(primitive="paper_ingest", backend="local"),
        {"source": "10.1/x"},
        topic_id=None,
    )
    recorder.record(
        _result(primitive="paper_search", backend="claude_code"),
        {"query": "b"},
        topic_id=topic_id,
    )

    assert len(recorder.list_records(topic_id=topic_id)) == 2
    assert len(recorder.list_records(primitive="paper_ingest")) == 1
    assert len(recorder.list_records(backend="claude_code")) == 1


def test_summarize(db) -> None:
    recorder = ProvenanceRecorder(db)
    recorder.record(_result(backend="local", cost_usd=1.25), {"query": "a"})
    recorder.record(
        _result(primitive="paper_ingest", backend="local", cost_usd=0.75),
        {"source": "10.1/x"},
    )
    recorder.record(
        _result(backend="claude_code", success=False, cost_usd=2.0), {"query": "b"}
    )

    summary = recorder.summarize()
    assert summary.total_operations == 3
    assert summary.total_cost_usd == 4.0
    assert summary.operations_by_backend == {"claude_code": 1, "local": 2}
    assert summary.operations_by_primitive == {"paper_ingest": 1, "paper_search": 2}
    assert summary.cost_by_backend == {"claude_code": 2.0, "local": 2.0}
    assert summary.success_rate == 2 / 3


def test_tracked_backend_auto_records(db) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
            (
                "Attention Is All You Need",
                "10.1000/attention",
                "1706.03762",
                "s2-attention",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    backend = TrackedBackend(LocalBackend(db), ProvenanceRecorder(db))
    result = backend.execute("paper_search", query="attention")

    assert result.success is True
    records = ProvenanceRecorder(db).list_records()
    assert len(records) == 1
    assert records[0].primitive == "paper_search"


def test_tracked_backend_provenance_failure_does_not_block(db) -> None:
    class BrokenRecorder:
        def record(self, **kwargs):
            raise RuntimeError("provenance down")

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
            (
                "Attention Is All You Need",
                "10.1000/attention",
                "1706.03762",
                "s2-attention",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    backend = TrackedBackend(LocalBackend(db), BrokenRecorder())
    result = backend.execute("paper_search", query="attention")

    assert result.success is True
    assert result.output.papers[0].title == "Attention Is All You Need"


def test_input_output_hashes_consistent(db) -> None:
    recorder = ProvenanceRecorder(db)
    result = _result()

    hash_a = recorder._hash_dict({"query": "attention"})
    hash_b = recorder._hash_dict({"query": "attention"})
    hash_c = recorder._hash_dict({"query": "transformer"})

    assert hash_a == hash_b
    assert hash_a != hash_c
    assert result.output_hash() == result.output_hash()


def test_parent_chain(db) -> None:
    recorder = ProvenanceRecorder(db)
    parent_id = recorder.record(_result(), {"query": "attention"})
    child_id = recorder.record(
        _result(primitive="paper_ingest"), {"source": "10.1/x"}, parent_id=parent_id
    )

    child = recorder.get(child_id)
    assert child is not None
    assert child.parent_id == parent_id


# ---------------------------------------------------------------------------
# Token usage accounting (migration 028)
# ---------------------------------------------------------------------------


def _result_with_tokens(
    primitive: str,
    backend: str,
    model: str,
    cost_usd: float,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> PrimitiveResult:
    return PrimitiveResult(
        primitive=primitive,
        success=True,
        output=PaperSearchOutput(),
        started_at="2026-04-16T00:00:00+00:00",
        finished_at="2026-04-16T00:00:01+00:00",
        backend=backend,
        model_used=model,
        cost_usd=cost_usd,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def test_record_persists_tokens(db) -> None:
    recorder = ProvenanceRecorder(db)
    record_id = recorder.record(
        _result_with_tokens(
            "paper_summarize", "research_harness", "gpt-5", 0.02, 1500, 320
        ),
        {"paper_id": 1},
    )
    record = recorder.get(record_id)
    assert record is not None
    assert record.prompt_tokens == 1500
    assert record.completion_tokens == 320


def test_record_accepts_null_tokens(db) -> None:
    """Providers without usage (cursor_agent CLI) store NULL, not 0."""
    recorder = ProvenanceRecorder(db)
    record_id = recorder.record(
        _result_with_tokens(
            "paper_summarize", "research_harness", "composer-2-fast", 0.01, None, None
        ),
        {"paper_id": 2},
    )
    record = recorder.get(record_id)
    assert record is not None
    assert record.prompt_tokens is None
    assert record.completion_tokens is None


def test_summarize_aggregates_tokens(db) -> None:
    recorder = ProvenanceRecorder(db)
    recorder.record(
        _result_with_tokens(
            "paper_summarize", "research_harness", "gpt-5", 0.02, 1000, 200
        ),
        {"paper_id": 1},
    )
    recorder.record(
        _result_with_tokens(
            "claim_extract", "research_harness", "gpt-5", 0.03, 2000, 400
        ),
        {"paper_id": 2},
    )
    recorder.record(
        _result_with_tokens(
            "deep_read", "research_harness", "Kimi-K2.5", 0.05, 5000, 800
        ),
        {"paper_id": 3},
    )
    # Mixed record without token usage must not break aggregation.
    recorder.record(
        _result_with_tokens(
            "paper_search", "research_harness", "composer-2-fast", 0.001, None, None
        ),
        {"query": "a"},
    )

    summary = recorder.summarize()
    assert summary.total_prompt_tokens == 8000
    assert summary.total_completion_tokens == 1400
    # Grouped by backend (all four went through the same backend here).
    assert summary.tokens_by_backend["research_harness"]["prompt"] == 8000
    assert summary.tokens_by_backend["research_harness"]["completion"] == 1400
    assert summary.tokens_by_primitive["paper_summarize"] == {
        "prompt": 1000,
        "completion": 200,
    }
    assert summary.tokens_by_primitive["deep_read"] == {
        "prompt": 5000,
        "completion": 800,
    }


def test_token_report_by_agent(db) -> None:
    recorder = ProvenanceRecorder(db)
    # Two agents, several calls, different costs
    recorder.record(
        _result_with_tokens(
            "paper_summarize", "research_harness", "gpt-5", 0.02, 1000, 200
        ),
        {"paper_id": 1},
    )
    recorder.record(
        _result_with_tokens(
            "paper_summarize", "research_harness", "gpt-5", 0.03, 1500, 250
        ),
        {"paper_id": 2},
    )
    recorder.record(
        _result_with_tokens(
            "deep_read", "research_harness", "Kimi-K2.5", 0.10, 5000, 800
        ),
        {"paper_id": 3},
    )

    report = recorder.token_report_by_agent()
    assert len(report) == 2
    # Sorted by cost desc: kimi ($0.10) > gpt-5 ($0.05)
    assert report[0]["model_used"] == "Kimi-K2.5"
    assert report[0]["calls"] == 1
    assert report[0]["prompt_tokens"] == 5000
    assert report[0]["completion_tokens"] == 800
    assert report[0]["total_tokens"] == 5800
    assert report[0]["cost_usd"] == 0.10
    assert report[0]["cost_per_call"] == 0.10

    assert report[1]["model_used"] == "gpt-5"
    assert report[1]["calls"] == 2
    assert report[1]["prompt_tokens"] == 2500
    assert report[1]["completion_tokens"] == 450
    assert abs(report[1]["cost_usd"] - 0.05) < 1e-9
    assert abs(report[1]["cost_per_call"] - 0.025) < 1e-9


def test_token_report_by_topic_isolation(db) -> None:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name) VALUES ('topic-a')")
        conn.execute("INSERT INTO topics (name) VALUES ('topic-b')")
        topic_a = int(
            conn.execute("SELECT id FROM topics WHERE name='topic-a'").fetchone()["id"]
        )
        topic_b = int(
            conn.execute("SELECT id FROM topics WHERE name='topic-b'").fetchone()["id"]
        )
        conn.commit()
    finally:
        conn.close()

    recorder = ProvenanceRecorder(db)
    recorder.record(
        _result_with_tokens(
            "paper_summarize", "research_harness", "gpt-5", 0.02, 1000, 200
        ),
        {"paper_id": 1},
        topic_id=topic_a,
    )
    recorder.record(
        _result_with_tokens(
            "paper_summarize", "research_harness", "gpt-5", 0.04, 2000, 400
        ),
        {"paper_id": 2},
        topic_id=topic_b,
    )

    report_a = recorder.token_report_by_agent(topic_id=topic_a)
    report_b = recorder.token_report_by_agent(topic_id=topic_b)

    assert len(report_a) == 1
    assert report_a[0]["prompt_tokens"] == 1000
    assert report_a[0]["cost_usd"] == 0.02

    assert len(report_b) == 1
    assert report_b[0]["prompt_tokens"] == 2000
    assert report_b[0]["cost_usd"] == 0.04


def test_llm_primitives_token_accumulator() -> None:
    """_client_chat accumulates usage across multiple calls."""
    from research_harness.execution import llm_primitives
    from paperindex.llm import client as pclient

    llm_primitives._reset_token_accumulator()
    # No calls yet
    assert llm_primitives._accumulated_tokens() == (None, None)

    # Simulate two provider calls reporting usage
    pclient._record_usage(1200, 300)
    # Manually replay what _client_chat does after client.chat returns.
    usage = pclient.get_last_usage()
    llm_primitives._token_acc_local.prompt = getattr(
        llm_primitives._token_acc_local, "prompt", 0
    ) + (usage.prompt_tokens or 0)
    llm_primitives._token_acc_local.completion = getattr(
        llm_primitives._token_acc_local, "completion", 0
    ) + (usage.completion_tokens or 0)
    llm_primitives._token_acc_local.observed = True

    pclient._record_usage(800, 150)
    usage = pclient.get_last_usage()
    llm_primitives._token_acc_local.prompt += usage.prompt_tokens or 0
    llm_primitives._token_acc_local.completion += usage.completion_tokens or 0

    assert llm_primitives._accumulated_tokens() == (2000, 450)

    # Reset makes it forget
    llm_primitives._reset_token_accumulator()
    assert llm_primitives._accumulated_tokens() == (None, None)
