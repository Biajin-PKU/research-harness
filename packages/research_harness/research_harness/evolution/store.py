"""Lesson store — JSONL-backed experience store with time decay.

Each lesson records what worked or failed at a specific stage, with a
30-day half-life so recent experience dominates.

Usage::

    store = LessonStore("/path/to/lessons.jsonl")
    store.append(Lesson(stage="build", content="S2 rate limit hit at 50 req/min"))
    lessons = store.query("build", top_k=5)
    overlay = store.build_overlay("build")  # formatted for LLM prompt injection
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HALF_LIFE_DAYS = 30.0
_LN2 = math.log(2)


@dataclass
class Lesson:
    """A single lesson learned during a research workflow stage."""

    stage: str
    content: str
    lesson_type: str = "observation"  # observation | success | failure | tip
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    weight: float = 1.0  # base importance (0-1)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


def _decay_weight(lesson: Lesson, now: datetime | None = None) -> float:
    """Compute time-decayed weight using 30-day half-life."""
    now = now or datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(lesson.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return lesson.weight * 0.1  # old/broken timestamp → heavy decay

    age_days = (now - created).total_seconds() / 86400.0
    if age_days < 0:
        age_days = 0.0

    decay = math.exp(-_LN2 * age_days / HALF_LIFE_DAYS)
    return lesson.weight * decay


class LessonStore:
    """JSONL-backed lesson store with time-decay ranking."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, lesson: Lesson) -> None:
        """Append a lesson to the store."""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(lesson), default=str) + "\n")

    def _load_all(self) -> list[Lesson]:
        """Load all lessons from the JSONL file."""
        if not self._path.exists():
            return []
        lessons: list[Lesson] = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    lessons.append(Lesson(**data))
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.debug("Skipping malformed lesson: %s", exc)
        return lessons

    def query(
        self,
        stage: str | None = None,
        top_k: int = 10,
        now: datetime | None = None,
    ) -> list[Lesson]:
        """Query lessons, optionally filtered by stage, ranked by decayed weight."""
        lessons = self._load_all()
        if stage:
            lessons = [lesson for lesson in lessons if lesson.stage == stage]

        # Sort by decayed weight descending
        lessons.sort(key=lambda lesson: _decay_weight(lesson, now), reverse=True)
        return lessons[:top_k]

    def build_overlay(
        self,
        stage: str,
        top_k: int = 5,
        now: datetime | None = None,
    ) -> str:
        """Build a prompt overlay string from recent lessons for a stage.

        Returns formatted text suitable for injection into LLM system prompts.
        """
        lessons = self.query(stage=stage, top_k=top_k, now=now)
        if not lessons:
            return ""

        lines = [f"## Lessons from previous runs (stage: {stage})\n"]
        for i, lesson in enumerate(lessons, 1):
            weight = _decay_weight(lesson, now)
            lines.append(
                f"{i}. [{lesson.lesson_type}] (relevance: {weight:.2f}) {lesson.content}"
            )
        lines.append("")
        return "\n".join(lines)

    def count(self, stage: str | None = None) -> int:
        """Count lessons, optionally filtered by stage."""
        lessons = self._load_all()
        if stage:
            return sum(1 for lesson in lessons if lesson.stage == stage)
        return len(lessons)

    def clear(self) -> None:
        """Remove all lessons."""
        if self._path.exists():
            self._path.unlink()


# ---------------------------------------------------------------------------
# DBLessonStore — SQLite-backed, same interface as LessonStore
# ---------------------------------------------------------------------------


class DBLessonStore:
    """SQLite-backed lesson store with time-decay ranking.

    Drop-in replacement for LessonStore that uses the ``lessons`` DB table
    (migration 024) instead of a JSONL file.  The same time-decay logic
    (30-day half-life) applies.
    """

    def __init__(self, db: Any) -> None:
        """*db* is a ``research_harness.storage.db.Database`` instance."""
        self._db = db

    # ---- write ----

    def append(
        self,
        lesson: Lesson,
        *,
        source: str = "manual",
        source_session_id: str = "",
        source_topic_id: int | None = None,
        topic_id: int | None = None,
    ) -> int:
        """Append a lesson. Returns the new row ID."""
        conn = self._db.connect()
        try:
            cursor = conn.execute(
                """INSERT INTO lessons
                   (stage, content, lesson_type, tags, weight,
                    source, source_session_id, source_project_id, topic_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lesson.stage,
                    lesson.content,
                    lesson.lesson_type,
                    json.dumps(lesson.tags),
                    lesson.weight,
                    source,
                    source_session_id,
                    source_topic_id,  # write to source_project_id column for compat
                    topic_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            conn.close()

    # ---- read ----

    def query(
        self,
        stage: str | None = None,
        *,
        top_k: int = 10,
        lesson_type: str | None = None,
        topic_id: int | None = None,
        now: datetime | None = None,
    ) -> list[Lesson]:
        """Query lessons ranked by time-decayed weight."""
        conn = self._db.connect()
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if stage:
                clauses.append("stage = ?")
                params.append(stage)
            if lesson_type:
                clauses.append("lesson_type = ?")
                params.append(lesson_type)
            if topic_id is not None:
                clauses.append("(topic_id = ? OR topic_id IS NULL)")
                params.append(topic_id)

            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM lessons {where} ORDER BY id DESC LIMIT 200",
                params,
            ).fetchall()
        finally:
            conn.close()

        lessons = [_row_to_lesson(r) for r in rows]
        lessons.sort(key=lambda lesson: _decay_weight(lesson, now), reverse=True)
        return lessons[:top_k]

    def build_overlay(
        self,
        stage: str,
        *,
        top_k: int = 5,
        topic_id: int | None = None,
        now: datetime | None = None,
    ) -> str:
        """Build prompt overlay text from recent lessons for a stage."""
        lessons = self.query(stage=stage, top_k=top_k, topic_id=topic_id, now=now)
        if not lessons:
            return ""

        lines = [f"## Lessons from previous runs (stage: {stage})\n"]
        for i, lesson in enumerate(lessons, 1):
            weight = _decay_weight(lesson, now)
            lines.append(
                f"{i}. [{lesson.lesson_type}] (relevance: {weight:.2f}) {lesson.content}"
            )
        lines.append("")
        return "\n".join(lines)

    def count(self, stage: str | None = None) -> int:
        """Count lessons, optionally filtered by stage."""
        conn = self._db.connect()
        try:
            if stage:
                row = conn.execute(
                    "SELECT COUNT(*) as n FROM lessons WHERE stage = ?", (stage,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) as n FROM lessons").fetchone()
            return row["n"] if row else 0
        finally:
            conn.close()

    def get_by_ids(self, ids: list[int]) -> list[Lesson]:
        """Fetch lessons by their IDs."""
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM lessons WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            return [_row_to_lesson(r) for r in rows]
        finally:
            conn.close()

    def clear(self) -> None:
        """Remove all lessons from DB."""
        conn = self._db.connect()
        try:
            conn.execute("DELETE FROM lessons")
            conn.commit()
        finally:
            conn.close()

    # ---- migration helper ----

    def migrate_from_jsonl(self, jsonl_path: str | Path) -> int:
        """Import lessons from a JSONL-backed LessonStore. Returns count imported."""
        old_store = LessonStore(jsonl_path)
        lessons = old_store._load_all()
        count = 0
        for lesson in lessons:
            self.append(lesson, source="migrated")
            count += 1
        logger.info("Migrated %d lessons from %s to DB", count, jsonl_path)
        return count


def _row_to_lesson(row: Any) -> Lesson:
    """Convert a DB row (sqlite3.Row) to a Lesson dataclass."""
    tags_raw = row["tags"] if row["tags"] else "[]"
    try:
        tags = json.loads(tags_raw)
    except (json.JSONDecodeError, TypeError):
        tags = []
    return Lesson(
        stage=row["stage"],
        content=row["content"],
        lesson_type=row["lesson_type"],
        tags=tags,
        created_at=row["created_at"] or "",
        weight=row["weight"],
    )
