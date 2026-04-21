"""Provenance data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProvenanceRecord:
    """A single provenance record stored in DB."""

    id: int
    primitive: str
    category: str
    started_at: str
    finished_at: str
    backend: str
    model_used: str
    topic_id: int | None
    stage: str
    input_hash: str
    output_hash: str
    cost_usd: float
    success: bool
    error: str
    parent_id: int | None = None
    artifact_id: int | None = None
    quality_score: float | None = None
    human_accept: bool | None = None
    loop_round: int = 0
    created_at: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class ProvenanceSummary:
    """Aggregated provenance statistics."""

    total_operations: int = 0
    total_cost_usd: float = 0.0
    operations_by_backend: dict[str, int] = field(default_factory=dict)
    operations_by_primitive: dict[str, int] = field(default_factory=dict)
    cost_by_backend: dict[str, float] = field(default_factory=dict)
    cost_by_primitive: dict[str, float] = field(default_factory=dict)
    success_rate: float = 1.0
    time_range: tuple[str, str] = ("", "")
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    tokens_by_backend: dict[str, dict[str, int]] = field(default_factory=dict)
    tokens_by_primitive: dict[str, dict[str, int]] = field(default_factory=dict)
