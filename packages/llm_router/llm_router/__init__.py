"""Pluggable multi-provider LLM router with task-tier routing."""

from .client import (
    LLMClient,
    LLMUsage,
    OpenAICompatibleClient,
    ResolvedLLMConfig,
    TaskTier,
    get_last_usage,
    get_provider,
    list_providers,
    register_provider,
    resolve_llm_config,
    resolve_route,
    set_default_route,
)

__all__ = [
    "LLMClient",
    "LLMUsage",
    "OpenAICompatibleClient",
    "ResolvedLLMConfig",
    "TaskTier",
    "get_last_usage",
    "get_provider",
    "list_providers",
    "register_provider",
    "resolve_llm_config",
    "resolve_route",
    "set_default_route",
]
