"""Tests for Sprint 5 — Lesson Store, SmartPause, evolution primitives."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from research_harness.evolution.store import (
    HALF_LIFE_DAYS,
    Lesson,
    LessonStore,
    _decay_weight,
)
from research_harness.auto_runner.smart_pause import (
    PauseAction,
    PauseThresholds,
    SmartPause,
)


# -- Lesson Store --------------------------------------------------------------


class TestLesson:
    def test_default_created_at(self):
        lesson = Lesson(stage="build", content="test")
        assert lesson.created_at  # auto-set

    def test_custom_fields(self):
        lesson = Lesson(
            stage="analyze",
            content="Found gap in X",
            lesson_type="success",
            tags=["gap_detect"],
        )
        assert lesson.lesson_type == "success"
        assert "gap_detect" in lesson.tags


class TestDecayWeight:
    def test_no_decay_for_fresh(self):
        lesson = Lesson(stage="build", content="test", weight=1.0)
        weight = _decay_weight(lesson)
        assert weight == pytest.approx(1.0, abs=0.01)

    def test_half_decay_at_half_life(self):
        now = datetime.now(timezone.utc)
        created = (now - timedelta(days=HALF_LIFE_DAYS)).isoformat()
        lesson = Lesson(stage="build", content="test", weight=1.0, created_at=created)
        weight = _decay_weight(lesson, now=now)
        assert weight == pytest.approx(0.5, abs=0.01)

    def test_quarter_decay_at_two_half_lives(self):
        now = datetime.now(timezone.utc)
        created = (now - timedelta(days=HALF_LIFE_DAYS * 2)).isoformat()
        lesson = Lesson(stage="build", content="test", weight=1.0, created_at=created)
        weight = _decay_weight(lesson, now=now)
        assert weight == pytest.approx(0.25, abs=0.01)

    def test_heavy_decay_for_old(self):
        now = datetime.now(timezone.utc)
        created = (now - timedelta(days=365)).isoformat()
        lesson = Lesson(stage="build", content="test", weight=1.0, created_at=created)
        weight = _decay_weight(lesson, now=now)
        assert weight < 0.001

    def test_base_weight_scales(self):
        now = datetime.now(timezone.utc)
        lesson = Lesson(stage="build", content="test", weight=0.5)
        weight = _decay_weight(lesson, now=now)
        assert weight == pytest.approx(0.5, abs=0.01)


class TestLessonStore:
    def test_append_and_query(self, tmp_path):
        store = LessonStore(tmp_path / "lessons.jsonl")
        store.append(Lesson(stage="build", content="lesson 1"))
        store.append(Lesson(stage="build", content="lesson 2"))
        store.append(Lesson(stage="analyze", content="lesson 3"))

        build_lessons = store.query("build")
        assert len(build_lessons) == 2

        all_lessons = store.query()
        assert len(all_lessons) == 3

    def test_query_ranked_by_decay(self, tmp_path):
        store = LessonStore(tmp_path / "lessons.jsonl")
        now = datetime.now(timezone.utc)

        # Old lesson
        store.append(Lesson(
            stage="build",
            content="old lesson",
            created_at=(now - timedelta(days=60)).isoformat(),
        ))
        # Fresh lesson
        store.append(Lesson(
            stage="build",
            content="fresh lesson",
            created_at=now.isoformat(),
        ))

        lessons = store.query("build", now=now)
        assert lessons[0].content == "fresh lesson"
        assert lessons[1].content == "old lesson"

    def test_build_overlay(self, tmp_path):
        store = LessonStore(tmp_path / "lessons.jsonl")
        store.append(Lesson(stage="build", content="S2 rate limit at 50/min", lesson_type="failure"))
        store.append(Lesson(stage="build", content="CrossRef works well", lesson_type="success"))

        overlay = store.build_overlay("build")
        assert "Lessons from previous runs" in overlay
        assert "S2 rate limit" in overlay
        assert "CrossRef works well" in overlay

    def test_empty_overlay(self, tmp_path):
        store = LessonStore(tmp_path / "lessons.jsonl")
        overlay = store.build_overlay("build")
        assert overlay == ""

    def test_count(self, tmp_path):
        store = LessonStore(tmp_path / "lessons.jsonl")
        store.append(Lesson(stage="build", content="a"))
        store.append(Lesson(stage="build", content="b"))
        store.append(Lesson(stage="analyze", content="c"))
        assert store.count() == 3
        assert store.count("build") == 2
        assert store.count("analyze") == 1

    def test_clear(self, tmp_path):
        store = LessonStore(tmp_path / "lessons.jsonl")
        store.append(Lesson(stage="build", content="a"))
        assert store.count() == 1
        store.clear()
        assert store.count() == 0

    def test_top_k(self, tmp_path):
        store = LessonStore(tmp_path / "lessons.jsonl")
        for i in range(10):
            store.append(Lesson(stage="build", content=f"lesson {i}"))
        lessons = store.query("build", top_k=3)
        assert len(lessons) == 3


# -- SmartPause ----------------------------------------------------------------


class TestSmartPause:
    def test_initial_continue(self):
        sp = SmartPause()
        decision = sp.evaluate()
        assert decision.action == PauseAction.CONTINUE

    def test_cost_warn(self):
        sp = SmartPause(PauseThresholds(max_cost_usd=1.0, hard_cost_usd=5.0))
        sp.record_success(cost_usd=1.5)
        decision = sp.evaluate()
        assert decision.action == PauseAction.WARN
        assert "Cost" in decision.reason

    def test_cost_pause(self):
        sp = SmartPause(PauseThresholds(hard_cost_usd=2.0))
        sp.record_success(cost_usd=2.5)
        decision = sp.evaluate()
        assert decision.action == PauseAction.PAUSE

    def test_failure_warn(self):
        sp = SmartPause(PauseThresholds(max_consecutive_failures=2, hard_consecutive_failures=5))
        sp.record_failure()
        sp.record_failure()
        decision = sp.evaluate()
        assert decision.action == PauseAction.WARN
        assert "consecutive failures" in decision.reason

    def test_failure_pause(self):
        sp = SmartPause(PauseThresholds(hard_consecutive_failures=3))
        for _ in range(3):
            sp.record_failure()
        decision = sp.evaluate()
        assert decision.action == PauseAction.PAUSE

    def test_success_resets_failures(self):
        sp = SmartPause(PauseThresholds(max_consecutive_failures=3))
        sp.record_failure()
        sp.record_failure()
        sp.record_success()
        assert sp.consecutive_failures == 0
        decision = sp.evaluate()
        assert decision.action == PauseAction.CONTINUE

    def test_wall_clock_warn(self):
        sp = SmartPause(PauseThresholds(max_wall_clock_sec=0.0))
        # Already exceeded since start_time is in the past
        decision = sp.evaluate()
        assert decision.action == PauseAction.WARN

    def test_signals_in_decision(self):
        sp = SmartPause()
        sp.record_success(cost_usd=0.5)
        decision = sp.evaluate()
        assert "cost_usd" in decision.signals
        assert decision.signals["cost_usd"] == pytest.approx(0.5)
        assert decision.signals["total_calls"] == 1.0

    def test_reset(self):
        sp = SmartPause()
        sp.record_failure()
        sp.record_success(cost_usd=1.0)
        sp.reset()
        assert sp.cumulative_cost == 0.0
        assert sp.consecutive_failures == 0

    def test_cost_accumulates(self):
        sp = SmartPause()
        sp.record_success(cost_usd=0.1)
        sp.record_success(cost_usd=0.2)
        sp.record_failure(cost_usd=0.05)
        assert sp.cumulative_cost == pytest.approx(0.35)


# -- Evolution Primitives (integration) ----------------------------------------


class TestEvolutionPrimitives:
    def test_lesson_extract_stub(self):
        from research_harness.primitives.evolution_impls import lesson_extract

        result = lesson_extract(
            stage="build",
            stage_summary="Built paper pool with 50 papers",
            issues_encountered=["S2 rate limit hit"],
        )
        assert len(result.lessons) == 2
        assert result.lessons[0].lesson_type == "failure"
        assert result.lessons[1].lesson_type == "observation"

    def test_lesson_extract_no_issues(self):
        from research_harness.primitives.evolution_impls import lesson_extract

        result = lesson_extract(
            stage="build",
            stage_summary="Everything went smoothly",
        )
        assert len(result.lessons) == 1
        assert result.lessons[0].lesson_type == "observation"

    def test_lesson_overlay_empty(self, tmp_path):
        from research_harness.primitives.evolution_impls import lesson_overlay

        result = lesson_overlay(
            stage="build",
            store_path=str(tmp_path / "empty.jsonl"),
        )
        assert result.overlay_text == ""
        assert result.lesson_count == 0

    def test_lesson_overlay_with_data(self, tmp_path):
        from research_harness.primitives.evolution_impls import lesson_overlay

        store = LessonStore(tmp_path / "lessons.jsonl")
        store.append(Lesson(stage="build", content="Use CrossRef first"))
        store.append(Lesson(stage="build", content="S2 has rate limits"))

        result = lesson_overlay(
            stage="build",
            store_path=str(tmp_path / "lessons.jsonl"),
        )
        assert result.lesson_count == 2
        assert "CrossRef" in result.overlay_text
        assert "S2" in result.overlay_text
