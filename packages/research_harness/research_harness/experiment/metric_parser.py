"""Parse experiment metrics from stdout and detect divergence.

Supports 5 metric output formats:
  1. Plain:              metric_name: value
  2. Condition-prefixed: condition=X metric_name: value
  3. Tagged:             condition=X regime=R metric_name: value
  4. Ratio:              condition=X metric_name: N/M
  5. SUMMARY:            SUMMARY condition=X metric=Y mean=M std=S

Adapted from AutoResearchClaw (MIT license).
"""

from __future__ import annotations

import logging
import math
import re

logger = logging.getLogger(__name__)

# Patterns
_PLAIN_METRIC = re.compile(
    r"^([a-zA-Z_][\w./]*)\s*[:=]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)"
)
_COND_METRIC = re.compile(
    r"condition=(\S+)\s+([a-zA-Z_][\w./]*)\s*[:=]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)"
)
_RATIO_METRIC = re.compile(
    r"condition=(\S+)\s+([a-zA-Z_][\w./]*)\s*[:=]\s*(\d+)\s*/\s*(\d+)"
)
_SUMMARY = re.compile(
    r"SUMMARY\s+condition=(\S+)\s+metric=(\S+)\s+mean=([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)"
    r"(?:\s+std=([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?))?"
)
_NAN_PATTERNS = [
    re.compile(r"\bloss\s*[:=]\s*nan\b", re.IGNORECASE),
    re.compile(r"\bnan\s+loss\b", re.IGNORECASE),
    re.compile(r"\bmath\s+domain\s+error\b", re.IGNORECASE),
    re.compile(r"\b(?<!info)nan\b", re.IGNORECASE),
]
_INF_PATTERN = re.compile(r"\binf\b(?!o)", re.IGNORECASE)
_LOSS_DIVERGE = re.compile(r"loss\s*[:=]\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)")


def parse_metrics(stdout: str) -> dict[str, float]:
    """Extract metrics from experiment stdout.

    Returns a flat dict of metric_name (or condition/metric_name) → value.
    Skips NaN/Inf values.
    """
    metrics: dict[str, float] = {}

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        # SUMMARY format (highest priority)
        m = _SUMMARY.match(line)
        if m:
            cond, metric, mean_str, std_str = m.groups()
            val = _safe_float(mean_str)
            if val is not None:
                metrics[f"{cond}/{metric}"] = val
            if std_str:
                std_val = _safe_float(std_str)
                if std_val is not None:
                    metrics[f"{cond}/{metric}_std"] = std_val
            continue

        # Ratio format
        m = _RATIO_METRIC.search(line)
        if m:
            cond, metric, num_str, den_str = m.groups()
            num, den = int(num_str), int(den_str)
            if den > 0:
                metrics[f"{cond}/{metric}"] = num / den
            continue

        # Condition-prefixed format
        m = _COND_METRIC.search(line)
        if m:
            cond, metric, val_str = m.groups()
            val = _safe_float(val_str)
            if val is not None:
                metrics[f"{cond}/{metric}"] = val
            continue

        # Plain format
        m = _PLAIN_METRIC.match(line)
        if m:
            metric, val_str = m.groups()
            val = _safe_float(val_str)
            if val is not None:
                metrics[metric] = val

    return metrics


def detect_nan_divergence(stdout: str, stderr: str) -> str:
    """Detect NaN, Inf, or divergence in experiment output.

    Returns a description of the issue, or empty string if clean.
    """
    combined = f"{stdout}\n{stderr}"

    for pattern in _NAN_PATTERNS:
        m = pattern.search(combined)
        if m:
            return f"NaN detected: {m.group()}"

    if _INF_PATTERN.search(combined):
        return "Inf value detected in output"

    # Check for diverging loss (> 100)
    for m in _LOSS_DIVERGE.finditer(combined):
        val = _safe_float(m.group(1))
        if val is not None and val > 100.0:
            return f"Loss divergence detected: {val}"

    # Check parsed metrics for non-finite values
    metrics = parse_metrics(stdout)
    for key, val in metrics.items():
        if math.isnan(val) or math.isinf(val):
            return f"Non-finite metric: {key}={val}"

    return ""


def _safe_float(s: str) -> float | None:
    try:
        v = float(s)
        if math.isnan(v) or math.isinf(v):
            logger.debug("Skipping non-finite metric value: %s", s)
            return None
        return v
    except (ValueError, TypeError):
        return None
