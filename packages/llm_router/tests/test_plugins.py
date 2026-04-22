"""Tests for the plugin discovery mechanism."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch):
    """Snapshot the provider registry and restore after each test."""
    from llm_router import client as client_mod

    before = dict(client_mod._PROVIDER_REGISTRY)
    yield
    client_mod._PROVIDER_REGISTRY.clear()
    client_mod._PROVIDER_REGISTRY.update(before)


def _write_plugin(path: Path, name: str, text: str) -> None:
    path.write_text(
        textwrap.dedent(f"""\
        from llm_router import register_provider

        def _chat_{name}(prompt, model, **_):
            return {text!r}

        register_provider({name!r}, _chat_{name})
        """),
        encoding="utf-8",
    )


def test_env_plugin_loads_single_file(tmp_path, monkeypatch):
    plugin_file = tmp_path / "my_provider.py"
    _write_plugin(plugin_file, "my_test_single", "ok-single")

    monkeypatch.setenv("LLM_ROUTER_PLUGINS", str(plugin_file))

    from llm_router import get_provider, list_providers, load_plugins

    load_plugins()

    assert "my_test_single" in list_providers()
    assert get_provider("my_test_single")("hi", "") == "ok-single"


def test_env_plugin_loads_directory(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text(
        "from llm_router import register_provider\n"
        "register_provider('plug_a', lambda p, m, **_: 'A')\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "from llm_router import register_provider\n"
        "register_provider('plug_b', lambda p, m, **_: 'B')\n",
        encoding="utf-8",
    )
    (tmp_path / "_skipped.py").write_text(
        "raise RuntimeError('underscore prefix should be ignored')\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("LLM_ROUTER_PLUGINS", str(tmp_path))

    from llm_router import list_providers, load_plugins

    load_plugins()

    providers = list_providers()
    assert "plug_a" in providers
    assert "plug_b" in providers


def test_broken_plugin_does_not_break_router(tmp_path, monkeypatch, caplog):
    good = tmp_path / "good.py"
    _write_plugin(good, "still_works", "ok")

    bad = tmp_path / "bad.py"
    bad.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    monkeypatch.setenv("LLM_ROUTER_PLUGINS", str(tmp_path))

    from llm_router import list_providers, load_plugins

    load_plugins()

    assert "still_works" in list_providers()


def test_missing_plugin_path_is_silent(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "LLM_ROUTER_PLUGINS",
        str(tmp_path / "does-not-exist.py"),
    )

    from llm_router import load_plugins

    # Must not raise
    load_plugins()


def test_default_dir_scanned_when_env_unset(tmp_path, monkeypatch):
    """When LLM_ROUTER_PLUGINS is unset, ~/.config/llm_router/plugins/ is scanned."""
    fake_home = tmp_path / "home"
    plugins_dir = fake_home / ".config" / "llm_router" / "plugins"
    plugins_dir.mkdir(parents=True)
    _write_plugin(plugins_dir / "default.py", "from_default_dir", "default ok")

    monkeypatch.delenv("LLM_ROUTER_PLUGINS", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))
    # os.path.expanduser uses HOME on POSIX; no further mocking needed.

    from llm_router import list_providers, load_plugins

    load_plugins()

    assert "from_default_dir" in list_providers()
