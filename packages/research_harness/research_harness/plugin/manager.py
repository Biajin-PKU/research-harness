"""Plugin discovery, validation, and registration.

Phase 0: Defines interfaces and validates manifests.
Phase 1: Will add actual dynamic loading and registration.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .manifest import PluginManifest, load_manifest_from_dict, validate_manifest

logger = logging.getLogger(__name__)


class PluginManager:
    """Discovers, validates, and registers plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginManifest] = {}
        self._load_errors: dict[str, list[str]] = {}

    @property
    def plugins(self) -> dict[str, PluginManifest]:
        return dict(self._plugins)

    @property
    def load_errors(self) -> dict[str, list[str]]:
        return dict(self._load_errors)

    def discover(self, search_paths: list[Path]) -> list[PluginManifest]:
        """Scan paths for plugin.yaml manifests and validate them."""
        discovered: list[PluginManifest] = []
        for path in search_paths:
            if not path.is_dir():
                continue
            for manifest_path in path.rglob("plugin.yaml"):
                try:
                    import yaml

                    data = yaml.safe_load(manifest_path.read_text())
                except ImportError:
                    # Fallback: try JSON
                    import json

                    json_path = manifest_path.with_suffix(".json")
                    if json_path.exists():
                        data = json.loads(json_path.read_text())
                    else:
                        logger.debug("PyYAML not installed, skipping %s", manifest_path)
                        continue
                except Exception as exc:
                    logger.warning("Failed to parse %s: %s", manifest_path, exc)
                    continue

                if not isinstance(data, dict):
                    continue

                manifest = load_manifest_from_dict(data)
                errors = validate_manifest(manifest)
                if errors:
                    self._load_errors[manifest.name or str(manifest_path)] = errors
                    logger.warning(
                        "Plugin %s has validation errors: %s",
                        manifest_path,
                        errors,
                    )
                else:
                    discovered.append(manifest)

        return discovered

    def register(self, manifest: PluginManifest) -> bool:
        """Register a validated plugin. Returns True if successful."""
        errors = validate_manifest(manifest)
        if errors:
            self._load_errors[manifest.name] = errors
            return False

        if manifest.name in self._plugins:
            existing = self._plugins[manifest.name]
            logger.info(
                "Replacing plugin %s v%s with v%s",
                manifest.name,
                existing.version,
                manifest.version,
            )

        self._plugins[manifest.name] = manifest
        logger.info("Registered plugin: %s v%s", manifest.name, manifest.version)
        return True

    def unregister(self, name: str) -> bool:
        """Remove a plugin by name."""
        if name in self._plugins:
            del self._plugins[name]
            return True
        return False

    def list_extensions(self, point: str) -> list[dict[str, Any]]:
        """List all registered extensions for a given extension point."""
        extensions: list[dict[str, Any]] = []
        for plugin in self._plugins.values():
            for ext in plugin.extension_points.get(point, []):
                extensions.append(
                    {
                        "plugin": plugin.name,
                        "plugin_version": plugin.version,
                        **ext,
                    }
                )
        return extensions
