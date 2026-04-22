# llm-router

Pluggable multi-provider LLM router with task-tier routing. Built-in providers
cover Anthropic, OpenAI (and OpenAI-compatible endpoints like Kimi/DeepSeek/
Ollama/vLLM), Kimi native, Cursor Agent CLI, and Codex CLI.

## Overview

```python
from llm_router import LLMClient, resolve_llm_config

# Auto-detect provider from env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...)
client = LLMClient()
reply = client.chat("Summarize this paper.")

# Or route by task tier (light/medium/heavy)
reply = client.chat("Extract claims.", tier="medium")

# Or force a specific provider + model
reply = client.chat("Review this design.", provider="codex", model="gpt-5.4-high")
```

## Tier routing

Override defaults with `LLM_ROUTE_{TIER}=provider:model`:

```bash
LLM_ROUTE_LIGHT=openai:gpt-4o-mini
LLM_ROUTE_MEDIUM=openai:gpt-4o
LLM_ROUTE_HEAVY=anthropic:claude-opus-4-6
```

## Adding a provider

```python
from llm_router import register_provider

def my_chat(prompt: str, model: str, **kwargs) -> str:
    # ... your implementation ...
    return response_text

register_provider("my_provider", my_chat)
```

Then use `LLM_ROUTE_HEAVY=my_provider:my-model-id` or pass `provider="my_provider"` explicitly.

## Config file (optional)

Pin provider priority and tier routes without shell env vars. Discovery
order:

1. `$LLM_ROUTER_CONFIG` — explicit path
2. `~/.config/llm_router/config.toml` — default user-wide location

```toml
[routing]
# Override the built-in auto-detect order. The first provider whose credentials
# are available is picked when resolve_llm_config() runs.
provider_order = ["openai", "anthropic", "kimi"]

# Same format as LLM_ROUTE_{TIER}. Env vars still win when set.
light  = "openai:gpt-4o-mini"
medium = "openai:gpt-4o"
heavy  = "anthropic:claude-opus-4-6"
```

The file is optional and failures are swallowed — on Python 3.10 without
`tomli` installed, the config is silently skipped and env-var behavior
takes over.

## Plugins

Register providers from outside the source tree by dropping plugin files where
`llm_router` will auto-discover them on import:

- `$LLM_ROUTER_PLUGINS` — comma-separated list of `.py` files and/or directories (tilde expansion supported)
- `~/.config/llm_router/plugins/*.py` — default user-wide location (used when the env var is unset)

A plugin is any Python file that imports `llm_router` and calls
`register_provider(...)`. Failures are logged but never propagated, so a
broken plugin cannot crash the router.

```python
# ~/.config/llm_router/plugins/my_gateway.py
from llm_router import register_provider

def _chat_my_gateway(prompt, model, **_):
    # talk to your corporate LLM gateway / local proxy / ...
    return response

register_provider("my_gateway", _chat_my_gateway)
```

## Consumers

Used by:
- `paperindex` — PDF understanding (card extraction, structural parsing)
- `research_harness` — research primitives, orchestrator, adversarial review
