"""Research orchestrator: stage-gated workflow control layer."""

from .models import (
    GateDecision,
    GateStatus,
    GateType,
    OrchestratorRun,
    ProjectArtifact,
    ReviewIssue,
    ReviewResponse,
    StageEvent,
    StageName,
    StageStatus,
    WorkflowMode,
)
from .integrity import (
    INTEGRITY_PHASES,
    FinalizeManager,
    IntegrityReport,
    IntegrityVerifier,
)
from .review import (
    MAX_REVIEW_CYCLES,
    REVIEW_CATEGORIES,
    REVIEW_DIMENSIONS,
    ReviewManager,
)
from .service import OrchestratorService
from .stages import (
    STAGE_REGISTRY,
    get_required_artifacts,
    get_stage_metadata,
    is_valid_transition,
    next_stage,
    stage_index,
)

__all__ = [
    "WorkflowMode",
    "StageName",
    "StageStatus",
    "GateType",
    "GateStatus",
    "GateDecision",
    "OrchestratorRun",
    "StageEvent",
    "ProjectArtifact",
    "ReviewIssue",
    "ReviewResponse",
    "IntegrityVerifier",
    "IntegrityReport",
    "FinalizeManager",
    "INTEGRITY_PHASES",
    "ReviewManager",
    "MAX_REVIEW_CYCLES",
    "REVIEW_CATEGORIES",
    "REVIEW_DIMENSIONS",
    "OrchestratorService",
    "STAGE_REGISTRY",
    "get_stage_metadata",
    "get_required_artifacts",
    "is_valid_transition",
    "next_stage",
    "stage_index",
]
