"""Evolution primitive implementations.

lesson_extract (stub fallback — real LLM version in llm_primitives.py),
lesson_overlay, strategy_distill, strategy_inject, experiment_log, meta_reflect.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..evolution.store import LessonStore
from .registry import (
    EXPERIMENT_LOG_SPEC,
    LESSON_EXTRACT_SPEC,
    LESSON_OVERLAY_SPEC,
    META_REFLECT_SPEC,
    STRATEGY_DISTILL_SPEC,
    STRATEGY_INJECT_SPEC,
    register_primitive,
)
from .types import (
    ExperimentLogOutput,
    LessonExtractOutput,
    LessonItem,
    LessonOverlayOutput,
    MetaReflectOutput,
    StrategyDistillOutput,
    StrategyInjectOutput,
)

logger = logging.getLogger(__name__)


@register_primitive(LESSON_EXTRACT_SPEC)
def lesson_extract(
    *,
    stage: str,
    stage_summary: str,
    issues_encountered: list[str] | None = None,
    **_: Any,
) -> LessonExtractOutput:
    """Extract lessons from stage execution. Stub — real LLM call dispatched by harness.

    In stub mode, converts issues_encountered into lesson items directly.
    """
    lessons: list[LessonItem] = []
    issues = issues_encountered or []

    if issues:
        for issue in issues:
            lessons.append(
                LessonItem(
                    stage=stage,
                    content=issue,
                    lesson_type="failure",
                    tags=[stage],
                )
            )

    # Always add a summary observation
    if stage_summary:
        lessons.append(
            LessonItem(
                stage=stage,
                content=stage_summary,
                lesson_type="observation",
                tags=[stage],
            )
        )

    return LessonExtractOutput(
        lessons=lessons,
        stage=stage,
        model_used="stub",
    )


@register_primitive(LESSON_OVERLAY_SPEC)
def lesson_overlay(
    *,
    stage: str,
    store_path: str,
    top_k: int = 5,
    **_: Any,
) -> LessonOverlayOutput:
    """Build prompt overlay from stored lessons."""
    store = LessonStore(store_path)
    overlay = store.build_overlay(stage, top_k=top_k)
    count = store.count(stage)

    return LessonOverlayOutput(
        overlay_text=overlay,
        lesson_count=count,
        stage=stage,
    )


@register_primitive(STRATEGY_DISTILL_SPEC)
def strategy_distill(
    *,
    db: Any = None,
    stage: str,
    min_lessons: int = 3,
    topic_id: int | None = None,
    force: bool = False,
    **_: Any,
) -> StrategyDistillOutput:
    """Distill lessons into strategies. Real LLM call dispatched by harness."""
    if db is None:
        return StrategyDistillOutput(stage=stage)

    from ..evolution.distiller import StrategyDistiller

    # Default strategies dir
    strategies_dir = (
        Path(db._path).parent / "strategies"
        if hasattr(db, "_path")
        else Path(".research-harness/strategies")
    )

    distiller = StrategyDistiller(db, strategies_dir)
    result = distiller.distill_stage(
        stage,
        min_lessons=min_lessons,
        topic_id=topic_id,
        force=force,
    )

    return StrategyDistillOutput(
        stage=result.stage,
        strategies_created=result.strategies_created,
        strategies_updated=result.strategies_updated,
        strategies_skipped=result.strategies_skipped,
        quality_scores=result.quality_scores,
        model_used=result.model_used,
    )


@register_primitive(STRATEGY_INJECT_SPEC)
def strategy_inject(
    *,
    db: Any = None,
    stage: str,
    topic_id: int | None = None,
    max_strategies: int = 3,
    **_: Any,
) -> StrategyInjectOutput:
    """Get active strategy overlay for a stage."""
    if db is None:
        return StrategyInjectOutput(stage=stage)

    from ..evolution.injector import StrategyInjector

    injector = StrategyInjector(db)
    overlay = injector.build_strategy_overlay(
        stage,
        topic_id=topic_id,
        max_strategies=max_strategies,
    )
    strategies = injector.get_active_strategies(
        stage,
        topic_id=topic_id,
        max_strategies=max_strategies,
    )

    return StrategyInjectOutput(
        overlay_text=overlay,
        strategy_count=len(strategies),
        stage=stage,
    )


@register_primitive(EXPERIMENT_LOG_SPEC)
def experiment_log(
    *,
    db: Any = None,
    topic_id: int,
    hypothesis: str,
    primary_metric_name: str = "",
    primary_metric_value: float | None = None,
    metrics: dict | None = None,
    outcome: str = "pending",
    notes: str = "",
    study_spec_artifact_id: int | None = None,
    result_artifact_id: int | None = None,
    **_: Any,
) -> ExperimentLogOutput:
    """Log an experiment result for dual-loop tracking."""
    if db is None:
        return ExperimentLogOutput(topic_id=topic_id)

    from ..evolution.outer_loop import OuterLoop

    loop = OuterLoop(db)
    eid = loop.log_experiment(
        topic_id,
        hypothesis,
        primary_metric_name=primary_metric_name,
        primary_metric_value=primary_metric_value,
        metrics=metrics,
        outcome=outcome,
        notes=notes,
        study_spec_artifact_id=study_spec_artifact_id,
        result_artifact_id=result_artifact_id,
    )

    exp_num = loop.get_experiment_count(topic_id)
    return ExperimentLogOutput(
        experiment_id=eid,
        experiment_number=exp_num,
        topic_id=topic_id,
    )


@register_primitive(META_REFLECT_SPEC)
def meta_reflect(
    *,
    db: Any = None,
    topic_id: int,
    force: bool = False,
    **_: Any,
) -> MetaReflectOutput:
    """Cross-experiment meta-reflection."""
    if db is None:
        return MetaReflectOutput()

    from ..evolution.outer_loop import OuterLoop

    loop = OuterLoop(db)
    reflection = loop.reflect(topic_id, force=force)

    if reflection is None:
        return MetaReflectOutput(
            decision="",
            reasoning="Not enough experiments for reflection",
        )

    should_transition = reflection.decision in ("PIVOT", "CONCLUDE")
    target = ""
    if reflection.decision == "PIVOT":
        target = "propose"
    elif reflection.decision == "CONCLUDE":
        target = "write"

    return MetaReflectOutput(
        decision=reflection.decision,
        reasoning=reflection.reasoning,
        next_hypothesis=reflection.next_hypothesis,
        patterns_observed=reflection.patterns_observed,
        confidence=reflection.confidence,
        reflection_number=reflection.reflection_number,
        model_used=reflection.model_used,
        should_transition=should_transition,
        transition_target=target,
    )
