"""V2 Self-Evolution Phase 2: Experience Validation Gate.

Two-tier filtering that prevents low-quality or irrelevant experience
from polluting the lesson/strategy store:

- **Tier 1 (per-record)**: rule-based + optional LLM scoring for applicability
- **Tier 2 (per-strategy)**: evaluates whether a strategy is still effective
  given recent experience records (future — deferred to Phase 4 integration)

The gate is non-blocking: it never prevents ingestion, only labels records
with accepted/rejected/deferred verdicts for downstream filtering.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

FIELD_DECAY_CONSTANTS: dict[str, float] = {
    "llm_systems": 18.0,
    "information_retrieval": 30.0,
    "data_mining": 30.0,
    "software_engineering": 36.0,
    "computer_vision": 24.0,
    "nlp": 20.0,
    "default": 30.0,
}

ACCEPT_THRESHOLD = 0.4
REJECT_THRESHOLD = 0.2


def temporal_relevance(age_months: float, field: str = "default") -> float:
    tau = FIELD_DECAY_CONSTANTS.get(field, FIELD_DECAY_CONSTANTS["default"])
    return math.exp(-age_months / tau)


@dataclass
class GateVerdict:
    verdict: str  # accepted | rejected | deferred
    score: float
    reasoning: str = ""
    rule_scores: dict[str, float] | None = None

    @property
    def is_accepted(self) -> bool:
        return self.verdict == "accepted"


class ValidationGate:
    def __init__(self, db: Any) -> None:
        self._db = db

    def evaluate_tier1(self, record: Any) -> GateVerdict:
        from .experience import ExperienceRecord

        if not isinstance(record, ExperienceRecord):
            return GateVerdict(verdict="rejected", score=0.0, reasoning="Invalid record type")

        # Human edits are always trusted
        if record.source_kind == "human_edit":
            verdict = GateVerdict(
                verdict="accepted",
                score=1.0,
                reasoning="Human edits bypass gate",
                rule_scores={"human_trust": 1.0},
            )
            self._persist_trace(record, verdict, "tier1")
            return verdict

        scores: dict[str, float] = {}

        # Rule 1: Content presence
        content = record.diff_summary or record.after_text or record.before_text
        if not content or len(content.strip()) < 10:
            verdict = GateVerdict(
                verdict="rejected",
                score=0.0,
                reasoning="No meaningful content in experience record",
                rule_scores={"content_presence": 0.0},
            )
            self._persist_trace(record, verdict, "tier1")
            return verdict
        scores["content_presence"] = min(1.0, len(content.strip()) / 50.0)

        # Rule 2: Source reliability
        source_weights = {
            "human_edit": 1.0,
            "gold_comparison": 0.9,
            "self_review": 0.7,
            "auto_extracted": 0.5,
        }
        scores["source_reliability"] = source_weights.get(record.source_kind, 0.3)

        # Rule 3: Quality delta (for gold_comparison)
        if record.source_kind == "gold_comparison":
            if record.quality_delta > 0.1:
                scores["quality_signal"] = min(1.0, record.quality_delta)
            elif record.quality_delta == 0.0:
                scores["quality_signal"] = 0.3  # deferred territory
            else:
                scores["quality_signal"] = 0.1
        else:
            scores["quality_signal"] = 0.7  # neutral for non-gold

        # Composite score
        weights = {"content_presence": 0.3, "source_reliability": 0.4, "quality_signal": 0.3}
        composite = sum(scores.get(k, 0) * w for k, w in weights.items())

        if composite >= ACCEPT_THRESHOLD:
            verdict_str = "accepted"
        elif composite >= REJECT_THRESHOLD:
            verdict_str = "deferred"
        else:
            verdict_str = "rejected"

        verdict = GateVerdict(
            verdict=verdict_str,
            score=composite,
            reasoning=f"Rule scores: {scores}",
            rule_scores=scores,
        )
        self._persist_trace(record, verdict, "tier1")
        return verdict

    def _persist_trace(self, record: Any, verdict: GateVerdict, tier: str) -> None:
        if not hasattr(record, "id") or record.id == 0:
            return
        try:
            conn = self._db.connect()
            try:
                conn.execute(
                    """INSERT INTO validation_traces
                       (experience_id, tier, verdict, score, reasoning, rule_scores)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        record.id,
                        tier,
                        verdict.verdict,
                        verdict.score,
                        verdict.reasoning,
                        json.dumps(verdict.rule_scores or {}),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("Could not persist validation trace: %s", exc)
