from __future__ import annotations

import json

from research_harness.cli import main
from research_harness.paper_source_clients import (
    available_provider_specs,
    build_provider_suite,
)


def test_available_provider_specs_reflect_current_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_SCHOLAR_API_URL", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test-key")
    monkeypatch.delenv("OPENREVIEW_ENABLE", raising=False)

    specs = {item.name: item for item in available_provider_specs()}

    assert specs["arxiv"].enabled is True
    assert specs["google_scholar"].enabled is False
    assert specs["openalex"].enabled is False
    assert specs["semantic_scholar"].enabled is True
    assert specs["openreview"].enabled is False


def test_build_provider_suite_uses_only_configured_sources(monkeypatch):
    monkeypatch.delenv("GOOGLE_SCHOLAR_API_URL", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test-key")
    monkeypatch.delenv("OPENREVIEW_ENABLE", raising=False)

    providers = build_provider_suite(fetcher=lambda url, headers: {"data": []})

    names = [provider.name for provider in providers]
    assert "arxiv" in names
    assert "semantic_scholar" in names
    # PASA is included by default as fallback
    assert "pasa" in names


def test_search_providers_cli_reports_enabled_sources(runner, monkeypatch):
    monkeypatch.delenv("GOOGLE_SCHOLAR_API_URL", raising=False)
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test-key")
    monkeypatch.delenv("OPENREVIEW_ENABLE", raising=False)

    result = runner.invoke(main, ["--json", "search", "providers"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    mapping = {item["name"]: item for item in payload}
    assert mapping["arxiv"]["enabled"] is True
    assert mapping["semantic_scholar"]["enabled"] is True
    assert mapping["google_scholar"]["enabled"] is False
    assert mapping["openalex"]["enabled"] is False
