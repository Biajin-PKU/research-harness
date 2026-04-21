"""Plugin manifest schema and validation.

A plugin is a bundle that can extend Research Harness with new:
- Primitives (paper sources, analysis tools, etc.)
- Gates (custom quality checks)
- Stages (new orchestrator stages)
- Advisory rules (heuristic warnings)
- Backends (execution providers)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MANIFEST_SCHEMA_VERSION = 1

VALID_EXTENSION_POINTS = frozenset({
    "primitives",
    "gates",
    "stages",
    "advisory_rules",
    "backends",
})


@dataclass(frozen=True)
class PluginManifest:
    """Declarative plugin descriptor loaded from plugin.yaml."""

    name: str
    version: str
    description: str
    author: str = ""
    license: str = "PolyForm-Noncommercial-1.0.0"
    homepage: str = ""
    schema_version: int = MANIFEST_SCHEMA_VERSION
    min_harness_version: str = "0.1.0"
    extension_points: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Example:
    # extension_points:
    #   primitives:
    #     - name: "my_search"
    #       category: "RETRIEVAL"
    #       module: "my_plugin.search"
    #       function: "search_impl"
    #   gates:
    #     - name: "quality_gate"
    #       module: "my_plugin.gates"
    #       class: "QualityGateEvaluator"


def validate_manifest(manifest: PluginManifest) -> list[str]:
    """Validate a plugin manifest. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    if not manifest.name:
        errors.append("Plugin name is required")
    if not manifest.version:
        errors.append("Plugin version is required")
    if manifest.schema_version != MANIFEST_SCHEMA_VERSION:
        errors.append(
            f"Unsupported schema version {manifest.schema_version}, "
            f"expected {MANIFEST_SCHEMA_VERSION}"
        )

    for point_name, extensions in manifest.extension_points.items():
        if point_name not in VALID_EXTENSION_POINTS:
            errors.append(f"Unknown extension point: {point_name}")
            continue
        if not isinstance(extensions, list):
            errors.append(f"Extension point '{point_name}' must be a list")
            continue
        for i, ext in enumerate(extensions):
            if not isinstance(ext, dict):
                errors.append(f"{point_name}[{i}] must be a dict")
                continue
            if "name" not in ext:
                errors.append(f"{point_name}[{i}] missing 'name' field")

    return errors


def load_manifest_from_dict(data: dict[str, Any]) -> PluginManifest:
    """Create a PluginManifest from a parsed YAML/JSON dict."""
    return PluginManifest(
        name=str(data.get("name", "")),
        version=str(data.get("version", "")),
        description=str(data.get("description", "")),
        author=str(data.get("author", "")),
        license=str(data.get("license", "PolyForm-Noncommercial-1.0.0")),
        homepage=str(data.get("homepage", "")),
        schema_version=int(data.get("schema_version", MANIFEST_SCHEMA_VERSION)),
        min_harness_version=str(data.get("min_harness_version", "0.1.0")),
        extension_points=data.get("extension_points", {}),
    )
