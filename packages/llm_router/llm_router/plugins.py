"""Plugin discovery for user-supplied providers.

Installations can ship custom providers (corporate LLM gateways, local
proxies, experimental models) without modifying this source tree. Plugins
are plain Python files that import :mod:`llm_router` and call
``register_provider()``.

Discovery order (first hit wins — explicit env disables default scan):

1. ``$LLM_ROUTER_PLUGINS`` — comma-separated list of ``.py`` files and/or
   directories. Tilde expansion is applied.
2. ``~/.config/llm_router/plugins/*.py`` — default user-wide location.

Any exception inside a plugin is logged at WARNING level but never
propagates, so a broken plugin cannot take down the rest of the router.
"""

from __future__ import annotations

import importlib.util
import logging
import os

logger = logging.getLogger(__name__)


def _load_plugin_file(path: str) -> None:
    name = f"_llm_router_plugin_{abs(hash(path))}"
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            logger.debug("llm_router plugin skipped (no loader): %s", path)
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        logger.debug("llm_router plugin loaded: %s", path)
    except Exception as exc:
        logger.warning("llm_router plugin failed to load: %s (%s)", path, exc)


def _load_plugins_from_dir(directory: str) -> None:
    if not os.path.isdir(directory):
        return
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".py") or entry.startswith("_"):
            continue
        _load_plugin_file(os.path.join(directory, entry))


def load_plugins() -> None:
    """Discover and load custom provider plugins. Idempotent."""
    env_paths = os.environ.get("LLM_ROUTER_PLUGINS", "").strip()
    if env_paths:
        for raw in env_paths.split(","):
            path = os.path.expanduser(raw.strip())
            if not path:
                continue
            if os.path.isdir(path):
                _load_plugins_from_dir(path)
            elif os.path.isfile(path):
                _load_plugin_file(path)
            else:
                logger.debug("LLM_ROUTER_PLUGINS entry not found: %s", path)
        return  # explicit env var disables default-dir scan

    default_dir = os.path.expanduser("~/.config/llm_router/plugins")
    _load_plugins_from_dir(default_dir)
