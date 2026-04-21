"""Verified number registry — anti-fabrication harness for experiment data.

Builds a whitelist of all numbers from actual experiment results,
including variant transforms (rounding, percentage, inverse).
Numbers in paper drafts are verified against this whitelist.

Adapted from AutoResearchClaw (MIT license).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.01  # 1% relative tolerance


@dataclass
class VerifiedRegistry:
    """Registry of verified numeric values from experiments."""

    values: dict[float, str] = field(default_factory=dict)  # number → provenance
    condition_names: set[str] = field(default_factory=set)
    primary_metric: float | None = None
    primary_metric_name: str = ""

    def add_value(self, value: float, source: str) -> None:
        """Register a verified value with its provenance source."""
        if not math.isfinite(value):
            return
        self.values[value] = source
        self._add_variants(value, source)

    def _add_variants(self, value: float, source: str) -> None:
        """Generate rounding, percentage, and inverse variants."""
        # Rounded variants at 1-4 decimal places
        for dp in (1, 2, 3, 4):
            rounded = round(value, dp)
            if rounded not in self.values:
                self.values[rounded] = f"{source} (rounded {dp}dp)"

        # Percentage conversion: 0.87 → 87.0
        if 0.0 < abs(value) <= 1.0:
            pct = value * 100.0
            if pct not in self.values:
                self.values[pct] = f"{source} (×100)"
                for dp in (1, 2):
                    r = round(pct, dp)
                    if r not in self.values:
                        self.values[r] = f"{source} (×100, rounded {dp}dp)"

        # Inverse: 87.0 → 0.87
        if abs(value) > 1.0:
            frac = value / 100.0
            if frac not in self.values:
                self.values[frac] = f"{source} (÷100)"

    def is_verified(self, number: float, tolerance: float = DEFAULT_TOLERANCE) -> bool:
        """Check if a number matches any registered value within tolerance."""
        if not math.isfinite(number):
            return False
        for v in self.values:
            if v == 0.0:
                if abs(number) < 1e-6:
                    return True
            elif abs(number - v) / max(abs(v), 1e-9) <= tolerance:
                return True
        return False

    def lookup(self, number: float, tolerance: float = DEFAULT_TOLERANCE) -> str | None:
        """Return provenance source if verified, else None."""
        if not math.isfinite(number):
            return None
        for v, source in self.values.items():
            if v == 0.0:
                if abs(number) < 1e-6:
                    return source
            elif abs(number - v) / max(abs(v), 1e-9) <= tolerance:
                return source
        return None

    @property
    def size(self) -> int:
        return len(self.values)


# -- Always-allowed numbers ---------------------------------------------------

ALWAYS_ALLOWED: frozenset[float] = frozenset({
    0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0,
    0.5, 0.01, 0.001, 0.0001, 0.1, 0.05, 0.95, 0.99,
    # Years
    2020.0, 2021.0, 2022.0, 2023.0, 2024.0, 2025.0, 2026.0, 2027.0,
    # Powers of 2
    8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 1024.0, 2048.0, 4096.0,
    # Image sizes
    224.0, 299.0, 384.0,
    # Common hyperparameters
    0.0003, 3e-4, 0.0005, 5e-4, 0.002, 2e-3,
    0.2, 0.3, 0.25, 0.7, 0.6, 0.8, 0.9, 0.999, 0.9999,
    0.02, 0.03, 1e-5, 1e-6, 1e-8,
    300.0, 400.0, 500.0, 8192.0,
})


def build_registry_from_metrics(
    metrics: dict[str, float],
    primary_metric_name: str = "",
) -> VerifiedRegistry:
    """Build a VerifiedRegistry from experiment metrics dict.

    Extracts conditions from metric keys (condition/metric_name format),
    registers all values with provenance, and computes pairwise differences.
    """
    registry = VerifiedRegistry(primary_metric_name=primary_metric_name)

    # Register all metric values
    conditions: dict[str, dict[str, float]] = {}
    for key, val in metrics.items():
        registry.add_value(val, f"metric:{key}")
        # Parse condition from key (e.g., "baseline/accuracy" → condition="baseline")
        if "/" in key:
            cond, metric = key.split("/", 1)
            registry.condition_names.add(cond)
            conditions.setdefault(cond, {})[metric] = val

    # Set primary metric
    if primary_metric_name:
        for key, val in metrics.items():
            if key.endswith(f"/{primary_metric_name}") or key == primary_metric_name:
                registry.primary_metric = val
                break

    # Compute pairwise differences between conditions
    cond_names = sorted(conditions.keys())
    for i, c1 in enumerate(cond_names):
        for c2 in cond_names[i + 1:]:
            for metric in conditions[c1]:
                if metric in conditions[c2]:
                    v1, v2 = conditions[c1][metric], conditions[c2][metric]
                    diff = v1 - v2
                    abs_diff = abs(diff)
                    registry.add_value(diff, f"diff:{c1}-{c2}/{metric}")
                    registry.add_value(abs_diff, f"|diff|:{c1}-{c2}/{metric}")
                    if abs(v2) > 1e-9:
                        rel = (v1 - v2) / abs(v2) * 100.0
                        registry.add_value(rel, f"rel_improve:{c1}-{c2}/{metric}")

    return registry
