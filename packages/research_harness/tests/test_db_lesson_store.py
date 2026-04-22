"""Tests for DBLessonStore (Sprint 1 — self-evolution foundation)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from research_harness.evolution.store import DBLessonStore, Lesson, LessonStore


class TestDBLessonStore:
    def test_append_and_query(self, db):
        store = DBLessonStore(db)
        store.append(Lesson(stage="build", content="lesson 1"))
        store.append(Lesson(stage="build", content="lesson 2"))
        store.append(Lesson(stage="analyze", content="lesson 3"))

        build = store.query("build")
        assert len(build) == 2

        all_lessons = store.query()
        assert len(all_lessons) == 3

    def test_query_with_lesson_type(self, db):
        store = DBLessonStore(db)
        store.append(Lesson(stage="build", content="failed X", lesson_type="failure"))
        store.append(Lesson(stage="build", content="worked Y", lesson_type="success"))
        store.append(
            Lesson(stage="build", content="observed Z", lesson_type="observation")
        )

        failures = store.query("build", lesson_type="failure")
        assert len(failures) == 1
        assert failures[0].content == "failed X"

    def test_query_ranked_by_decay(self, db):
        store = DBLessonStore(db)
        now = datetime.now(timezone.utc)

        # Old lesson — insert with explicit created_at via raw SQL
        conn = db.connect()
        old_time = (now - timedelta(days=60)).isoformat()
        conn.execute(
            "INSERT INTO lessons (stage, content, lesson_type, tags, weight, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("build", "old lesson", "observation", "[]", 1.0, "manual", old_time),
        )
        conn.execute(
            "INSERT INTO lessons (stage, content, lesson_type, tags, weight, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "build",
                "fresh lesson",
                "observation",
                "[]",
                1.0,
                "manual",
                now.isoformat(),
            ),
        )
        conn.commit()
        conn.close()

        lessons = store.query("build", now=now)
        assert lessons[0].content == "fresh lesson"
        assert lessons[1].content == "old lesson"

    def test_build_overlay(self, db):
        store = DBLessonStore(db)
        store.append(
            Lesson(
                stage="build", content="S2 rate limit at 50/min", lesson_type="failure"
            )
        )
        store.append(
            Lesson(stage="build", content="CrossRef works well", lesson_type="success")
        )

        overlay = store.build_overlay("build")
        assert "Lessons from previous runs" in overlay
        assert "S2 rate limit" in overlay
        assert "CrossRef" in overlay

    def test_empty_overlay(self, db):
        store = DBLessonStore(db)
        overlay = store.build_overlay("build")
        assert overlay == ""

    def test_count(self, db):
        store = DBLessonStore(db)
        store.append(Lesson(stage="build", content="a"))
        store.append(Lesson(stage="build", content="b"))
        store.append(Lesson(stage="analyze", content="c"))
        assert store.count() == 3
        assert store.count("build") == 2
        assert store.count("analyze") == 1

    def test_clear(self, db):
        store = DBLessonStore(db)
        store.append(Lesson(stage="build", content="a"))
        assert store.count() == 1
        store.clear()
        assert store.count() == 0

    def test_top_k(self, db):
        store = DBLessonStore(db)
        for i in range(10):
            store.append(Lesson(stage="build", content=f"lesson {i}"))
        lessons = store.query("build", top_k=3)
        assert len(lessons) == 3

    def test_append_with_source_metadata(self, db):
        store = DBLessonStore(db)
        rid = store.append(
            Lesson(stage="build", content="auto-extracted lesson"),
            source="extracted",
            source_session_id="sess-001",
            source_topic_id=5,
            topic_id=1,
        )
        assert rid > 0

    def test_query_with_topic_id(self, db):
        store = DBLessonStore(db)
        store.append(Lesson(stage="build", content="topic 1 lesson"), topic_id=1)
        store.append(Lesson(stage="build", content="topic 2 lesson"), topic_id=2)
        store.append(Lesson(stage="build", content="global lesson"))

        # topic_id=1 should return topic-1 and global lessons
        lessons = store.query("build", topic_id=1)
        contents = {lesson.content for lesson in lessons}
        assert "topic 1 lesson" in contents
        assert "global lesson" in contents
        # topic 2 lesson should not appear
        assert "topic 2 lesson" not in contents

    def test_get_by_ids(self, db):
        store = DBLessonStore(db)
        id1 = store.append(Lesson(stage="build", content="lesson A"))
        id2 = store.append(Lesson(stage="build", content="lesson B"))
        store.append(Lesson(stage="build", content="lesson C"))

        fetched = store.get_by_ids([id1, id2])
        assert len(fetched) == 2
        contents = {lesson.content for lesson in fetched}
        assert "lesson A" in contents
        assert "lesson B" in contents

    def test_get_by_ids_empty(self, db):
        store = DBLessonStore(db)
        assert store.get_by_ids([]) == []

    def test_migrate_from_jsonl(self, db, tmp_path):
        # Create JSONL store with some data
        jsonl_path = tmp_path / "lessons.jsonl"
        old_store = LessonStore(jsonl_path)
        old_store.append(Lesson(stage="build", content="migrated lesson 1"))
        old_store.append(Lesson(stage="analyze", content="migrated lesson 2"))
        old_store.append(
            Lesson(stage="build", content="migrated lesson 3", lesson_type="failure")
        )

        # Migrate to DB
        db_store = DBLessonStore(db)
        count = db_store.migrate_from_jsonl(jsonl_path)
        assert count == 3
        assert db_store.count() == 3
        assert db_store.count("build") == 2

        # Verify content preserved
        build_lessons = db_store.query("build")
        contents = {lesson.content for lesson in build_lessons}
        assert "migrated lesson 1" in contents
        assert "migrated lesson 3" in contents

    def test_tags_preserved(self, db):
        store = DBLessonStore(db)
        store.append(Lesson(stage="build", content="tagged", tags=["s2", "rate_limit"]))

        lessons = store.query("build")
        assert lessons[0].tags == ["s2", "rate_limit"]
