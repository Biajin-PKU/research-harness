"""Experiment primitive implementations — non-LLM operations.

code_validate, experiment_run, verified_registry_build, verified_registry_check.
(code_generate is LLM-powered, implemented in execution/llm_primitives.py)
"""

from __future__ import annotations

import logging
from typing import Any

from ..experiment.sandbox import run_experiment
from ..experiment.validator import auto_fix_unbound_locals, validate_code
from ..experiment.verified_registry import (
    ALWAYS_ALLOWED,
    build_registry_from_metrics,
)
from ..storage.db import Database
from .registry import (
    CODE_VALIDATE_SPEC,
    EXPERIMENT_RUN_SPEC,
    VERIFIED_REGISTRY_BUILD_SPEC,
    VERIFIED_REGISTRY_CHECK_SPEC,
    register_primitive,
)
from .types import (
    CodeValidationIssue,
    CodeValidationOutput,
    ExperimentRunOutput,
    VerifiedRegistryCheckOutput,
    VerifiedRegistryOutput,
)

logger = logging.getLogger(__name__)


@register_primitive(CODE_VALIDATE_SPEC)
def code_validate(
    *, code: str, auto_fix: bool = True, **_: Any
) -> CodeValidationOutput:
    """Validate experiment code: syntax, security, imports."""
    auto_fixed = 0
    if auto_fix:
        code, n = auto_fix_unbound_locals(code)
        auto_fixed = n

    result = validate_code(code)
    issues = [
        CodeValidationIssue(
            severity=i.severity,
            category=i.category,
            message=i.message,
            line=i.line,
        )
        for i in result.issues
    ]
    return CodeValidationOutput(
        ok=result.ok,
        issues=issues,
        summary=result.summary(),
        auto_fixed=auto_fixed,
    )


@register_primitive(EXPERIMENT_RUN_SPEC)
def experiment_run(
    *,
    code: str,
    timeout_sec: float = 300.0,
    primary_metric: str = "",
    **_: Any,
) -> ExperimentRunOutput:
    """Run experiment in local sandbox."""
    result = run_experiment(code, timeout_sec=timeout_sec)

    primary_value = None
    if primary_metric and result.metrics:
        # Look for the primary metric in results
        for key, val in result.metrics.items():
            if key == primary_metric or key.endswith(f"/{primary_metric}"):
                primary_value = val
                break

    return ExperimentRunOutput(
        metrics=result.metrics,
        primary_metric_value=primary_value,
        primary_metric_name=primary_metric,
        elapsed_sec=result.elapsed_sec,
        returncode=result.returncode,
        timed_out=result.timed_out,
        divergence=result.divergence,
        code_hash=result.code_hash,
        stdout_tail=result.stdout[-1000:] if result.stdout else "",
        stderr_tail=result.stderr[-500:] if result.stderr else "",
    )


@register_primitive(VERIFIED_REGISTRY_BUILD_SPEC)
def verified_registry_build(
    *,
    db: Database,
    topic_id: int,
    metrics: dict[str, float],
    primary_metric_name: str = "",
    **_: Any,
) -> VerifiedRegistryOutput:
    """Build verified number registry from experiment metrics and persist to DB."""
    registry = build_registry_from_metrics(metrics, primary_metric_name)

    # Persist to DB
    conn = db.connect()
    try:
        # Clear previous entries for this topic (use topic_id in both columns for compat)
        conn.execute("DELETE FROM verified_numbers WHERE topic_id = ?", (topic_id,))
        for number, source in registry.values.items():
            # Compute variants
            rounded = round(number, 2)
            pct = number * 100.0 if 0.0 < abs(number) <= 1.0 else None
            inv = number / 100.0 if abs(number) > 1.0 else None
            conn.execute(
                """INSERT INTO verified_numbers
                   (project_id, topic_id, source, number_original, number_rounded, number_percentage, number_inverse)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (topic_id, topic_id, source[:200], number, rounded, pct, inv),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed to persist verified numbers: %s", exc)
    finally:
        conn.close()

    return VerifiedRegistryOutput(
        whitelist_size=registry.size,
        condition_names=sorted(registry.condition_names),
        primary_metric=registry.primary_metric,
        primary_metric_name=primary_metric_name,
    )


@register_primitive(VERIFIED_REGISTRY_CHECK_SPEC)
def verified_registry_check(
    *,
    db: Database,
    topic_id: int,
    numbers: list[float],
    tolerance: float = 0.01,
    **_: Any,
) -> VerifiedRegistryCheckOutput:
    """Check numbers against the verified registry whitelist."""
    # Load registry from DB
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT number_original, source FROM verified_numbers WHERE topic_id = ?",
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    # Build in-memory registry
    registry = build_registry_from_metrics({})
    for row in rows:
        registry.add_value(row["number_original"], row["source"])

    verified: list[float] = []
    unverified: list[float] = []
    always_allowed: list[float] = []

    for n in numbers:
        if n in ALWAYS_ALLOWED:
            always_allowed.append(n)
        elif registry.is_verified(n, tolerance):
            verified.append(n)
        else:
            unverified.append(n)

    total = len(numbers)
    pass_rate = (len(verified) + len(always_allowed)) / total if total > 0 else 1.0

    return VerifiedRegistryCheckOutput(
        verified=verified,
        unverified=unverified,
        always_allowed=always_allowed,
        pass_rate=pass_rate,
        total_checked=total,
    )
