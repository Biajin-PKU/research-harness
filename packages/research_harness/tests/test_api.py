from __future__ import annotations

from research_harness.api import ResearchAPI
from research_harness.storage.db import Database


def test_api_artifact_dependency_and_stale(tmp_path):
    db_path = tmp_path / "api.db"
    db = Database(db_path)
    db.migrate()

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description) VALUES (1, ?, ?)",
            ("api-topic", "API topic"),
        )
        # Bridge row: project_artifacts.project_id FK still references projects(id)
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, ?, ?)",
            ("api-topic", "API topic"),
        )
        conn.commit()
    finally:
        conn.close()

    api = ResearchAPI(db_path=db_path)
    upstream = api.record_artifact(
        topic_id=1,
        stage="build",
        artifact_type="literature_map",
        payload={"v": 1},
    )
    downstream = api.record_artifact(
        topic_id=1,
        stage="analyze",
        artifact_type="gap_analysis",
        payload={"v": 1},
        dependency_artifact_ids=[upstream["artifact_id"]],
    )

    api.record_artifact(
        topic_id=1,
        stage="build",
        artifact_type="literature_map",
        payload={"v": 2},
    )

    stale = api.list_stale_artifacts(1)
    assert any(item["id"] == downstream["artifact_id"] for item in stale)

    cleared = api.clear_artifact_stale(downstream["artifact_id"])
    assert cleared["success"] is True
