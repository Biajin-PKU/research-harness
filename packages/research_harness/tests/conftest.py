from __future__ import annotations

import os

import pytest
from click.testing import CliRunner

from research_harness.storage.db import Database


@pytest.fixture(autouse=True)
def _no_external_providers(monkeypatch):
    """Prevent real HTTP calls to search providers in all tests."""
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [],
    )


@pytest.fixture(autouse=True)
def _stub_paperindex_llm_chat(monkeypatch):
    """Short-circuit paperindex's LLM chat calls in tests without a real
    provider. Returns deterministic JSON so the card-extraction path
    (``build_card`` → ``LLMClient.chat`` → ``PaperCard.from_dict``) runs
    end-to-end without network/LLM, keeping CLI tests exercising the real
    assembler and adapter code.

    When an API key or agent-mode provider is configured, the real chat
    is preserved so integration tests can still exercise it end-to-end.
    Tests that patch ``LLMClient.chat`` themselves override this stub
    (monkeypatch order: test-local patch wins).
    """
    if (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CURSOR_AGENT_ENABLED")
        or os.getenv("CODEX_ENABLED")
    ):
        return

    import json as _json

    def _fake_chat(self, prompt, model=None, temperature=0.0):
        del self, prompt, model, temperature
        return _json.dumps(
            {
                "title": "Stubbed paper",
                "core_idea": "Stubbed core idea for test runs without an LLM provider.",
                "method_summary": "Stubbed method summary.",
                "key_results": ["stubbed result"],
                "evidence": [
                    {
                        "section": "summary",
                        "confidence": 0.9,
                        "snippet": "stubbed evidence",
                    }
                ],
            }
        )

    monkeypatch.setattr("paperindex.llm.client.LLMClient.chat", _fake_chat)


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    return db


@pytest.fixture
def conn(db):
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def runner(tmp_path, monkeypatch):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    return CliRunner()
