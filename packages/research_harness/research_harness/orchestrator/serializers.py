"""JSON-safe serializers for orchestrator outputs."""

from __future__ import annotations

from typing import Any

from .models import (
    GateDecision,
    OrchestratorRun,
    ProjectArtifact,
    StageEvent,
    StageName,
    StageStatus,
)


def serialize_run(run: OrchestratorRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "topic_id": run.topic_id,
        "mode": run.mode,
        "current_stage": run.current_stage,
        "stage_status": run.stage_status,
        "gate_status": run.gate_status,
        "blocking_issue_count": run.blocking_issue_count,
        "unresolved_issue_count": run.unresolved_issue_count,
        "latest_plan_artifact_id": run.latest_plan_artifact_id,
        "latest_draft_artifact_id": run.latest_draft_artifact_id,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def serialize_artifact(artifact: ProjectArtifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "project_id": artifact.project_id,
        "topic_id": artifact.topic_id,
        "stage": artifact.stage,
        "artifact_type": artifact.artifact_type,
        "status": artifact.status,
        "version": artifact.version,
        "title": artifact.title,
        "path": artifact.path,
        "payload": artifact.payload,
        "metadata": artifact.metadata,
        "parent_artifact_id": artifact.parent_artifact_id,
        "provenance_record_id": artifact.provenance_record_id,
        "created_at": artifact.created_at,
        "updated_at": artifact.updated_at,
    }


def serialize_event(event: StageEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "project_id": event.project_id,
        "topic_id": event.topic_id,
        "from_stage": event.from_stage,
        "to_stage": event.to_stage,
        "event_type": event.event_type,
        "status": event.status,
        "gate_type": event.gate_type,
        "actor": event.actor,
        "rationale": event.rationale,
        "payload": event.payload,
        "created_at": event.created_at,
    }


def serialize_status(status: dict[str, Any]) -> dict[str, Any]:
    """Pass-through with optional pretty formatting hints."""
    return status
