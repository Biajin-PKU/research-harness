from __future__ import annotations

from research_harness.execution import LocalBackend, create_backend
from research_harness.execution.backend import BackendInfo, ExecutionBackend
from research_harness.execution.claude_code import ClaudeCodeBackend
from research_harness.execution.factory import get_backend_names
from research_harness.execution.harness import ResearchHarnessBackend


def test_local_backend_supports_non_llm(db) -> None:
    backend = LocalBackend(db)
    assert backend.supports("paper_search") is True
    assert backend.supports("claim_extract") is False


def test_local_backend_execute_paper_search(db) -> None:
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

    backend = LocalBackend(db)
    result = backend.execute("paper_search", query="attention")

    assert result.success is True
    assert result.backend == "local"
    assert result.output.provider in ("local", "multi")
    titles = [p.title for p in result.output.papers]
    assert "Attention Is All You Need" in titles


def test_local_backend_execute_unknown_primitive(db) -> None:
    backend = LocalBackend(db)
    result = backend.execute("nonexistent")

    assert result.success is False
    assert result.error == "Unknown primitive: nonexistent"


def test_local_backend_llm_primitive_raises(db) -> None:
    backend = LocalBackend(db)

    try:
        backend.execute("claim_extract", paper_ids=[1], topic_id=1)
    except NotImplementedError as exc:
        assert "requires LLM" in str(exc)
    else:
        raise AssertionError("expected NotImplementedError")


def test_claude_code_backend_supports_non_llm(db) -> None:
    backend = ClaudeCodeBackend(db=db)
    assert backend.supports("paper_search") is True


def test_claude_code_backend_results_tagged(db) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
            ("Test Paper", "10.1000/test", "0000.00000", "s2-test"),
        )
        conn.commit()
    finally:
        conn.close()
    backend = ClaudeCodeBackend(db=db)
    result = backend.execute("paper_search", query="test")
    assert result.success is True
    assert result.backend == "claude_code"


def test_harness_stub_raises() -> None:
    backend = ResearchHarnessBackend()

    try:
        backend.execute("paper_search", query="attention")
    except NotImplementedError as exc:
        assert "Phase 3" in str(exc)
    else:
        raise AssertionError("expected NotImplementedError")


def test_backend_factory(db) -> None:
    backend = create_backend("local", db=db)
    assert isinstance(backend, LocalBackend)
    assert get_backend_names() == ["claude_code", "local", "research_harness"]

    try:
        create_backend("unknown")
    except ValueError as exc:
        assert "Unknown backend" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_backend_info(db) -> None:
    backends = [
        LocalBackend(db),
        ClaudeCodeBackend(),
        ResearchHarnessBackend(),
    ]

    for backend in backends:
        info = backend.get_info()
        assert isinstance(info, BackendInfo)
        assert info.name
        assert info.version
        assert info.description


def test_execution_backend_protocol(db) -> None:
    backend = LocalBackend(db)
    assert isinstance(backend, ExecutionBackend)
