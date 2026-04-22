from research_harness.core.paper_pool import PaperPool
from research_harness.storage.models import Paper, PaperAnnotation, TopicPaperNote


def test_ingest_is_idempotent_and_updates_topic_link(conn):
    conn.execute("INSERT INTO topics (name) VALUES ('demo')")
    topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[0]
    pool = PaperPool(conn)
    first_id = pool.ingest(
        Paper(
            title="Attention Is All You Need",
            arxiv_id="1706.03762",
            authors=["A"],
            year=2017,
            venue="NeurIPS",
        ),
        topic_id=topic_id,
        relevance="high",
    )
    second_id = pool.ingest(
        Paper(
            title="Attention Is All You Need",
            arxiv_id="1706.03762",
            authors=["A", "B"],
            year=2017,
            venue="NeurIPS",
        ),
        topic_id=topic_id,
        relevance="medium",
    )
    rows = conn.execute("SELECT * FROM paper_topics").fetchall()
    assert first_id == second_id
    assert len(rows) == 1
    assert rows[0]["relevance"] == "medium"


def test_annotations_upsert(conn):
    conn.execute("INSERT INTO papers (title) VALUES ('p1')")
    paper_id = conn.execute("SELECT id FROM papers WHERE title = 'p1'").fetchone()[0]
    pool = PaperPool(conn)
    pool.upsert_annotation(
        PaperAnnotation(
            paper_id=paper_id, section="summary", content="a", source="test"
        )
    )
    pool.upsert_annotation(
        PaperAnnotation(
            paper_id=paper_id, section="summary", content="b", source="test2"
        )
    )
    annotations = pool.get_annotations(paper_id)
    assert len(annotations) == 1
    assert annotations[0].content == "b"


def test_topic_notes_upsert_and_filter(conn):
    conn.execute("INSERT INTO topics (name) VALUES ('demo')")
    conn.execute("INSERT INTO papers (title) VALUES ('p1')")
    topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[0]
    paper_id = conn.execute("SELECT id FROM papers WHERE title = 'p1'").fetchone()[0]
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
        (paper_id, topic_id, "high"),
    )
    conn.commit()

    pool = PaperPool(conn)
    note_id = pool.upsert_topic_note(
        TopicPaperNote(
            paper_id=paper_id,
            topic_id=topic_id,
            note_type="relevance",
            content="first",
            source="codex",
        )
    )
    pool.upsert_topic_note(
        TopicPaperNote(
            paper_id=paper_id,
            topic_id=topic_id,
            note_type="relevance",
            content="updated",
            source="claude",
        )
    )

    notes = pool.get_topic_notes(paper_id, topic_id=topic_id)
    assert len(notes) == 1
    assert notes[0].id == note_id
    assert notes[0].content == "updated"
    assert notes[0].source == "claude"


def test_topic_note_requires_existing_topic_link(conn):
    conn.execute("INSERT INTO topics (name) VALUES ('demo')")
    conn.execute("INSERT INTO papers (title) VALUES ('p1')")
    topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[0]
    paper_id = conn.execute("SELECT id FROM papers WHERE title = 'p1'").fetchone()[0]
    pool = PaperPool(conn)

    try:
        pool.upsert_topic_note(
            TopicPaperNote(
                paper_id=paper_id,
                topic_id=topic_id,
                note_type="relevance",
                content="x",
                source="codex",
            )
        )
    except ValueError as exc:
        assert "not linked to topic" in str(exc)
    else:
        raise AssertionError("expected ValueError for unlinked paper/topic pair")
