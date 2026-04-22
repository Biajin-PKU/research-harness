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

## Consumers

Used by:
- `paperindex` — PDF understanding (card extraction, structural parsing)
- `research_harness` — research primitives, orchestrator, adversarial review
