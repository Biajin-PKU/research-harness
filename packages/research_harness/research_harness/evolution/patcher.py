"""Strategy patcher — incremental updates instead of full rewrites.

When new lessons arrive that relate to an existing strategy:
1. Check if existing strategy needs update (staleness detection)
2. Generate a targeted patch (add/modify/remove sections)
3. Apply patch to create new version (old version → superseded)
4. Quality gate the patched version

Also manages probation: new strategies start as 'draft' and are promoted
to 'active' only after being injected in N sessions with positive outcomes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ..storage.db import Database
from .models import Strategy
from .store import DBLessonStore, Lesson

logger = logging.getLogger(__name__)

PROBATION_INJECTION_THRESHOLD = 3  # must be injected N times
PROBATION_POSITIVE_THRESHOLD = 1   # must have at least 1 positive feedback


@dataclass
class StaleCheckResult:
    """Result of checking if a strategy is stale."""

    strategy_id: int = 0
    is_stale: bool = False
    new_lesson_count: int = 0
    reason: str = ""


def _get_llm_client(tier: str) -> Any:
    from paperindex.llm.client import LLMClient, resolve_llm_config
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


class StrategyPatcher:
    """Incremental strategy patching with probation management."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._lesson_store = DBLessonStore(db)

    # ---- Staleness Detection ----

    def check_stale(self, strategy_id: int) -> StaleCheckResult:
        """Check if a strategy has newer lessons that warrant an update."""
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM strategies WHERE id = ?", (strategy_id,),
            ).fetchone()
            if not row:
                return StaleCheckResult(strategy_id=strategy_id, reason="not found")

            # Count lessons created after this strategy
            new_lessons = conn.execute(
                """SELECT COUNT(*) as n FROM lessons
                   WHERE stage = ? AND created_at > ?""",
                (row["stage"], row["created_at"]),
            ).fetchone()
            new_count = new_lessons["n"] if new_lessons else 0

            is_stale = new_count >= 3  # at least 3 new lessons to justify a patch
            reason = f"{new_count} new lessons since strategy creation" if is_stale else ""

            return StaleCheckResult(
                strategy_id=strategy_id,
                is_stale=is_stale,
                new_lesson_count=new_count,
                reason=reason,
            )
        finally:
            conn.close()

    # ---- Incremental Patching ----

    def patch_strategy(
        self, strategy_id: int,
    ) -> Strategy | None:
        """Generate and apply an incremental patch to a strategy.

        Returns the new version if accepted, None if rejected by gate.
        """
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM strategies WHERE id = ?", (strategy_id,),
            ).fetchone()
            if not row:
                return None

            # Get new lessons since strategy was created
            new_lessons = conn.execute(
                """SELECT * FROM lessons
                   WHERE stage = ? AND created_at > ?
                   ORDER BY created_at DESC LIMIT 10""",
                (row["stage"], row["created_at"]),
            ).fetchall()
        finally:
            conn.close()

        if not new_lessons:
            return None

        evidence = "\n".join(
            f"- [{r['lesson_type']}] {r['content']}" for r in new_lessons
        )

        # Generate patch via LLM (light tier)
        patched_content = self._generate_patch(row["content"], evidence)
        if not patched_content:
            return None

        # Quality gate (medium tier)
        score, gate_model, accepted = self._quality_gate(patched_content, row["stage"])
        if not accepted:
            logger.info("Patch rejected for strategy %d (score=%.2f)", strategy_id, score)
            return None

        # Create new version
        return self._create_new_version(row, patched_content, score, gate_model)

    def _generate_patch(self, existing_content: str, new_evidence: str) -> str:
        """Generate a patched version via LLM (light tier)."""
        prompt = f"""\
You are a research strategy editor. Update the following strategy with new evidence.
Make TARGETED changes only — do not rewrite from scratch. Preserve what works.

## Existing Strategy
{existing_content}

## New Evidence Since Last Update
{new_evidence}

## Task
Update the strategy to incorporate the new evidence. Changes should be:
1. Additive where possible (add new steps, warnings, tips)
2. Corrective where evidence shows the old advice was wrong
3. Minimal — don't change what's still valid

Return JSON: {{"patched_content": "<updated markdown>"}}"""

        client = _get_llm_client("light")
        raw = _llm_chat(client, prompt)
        parsed = _parse_json(raw)
        content = str(parsed.get("patched_content", "")).strip()
        return content if content else raw.strip() if raw.strip() else ""

    def _quality_gate(
        self, content: str, stage: str,
    ) -> tuple[float, str, bool]:
        """Quality gate for patched content (medium tier)."""
        from .prompts import quality_gate_prompt
        prompt = quality_gate_prompt(content, stage)
        client = _get_llm_client("medium")
        raw = _llm_chat(client, prompt)
        parsed = _parse_json(raw)

        scores = parsed.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}

        dim_scores = [
            float(scores.get("evidence_grounded", 0)),
            float(scores.get("preserves_existing", 0)),
            float(scores.get("specific_reusable", 0)),
            float(scores.get("safe_to_publish", 0)),
        ]
        overall = float(parsed.get("overall", 0))
        if overall == 0 and any(s > 0 for s in dim_scores):
            overall = sum(dim_scores) / len(dim_scores)

        decision = str(parsed.get("decision", "")).lower()
        accepted = decision == "accept" and overall >= 0.75

        model_name = getattr(client, "model", "unknown")
        return overall, model_name, accepted

    def _create_new_version(
        self, old_row: Any, new_content: str,
        quality_score: float, gate_model: str,
    ) -> Strategy:
        """Create a new version of a strategy, superseding the old one."""
        conn = self._db.connect()
        try:
            new_version = old_row["version"] + 1

            # Supersede old
            conn.execute(
                "UPDATE strategies SET status = 'superseded' WHERE id = ?",
                (old_row["id"],),
            )

            # Insert new
            conn.execute(
                """INSERT INTO strategies
                   (stage, strategy_key, title, content, scope, topic_id, version,
                    quality_score, gate_model, source_lesson_ids,
                    source_session_count, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
                (
                    old_row["stage"], old_row["strategy_key"], old_row["title"],
                    new_content, old_row["scope"], old_row["topic_id"],
                    new_version, quality_score, gate_model,
                    old_row["source_lesson_ids"], old_row["source_session_count"],
                ),
            )
            new_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        return Strategy(
            id=new_id,
            stage=old_row["stage"],
            strategy_key=old_row["strategy_key"],
            title=old_row["title"],
            content=new_content,
            version=new_version,
            quality_score=quality_score,
            status="active",
        )

    # ---- Probation Management ----

    def check_promotions(self) -> list[int]:
        """Check draft strategies eligible for promotion to active.

        Returns list of promoted strategy IDs.
        """
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT id, injection_count, positive_feedback
                   FROM strategies
                   WHERE status = 'draft'
                     AND injection_count >= ?
                     AND positive_feedback >= ?""",
                (PROBATION_INJECTION_THRESHOLD, PROBATION_POSITIVE_THRESHOLD),
            ).fetchall()

            promoted: list[int] = []
            for r in rows:
                conn.execute(
                    "UPDATE strategies SET status = 'active', updated_at = datetime('now') WHERE id = ?",
                    (r["id"],),
                )
                promoted.append(r["id"])

            if promoted:
                conn.commit()
                logger.info("Promoted %d strategies from draft to active", len(promoted))

            return promoted
        finally:
            conn.close()

    def get_draft_strategies(self) -> list[dict[str, Any]]:
        """Get all draft strategies with their probation progress."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT id, strategy_key, title, injection_count, positive_feedback
                   FROM strategies WHERE status = 'draft'"""
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "strategy_key": r["strategy_key"],
                    "title": r["title"],
                    "injection_count": r["injection_count"],
                    "positive_feedback": r["positive_feedback"],
                    "injections_needed": max(0, PROBATION_INJECTION_THRESHOLD - r["injection_count"]),
                    "feedback_needed": max(0, PROBATION_POSITIVE_THRESHOLD - (r["positive_feedback"] or 0)),
                }
                for r in rows
            ]
        finally:
            conn.close()
