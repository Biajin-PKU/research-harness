"""Strategy distiller — SkillClaw-inspired pipeline to convert lessons into strategies.

5-phase pipeline:
1. Collect: gather lessons + trajectory evidence for a stage
2. Aggregate: LLM clusters evidence into themes (light tier)
3. Distill: LLM generates strategy text per theme (light tier)
4. Gate: LLM 4-dimension quality evaluation (medium tier)
5. Persist: write to DB + STRATEGY.md file

All LLM calls go through the existing tier routing. Never uses Anthropic.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..storage.db import Database
from . import prompts as evo_prompts
from .models import Strategy, StrategyDistillResult
from .store import DBLessonStore, Lesson
from .trajectory import TrajectoryRecorder

logger = logging.getLogger(__name__)

QUALITY_THRESHOLD = 0.75


def _get_llm_client(tier: str) -> Any:
    """Get an LLM client via the shared paperindex routing."""
    from paperindex.llm.client import LLMClient, resolve_llm_config
    client = LLMClient(resolve_llm_config())
    client._default_tier = tier  # type: ignore[attr-defined]
    return client


def _llm_chat(client: Any, prompt: str) -> str:
    tier = getattr(client, "_default_tier", None)
    return client.chat(prompt, tier=tier)


def _parse_json(text: str) -> dict[str, Any]:
    """Best-effort JSON parse from LLM output."""
    text = text.strip()
    if not text:
        return {}
    # Try raw
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown code block
    for marker in ("```json", "```"):
        if marker in text:
            start = text.index(marker) + len(marker)
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass
    return {}


class StrategyDistiller:
    """Distills lessons and trajectories into reusable strategies."""

    def __init__(self, db: Database, strategies_dir: Path | str) -> None:
        self._db = db
        self._strategies_dir = Path(strategies_dir)
        self._strategies_dir.mkdir(parents=True, exist_ok=True)
        self._lesson_store = DBLessonStore(db)

    def distill_stage(
        self,
        stage: str,
        *,
        min_lessons: int = 3,
        topic_id: int | None = None,
        force: bool = False,
    ) -> StrategyDistillResult:
        """Run the full distillation pipeline for one stage."""
        result = StrategyDistillResult(stage=stage)

        # Phase 1: Collect
        evidence = self._collect_evidence(stage, topic_id=topic_id)
        if not force and evidence["lesson_count"] < min_lessons:
            logger.info(
                "Not enough lessons for %s (%d < %d)",
                stage, evidence["lesson_count"], min_lessons,
            )
            return result

        # Phase 2: Aggregate into themes
        themes = self._aggregate_themes(stage, evidence)
        if not themes:
            logger.info("No themes found for stage %s", stage)
            return result

        # Phase 3+4+5: Distill, gate, persist each theme
        for theme in themes:
            strategy_text = self._distill_strategy(stage, theme)
            if not strategy_text:
                result.strategies_skipped += 1
                continue

            score, gate_model, accepted = self._quality_gate(strategy_text, stage)
            result.quality_scores.append(score)

            if accepted:
                self._persist_strategy(
                    stage=stage,
                    strategy_key=f"{stage}.{theme['theme_key']}",
                    title=theme["title"],
                    content=strategy_text,
                    quality_score=score,
                    gate_model=gate_model,
                    lesson_ids=theme.get("evidence_ids", []),
                    scope=theme.get("scope", "global"),
                    topic_id=topic_id,
                )
                result.strategies_created += 1
            else:
                # Store as draft for potential future promotion
                self._persist_strategy(
                    stage=stage,
                    strategy_key=f"{stage}.{theme['theme_key']}",
                    title=theme["title"],
                    content=strategy_text,
                    quality_score=score,
                    gate_model=gate_model,
                    lesson_ids=theme.get("evidence_ids", []),
                    scope=theme.get("scope", "global"),
                    topic_id=topic_id,
                    status="draft",
                )
                result.strategies_skipped += 1

        # Write consolidated STRATEGY.md for this stage
        self._write_strategy_file(stage)

        return result

    def distill_all(self, *, min_lessons: int = 3) -> list[StrategyDistillResult]:
        """Distill strategies for all stages that have enough lessons."""
        stages = self._get_stages_with_lessons()
        results = []
        for stage in stages:
            r = self.distill_stage(stage, min_lessons=min_lessons)
            results.append(r)
        return results

    # ---- Phase 1: Collect ----

    def _collect_evidence(
        self, stage: str, *, topic_id: int | None = None,
    ) -> dict[str, Any]:
        """Gather lessons and trajectory snippets for a stage."""
        lessons = self._lesson_store.query(
            stage, top_k=30, topic_id=topic_id,
        )
        trajectory_events = TrajectoryRecorder.get_stage_trajectories(
            self._db, stage, topic_id=topic_id, limit=50,
        )

        # Build evidence text
        parts: list[str] = []
        for i, lesson in enumerate(lessons):
            parts.append(
                f"[L{i+1}] [{lesson.lesson_type}] {lesson.content}"
            )
        if trajectory_events:
            parts.append("\n--- Trajectory Patterns ---")
            traj_text = TrajectoryRecorder.format_trajectory_text(
                trajectory_events[:20]
            )
            parts.append(traj_text)

        return {
            "evidence_text": "\n".join(parts),
            "lesson_count": len(lessons),
            "trajectory_count": len(trajectory_events),
            "lessons": lessons,
        }

    # ---- Phase 2: Aggregate ----

    def _aggregate_themes(
        self, stage: str, evidence: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """LLM clusters evidence into themes (light tier)."""
        prompt = evo_prompts.aggregate_themes_prompt(
            stage, evidence["evidence_text"],
        )
        client = _get_llm_client("light")
        raw = _llm_chat(client, prompt)
        parsed = _parse_json(raw)

        themes = parsed.get("themes", [])
        if not isinstance(themes, list):
            return []

        # Validate and clean themes
        valid: list[dict[str, Any]] = []
        for t in themes:
            if not isinstance(t, dict):
                continue
            key = str(t.get("theme_key", "")).strip()
            title = str(t.get("title", "")).strip()
            if not key or not title:
                continue
            # Sanitize key to valid slug
            key = key.lower().replace(" ", "_").replace("-", "_")
            t["theme_key"] = key
            t["title"] = title
            t["summary"] = str(t.get("summary", "")).strip()
            t["evidence_ids"] = [
                int(x) for x in (t.get("evidence_ids") or [])
                if str(x).isdigit()
            ]
            t["scope"] = t.get("scope", "global")
            valid.append(t)

        return valid[:5]  # Cap at 5 themes

    # ---- Phase 3: Distill ----

    def _distill_strategy(
        self, stage: str, theme: dict[str, Any],
    ) -> str:
        """LLM generates strategy text for a theme (light tier)."""
        # Gather supporting lesson content for this theme
        evidence_ids = theme.get("evidence_ids", [])
        if evidence_ids:
            supporting_lessons = self._lesson_store.get_by_ids(evidence_ids)
            evidence_text = "\n".join(
                f"- [{l.lesson_type}] {l.content}" for l in supporting_lessons
            )
        else:
            evidence_text = theme.get("summary", "")

        prompt = evo_prompts.distill_strategy_prompt(
            stage=stage,
            theme_key=theme["theme_key"],
            theme_title=theme["title"],
            theme_summary=theme.get("summary", ""),
            supporting_evidence=evidence_text,
        )
        client = _get_llm_client("light")
        raw = _llm_chat(client, prompt)
        parsed = _parse_json(raw)
        content = str(parsed.get("content", "")).strip()
        # Fallback: if no JSON, use the raw text
        if not content and raw.strip():
            content = raw.strip()
        return content

    # ---- Phase 4: Quality Gate ----

    def _quality_gate(
        self, strategy_text: str, stage: str,
    ) -> tuple[float, str, bool]:
        """LLM 4-dimension quality evaluation (medium tier).

        Returns (overall_score, model_used, accepted).
        """
        prompt = evo_prompts.quality_gate_prompt(strategy_text, stage)
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
        accepted = decision == "accept" and overall >= QUALITY_THRESHOLD

        model_name = getattr(client, "model", "unknown")
        return overall, model_name, accepted

    # ---- Phase 5: Persist ----

    def _persist_strategy(
        self,
        *,
        stage: str,
        strategy_key: str,
        title: str,
        content: str,
        quality_score: float,
        gate_model: str,
        lesson_ids: list[int],
        scope: str = "global",
        topic_id: int | None = None,
        status: str = "active",
    ) -> Strategy:
        """Write strategy to DB. Returns the Strategy object."""
        conn = self._db.connect()
        try:
            # Check for existing version
            existing = conn.execute(
                "SELECT MAX(version) as v FROM strategies WHERE strategy_key = ?",
                (strategy_key,),
            ).fetchone()
            version = (existing["v"] or 0) + 1 if existing else 1

            # Mark previous versions as superseded
            if version > 1:
                conn.execute(
                    "UPDATE strategies SET status = 'superseded' WHERE strategy_key = ? AND status != 'superseded'",
                    (strategy_key,),
                )

            conn.execute(
                """INSERT INTO strategies
                   (stage, strategy_key, title, content, scope, topic_id, version,
                    quality_score, gate_model, source_lesson_ids,
                    source_session_count, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    stage, strategy_key, title, content, scope, topic_id,
                    version, quality_score, gate_model,
                    json.dumps(lesson_ids), len(lesson_ids), status,
                ),
            )
            sid = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
            conn.commit()
        finally:
            conn.close()

        return Strategy(
            id=sid,
            stage=stage,
            strategy_key=strategy_key,
            title=title,
            content=content,
            scope=scope,
            topic_id=topic_id,
            version=version,
            quality_score=quality_score,
            gate_model=gate_model,
            source_lesson_ids=lesson_ids,
            status=status,
        )

    def _write_strategy_file(self, stage: str) -> Path:
        """Write consolidated STRATEGY.md for a stage from all active strategies."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT * FROM strategies
                   WHERE stage = ? AND status = 'active'
                   ORDER BY quality_score DESC""",
                (stage,),
            ).fetchall()
        finally:
            conn.close()

        path = self._strategies_dir / f"{stage}.md"
        lines = [f"# Strategies for Stage: {stage}\n"]
        lines.append(f"_Auto-generated from {len(rows)} active strategies._\n")

        if not rows:
            lines.append("No active strategies yet.\n")
        else:
            for row in rows:
                lines.append(f"## {row['title']}")
                lines.append(f"_Key: `{row['strategy_key']}` | "
                             f"Version: {row['version']} | "
                             f"Score: {row['quality_score']:.2f}_\n")
                lines.append(row["content"])
                lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Wrote strategy file: %s (%d strategies)", path, len(rows))
        return path

    # ---- Helpers ----

    def _get_stages_with_lessons(self) -> list[str]:
        """Get stages that have lessons in the DB."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT stage FROM lessons ORDER BY stage"
            ).fetchall()
            return [r["stage"] for r in rows]
        finally:
            conn.close()
