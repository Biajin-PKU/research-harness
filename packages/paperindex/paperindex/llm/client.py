"""Multi-provider LLM client with task-tier routing.

Architecture:
  - Provider Registry: pluggable provider functions (cursor_agent, codex, openai, anthropic, kimi)
  - Task Tier Routing: light/medium/heavy → provider:model mapping via env vars
  - LLMClient: unified interface, backwards-compatible

Adding a new provider:
  1. Write a function: (prompt: str, model: str, **kwargs) -> str
  2. Call register_provider("name", fn)
  3. Set env: LLM_ROUTE_LIGHT=name:model-id
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal
from urllib import error, request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token usage accounting
#
# Providers call ``_record_usage`` after a successful request so LLMClient can
# surface it via ``get_last_usage``. Stored in thread-local storage so
# concurrent calls from different threads do not cross-contaminate. Providers
# that cannot observe token counts (e.g. CLI agents) simply skip recording.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMUsage:
    """Token usage reported by a provider for a single request."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


_usage_local = threading.local()


def _record_usage(prompt_tokens: int | None, completion_tokens: int | None) -> None:
    """Record usage for the current thread's most recent LLM call."""
    _usage_local.value = LLMUsage(
        prompt_tokens=prompt_tokens if prompt_tokens is not None else None,
        completion_tokens=completion_tokens if completion_tokens is not None else None,
    )


def _clear_usage() -> None:
    _usage_local.value = None


def get_last_usage() -> LLMUsage | None:
    """Return usage recorded by the most recent provider call on this thread."""
    return getattr(_usage_local, "value", None)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _usage_from_openai_dict(payload: Any) -> tuple[int | None, int | None]:
    """Extract (prompt_tokens, completion_tokens) from an OpenAI-style dict."""
    if not isinstance(payload, dict):
        return (None, None)
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return (None, None)
    prompt = _coerce_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _coerce_int(usage.get("completion_tokens") or usage.get("output_tokens"))
    return (prompt, completion)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Provider = Literal["anthropic", "openai", "kimi", "cursor_agent", "codex", "joy_kimi", "joy_gpt"]
TaskTier = Literal["light", "medium", "heavy"]
ProviderFn = Callable[..., str]  # (prompt, model, **kwargs) -> response

# ---------------------------------------------------------------------------
# Provider Registry
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: dict[str, ProviderFn] = {}


def register_provider(name: str, fn: ProviderFn) -> None:
    """Register a provider function. Overwrites existing registration."""
    _PROVIDER_REGISTRY[name] = fn


def get_provider(name: str) -> ProviderFn:
    """Get a registered provider by name."""
    fn = _PROVIDER_REGISTRY.get(name)
    if fn is None:
        available = ", ".join(sorted(_PROVIDER_REGISTRY)) or "(none)"
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    return fn


def list_providers() -> list[str]:
    """List all registered provider names."""
    return sorted(_PROVIDER_REGISTRY)


# ---------------------------------------------------------------------------
# Task Tier Routing
# ---------------------------------------------------------------------------

_DEFAULT_ROUTES: dict[TaskTier, tuple[str, str]] = {
    "light": ("joy_gpt", "gpt-5"),
    "medium": ("joy_gpt", "gpt-5"),
    "heavy": ("codex", "gpt-5.4"),
}

# ---------------------------------------------------------------------------
# Provider Blocklist — RED LINE: never use these providers for paper-reading
# tasks (light/medium tiers). Anthropic API is too expensive for bulk
# summarization, card extraction, and deep-reading work that basic models
# handle well. Heavy tier (review/approval) is exempt.
# ---------------------------------------------------------------------------

_BLOCKED_PROVIDERS_BY_TIER: dict[TaskTier, frozenset[str]] = {
    "light": frozenset({"anthropic"}),
    "medium": frozenset({"anthropic"}),
    "heavy": frozenset(),  # heavy tier may use any provider
}

_TIER_FALLBACKS: dict[TaskTier, tuple[str, str]] = {
    "light": ("joy_gpt", "gpt-5"),
    "medium": ("joy_gpt", "gpt-5"),
}


def resolve_route(tier: TaskTier) -> tuple[str, str]:
    """Resolve a task tier to (provider_name, model).

    Checks env var LLM_ROUTE_{TIER} first (format: "provider:model"),
    then falls back to _DEFAULT_ROUTES.

    RED LINE: if the resolved provider is in the blocklist for this tier,
    logs a warning and falls back to the safe default.
    """
    env_key = f"LLM_ROUTE_{tier.upper()}"
    env_val = os.environ.get(env_key, "").strip()
    if env_val and ":" in env_val:
        provider_name, model = env_val.split(":", 1)
        provider_name, model = provider_name.strip(), model.strip()
        blocked = _BLOCKED_PROVIDERS_BY_TIER.get(tier, frozenset())
        if provider_name in blocked:
            fallback = _TIER_FALLBACKS.get(tier, _DEFAULT_ROUTES["medium"])
            logger.warning(
                "RED LINE: provider '%s' is blocked for tier '%s' "
                "(paper-reading tasks must not use expensive APIs). "
                "Falling back to %s:%s",
                provider_name, tier, fallback[0], fallback[1],
            )
            return fallback
        return (provider_name, model)

    return _DEFAULT_ROUTES.get(tier, _DEFAULT_ROUTES["medium"])


def set_default_route(tier: TaskTier, provider: str, model: str) -> None:
    """Override default route for a tier (programmatic, not env-based)."""
    _DEFAULT_ROUTES[tier] = (provider, model)


# ---------------------------------------------------------------------------
# CLI Provider Implementations
# ---------------------------------------------------------------------------

_CLI_TIMEOUT = 300  # 5-minute hard ceiling


def _chat_cursor_agent(prompt: str, model: str, **_: Any) -> str:
    """Call Cursor Agent CLI in headless print mode."""
    cmd = ["agent", "--print", "--trust", "--model", model, prompt]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_CLI_TIMEOUT)
    except FileNotFoundError:
        raise RuntimeError("Cursor Agent CLI not found. Install from https://docs.cursor.com/agent")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Cursor Agent timed out after {_CLI_TIMEOUT}s")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"Cursor Agent failed (exit {result.returncode}): {stderr}")
    return (result.stdout or "").strip()


def _chat_codex(prompt: str, model: str, **_: Any) -> str:
    """Call Codex CLI in non-interactive mode."""
    cmd = ["codex", "exec", "--full-auto", "--ephemeral", "--json"]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_CLI_TIMEOUT)
    except FileNotFoundError:
        raise RuntimeError("Codex CLI not found. Install with: npm install -g @openai/codex")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Codex timed out after {_CLI_TIMEOUT}s")
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"Codex failed (exit {result.returncode}): {stderr}")
    # Parse JSONL output: find last agent_message item AND scan for usage events.
    text_parts: list[str] = []
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    for line in (result.stdout or "").strip().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        if etype == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message" and item.get("text"):
                text_parts.append(item["text"])
        # Codex emits token usage in a variety of event shapes; probe the most
        # common places conservatively and let the last seen value win.
        usage_like: dict[str, Any] | None = None
        if isinstance(event.get("usage"), dict):
            usage_like = event["usage"]
        elif isinstance(event.get("token_usage"), dict):
            usage_like = event["token_usage"]
        elif isinstance(event.get("info"), dict) and isinstance(
            event["info"].get("usage"), dict
        ):
            usage_like = event["info"]["usage"]
        if usage_like is not None:
            p = _coerce_int(
                usage_like.get("prompt_tokens") or usage_like.get("input_tokens")
            )
            c = _coerce_int(
                usage_like.get("completion_tokens") or usage_like.get("output_tokens")
            )
            if p is not None:
                prompt_tokens = p
            if c is not None:
                completion_tokens = c
    if prompt_tokens is not None or completion_tokens is not None:
        _record_usage(prompt_tokens, completion_tokens)
    return "\n".join(text_parts).strip() if text_parts else (result.stdout or "").strip()


# ---------------------------------------------------------------------------
# API Provider Implementations
# ---------------------------------------------------------------------------

_LLM_TIMEOUT_SECONDS = 300.0


def _build_anthropic_client(api_key: str, base_url: str, timeout: float = _LLM_TIMEOUT_SECONDS):
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "anthropic package is required. Install with: pip install anthropic"
        ) from exc
    kwargs: dict[str, Any] = {"api_key": api_key or None, "timeout": timeout}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def _chat_anthropic(prompt: str, model: str, *, api_key: str = "", base_url: str = "",
                     temperature: float = 0.0, **_: Any) -> str:
    if not api_key:
        raise ValueError("Anthropic provider requires api_key")
    client = _build_anthropic_client(api_key, base_url)
    response = client.messages.create(
        model=model, max_tokens=2048, temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = getattr(response, "usage", None)
    if usage is not None:
        _record_usage(
            _coerce_int(getattr(usage, "input_tokens", None)),
            _coerce_int(getattr(usage, "output_tokens", None)),
        )
    return "\n".join(b.text for b in response.content if hasattr(b, "text"))


_KIMI_DEFAULT_BASE_URL = "https://api.kimi.com/coding/"
_KIMI_MAX_TOKENS = 20480


def _resolve_kimi_base_url(base_url: str) -> str:
    normalized = (base_url or _KIMI_DEFAULT_BASE_URL).strip().rstrip("/")
    if normalized.endswith("/messages"):
        normalized = normalized[: -len("/messages")]
    if normalized.endswith("/v1"):
        normalized = normalized[: -len("/v1")]
    return normalized + "/"


def _chat_kimi(prompt: str, model: str, *, api_key: str = "", base_url: str = "",
               temperature: float = 0.0, **_: Any) -> str:
    if not api_key:
        raise ValueError("Kimi provider requires api_key")
    resolved_url = _resolve_kimi_base_url(base_url)
    client = _build_anthropic_client(api_key, resolved_url)
    with client.messages.stream(
        model=model, max_tokens=_KIMI_MAX_TOKENS, temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        text = stream.get_final_text()
        try:
            final_message = stream.get_final_message()
            usage = getattr(final_message, "usage", None)
            if usage is not None:
                _record_usage(
                    _coerce_int(getattr(usage, "input_tokens", None)),
                    _coerce_int(getattr(usage, "output_tokens", None)),
                )
        except Exception:  # pragma: no cover - best-effort usage capture
            pass
        return text


# Backward-compat aliases for tests
_resolve_kimi_anthropic_base_url = _resolve_kimi_base_url


def _resolve_kimi_messages_url(base_url: str) -> str:
    normalized = (base_url or "https://api.kimi.com/coding/v1/messages").strip().rstrip("/")
    if normalized.endswith("/messages"):
        return normalized
    if normalized.endswith("/coding"):
        return f"{normalized}/v1/messages"
    return f"{normalized}/messages"


def _chat_openai(prompt: str, model: str, *, api_key: str = "", base_url: str = "",
                 temperature: float = 0.0, **_: Any) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package is required. Install with: pip install openai"
        ) from exc
    client = OpenAI(api_key=api_key, base_url=base_url or None)
    response = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    usage = getattr(response, "usage", None)
    if usage is not None:
        _record_usage(
            _coerce_int(getattr(usage, "prompt_tokens", None)),
            _coerce_int(getattr(usage, "completion_tokens", None)),
        )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# JoyCode Providers — direct call via local login state (OpenAI format)
#
# JoyCode exposes multiple models (Kimi, GPT-5, GLM, Claude, Gemini, ...) behind
# a single OpenAI-compatible endpoint. We register two logical providers on top
# of that shared transport:
#   - joy_kimi → Kimi-K2.5 (single-paper reading, cheap/fast)
#   - joy_gpt  → gpt-5      (general worker, largest 200k+ context, replaces cursor_agent)
# Both share the same login state and rate limiter because they hit the same
# backend.
# ---------------------------------------------------------------------------

_JOY_KIMI_DEFAULT_MODEL = "Kimi-K2.5"
_JOY_GPT_DEFAULT_MODEL = "gpt-5"  # OpenAI flagship via JoyCode; 400k context window
_JOYCODE_MAX_RPS = 5  # max requests per second (shared across joy_* providers)
_JOYCODE_MAX_TOKENS = 4096

# Backward-compat alias (tests and older code reference _JOY_KIMI_MAX_RPS).
_JOY_KIMI_MAX_RPS = _JOYCODE_MAX_RPS

# Tasks that should use joy_kimi when enabled (single-paper reading + light analysis).
# Kimi handles all basic paper comprehension; joy_gpt / cross-paper synthesis
# handle heavy analysis that needs broader context.
_JOY_KIMI_TASKS: frozenset[str] = frozenset({
    # Core reading
    "paper_summarize",
    "deep_read_pass1",
    "build_paper_card",
    # Light-tier extraction (single-paper scope)
    "compiled_summary",
    "claim_extract",
    "paper_coverage_check",
    "query_refine",
    # Quantitative extraction (single-paper scope)
    "table_extract",
    "figure_interpret",
    # Evolution (lightweight)
    "lesson_extract",
    "strategy_distill",
})

# Shared token-bucket rate limiter for all joycode-backend providers.
_joycode_timestamps: list[float] = []
_joycode_lock = __import__("threading").Lock()

# Backward-compat aliases (older code may reference the joy_kimi-prefixed names).
_joy_kimi_timestamps = _joycode_timestamps
_joy_kimi_lock = _joycode_lock


def _joycode_rate_limit() -> None:
    """Block until a request slot is available (max _JOYCODE_MAX_RPS per second)."""
    with _joycode_lock:
        now = time.time()
        window = now - 1.0
        # Evict timestamps older than 1 second
        while _joycode_timestamps and _joycode_timestamps[0] < window:
            _joycode_timestamps.pop(0)
        if len(_joycode_timestamps) >= _JOYCODE_MAX_RPS:
            sleep_until = _joycode_timestamps[0] + 1.0
            sleep_dur = sleep_until - now
            if sleep_dur > 0:
                time.sleep(sleep_dur)
            # Re-evict after sleeping
            now = time.time()
            window = now - 1.0
            while _joycode_timestamps and _joycode_timestamps[0] < window:
                _joycode_timestamps.pop(0)
        _joycode_timestamps.append(time.time())


# Backward-compat alias.
_joy_kimi_rate_limit = _joycode_rate_limit


def _call_joycode_chat(prompt: str, model: str, *, temperature: float = 0.0,
                        max_tokens: int = _JOYCODE_MAX_TOKENS) -> str:
    """Shared transport for JoyCode-backed providers.

    NOTE: JoyCode is an internal provider that depends on a private library
    (``~/code/joycode``) not included in this open-source release. The
    ``joy_kimi`` and ``joy_gpt`` providers are therefore unavailable to
    public users. Use the standard ``anthropic``, ``openai``, ``codex``, or
    ``cursor_agent`` providers instead. Contributors who want to re-enable
    JoyCode on their own infrastructure can provide an equivalent transport
    that exposes ``build_headers``, ``get_chat_url``, ``load_login_info``,
    ``load_state``, and ``request_json``.
    """
    _joycode_rate_limit()

    import sys as _sys

    _joycode_path = os.path.expanduser(
        os.environ.get("JOYCODE_PATH", "~/code/joycode")
    )
    if not os.path.isdir(_joycode_path):
        raise RuntimeError(
            "JoyCode provider is not available in the open-source build. "
            "Set JOY_KIMI_ENABLED=0 and JOY_GPT_ENABLED=0, or point "
            "JOYCODE_PATH at a local JoyCode checkout. "
            "Alternatives: use provider='anthropic', 'openai', 'codex', or 'cursor_agent'."
        )
    if _joycode_path not in _sys.path:
        _sys.path.insert(0, _joycode_path)

    from joycode_api_probe import (  # type: ignore[import-untyped]
        build_headers,
        get_chat_url,
        load_login_info,
        load_state,
        request_json,
    )

    state = load_state()
    login_info = load_login_info(state)
    headers = build_headers(login_info)

    # Enable streaming to bypass nginx upstream timeout (504 Gateway Timeout).
    # nginx proxy_read_timeout is inter-frame silence (~60s), not total duration.
    # With stream=True, backend flushes tokens continuously so nginx never
    # sees a 60s silence gap — long prompts / long outputs stop triggering 504.
    # The curl-based transport buffers all SSE frames and
    # _parse_json_response / _merge_chunked_json already merge them into the
    # standard non-streaming shape, so callers need no changes.
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        # Ask the backend to include a final usage-only frame so provenance
        # token accounting survives under streaming (OpenAI spec §stream_options).
        "stream_options": {"include_usage": True},
    }

    resp = request_json(get_chat_url(login_info), payload, headers, timeout=600)

    prompt_tokens, completion_tokens = _usage_from_openai_dict(resp)
    _record_usage(prompt_tokens, completion_tokens)

    # Extract content from OpenAI-format response
    choices = resp.get("choices", [])
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message", {})
        if isinstance(msg, dict) and isinstance(msg.get("content"), str):
            return msg["content"].strip()
    return json.dumps(resp, ensure_ascii=False)


def _chat_joy_kimi(prompt: str, model: str, *, temperature: float = 0.0, **_: Any) -> str:
    """Call JoyCode Kimi K2.5 via the shared joycode transport."""
    return _call_joycode_chat(prompt, model or _JOY_KIMI_DEFAULT_MODEL, temperature=temperature)


def _chat_joy_gpt(prompt: str, model: str, *, temperature: float = 0.0, **_: Any) -> str:
    """Call JoyCode GPT (default: gpt-5) via the shared joycode transport.

    Replaces the Cursor Agent worker for light/medium tiers: the JoyCode
    backend exposes OpenAI's flagship GPT-5 (400k context window), which is
    more than sufficient for paper reading / summarization / gap detection
    and far cheaper than the Anthropic API path.
    """
    return _call_joycode_chat(prompt, model or _JOY_GPT_DEFAULT_MODEL, temperature=temperature)


_JOY_GPT_TASKS: frozenset[str] = frozenset({
    # Heavy-tier paper reading (cross-paper synthesis, critical analysis)
    "deep_read_pass2",
    "gap_detect",
    "baseline_identify",
    "method_taxonomy",
    "evidence_matrix",
    "contradiction_detect",
    "direction_ranking",
    "consistency_check",
    # Auto-runner stage planner
    "stage_planner",
})


def is_joy_kimi_task(task_name: str) -> bool:
    """Check if *task_name* should be routed to joy_kimi (when enabled via env)."""
    if os.environ.get("JOY_KIMI_ENABLED", "").strip().lower() not in ("1", "true", "yes"):
        return False
    return task_name in _JOY_KIMI_TASKS


def is_joy_gpt_task(task_name: str) -> bool:
    """Check if *task_name* should be routed to joy_gpt (when enabled via env)."""
    if os.environ.get("JOY_GPT_ENABLED", "").strip().lower() not in ("1", "true", "yes"):
        return False
    return task_name in _JOY_GPT_TASKS


def joy_kimi_route() -> tuple[str, str]:
    """Return ``(provider, model)`` tuple for joy_kimi tasks."""
    model = os.environ.get("JOY_KIMI_MODEL", "").strip() or _JOY_KIMI_DEFAULT_MODEL
    return ("joy_kimi", model)


def joy_gpt_route() -> tuple[str, str]:
    """Return ``(provider, model)`` tuple for joy_gpt tasks."""
    model = os.environ.get("JOY_GPT_MODEL", "").strip() or _JOY_GPT_DEFAULT_MODEL
    return ("joy_gpt", model)


# ---------------------------------------------------------------------------
# Register Built-in Providers
# ---------------------------------------------------------------------------

register_provider("cursor_agent", _chat_cursor_agent)
register_provider("codex", _chat_codex)
register_provider("anthropic", _chat_anthropic)
register_provider("openai", _chat_openai)
register_provider("kimi", _chat_kimi)
register_provider("joy_kimi", _chat_joy_kimi)
register_provider("joy_gpt", _chat_joy_gpt)


# ---------------------------------------------------------------------------
# Config Resolution (backwards-compatible)
# ---------------------------------------------------------------------------

@dataclass
class ResolvedLLMConfig:
    provider: str = "openai"
    model: str = ""
    api_key: str = ""
    base_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in {
            "provider": self.provider, "model": self.model,
            "api_key": self.api_key, "base_url": self.base_url,
        }.items() if v}


def resolve_llm_config(overrides: dict[str, Any] | None = None) -> ResolvedLLMConfig:
    """Resolve LLM config from overrides -> env vars, auto-detecting provider.

    Priority: explicit override > joy_gpt > cursor_agent > codex > anthropic > openai > kimi
    """
    overrides = overrides or {}
    provider_override = str(overrides.get("provider", "")).strip().lower()

    # Env detection
    joy_kimi_enabled = os.environ.get("JOY_KIMI_ENABLED", "").strip().lower() in ("1", "true", "yes")
    joy_gpt_enabled = os.environ.get("JOY_GPT_ENABLED", "").strip().lower() in ("1", "true", "yes")
    cursor_enabled = os.environ.get("CURSOR_AGENT_ENABLED", "").strip().lower() in ("1", "true", "yes")
    codex_enabled = os.environ.get("CODEX_ENABLED", "").strip().lower() in ("1", "true", "yes")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or ""
    openai_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("CHATGPT_API_KEY") or ""
    kimi_key = os.environ.get("KIMI_API_KEY", "")

    valid_providers = set(_PROVIDER_REGISTRY)
    if provider_override in valid_providers:
        provider = provider_override
    elif overrides.get("api_key"):
        provider = "openai"
    elif joy_kimi_enabled and provider_override == "joy_kimi":
        provider = "joy_kimi"
    elif joy_gpt_enabled:
        provider = "joy_gpt"
    elif cursor_enabled:
        provider = "cursor_agent"
    elif codex_enabled:
        provider = "codex"
    elif anthropic_key and (not openai_key or os.environ.get("ANTHROPIC_MODEL")):
        provider = "anthropic"
    elif openai_key:
        provider = "openai"
    elif kimi_key:
        provider = "kimi"
    else:
        provider = "cursor_agent" if cursor_enabled else "openai"

    # Resolve model/key/url per provider
    model: str
    api_key: str
    base_url: str

    if provider == "joy_kimi":
        model = str(overrides.get("model") or os.environ.get("JOY_KIMI_MODEL") or _JOY_KIMI_DEFAULT_MODEL)
        api_key = ""
        base_url = ""
    elif provider == "joy_gpt":
        model = str(overrides.get("model") or os.environ.get("JOY_GPT_MODEL") or _JOY_GPT_DEFAULT_MODEL)
        api_key = ""
        base_url = ""
    elif provider == "cursor_agent":
        model = str(overrides.get("model") or os.environ.get("CURSOR_AGENT_MODEL") or "composer-2-fast")
        api_key = ""
        base_url = ""
    elif provider == "codex":
        model = str(overrides.get("model") or os.environ.get("CODEX_MODEL") or "")
        api_key = ""
        base_url = ""
    elif provider == "kimi":
        model = str(overrides.get("model") or os.environ.get("KIMI_MODEL") or "kimi-for-coding")
        api_key = str(overrides.get("api_key") or kimi_key)
        base_url = _resolve_kimi_base_url(
            str(overrides.get("base_url") or os.environ.get("KIMI_BASE_URL") or _KIMI_DEFAULT_BASE_URL)
        )
    elif provider == "anthropic":
        model = str(overrides.get("model") or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-6")
        api_key = str(overrides.get("api_key") or anthropic_key)
        base_url = str(overrides.get("base_url") or os.environ.get("ANTHROPIC_BASE_URL") or "")
    else:  # openai
        model = str(
            overrides.get("model")
            or os.environ.get("PAPERINDEX_LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("CHATGPT_MODEL")
            or ""
        )
        api_key = str(overrides.get("api_key") or openai_key)
        base_url = str(
            overrides.get("base_url")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("CHATGPT_BASE_URL")
            or ""
        )

    return ResolvedLLMConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)


# ---------------------------------------------------------------------------
# LLMClient — unified interface
# ---------------------------------------------------------------------------

class LLMClient:
    """Unified LLM client with provider registry and task-tier routing.

    Usage:
        # Default provider from config
        client = LLMClient()
        client.chat("summarize this")

        # Tier-based routing (ignores default provider)
        client.chat("extract claims", tier="medium")

        # Explicit provider + model
        client.chat("review this", provider="codex", model="gpt-5.4-high")
    """

    def __init__(self, config: ResolvedLLMConfig | None = None, **kwargs: Any) -> None:
        self._config = config or resolve_llm_config(kwargs if kwargs else None)

    @property
    def provider(self) -> str:
        return self._config.provider

    @property
    def model(self) -> str:
        return self._config.model

    def chat(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
        *,
        tier: TaskTier | None = None,
        provider: str | None = None,
    ) -> str:
        """Send a prompt and get a response.

        Args:
            prompt: The input text.
            model: Override model (optional).
            temperature: Sampling temperature (ignored by CLI providers).
            tier: Task tier for automatic routing (light/medium/heavy).
                  When set, overrides the default provider/model.
            provider: Explicit provider name override.
        """
        _clear_usage()
        # Tier-based routing takes priority
        if tier and not (provider or model):
            prov_name, route_model = resolve_route(tier)
            logger.debug("tier=%s → provider=%s model=%s", tier, prov_name, route_model)
            fn = get_provider(prov_name)
            return fn(prompt, route_model, api_key=self._config.api_key,
                      base_url=self._config.base_url, temperature=temperature)

        # Explicit provider override
        prov_name = provider or self._config.provider
        use_model = model or self._config.model
        if not use_model:
            raise ValueError("No model specified in config or call")

        fn = get_provider(prov_name)
        return fn(prompt, use_model, api_key=self._config.api_key,
                  base_url=self._config.base_url, temperature=temperature)

    def chat_with_usage(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
        *,
        tier: TaskTier | None = None,
        provider: str | None = None,
    ) -> tuple[str, LLMUsage | None]:
        """Send a prompt and return (text, usage). ``usage`` may be None for
        providers that cannot observe token counts (e.g. cursor_agent)."""
        text = self.chat(
            prompt, model=model, temperature=temperature, tier=tier, provider=provider
        )
        return text, get_last_usage()

    def get_last_usage(self) -> LLMUsage | None:
        """Return token usage recorded by the most recent call on this thread."""
        return get_last_usage()


# Backwards compatibility alias
OpenAICompatibleClient = LLMClient


# ---------------------------------------------------------------------------
# Utility helpers (kept for backward compat, used by paperindex internals)
# ---------------------------------------------------------------------------

def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float = 60.0) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method="POST")
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt == 2:
                raise
            last_error = exc
        except (error.URLError, TimeoutError, ConnectionResetError) as exc:
            if attempt == 2:
                raise
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable")


def _extract_kimi_text(response_payload: Any) -> str:
    if not isinstance(response_payload, dict):
        return ""
    content = response_payload.get("content")
    if isinstance(content, list):
        parts = [str(b.get("text", "")).strip() for b in content if isinstance(b, dict) and b.get("text")]
        if parts:
            return "\n".join(parts)
    if isinstance(content, str):
        return content
    messages = response_payload.get("messages")
    if isinstance(messages, list):
        parts = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            mc = msg.get("content")
            if isinstance(mc, str) and mc.strip():
                parts.append(mc.strip())
            elif isinstance(mc, list):
                parts.extend(str(b.get("text", "")).strip() for b in mc if isinstance(b, dict) and b.get("text"))
        if parts:
            return "\n".join(p for p in parts if p)
    return json.dumps(response_payload, ensure_ascii=False)
