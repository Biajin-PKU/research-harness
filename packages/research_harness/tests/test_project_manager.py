from research_harness.core.project_manager import ProjectManager


def test_project_create_and_list(conn):
    conn.execute("INSERT INTO topics (name) VALUES ('demo')")
    topic_id = conn.execute("SELECT id FROM topics WHERE name = 'demo'").fetchone()[0]
    manager = ProjectManager(conn)
    project_id = manager.create(topic_id, "paper1", target_venue="KDD")
    projects = manager.list_projects(topic_id)
    assert project_id == projects[0].id
    assert projects[0].target_venue == "KDD"
