"""Orchestrator dataclasses and enums."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MIN_PAPER_COUNT = int(os.environ.get("RH_MIN_CORPUS_SIZE", "50"))

# Gate thresholds (env-overridable)
MIN_GAP_COUNT = int(os.environ.get("RH_MIN_GAP_COUNT", "3"))
MAX_GAP_LOOPBACKS = int(os.environ.get("RH_MAX_GAP_LOOPBACKS", "2"))
MAX_EVIDENCE_LOOPBACKS = int(os.environ.get("RH_MAX_EVIDENCE_LOOPBACKS", "2"))
MAX_EXPERIMENT_LOOPBACKS = int(os.environ.get("RH_MAX_EXPERIMENT_LOOPBACKS", "2"))
MIN_YEAR_SPAN = int(os.environ.get("RH_MIN_YEAR_SPAN", "2"))
MIN_EVIDENCE_COVERAGE = float(os.environ.get("RH_MIN_EVIDENCE_COVERAGE", "0.8"))
MIN_SEED_PAPER_COUNT = int(os.environ.get("RH_MIN_SEED_PAPER_COUNT", "3"))


# ---------------------------------------------------------------------------
# Enums (as string constants for SQLite compatibility)
# ---------------------------------------------------------------------------

WORKFLOW_MODES = ("explore", "standard", "strict", "demo")

LEGACY_STAGE_NAMES = (
    "topic_framing",
    "literature_mapping",
    "paper_acquisition",
    "evidence_structuring",
    "research_direction",
    "adversarial_optimization",
    "study_design",
    "draft_preparation",
    "formal_review",
    "revision",
    "re_review",
    "final_integrity",
    "finalize",
)

STAGE_NAMES = ("init", "build", "analyze", "propose", "experiment", "write")

# Mapping: new 5-stage → legacy substep names
STAGE_SUBSTEP_MAP: dict[str, tuple[str, ...]] = {
    "init": ("topic_framing",),
    "build": ("literature_mapping", "paper_acquisition"),
    "analyze": ("evidence_structuring", "research_direction"),
    "propose": ("adversarial_optimization", "study_design"),
    "experiment": ("experiment_execution",),
    "write": (
        "draft_preparation",
        "formal_review",
        "revision",
        "re_review",
        "final_integrity",
        "finalize",
    ),
}

# Reverse mapping: legacy substep name → new stage name
SUBSTEP_TO_STAGE: dict[str, str] = {
    sub: stage for stage, subs in STAGE_SUBSTEP_MAP.items() for sub in subs
}

# Stage graph: each stage maps to the set of valid next stages.
# Replaces the old linear STAGE_ORDER + LOOPBACK_TRANSITIONS.
# Self-loops allow staying in the same stage for iteration.
STAGE_GRAPH: dict[str, frozenset[str]] = {
    "init": frozenset({"build", "init"}),
    "build": frozenset({"analyze", "build"}),
    "analyze": frozenset({"propose", "build", "analyze"}),
    "propose": frozenset({"experiment", "build", "analyze", "propose"}),
    "experiment": frozenset({"write", "propose", "experiment"}),
    "write": frozenset({"write", "experiment"}),
}

# Backward-compat alias (used in some imports)
LOOPBACK_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "analyze": ("build",),
    "propose": ("build", "analyze"),
    "experiment": ("propose",),
    "write": ("experiment",),
}

STAGE_STATUSES = (
    "not_started",
    "in_progress",
    "blocked",
    "awaiting_review",
    "awaiting_resolution",
    "approved",
    "rejected",
    "completed",
)

GATE_TYPES = (
    "approval_gate",
    "coverage_gate",
    "adversarial_gate",
    "review_gate",
    "integrity_gate",
    "experiment_gate",
)

GATE_STATUSES = (
    "not_evaluated",
    "pass",
    "fail",
    "blocked",
    "needs_manual",
)

GATE_DECISIONS = (
    "pass",
    "fail",
    "needs_approval",
    "needs_coverage",
    "needs_adversarial",
    "needs_review",
    "needs_integrity",
    "needs_experiment",
    "needs_expansion",
)

SEVERITY_LEVELS = ("critical", "high", "medium", "low")

ISSUE_STATUSES = ("open", "in_progress", "resolved", "wontfix")

RESPONSE_TYPES = ("change", "clarify", "dispute", "acknowledge")

RESPONSE_STATUSES = ("proposed", "accepted", "rejected")

ARTIFACT_STATUSES = ("active", "deprecated", "superseded")

# ---------------------------------------------------------------------------
# Autonomy & budget (Phase 0.5)
# ---------------------------------------------------------------------------

AUTONOMY_MODES = ("supervised", "autonomous")
TASK_PROFILES = ("exploratory", "bounded", "benchmark", "writing")

AutonomyMode = str  # one of AUTONOMY_MODES
TaskProfile = str  # one of TASK_PROFILES


# Convenience type aliases
WorkflowMode = str  # one of WORKFLOW_MODES
StageName = str  # one of STAGE_NAMES
StageStatus = str  # one of STAGE_STATUSES
GateType = str  # one of GATE_TYPES
GateStatus = str  # one of GATE_STATUSES
GateDecision = str  # one of GATE_DECISIONS
Severity = str  # one of SEVERITY_LEVELS
IssueStatus = str  # one of ISSUE_STATUSES
ResponseType = str  # one of RESPONSE_TYPES
ResponseStatus = str  # one of RESPONSE_STATUSES
ArtifactStatus = str  # one of ARTIFACT_STATUSES


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StageMetadata:
    """Canonical metadata for a single stage."""

    name: StageName
    display_name: str
    description: str
    predecessor: StageName | None
    required_artifacts: tuple[str, ...]
    fallback_stage: StageName | None
    gate_type: GateType
    soft_prerequisites: tuple[str, ...] = ()


@dataclass
class OrchestratorRun:
    """Current orchestrator state for a topic."""

    id: int
    topic_id: int
    mode: WorkflowMode
    current_stage: StageName
    stage_status: StageStatus
    gate_status: GateStatus
    blocking_issue_count: int = 0
    unresolved_issue_count: int = 0
    latest_plan_artifact_id: int | None = None
    latest_draft_artifact_id: int | None = None
    stop_before: str = ""  # hard stop: advance() refuses to enter this stage
    created_at: str = ""
    updated_at: str = ""


@dataclass
class StageEvent:
    """Append-only record of stage transitions and gate outcomes."""

    id: int
    run_id: int
    topic_id: int
    from_stage: StageName
    to_stage: StageName
    event_type: str
    status: StageStatus
    gate_type: GateType
    actor: str
    rationale: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass
class ProjectArtifact:
    """Typed artifact produced by a stage."""

    id: int
    topic_id: int
    stage: StageName
    artifact_type: str
    status: ArtifactStatus
    version: int
    title: str
    path: str
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_artifact_id: int | None = None
    provenance_record_id: int | None = None
    stale: bool = False
    stale_reason: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ReviewIssue:
    """Blocking or non-blocking finding from review."""

    id: int
    topic_id: int
    review_artifact_id: int | None
    stage: StageName
    review_type: str
    severity: Severity
    category: str
    affected_object_type: str
    affected_object_id: str
    blocking: bool
    status: IssueStatus
    summary: str
    details: str
    recommended_action: str
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ReviewResponse:
    """Traceable response to a review issue."""

    id: int
    issue_id: int
    topic_id: int
    response_type: ResponseType
    status: ResponseStatus
    artifact_id: int | None
    response_text: str
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class RunPolicy:
    """Budget and scope constraints for an orchestrator run."""

    autonomy_mode: str = "supervised"
    task_profile: str = "exploratory"
    max_cost_usd: float = 50.0
    max_wall_time_min: int = 480
    max_tool_calls: int = 500
    max_papers: int = 100
    max_iterations: int = 20
    allowed_tools: tuple[str, ...] | None = None  # None = all allowed
    auto_resolve_gates: bool = False  # True in autonomous mode

    @classmethod
    def for_autonomous(cls, task_profile: str = "bounded", **overrides) -> "RunPolicy":
        """Create a policy for autonomous execution with sensible defaults."""
        defaults = {
            "autonomy_mode": "autonomous",
            "task_profile": task_profile,
            "auto_resolve_gates": True,
            "max_cost_usd": 30.0,
            "max_wall_time_min": 240,
        }
        defaults.update(overrides)
        return cls(**defaults)
