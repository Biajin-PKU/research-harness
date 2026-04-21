"""Evolution data models — trajectory events, strategies, meta-reflections."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrajectoryEvent:
    """A single event in a session's decision trajectory."""

    id: int = 0
    session_id: str = ""
    event_type: str = ""  # tool_call | decision | gate_outcome | error_recovery | user_override
    tool_name: str = ""
    stage: str = ""
    topic_id: int | None = None
    project_id: int | None = None
    input_summary: str = ""
    output_summary: str = ""
    reasoning: str = ""
    success: bool = True
    cost_usd: float = 0.0
    latency_ms: int = 0
    parent_event_id: int | None = None
    sequence_number: int = 0
    created_at: str = ""


@dataclass
class Strategy:
    """A distilled, reusable research strategy for a workflow stage."""

    id: int = 0
    stage: str = ""
    strategy_key: str = ""
    title: str = ""
    content: str = ""
    scope: str = "global"  # global | topic
    topic_id: int | None = None
    version: int = 1
    quality_score: float | None = None
    gate_model: str = ""
    source_lesson_ids: list[int] = field(default_factory=list)
    source_session_count: int = 0
    injection_count: int = 0
    positive_feedback: int = 0
    status: str = "draft"  # draft | active | superseded
    created_at: str = ""
    updated_at: str = ""


@dataclass
class StrategyDistillResult:
    """Result of a strategy distillation run for one stage."""

    stage: str = ""
    strategies_created: int = 0
    strategies_updated: int = 0
    strategies_skipped: int = 0
    quality_scores: list[float] = field(default_factory=list)
    model_used: str = ""


@dataclass
class ExperimentEntry:
    """A logged experiment for outer-loop tracking."""

    id: int = 0
    project_id: int = 0
    topic_id: int = 0
    experiment_number: int = 0
    hypothesis: str = ""
    study_spec_artifact_id: int | None = None
    result_artifact_id: int | None = None
    primary_metric_name: str = ""
    primary_metric_value: float | None = None
    metrics: dict = field(default_factory=dict)
    outcome: str = "pending"  # pending | success | partial | failure
    notes: str = ""
    created_at: str = ""


@dataclass
class MetaReflection:
    """An outer-loop meta-reflection across experiments."""

    id: int = 0
    project_id: int = 0
    topic_id: int = 0
    reflection_number: int = 0
    trigger_type: str = ""  # periodic | failure_streak | manual
    experiments_reviewed: list[int] = field(default_factory=list)
    patterns_observed: str = ""
    decision: str = ""  # DEEPEN | BROADEN | PIVOT | CONCLUDE
    reasoning: str = ""
    next_hypothesis: str = ""
    confidence: float = 0.5
    model_used: str = ""
    created_at: str = ""


@dataclass
class NudgeDecision:
    """A nudge to inject into the agent's context."""

    nudge_type: str = ""  # strategy_extraction | pattern_alert | cost_awareness | reflection_prompt
    message: str = ""
    stage: str = ""
    priority: str = "low"  # low | medium | high
