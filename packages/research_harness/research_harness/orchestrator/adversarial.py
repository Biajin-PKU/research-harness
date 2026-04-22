"""Adversarial optimization: proposer/auditor/resolver protocol.

This module formalizes the structured challenge-and-resolution cycle
for high-risk research decisions (direction selection, study design).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..storage.db import Database
from .artifacts import ArtifactManager


@dataclass
class Objection:
    """A single objection raised by the auditor."""

    category: str
    severity: str  # critical, major, minor
    target: str
    reasoning: str
    suggested_fix: str = ""


@dataclass
class AdversarialRound:
    """One round of proposal, audit, and response."""

    round_number: int
    target_artifact_id: int
    target_stage: str
    proposal_snapshot: dict[str, Any] = field(default_factory=dict)
    objections: list[Objection] = field(default_factory=list)
    proposer_responses: list[dict[str, Any]] = field(default_factory=list)
    unresolved_objections: list[Objection] = field(default_factory=list)
    resolver_notes: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "target_artifact_id": self.target_artifact_id,
            "target_stage": self.target_stage,
            "proposal_snapshot": self.proposal_snapshot,
            "objections": [
                {
                    "category": o.category,
                    "severity": o.severity,
                    "target": o.target,
                    "reasoning": o.reasoning,
                    "suggested_fix": o.suggested_fix,
                }
                for o in self.objections
            ],
            "proposer_responses": self.proposer_responses,
            "unresolved_objections": [
                {
                    "category": o.category,
                    "severity": o.severity,
                    "target": o.target,
                    "reasoning": o.reasoning,
                }
                for o in self.unresolved_objections
            ],
            "resolver_notes": self.resolver_notes,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AdversarialRound":
        objections = [
            Objection(
                category=o.get("category", ""),
                severity=o.get("severity", "minor"),
                target=o.get("target", ""),
                reasoning=o.get("reasoning", ""),
                suggested_fix=o.get("suggested_fix", ""),
            )
            for o in payload.get("objections", [])
        ]
        unresolved = [
            Objection(
                category=o.get("category", ""),
                severity=o.get("severity", "minor"),
                target=o.get("target", ""),
                reasoning=o.get("reasoning", ""),
            )
            for o in payload.get("unresolved_objections", [])
        ]
        return cls(
            round_number=payload.get("round_number", 0),
            target_artifact_id=payload.get("target_artifact_id", 0),
            target_stage=payload.get("target_stage", ""),
            proposal_snapshot=payload.get("proposal_snapshot", {}),
            objections=objections,
            proposer_responses=payload.get("proposer_responses", []),
            unresolved_objections=unresolved,
            resolver_notes=payload.get("resolver_notes", ""),
        )


@dataclass
class AdversarialResolution:
    """Outcome of an adversarial round."""

    outcome: (
        str  # approved, approved_with_conditions, revise_and_repeat, reject_and_return
    )
    scores: dict[str, float] = field(default_factory=dict)
    mean_score: float = 0.0
    critical_unresolved: int = 0
    major_unresolved: int = 0
    round_number: int = 0
    notes: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "scores": self.scores,
            "mean_score": self.mean_score,
            "critical_unresolved": self.critical_unresolved,
            "major_unresolved": self.major_unresolved,
            "round_number": self.round_number,
            "notes": self.notes,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AdversarialResolution":
        return cls(
            outcome=payload.get("outcome", "revise_and_repeat"),
            scores=payload.get("scores", {}),
            mean_score=payload.get("mean_score", 0.0),
            critical_unresolved=payload.get("critical_unresolved", 0),
            major_unresolved=payload.get("major_unresolved", 0),
            round_number=payload.get("round_number", 0),
            notes=payload.get("notes", ""),
        )


class AdversarialLoop:
    """Manages adversarial rounds for a project."""

    MAX_ROUNDS: dict[str, int] = {
        "explore": 2,
        "standard": 3,
        "strict": 5,
        "demo": 2,
    }

    SCORE_DIMENSIONS: tuple[str, ...] = (
        "novelty",
        "evidence_coverage",
        "method_validity",
        "baseline_completeness",
        "scope_discipline",
        "falsifiability",
        "clarity",
    )

    def __init__(self, db: Database):
        self._db = db
        self._artifact_manager = ArtifactManager(db)

    def get_max_rounds(self, mode: str) -> int:
        return self.MAX_ROUNDS.get(mode, 3)

    def run_round(
        self,
        topic_id: int,
        target_artifact_id: int,
        target_stage: str,
        round_number: int,
        proposal_snapshot: dict[str, Any],
        objections: list[Objection],
        proposer_responses: list[dict[str, Any]] | None = None,
        resolver_notes: str = "",
    ) -> dict[str, Any]:
        """Record an adversarial round artifact."""
        unresolved = self._compute_unresolved(objections, proposer_responses or [])

        round_obj = AdversarialRound(
            round_number=round_number,
            target_artifact_id=target_artifact_id,
            target_stage=target_stage,
            proposal_snapshot=proposal_snapshot,
            objections=objections,
            proposer_responses=proposer_responses or [],
            unresolved_objections=unresolved,
            resolver_notes=resolver_notes,
        )

        artifact = self._artifact_manager.record(
            topic_id=topic_id,
            stage=target_stage,
            artifact_type="adversarial_round",
            title=f"Adversarial Round {round_number}",
            payload=round_obj.to_payload(),
            metadata={
                "round_number": round_number,
                "target_artifact_id": target_artifact_id,
            },
        )

        return {
            "artifact_id": artifact.id,
            "round": round_obj.to_payload(),
        }

    def resolve_round(
        self,
        topic_id: int,
        target_stage: str,
        round_number: int,
        round_artifact_id: int,
        scores: dict[str, float] | None = None,
        notes: str = "",
        parent_artifact_id: int | None = None,
    ) -> dict[str, Any]:
        """Record an adversarial resolution artifact."""
        # Fetch the round to compute unresolved counts
        round_artifact = self._artifact_manager.get(round_artifact_id)
        if round_artifact is None:
            raise ValueError(f"Round artifact {round_artifact_id} not found")

        round_payload = round_artifact.payload
        round_obj = AdversarialRound.from_payload(round_payload)

        critical = sum(
            1 for o in round_obj.unresolved_objections if o.severity == "critical"
        )
        major = sum(1 for o in round_obj.unresolved_objections if o.severity == "major")

        computed_scores = scores or {}
        mean_score = (
            sum(computed_scores.values()) / len(computed_scores)
            if computed_scores
            else 0.0
        )

        outcome = self._determine_outcome(
            critical=critical,
            major=major,
            mean_score=mean_score,
        )

        resolution = AdversarialResolution(
            outcome=outcome,
            scores=computed_scores,
            mean_score=mean_score,
            critical_unresolved=critical,
            major_unresolved=major,
            round_number=round_number,
            notes=notes,
        )

        artifact = self._artifact_manager.record(
            topic_id=topic_id,
            stage=target_stage,
            artifact_type="adversarial_resolution",
            title=f"Resolution Round {round_number}",
            payload=resolution.to_payload(),
            metadata={
                "round_number": round_number,
                "outcome": outcome,
                "mean_score": mean_score,
            },
            parent_artifact_id=parent_artifact_id or round_artifact_id,
        )

        return {
            "artifact_id": artifact.id,
            "resolution": resolution.to_payload(),
        }

    def should_repeat(
        self,
        topic_id: int,
        target_stage: str,
        mode: str,
    ) -> tuple[bool, str]:
        """Determine if another adversarial round is needed.

        Returns (should_repeat, reason).
        """
        # Fetch latest resolution
        resolution_artifact = self._artifact_manager.get_latest(
            topic_id, target_stage, "adversarial_resolution"
        )
        if resolution_artifact is None:
            return True, "No resolution recorded yet"

        resolution = AdversarialResolution.from_payload(resolution_artifact.payload)

        if resolution.outcome in ("approved", "approved_with_conditions"):
            return False, f"Resolution outcome: {resolution.outcome}"

        if resolution.outcome == "reject_and_return":
            return False, "Proposal rejected"

        # Check max rounds
        max_rounds = self.get_max_rounds(mode)
        round_count = self._count_rounds(topic_id, target_stage)
        if round_count >= max_rounds:
            return False, f"Max rounds ({max_rounds}) reached"

        return (
            True,
            f"Round {round_count}/{max_rounds}: outcome was {resolution.outcome}",
        )

    def check_convergence(
        self,
        scores: dict[str, float],
        critical_unresolved: int,
        mode: str = "standard",
    ) -> tuple[bool, str]:
        """Check if adversarial process has converged.

        Returns (converged, reason).
        """
        if critical_unresolved > 0:
            return False, f"{critical_unresolved} critical objections unresolved"

        if not scores:
            return False, "No scores provided"

        mean = sum(scores.values()) / len(scores)
        threshold = 4.0 if mode == "standard" else 4.5

        # Check key dimensions
        key_dims = ("novelty", "evidence_coverage", "method_validity")
        for dim in key_dims:
            if dim in scores and scores[dim] < 4:
                return False, f"{dim} score {scores[dim]} below 4"

        if mean < threshold:
            return False, f"Mean score {mean:.1f} below threshold {threshold}"

        return True, f"Converged: mean={mean:.1f}, no critical objections"

    def _compute_unresolved(
        self,
        objections: list[Objection],
        responses: list[dict[str, Any]],
    ) -> list[Objection]:
        """Compute which objections remain unresolved after responses."""
        if not responses:
            return list(objections)

        resolved_targets = {
            r.get("target", "") for r in responses if r.get("resolved", False)
        }
        return [o for o in objections if o.target not in resolved_targets]

    def _determine_outcome(
        self,
        critical: int,
        major: int,
        mean_score: float,
    ) -> str:
        """Determine resolution outcome from metrics."""
        if critical > 0:
            return "revise_and_repeat"
        if mean_score >= 4.0 and major == 0:
            return "approved"
        if mean_score >= 4.0 and major > 0:
            return "approved_with_conditions"
        if mean_score < 3.0:
            return "reject_and_return"
        return "revise_and_repeat"

    def _count_rounds(self, topic_id: int, target_stage: str) -> int:
        """Count how many adversarial rounds have been recorded."""
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM project_artifacts
                WHERE topic_id = ? AND stage = ? AND artifact_type = 'adversarial_round' AND status = 'active'
                """,
                (topic_id, target_stage),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()
