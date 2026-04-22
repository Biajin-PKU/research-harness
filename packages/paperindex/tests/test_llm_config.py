from llm_router.client import (
    LLMClient,
    ResolvedLLMConfig,
    _extract_kimi_text,
    _post_json,
    _resolve_kimi_anthropic_base_url,
    _resolve_kimi_messages_url,
    resolve_llm_config,
)


ALL_ENV_VARS = [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "CHATGPT_API_KEY",
    "CHATGPT_BASE_URL",
    "CHATGPT_MODEL",
    "KIMI_API_KEY",
    "KIMI_BASE_URL",
    "KIMI_MODEL",
    "PAPERINDEX_LLM_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_BASE_URL",
    "CURSOR_AGENT_ENABLED",
    "CURSOR_AGENT_MODEL",
    "CODEX_ENABLED",
    "CODEX_MODEL",
    "LLM_ROUTE_LIGHT",
    "LLM_ROUTE_MEDIUM",
    "LLM_ROUTE_HEAVY",
]


def _clear_env(monkeypatch):
    for name in ALL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_resolve_llm_config_prefers_explicit_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    config = resolve_llm_config(
        {
            "api_key": "override-key",
            "base_url": "https://override.example/v1",
            "model": "override-model",
        }
    )
    assert config.api_key == "override-key"
    assert config.base_url == "https://override.example/v1"
    assert config.model == "override-model"


def test_resolve_llm_config_supports_kimi_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("KIMI_API_KEY", "kimi-key")
    monkeypatch.setenv("KIMI_BASE_URL", "https://kimi.example/v1")
    monkeypatch.setenv("KIMI_MODEL", "kimi-model")

    config = resolve_llm_config()
    assert config.api_key == "kimi-key"
    assert config.base_url == "https://kimi.example/"
    assert config.model == "kimi-model"
    assert config.provider == "kimi"


def test_resolve_kimi_via_explicit_provider_override(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("KIMI_API_KEY", "kimi-key")
    monkeypatch.setenv("KIMI_BASE_URL", "https://api.kimi.com/coding/v1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")

    config = resolve_llm_config({"provider": "kimi"})
    assert config.provider == "kimi"
    assert config.api_key == "kimi-key"
    assert config.base_url == "https://api.kimi.com/coding/"
    assert config.model == "kimi-for-coding"


def test_resolve_llm_config_returns_empty_when_unconfigured(monkeypatch):
    _clear_env(monkeypatch)

    config = resolve_llm_config()
    assert config.api_key == ""
    assert config.base_url == ""
    assert config.model == ""


def test_resolve_anthropic_from_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key-12345")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    config = resolve_llm_config()
    assert config.provider == "anthropic"
    assert config.api_key == "ant-key-12345"
    assert config.model == "claude-sonnet-4-6"


def test_resolve_anthropic_only_key_defaults_model(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key-12345")

    config = resolve_llm_config()
    assert config.provider == "anthropic"
    assert config.model == "claude-sonnet-4-6"


def test_resolve_explicit_provider_override(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")

    config = resolve_llm_config({"provider": "anthropic"})
    assert config.provider == "anthropic"
    assert config.api_key == "ant-key"

    config = resolve_llm_config({"provider": "openai"})
    assert config.provider == "openai"
    assert config.api_key == "oai-key"


def test_resolve_both_keys_prefers_anthropic_when_model_set(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("OPENAI_API_KEY", "oai-key")

    config = resolve_llm_config()
    assert config.provider == "anthropic"
    assert config.model == "claude-haiku-4-5-20251001"


def test_resolve_prefers_anthropic_over_kimi_when_both_present(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("KIMI_API_KEY", "kimi-key")
    monkeypatch.setenv("KIMI_MODEL", "kimi-for-coding")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    config = resolve_llm_config()
    assert config.provider == "anthropic"
    assert config.api_key == "ant-key"
    assert config.model == "claude-haiku-4-5-20251001"


def test_resolve_anthropic_auth_token_and_base_url(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-xyz")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy.local:8080")

    config = resolve_llm_config()
    assert config.provider == "anthropic"
    assert config.api_key == "token-xyz"
    assert config.base_url == "http://proxy.local:8080"
    assert config.model == "claude-sonnet-4-6"


def test_resolve_anthropic_api_key_takes_precedence_over_auth_token(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "primary-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fallback-token")

    config = resolve_llm_config()
    assert config.api_key == "primary-key"


def test_resolve_config_to_dict_includes_provider(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")

    config = resolve_llm_config()
    d = config.to_dict()
    assert d["provider"] == "anthropic"
    assert "model" in d


def test_resolve_kimi_messages_url_accepts_base_or_messages_endpoint():
    assert (
        _resolve_kimi_messages_url("https://api.kimi.com/coding")
        == "https://api.kimi.com/coding/v1/messages"
    )
    assert (
        _resolve_kimi_messages_url("https://api.kimi.com/coding/v1")
        == "https://api.kimi.com/coding/v1/messages"
    )
    assert (
        _resolve_kimi_messages_url("https://api.kimi.com/coding/v1/messages")
        == "https://api.kimi.com/coding/v1/messages"
    )


def test_resolve_kimi_anthropic_base_url_normalizes_variants():
    assert (
        _resolve_kimi_anthropic_base_url("https://api.kimi.com/coding")
        == "https://api.kimi.com/coding/"
    )
    assert (
        _resolve_kimi_anthropic_base_url("https://api.kimi.com/coding/v1")
        == "https://api.kimi.com/coding/"
    )
    assert (
        _resolve_kimi_anthropic_base_url("https://api.kimi.com/coding/v1/messages")
        == "https://api.kimi.com/coding/"
    )


def test_extract_kimi_text_reads_content_blocks():
    payload = {
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": "world"},
        ]
    }
    assert _extract_kimi_text(payload) == "hello\nworld"


def test_llm_client_kimi_uses_anthropic_streaming(monkeypatch):
    captured = {}

    class DummyStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_final_text(self):
            return "kimi ok"

    class DummyMessages:
        def stream(self, **kwargs):
            captured.update(kwargs)
            return DummyStream()

    class DummyClient:
        def __init__(self):
            self.messages = DummyMessages()

    monkeypatch.setattr(
        "llm_router.client._build_anthropic_client",
        lambda api_key, base_url: DummyClient(),
    )

    client = LLMClient(
        ResolvedLLMConfig(
            provider="kimi",
            model="kimi-for-coding",
            api_key="sk-kimi-test",
            base_url="https://api.kimi.com/coding/",
        )
    )
    output = client.chat("你好，请介绍一下自己", temperature=0.1)

    assert output == "kimi ok"
    assert captured["model"] == "kimi-for-coding"
    assert captured["max_tokens"] == 20480
    assert captured["messages"] == [{"role": "user", "content": "你好，请介绍一下自己"}]



def test_post_json_retries_transient_errors(monkeypatch):
    attempts = {"count": 0}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(req, timeout=60.0):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionResetError("peer reset")
        return DummyResponse()

    monkeypatch.setattr("llm_router.client.request.urlopen", fake_urlopen)
    monkeypatch.setattr("llm_router.client.time.sleep", lambda _: None)

    payload = _post_json("https://example.com/messages", {"ping": 1}, {"x-test": "1"})
    assert payload == {"ok": True}
    assert attempts["count"] == 3
