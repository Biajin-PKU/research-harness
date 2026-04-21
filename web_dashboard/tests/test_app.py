from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from web_dashboard import app as dashboard_app


@pytest.fixture
def client():
    dashboard_app.app.config["TESTING"] = True
    with dashboard_app.app.test_client() as test_client:
        yield test_client


def _write_project_workspace(root: Path, slug: str, title: str) -> Path:
    project_dir = root / slug
    docs_dir = project_dir / "docs"
    refs_dir = project_dir / "references"
    docs_dir.mkdir(parents=True)
    refs_dir.mkdir(parents=True)
    (project_dir / "README.md").write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                "更新时间: 2026-04-07",
                "",
                "## 研究主题",
                "",
                title,
                "",
                "## 当前状态",
                "",
                "- 状态已确认",
                "- 目标会议: TESTCONF",
            ]
        )
    )
    (project_dir / "session_handoff.md").write_text(
        "\n".join(
            [
                f"# {title} Session Handoff",
                "",
                "## 当前阻塞",
                "",
                "1. blocker one",
                "2. blocker two",
                "",
                "## 下一步",
                "",
                "1. next one",
                "2. next two",
            ]
        )
    )
    (docs_dir / f"{slug}_experiment_design.md").write_text(
        "\n".join(
            [
                f"# {title} Design",
                "",
                "## Summary",
                "",
                "| Col | Value |",
                "| --- | --- |",
                "| A | B |",
                "",
                "- item one",
            ]
        )
    )
    (refs_dir / f"{slug}_notes.md").write_text("# Notes\n\nReference note.")
    return project_dir


def _sample_papers() -> list[dict[str, object]]:
    return [
        {
            "id": 1,
            "title": "Cross-Channel Budget Allocation with Spillover",
            "venue": "WWW",
            "year": 2025,
            "doi": "",
            "arxiv_id": "2501.00001",
            "topics": ["cross-budget-rebalancing"],
            "url": "",
            "status": "annotated",
            "has_pdf": True,
            "pdf_path": "paper1.pdf",
            "card_status": "exported",
            "card_path": "/tmp/card1.json",
            "created_at": "2026-04-06 08:00:00",
        },
        {
            "id": 2,
            "title": "Retail Auction Simulator Benchmark",
            "venue": "KDD",
            "year": 2026,
            "doi": "",
            "arxiv_id": "2601.00002",
            "topics": ["cross-budget-rebalancing"],
            "url": "",
            "status": "meta_only",
            "has_pdf": False,
            "pdf_path": "",
            "card_status": "missing",
            "card_path": None,
            "created_at": "2026-04-07 08:00:00",
        },
    ]


def test_theme_overview_includes_health_risks_and_trends(tmp_path, monkeypatch):
    project_root = tmp_path / "projects"
    paper2 = _write_project_workspace(project_root, "paper2", "Paper 2")
    paper4 = _write_project_workspace(project_root, "paper4", "Paper 4")
    monkeypatch.setitem(
        dashboard_app.THEMES,
        "auto-bidding",
        {
            "slug": "auto-bidding",
            "title": "Auto Bidding Research",
            "summary": "theme summary",
            "status": "active",
            "project_slugs": ["paper2", "paper4"],
        },
    )
    monkeypatch.setitem(dashboard_app.PROJECTS, "paper2", {**dashboard_app.PROJECTS["paper2"], "path": paper2})
    monkeypatch.setitem(dashboard_app.PROJECTS, "paper4", {**dashboard_app.PROJECTS["paper4"], "path": paper4})
    monkeypatch.setattr(dashboard_app, "list_theme_papers", lambda theme_slug: _sample_papers())

    overview = dashboard_app.theme_overview("auto-bidding")

    assert "health" in overview
    assert "risk_alerts" in overview
    assert "recent_trends" in overview
    assert len(overview["recent_trends"]) == 7
    assert overview["projects"][0]["health_score"] >= 0
    assert overview["risk_alerts"][0]["action"]


def test_project_detail_and_document_preview_routes(tmp_path, monkeypatch, client):
    project_root = tmp_path / "projects"
    paper2 = _write_project_workspace(project_root, "paper2", "Paper 2")
    monkeypatch.setitem(dashboard_app.PROJECTS, "paper2", {**dashboard_app.PROJECTS["paper2"], "path": paper2})
    monkeypatch.setattr(dashboard_app, "list_theme_papers", lambda theme_slug: _sample_papers())

    detail_response = client.get("/api/projects/paper2")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()
    assert detail["monitor"]
    assert detail["documents"]
    assert detail["blockers"] == ["blocker one", "blocker two"]
    assert detail["next_steps"] == ["next one", "next two"]

    doc_response = client.get("/api/projects/paper2/documents/paper2_experiment_design.md")
    assert doc_response.status_code == 200
    doc_payload = doc_response.get_json()
    assert "| Col | Value |" in doc_payload["content"]


def test_project_papers_are_grouped_and_card_route_reads_topics(tmp_path, monkeypatch, client):
    db_path = tmp_path / "dashboard.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE papers (id INTEGER PRIMARY KEY, title TEXT, venue TEXT, year INTEGER, doi TEXT, arxiv_id TEXT, url TEXT, pdf_path TEXT, status TEXT, created_at TEXT, affiliations TEXT DEFAULT '[]')")
    conn.execute("CREATE TABLE topics (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE paper_topics (paper_id INTEGER, topic_id INTEGER)")
    conn.execute(
        "INSERT INTO papers (id, title, venue, year, doi, arxiv_id, url, pdf_path, status, created_at) VALUES (1, 'Auto-bidding Survey', 'arXiv', 2024, '', '2408.07685', '', 'paper.pdf', 'annotated', '2026-04-06 08:00:00')"
    )
    conn.execute("INSERT INTO topics (id, name) VALUES (1, 'cross-budget-rebalancing')")
    conn.execute("INSERT INTO paper_topics (paper_id, topic_id) VALUES (1, 1)")
    conn.commit()
    conn.close()

    card_path = tmp_path / "card_2408.07685.json"
    card_path.write_text(json.dumps({"title": "Auto-bidding Survey", "core_idea": "summary"}))

    monkeypatch.setattr(dashboard_app, "DB_PATH", db_path)
    monkeypatch.setattr(
        dashboard_app,
        "list_theme_papers",
        lambda theme_slug: _sample_papers(),
    )
    monkeypatch.setattr(
        dashboard_app,
        "load_card_payload",
        lambda paper_id, arxiv_id: ({"title": "Auto-bidding Survey", "core_idea": "summary"}, "exported", str(card_path)),
    )

    grouped_response = client.get("/api/projects/paper2/papers")
    assert grouped_response.status_code == 200
    grouped_payload = grouped_response.get_json()
    assert grouped_payload[0]["group"]["key"]

    card_response = client.get("/api/papers/1/card")
    assert card_response.status_code == 200
    card_payload = card_response.get_json()
    assert card_payload["paper"]["topics"] == ["cross-budget-rebalancing"]
    assert card_payload["card"]["core_idea"] == "summary"


def test_attach_project_groups_sorts_core_and_card_ready_first():
    papers = [
        {
            "id": 1,
            "title": "Budget Pacing in Repeated Auctions",
            "venue": "EC",
            "year": 2024,
            "card_status": "generated",
            "status": "annotated",
        },
        {
            "id": 2,
            "title": "Cross-Channel Budget Allocation with Spillover",
            "venue": "WWW",
            "year": 2025,
            "card_status": "exported",
            "status": "annotated",
        },
        {
            "id": 3,
            "title": "Cross-Channel Advertising Allocation and Consumer Dynamics",
            "venue": "KDD",
            "year": 2023,
            "card_status": "missing",
            "status": "meta_only",
        },
    ]

    ordered = dashboard_app.attach_project_groups("paper2", papers)

    assert [paper["id"] for paper in ordered] == [2, 3, 1]
    assert ordered[0]["group"]["key"] == "core-question"
    assert ordered[-1]["group"]["key"] == "execution-layer"


def test_dedupe_activities_removes_same_project_kind_description():
    activities = [
        {"project_slug": "paper2", "kind": "doc", "description": "README.md", "timestamp": "2026-04-07T10:00:00Z"},
        {"project_slug": "paper2", "kind": "doc", "description": "README.md", "timestamp": "2026-04-07T09:00:00Z"},
        {"project_slug": "paper2", "kind": "card", "description": "card one", "timestamp": "2026-04-07T08:00:00Z"},
    ]

    deduped = dashboard_app.dedupe_activities(activities, limit=10)

    assert len(deduped) == 2
    assert deduped[0]["description"] == "README.md"
    assert deduped[1]["description"] == "card one"
