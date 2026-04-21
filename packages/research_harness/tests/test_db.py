def test_migrate_creates_core_tables(db):
    conn = db.connect()
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    conn.close()
    assert "topics" in tables
    assert "projects" in tables
    assert "reviews" in tables
    assert "search_runs" in tables
    assert "tasks" in tables
