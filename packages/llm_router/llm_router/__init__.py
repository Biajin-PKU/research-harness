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
from .config import (
    detect_available_providers,
    get_provider_order,
    get_tier_route,
    load_config,
)
from .plugins import load_plugins

__all__ = [
    "LLMClient",
    "LLMUsage",
    "OpenAICompatibleClient",
    "ResolvedLLMConfig",
    "TaskTier",
    "detect_available_providers",
    "get_last_usage",
    "get_provider",
    "get_provider_order",
    "get_tier_route",
    "list_providers",
    "load_config",
    "load_plugins",
    "register_provider",
    "resolve_llm_config",
    "resolve_route",
    "set_default_route",
]

# Discover user-supplied provider plugins. Failures are logged, not raised,
# so a broken plugin cannot crash the rest of the router.
load_plugins()
