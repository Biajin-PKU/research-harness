"""Tests for the optional config file + backend detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


pytest.importorskip("tomllib", reason="TOML config support requires Python 3.11+")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Point LLM_ROUTER_CONFIG at a tmp file and clear overlapping env vars."""
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "CHATGPT_API_KEY",
        "KIMI_API_KEY",
        "KIMI_MODEL",
        "CURSOR_AGENT_ENABLED",
        "CODEX_ENABLED",
        "LLM_ROUTE_LIGHT",
        "LLM_ROUTE_MEDIUM",
        "LLM_ROUTE_HEAVY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_ROUTER_CONFIG", str(tmp_path / "config.toml"))


def _write_config(path_env: str, body: str) -> None:
    Path(path_env).write_text(body, encoding="utf-8")


def test_missing_config_returns_empty_dict(monkeypatch):
    from llm_router.config import load_config

    monkeypatch.setenv("LLM_ROUTER_CONFIG", "/does/not/exist.toml")
    assert load_config() == {}


def test_invalid_toml_is_swallowed(monkeypatch, tmp_path, caplog):
    import logging

    cfg = tmp_path / "broken.toml"
    cfg.write_text("this = is [not valid\n", encoding="utf-8")
    monkeypatch.setenv("LLM_ROUTER_CONFIG", str(cfg))

    from llm_router.config import load_config

    with caplog.at_level(logging.WARNING, logger="llm_router.config"):
        assert load_config() == {}
    assert any("config load failed" in rec.message for rec in caplog.records)


def test_get_provider_order_parsed(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nprovider_order = ["openai", "anthropic"]\n',
    )
    from llm_router.config import get_provider_order

    assert get_provider_order() == ["openai", "anthropic"]


def test_get_tier_route_parsed(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nheavy = "anthropic:claude-opus-4-6"\n',
    )
    from llm_router.config import get_tier_route

    assert get_tier_route("heavy") == ("anthropic", "claude-opus-4-6")
    assert get_tier_route("medium") is None


def test_resolve_route_uses_config_when_env_unset(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nheavy = "anthropic:claude-opus-4-6"\n',
    )

    from llm_router.client import resolve_route

    assert resolve_route("heavy") == ("anthropic", "claude-opus-4-6")


def test_env_var_beats_config_for_route(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nheavy = "anthropic:claude-opus-4-6"\n',
    )
    monkeypatch.setenv("LLM_ROUTE_HEAVY", "openai:gpt-4o")

    from llm_router.client import resolve_route

    assert resolve_route("heavy") == ("openai", "gpt-4o")


def test_provider_order_picks_first_available(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nprovider_order = ["kimi", "openai", "anthropic"]\n',
    )
    # Only OPENAI has credentials — config order should skip kimi.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    from llm_router.client import resolve_llm_config

    cfg = resolve_llm_config()
    assert cfg.provider == "openai"


def test_provider_order_falls_through_when_none_available(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nprovider_order = ["kimi", "cursor_agent"]\n',
    )
    # No credentials for either entry — built-in auto-detect should kick in.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    from llm_router.client import resolve_llm_config

    cfg = resolve_llm_config()
    assert cfg.provider == "anthropic"


def test_provider_order_respects_plugin_providers(monkeypatch):
    import os

    _write_config(
        os.environ["LLM_ROUTER_CONFIG"],
        '[routing]\nprovider_order = ["fake_plugin"]\n',
    )
    # No built-in credentials.
    from llm_router import client as client_mod

    snapshot = dict(client_mod._PROVIDER_REGISTRY)
    try:
        client_mod._PROVIDER_REGISTRY["fake_plugin"] = (
            lambda prompt, model, **_: "ok"
        )
        cfg = client_mod.resolve_llm_config()
        assert cfg.provider == "fake_plugin"
    finally:
        client_mod._PROVIDER_REGISTRY.clear()
        client_mod._PROVIDER_REGISTRY.update(snapshot)


def test_detect_available_providers(monkeypatch):
    from llm_router.config import detect_available_providers

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("KIMI_API_KEY", "sk-test")

    available = detect_available_providers()
    assert "openai" in available
    assert "kimi" in available
    assert "anthropic" not in available
