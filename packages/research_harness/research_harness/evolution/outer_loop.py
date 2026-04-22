"""Outer loop — meta-reflection across experiments.

AI-Research-SKILLs-inspired dual loop architecture:
- Inner loop: per-experiment execution (existing orchestrator experiment stage)
- Outer loop: every N experiments, reflect and decide direction

Decisions:
- DEEPEN: refine current hypothesis with tighter experiments
- BROADEN: explore adjacent hypotheses
- PIVOT: abandon current direction, fundamentally different approach
- CONCLUDE: enough evidence, proceed to writing
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..storage.db import Database
from .models import ExperimentEntry, MetaReflection

logger = logging.getLogger(__name__)

VALID_DECISIONS = frozenset({"DEEPEN", "BROADEN", "PIVOT", "CONCLUDE"})
DEFAULT_REFLECTION_INTERVAL = 3


def _get_llm_client(tier: str) -> Any:
    from llm_router.client import LLMClient, resolve_llm_config

    client = LLMClient(resolve_llm_config())
    client._default_tier = tier  # type: ignore[attr-defined]
    return client


def _llm_chat(client: Any, prompt: str) -> str:
    tier = getattr(client, "_default_tier", None)
    return client.chat(prompt, tier=tier)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for marker in ("```json", "```"):
        if marker in text:
            start = text.index(marker) + len(marker)
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass
    return {}


class OuterLoop:
    """Meta-reflection across experiments for research direction decisions."""

    def __init__(
        self,
        db: Database,
        reflection_interval: int = DEFAULT_REFLECTION_INTERVAL,
    ) -> None:
        self._db = db
        self._interval = reflection_interval

    # ---- Experiment Logging ----

    def log_experiment(
        self,
        topic_id: int,
        hypothesis: str,
        *,
        primary_metric_name: str = "",
        primary_metric_value: float | None = None,
        metrics: dict[str, Any] | None = None,
        outcome: str = "pending",
        notes: str = "",
        study_spec_artifact_id: int | None = None,
        result_artifact_id: int | None = None,
    ) -> int:
        """Log an experiment result. Returns the experiment log ID."""
        conn = self._db.connect()
        try:
            # Determine experiment number
            row = conn.execute(
                "SELECT MAX(experiment_number) as n FROM experiment_log WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()
            exp_num = (row["n"] or 0) + 1

            cursor = conn.execute(
                """INSERT INTO experiment_log
                   (project_id, topic_id, experiment_number, hypothesis,
                    study_spec_artifact_id, result_artifact_id,
                    primary_metric_name, primary_metric_value, metrics_json,
                    outcome, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    topic_id,
                    topic_id,
                    exp_num,
                    hypothesis,
                    study_spec_artifact_id,
                    result_artifact_id,
                    primary_metric_name,
                    primary_metric_value,
                    json.dumps(metrics or {}),
                    outcome,
                    notes,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            conn.close()

    # ---- Reflection Logic ----

    def should_reflect(self, topic_id: int) -> bool:
        """Check if it's time for a meta-reflection."""
        conn = self._db.connect()
        try:
            # Count experiments since last reflection
            last_refl = conn.execute(
                """SELECT MAX(id) as last_id FROM meta_reflections
                   WHERE topic_id = ?""",
                (topic_id,),
            ).fetchone()
            last_refl_id = last_refl["last_id"] if last_refl else None

            if last_refl_id:
                # Get experiments reviewed in last reflection
                refl_row = conn.execute(
                    "SELECT experiments_reviewed FROM meta_reflections WHERE id = ?",
                    (last_refl_id,),
                ).fetchone()
                reviewed = (
                    json.loads(refl_row["experiments_reviewed"] or "[]")
                    if refl_row
                    else []
                )
                if reviewed:
                    max_reviewed = max(reviewed)
                    new_count = conn.execute(
                        "SELECT COUNT(*) as n FROM experiment_log WHERE topic_id = ? AND id > ?",
                        (topic_id, max_reviewed),
                    ).fetchone()["n"]
                else:
                    new_count = conn.execute(
                        "SELECT COUNT(*) as n FROM experiment_log WHERE topic_id = ?",
                        (topic_id,),
                    ).fetchone()["n"]
            else:
                new_count = conn.execute(
                    "SELECT COUNT(*) as n FROM experiment_log WHERE topic_id = ?",
                    (topic_id,),
                ).fetchone()["n"]

            return new_count >= self._interval
        finally:
            conn.close()

    def reflect(
        self,
        topic_id: int,
        *,
        force: bool = False,
    ) -> MetaReflection | None:
        """Run a meta-reflection. Returns None if not enough experiments."""
        if not force and not self.should_reflect(topic_id):
            return None

        experiments = self.get_experiment_history(topic_id)
        if not experiments:
            return None

        previous = self.get_reflection_history(topic_id, limit=3)

        # Get topic context
        topic_context = self._get_topic_context(topic_id)

        # Build prompt and call LLM
        prompt = _build_reflection_prompt(experiments, previous, topic_context)
        client = _get_llm_client("medium")
        raw = _llm_chat(client, prompt)
        parsed = _parse_json(raw)

        decision = str(parsed.get("decision", "")).upper()
        if decision not in VALID_DECISIONS:
            decision = "DEEPEN"  # safe default

        # Determine reflection number
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT MAX(reflection_number) as n FROM meta_reflections WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()
            refl_num = (row["n"] or 0) + 1
        finally:
            conn.close()

        exp_ids = [e.id for e in experiments]
        model_name = getattr(client, "model", "unknown")

        reflection = MetaReflection(
            topic_id=topic_id,
            reflection_number=refl_num,
            trigger_type="periodic" if not force else "manual",
            experiments_reviewed=exp_ids,
            patterns_observed=str(parsed.get("patterns", "")).strip(),
            decision=decision,
            reasoning=str(parsed.get("reasoning", "")).strip(),
            next_hypothesis=str(parsed.get("next_hypothesis", "")).strip(),
            confidence=float(parsed.get("confidence", 0.5)),
            model_used=model_name,
        )

        # Persist
        self._save_reflection(reflection)

        return reflection

    # ---- History Queries ----

    def get_experiment_history(
        self,
        topic_id: int,
        *,
        limit: int = 20,
    ) -> list[ExperimentEntry]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT * FROM experiment_log
                   WHERE topic_id = ?
                   ORDER BY experiment_number DESC LIMIT ?""",
                (topic_id, limit),
            ).fetchall()
            return [_row_to_experiment(r) for r in reversed(rows)]
        finally:
            conn.close()

    def get_reflection_history(
        self,
        topic_id: int,
        *,
        limit: int = 10,
    ) -> list[MetaReflection]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT * FROM meta_reflections
                   WHERE topic_id = ?
                   ORDER BY reflection_number DESC LIMIT ?""",
                (topic_id, limit),
            ).fetchall()
            return [_row_to_reflection(r) for r in reversed(rows)]
        finally:
            conn.close()

    def get_experiment_count(self, topic_id: int) -> int:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM experiment_log WHERE topic_id = ?",
                (topic_id,),
            ).fetchone()
            return row["n"] if row else 0
        finally:
            conn.close()

    # ---- Internals ----

    def _get_topic_context(self, topic_id: int) -> str:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT name, description FROM topics WHERE id = ?",
                (topic_id,),
            ).fetchone()
            if row:
                return f"Topic: {row['name']}\nDescription: {row['description'] or '(none)'}"
            return ""
        finally:
            conn.close()

    def _save_reflection(self, r: MetaReflection) -> int:
        conn = self._db.connect()
        try:
            cursor = conn.execute(
                """INSERT INTO meta_reflections
                   (project_id, topic_id, reflection_number, trigger_type,
                    experiments_reviewed, patterns_observed, decision,
                    reasoning, next_hypothesis, confidence, model_used)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r.topic_id,
                    r.topic_id,
                    r.reflection_number,
                    r.trigger_type,
                    json.dumps(r.experiments_reviewed),
                    r.patterns_observed,
                    r.decision,
                    r.reasoning,
                    r.next_hypothesis,
                    r.confidence,
                    r.model_used,
                ),
            )
            conn.commit()
            r.id = cursor.lastrowid or 0
            return r.id
        finally:
            conn.close()


# ---- Prompt ----


def _build_reflection_prompt(
    experiments: list[ExperimentEntry],
    previous_reflections: list[MetaReflection],
    topic_context: str,
) -> str:
    """Build the meta-reflection prompt."""
    exp_lines: list[str] = []
    for e in experiments:
        line = f"[Exp {e.experiment_number}] {e.outcome.upper()}: {e.hypothesis}"
        if e.primary_metric_name and e.primary_metric_value is not None:
            line += f" ({e.primary_metric_name}={e.primary_metric_value})"
        if e.notes:
            line += f"\n  Notes: {e.notes}"
        exp_lines.append(line)

    refl_lines: list[str] = []
    for r in previous_reflections:
        refl_lines.append(
            f"[Reflection {r.reflection_number}] {r.decision}: {r.reasoning}"
        )

    return f"""\
You are a research methodology advisor. Analyze the experiment history and
decide the next research direction.

## Topic Context
{topic_context or "(not available)"}

## Experiment History
{chr(10).join(exp_lines) if exp_lines else "(no experiments yet)"}

## Previous Reflections
{chr(10).join(refl_lines) if refl_lines else "(first reflection)"}

## Task
Analyze cross-experiment patterns and decide one of:
- **DEEPEN**: Current hypothesis is promising, refine with tighter experiments
- **BROADEN**: Current direction works but explore adjacent hypotheses too
- **PIVOT**: Current approach isn't working, try a fundamentally different one
- **CONCLUDE**: Enough evidence gathered, ready to proceed to paper writing

Return JSON:
{{
  "patterns": "2-3 sentence summary of observed patterns across experiments",
  "decision": "DEEPEN" | "BROADEN" | "PIVOT" | "CONCLUDE",
  "reasoning": "2-3 sentences explaining why this decision",
  "next_hypothesis": "specific hypothesis for next experiment (if not CONCLUDE)",
  "confidence": 0.0-1.0
}}"""


# ---- Row converters ----


def _row_to_experiment(row: Any) -> ExperimentEntry:
    metrics_raw = row["metrics_json"] or "{}"
    try:
        metrics = json.loads(metrics_raw)
    except (json.JSONDecodeError, TypeError):
        metrics = {}
    return ExperimentEntry(
        id=row["id"],
        topic_id=row["topic_id"],
        experiment_number=row["experiment_number"],
        hypothesis=row["hypothesis"],
        study_spec_artifact_id=row["study_spec_artifact_id"],
        result_artifact_id=row["result_artifact_id"],
        primary_metric_name=row["primary_metric_name"] or "",
        primary_metric_value=row["primary_metric_value"],
        metrics=metrics,
        outcome=row["outcome"],
        notes=row["notes"] or "",
        created_at=row["created_at"] or "",
    )


def _row_to_reflection(row: Any) -> MetaReflection:
    reviewed_raw = row["experiments_reviewed"] or "[]"
    try:
        reviewed = json.loads(reviewed_raw)
    except (json.JSONDecodeError, TypeError):
        reviewed = []
    return MetaReflection(
        id=row["id"],
        topic_id=row["topic_id"],
        reflection_number=row["reflection_number"],
        trigger_type=row["trigger_type"],
        experiments_reviewed=reviewed,
        patterns_observed=row["patterns_observed"] or "",
        decision=row["decision"],
        reasoning=row["reasoning"],
        next_hypothesis=row["next_hypothesis"] or "",
        confidence=row["confidence"] or 0.5,
        model_used=row["model_used"] or "",
        created_at=row["created_at"] or "",
    )
