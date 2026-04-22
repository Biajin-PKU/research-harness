from research_harness.core.review_manager import ReviewManager


def test_review_add_and_list(conn):
    conn.execute("INSERT INTO topics (name) VALUES ('demo')")
    topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[0]
    conn.execute(
        "INSERT INTO projects (topic_id, name) VALUES (?, ?)", (topic_id, "paper1")
    )
    project_id = conn.execute(
        "SELECT id FROM projects WHERE name = 'paper1'"
    ).fetchone()[0]
    manager = ReviewManager(conn)
    review_id = manager.add_review(project_id, "novelty", "codex", "pass", 8.0, "ok")
    reviews = manager.list_reviews(project_id)
    assert review_id == reviews[0].id
    assert reviews[0].verdict == "pass"
