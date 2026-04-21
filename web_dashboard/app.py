#!/usr/bin/env python3
"""
Research Hub monitoring dashboard.

Theme -> Project -> Paper hierarchy:
- Theme: configurable (see dashboard_config.json)
- Projects: configurable (see dashboard_config.json)
- Papers: literature assets stored in research-harness
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_CONFIG_PATH = Path(__file__).resolve().parent / "dashboard_config.json"

# Resolve paths via environment or defaults
DB_PATH = Path(os.environ.get("RESEARCH_HARNESS_DB_PATH", os.environ.get("RESEARCH_HUB_DB_PATH", str(BASE_DIR / ".research-harness" / "pool.db"))))
CARDS_DIR = Path(os.environ.get("RESEARCH_HARNESS_CARDS_DIR", os.environ.get("RESEARCH_HUB_CARDS_DIR", str(BASE_DIR / "paper_library" / "papers"))))
ARTIFACTS_DIR = Path(os.environ.get("RESEARCH_HARNESS_ARTIFACTS_DIR", os.environ.get("RESEARCH_HUB_ARTIFACTS_DIR", str(BASE_DIR / ".research-harness" / "artifacts"))))
PROJECTS_ROOT = Path(os.environ.get("RESEARCH_HARNESS_PROJECTS_ROOT", os.environ.get("RESEARCH_HUB_PROJECTS_ROOT", str(BASE_DIR))))


def _load_dashboard_config() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load themes and projects from dashboard_config.json."""
    if not DASHBOARD_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Dashboard config not found: {DASHBOARD_CONFIG_PATH}")
    raw = json.loads(DASHBOARD_CONFIG_PATH.read_text())
    themes = raw.get("themes", {})
    projects = raw.get("projects", {})
    # Resolve relative project paths against PROJECTS_ROOT
    for project in projects.values():
        rel = project.pop("relative_path", None)
        if rel:
            project["path"] = PROJECTS_ROOT / rel
        elif "path" not in project:
            project["path"] = PROJECTS_ROOT / project["slug"]
    return themes, projects


THEMES, PROJECTS = _load_dashboard_config()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def to_iso_from_ts(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.utcfromtimestamp(ts).replace(microsecond=0).isoformat() + "Z"


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for parser in (
        lambda item: datetime.fromisoformat(item.replace("Z", "+00:00")).replace(tzinfo=None),
        lambda item: datetime.strptime(item, "%Y-%m-%d %H:%M:%S"),
        lambda item: datetime.strptime(item, "%Y-%m-%dT%H:%M:%SZ"),
    ):
        try:
            return parser(value)
        except ValueError:
            continue
    return None


def parse_updated_label(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("更新时间:") or stripped.startswith("Updated:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def extract_heading_section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    target = heading.strip()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == target:
            start = idx + 1
            break
    if start is None:
        return []
    collected: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped:
            collected.append(stripped)
    return collected


def first_nonempty_markdown_paragraph(text: str) -> str:
    paragraph: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("---"):
            if paragraph:
                break
            continue
        if stripped.startswith(("- ", "* ", "1. ")):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    return " ".join(paragraph)


def extract_bullets(lines: list[str]) -> list[str]:
    bullets = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
        elif len(stripped) > 2:
            number_part, sep, rest = stripped.partition(". ")
            if sep and number_part.isdigit():
                bullets.append(rest.strip())
    return bullets


def clean_markdown_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            cleaned.append(stripped[2:].strip())
            continue
        number_part, sep, rest = stripped.partition(". ")
        if sep and number_part.isdigit():
            cleaned.append(rest.strip())
            continue
        cleaned.append(stripped)
    return [line for line in cleaned if line]


def check_card_status(paper_id: int, arxiv_id: str | None) -> tuple[str, str | None]:
    if arxiv_id:
        exported_card = CARDS_DIR / f"card_{arxiv_id}.json"
        if exported_card.exists():
            return "exported", str(exported_card)

    artifact_card = ARTIFACTS_DIR / f"paper_{paper_id}" / "card.json"
    if artifact_card.exists():
        return "generated", str(artifact_card)

    return "missing", None


def load_card_payload(paper_id: int, arxiv_id: str | None) -> tuple[dict[str, Any] | None, str | None, str | None]:
    card_status, card_path = check_card_status(paper_id, arxiv_id)
    if not card_path:
        return None, card_status, None
    try:
        payload = json.loads(Path(card_path).read_text())
    except (json.JSONDecodeError, OSError):
        return None, card_status, card_path
    return payload, card_status, card_path


def serialize_paper_row(row: sqlite3.Row) -> dict[str, Any]:
    paper_id = int(row["id"])
    arxiv_id = row["arxiv_id"] or ""
    card_status, card_path = check_card_status(paper_id, arxiv_id)
    has_pdf = bool(row["pdf_path"]) and Path(row["pdf_path"]).exists()
    topics_raw = row["topic_names"] if "topic_names" in row.keys() else ""
    topic_list = [item for item in topics_raw.split("|") if item]
    affiliations_raw = row["affiliations"] if "affiliations" in row.keys() else "[]"
    try:
        affiliations = json.loads(affiliations_raw) if affiliations_raw else []
    except (json.JSONDecodeError, TypeError):
        affiliations = []
    return {
        "id": paper_id,
        "title": row["title"],
        "venue": row["venue"] or "",
        "year": row["year"],
        "doi": row["doi"] or "",
        "arxiv_id": arxiv_id,
        "topics": topic_list,
        "url": row["url"] or "",
        "status": row["status"] or "",
        "has_pdf": has_pdf,
        "pdf_path": row["pdf_path"] or "",
        "card_status": card_status,
        "card_path": card_path,
        "created_at": row["created_at"] or "",
        "affiliations": affiliations,
    }


def _collect_theme_topics(theme_slug: str) -> list[str]:
    """Gather all topic names from projects belonging to this theme."""
    theme = THEMES.get(theme_slug)
    if not theme:
        return []
    topics: list[str] = []
    for slug in theme.get("project_slugs", []):
        project = PROJECTS.get(slug, {})
        topics.extend(project.get("include_topics", []))
    return topics if topics else []


def list_theme_papers(theme_slug: str) -> list[dict[str, Any]]:
    if theme_slug not in THEMES:
        return []
    topic_names = _collect_theme_topics(theme_slug)
    if not topic_names:
        # Fallback: return all papers if no topic filter is configured
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.venue, p.year, p.doi, p.arxiv_id,
                   p.url, p.pdf_path, p.status, p.created_at, p.affiliations,
                   GROUP_CONCAT(t.name, '|') AS topic_names
            FROM papers p
            LEFT JOIN paper_topics pt ON pt.paper_id = p.id
            LEFT JOIN topics t ON t.id = pt.topic_id
            GROUP BY p.id
            ORDER BY COALESCE(p.year, 0) DESC, p.id DESC
            """,
        ).fetchall()
        conn.close()
        return [serialize_paper_row(row) for row in rows]

    placeholders = ",".join("?" for _ in topic_names)
    conn = get_db_connection()
    rows = conn.execute(
        f"""
        SELECT
            p.id,
            p.title,
            p.venue,
            p.year,
            p.doi,
            p.arxiv_id,
            p.url,
            p.pdf_path,
            p.status,
            p.created_at,
            p.affiliations,
            GROUP_CONCAT(t.name, '|') AS topic_names
        FROM papers p
        JOIN paper_topics pt ON pt.paper_id = p.id
        JOIN topics t ON t.id = pt.topic_id
        WHERE t.name IN ({placeholders})
        GROUP BY p.id
        ORDER BY COALESCE(p.year, 0) DESC, p.id DESC
        """,
        topic_names,
    ).fetchall()
    conn.close()
    return [serialize_paper_row(row) for row in rows]


def match_project_papers(project_slug: str, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    project = PROJECTS[project_slug]
    def keyword_match(field_value: str, keywords: list[str]) -> bool:
        haystack = field_value.lower()
        return any(keyword in haystack for keyword in keywords)

    filtered = papers
    include_topics = project.get("include_topics")
    if include_topics:
        include_topics_set = {topic.lower() for topic in include_topics}
        filtered = [
            paper
            for paper in filtered
            if any(topic.lower() in include_topics_set for topic in paper.get("topics", []))
        ]

    include_keywords = [kw.lower() for kw in project.get("include_keywords", [])]
    if include_keywords:
        filtered = [
            paper
            for paper in filtered
            if keyword_match(paper.get("title", ""), include_keywords)
            or keyword_match(paper.get("venue", ""), include_keywords)
        ]

    exclude_keywords = [kw.lower() for kw in project.get("exclude_keywords", [])]
    if exclude_keywords:
        filtered = [
            paper
            for paper in filtered
            if not (
                keyword_match(paper.get("title", ""), exclude_keywords)
                or keyword_match(paper.get("venue", ""), exclude_keywords)
            )
        ]

    return filtered


def assign_project_papers(theme_slug: str, papers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    assignments: dict[str, list[dict[str, Any]]] = {}
    remaining = list(papers)
    project_slugs = THEMES[theme_slug]["project_slugs"]
    order = sorted(project_slugs, key=lambda slug: PROJECTS[slug].get("selection_priority", 0), reverse=True)
    for slug in order:
        selected = match_project_papers(slug, remaining)
        assignments[slug] = selected
        if not PROJECTS[slug].get("allow_shared", False):
            remaining = [paper for paper in remaining if paper not in selected]
    return assignments


def compute_project_stage(project_slug: str) -> str:
    project = PROJECTS[project_slug]
    readme_path = project["path"] / "README.md"
    if not readme_path.exists():
        return project.get("stage", "unknown")
    text = readme_path.read_text()
    status_lines = extract_heading_section(text, "## 当前状态")
    joined = " ".join(status_lines).lower()
    if "待正式启动" in joined or "尚未进入正式实现" in joined:
        return "pre-start"
    if "待数据" in joined or "待" in joined:
        return "design-ready"
    return project.get("stage", "active")


def project_artifact_counts(project_path: Path) -> dict[str, int]:
    docs_dir = project_path / "docs"
    refs_dir = project_path / "references"
    return {
        "doc_count": len(list(docs_dir.glob("*.md"))) if docs_dir.exists() else 0,
        "reference_count": len(list(refs_dir.glob("*.md"))) if refs_dir.exists() else 0,
    }


def project_documents(project_slug: str) -> list[dict[str, Any]]:
    project = PROJECTS[project_slug]
    docs_root = project["path"] / "docs"
    refs_root = project["path"] / "references"
    entries: list[dict[str, Any]] = []

    for label, root in [("docs", docs_root), ("references", refs_root)]:
        if not root.exists():
            continue
        for doc in sorted(root.glob("*.md")):
            entries.append(
                {
                    "id": doc.name,
                    "label": label,
                    "path": str(doc),
                    "updated_at": to_iso_from_ts(doc.stat().st_mtime),
                }
            )
    return entries


def project_monitor(project_slug: str, project_papers: list[dict[str, Any]], documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    doc_count = len([doc for doc in documents if doc["label"] == "docs"])
    ref_count = len([doc for doc in documents if doc["label"] == "references"])
    with_pdf = sum(1 for paper in project_papers if paper["has_pdf"])
    with_cards = sum(1 for paper in project_papers if paper["card_status"] != "missing")
    annotated = sum(1 for paper in project_papers if paper["status"] == "annotated")

    if project_slug == "paper2":
        return [
            {"label": "Paper Coverage", "value": str(len(project_papers)), "detail": "theme-linked papers assigned to this project"},
            {"label": "PDF / Card", "value": f"{with_pdf}/{with_cards}", "detail": "papers with local PDFs vs readable cards"},
            {"label": "Research Assets", "value": str(doc_count + ref_count), "detail": "docs and reference notes in the project workspace"},
        ]

    return [
        {"label": "Design Docs", "value": str(doc_count), "detail": "system and experiment design documents"},
        {"label": "Evidence Base", "value": str(annotated), "detail": "assigned papers already annotated for simulator context"},
        {"label": "Card Coverage", "value": f"{with_cards}/{len(project_papers)}", "detail": "papers with cards for rapid reading"},
    ]


def resolve_project_document(project_slug: str, doc_id: str) -> Path | None:
    for entry in project_documents(project_slug):
        if entry["id"] == doc_id:
            return Path(entry["path"])
    return None


def paper_group_for_project(project_slug: str, paper: dict[str, Any]) -> dict[str, str]:
    title = (paper.get("title") or "").lower()
    venue = (paper.get("venue") or "").lower()
    haystack = f"{title} {venue}"

    if project_slug == "paper2":
        if any(keyword in haystack for keyword in ["cross-channel", "multichannel", "budget allocation", "spillover", "marketing mix", "attribution"]):
            return {
                "key": "core-question",
                "label": "Core Question",
                "description": "Directly relevant papers on cross-channel allocation, spillover, and budget misallocation.",
            }
        if any(keyword in haystack for keyword in ["pacing", "autobidding", "budget-constrained", "roi constraints", "auction"]):
            return {
                "key": "execution-layer",
                "label": "Execution Layer",
                "description": "Autobidding, pacing, and auction papers that connect the allocator to execution.",
            }
        return {
            "key": "adjacent-methods",
            "label": "Adjacent Methods",
            "description": "Methodological context and neighboring optimization work.",
        }

    if any(keyword in haystack for keyword in ["simulator", "benchmark", "arena", "auction design", "neural auction"]):
        return {
            "key": "platform-design",
            "label": "Platform Design",
            "description": "Benchmarks, simulator design, and auction mechanism work relevant to this project.",
        }
    if any(keyword in haystack for keyword in ["multi-agent", "meta-reinforcement", "strateg", "learning to bid"]):
        return {
            "key": "agent-behavior",
            "label": "Agent Behavior",
            "description": "Agent strategy and multi-agent learning papers relevant to emergent behavior.",
        }
    return {
        "key": "market-theory",
        "label": "Market Theory",
        "description": "Auction theory, pacing, and market-structure papers that ground the simulator.",
    }


def attach_project_groups(project_slug: str, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for paper in papers:
        group = paper_group_for_project(project_slug, paper)
        enriched.append({**paper, "group": group})
    group_order = {
        "paper2": {
            "core-question": 0,
            "execution-layer": 1,
            "adjacent-methods": 2,
        },
        "paper4": {
            "platform-design": 0,
            "agent-behavior": 1,
            "market-theory": 2,
        },
    }
    order = group_order.get(project_slug, {})
    return sorted(
        enriched,
        key=lambda paper: (
            order.get(paper["group"]["key"], 99),
            0 if paper["card_status"] == "exported" else 1,
            0 if paper["status"] == "annotated" else 1,
            -(paper["year"] or 0),
            paper["id"],
        ),
    )


def recent_annotations(theme_slug: str, limit: int = 5) -> list[sqlite3.Row]:
    topic_names = _collect_theme_topics(theme_slug)
    conn = get_db_connection()
    try:
        if topic_names:
            placeholders = ",".join("?" for _ in topic_names)
            rows = conn.execute(
                f"""
                SELECT pa.paper_id, pa.section, pa.created_at, p.title
                FROM paper_annotations pa
                JOIN papers p ON p.id = pa.paper_id
                JOIN paper_topics pt ON pt.paper_id = p.id
                JOIN topics t ON t.id = pt.topic_id
                WHERE t.name IN ({placeholders})
                ORDER BY pa.created_at DESC
                LIMIT ?
                """,
                [*topic_names, limit],
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT pa.paper_id, pa.section, pa.created_at, p.title
                FROM paper_annotations pa
                JOIN papers p ON p.id = pa.paper_id
                ORDER BY pa.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.DatabaseError:
        rows = []
    conn.close()
    return rows


def load_project_summary(project_slug: str, project_papers: list[dict[str, Any]]) -> dict[str, Any]:
    config = PROJECTS[project_slug]
    project_path: Path = config["path"]
    readme_path = project_path / "README.md"
    handoff_path = project_path / "session_handoff.md"
    readme_text = readme_path.read_text() if readme_path.exists() else ""
    handoff_text = handoff_path.read_text() if handoff_path.exists() else ""
    current_status_lines = extract_heading_section(readme_text, "## 当前状态")
    handoff_blockers = extract_bullets(extract_heading_section(handoff_text, "## 当前阻塞"))
    handoff_next_steps = extract_bullets(extract_heading_section(handoff_text, "## 下一步"))
    counts = project_artifact_counts(project_path)
    card_count = sum(1 for paper in project_papers if paper["card_status"] != "missing")
    annotated_count = sum(1 for paper in project_papers if paper["status"] == "annotated")
    card_coverage = round((card_count / len(project_papers)) * 100, 1) if project_papers else 0.0
    health_score = max(0, min(100, int(card_coverage * 0.45 + counts["doc_count"] * 4 + counts["reference_count"] * 3 - len(handoff_blockers) * 8)))
    last_updated_candidates = [
        path.stat().st_mtime
        for path in (readme_path, handoff_path)
        if path.exists()
    ]
    last_updated_at = to_iso_from_ts(max(last_updated_candidates)) if last_updated_candidates else None
    summary = first_nonempty_markdown_paragraph((project_path / "docs").joinpath(f"{project_slug}_experiment_design.md").read_text()) if (project_path / "docs").joinpath(f"{project_slug}_experiment_design.md").exists() else ""

    return {
        "slug": config["slug"],
        "theme_slug": config["theme_slug"],
        "title": config["title"],
        "short_title": config["short_title"],
        "status_lines": clean_markdown_lines(current_status_lines),
        "stage": compute_project_stage(project_slug),
        "status": "active" if compute_project_stage(project_slug) != "pre-start" else "planned",
        "updated_label": parse_updated_label(readme_text) or parse_updated_label(handoff_text),
        "summary": summary or "No project summary captured yet.",
        "blockers": handoff_blockers[:3],
        "next_steps": handoff_next_steps[:3],
        "paper_count": len(project_papers),
        "annotated_count": annotated_count,
        "card_count": card_count,
        "card_coverage": card_coverage,
        "doc_count": counts["doc_count"],
        "reference_count": counts["reference_count"],
        "health_score": health_score,
        "last_updated_at": last_updated_at,
        "path": str(project_path),
    }


def theme_stage_summary(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for project in projects:
        stage = project["stage"]
        counts[stage] = counts.get(stage, 0) + 1
    return [
        {"stage": stage, "count": count}
        for stage, count in sorted(counts.items(), key=lambda item: item[0])
    ]


def theme_health_summary(projects: list[dict[str, Any]], papers: list[dict[str, Any]]) -> dict[str, Any]:
    total_papers = len(papers)
    total_cards = sum(1 for paper in papers if paper["card_status"] != "missing")
    total_annotated = sum(1 for paper in papers if paper["status"] == "annotated")
    total_pdf = sum(1 for paper in papers if paper["has_pdf"])
    project_health = []
    for project in projects:
        project_health.append(
            {
                "slug": project["slug"],
                "short_title": project["short_title"],
                "health_score": project["health_score"],
                "card_coverage": project["card_coverage"],
                "blocker_count": len(project["blockers"]),
            }
        )
    project_health.sort(key=lambda item: item["health_score"], reverse=True)
    return {
        "paper_completion": {
            "card_coverage": round((total_cards / total_papers) * 100, 1) if total_papers else 0.0,
            "annotation_coverage": round((total_annotated / total_papers) * 100, 1) if total_papers else 0.0,
            "pdf_coverage": round((total_pdf / total_papers) * 100, 1) if total_papers else 0.0,
        },
        "project_health": project_health,
    }


def theme_risk_alerts(projects: list[dict[str, Any]], papers: list[dict[str, Any]]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    missing_pdf = sum(1 for paper in papers if not paper["has_pdf"])
    missing_cards = sum(1 for paper in papers if paper["card_status"] == "missing")
    if missing_pdf:
        alerts.append(
            {
                "level": "risk",
                "title": "PDF coverage gap",
                "detail": f"{missing_pdf} tracked papers still have no local PDF.",
                "action": "Prioritize PDF acquisition for the missing backlog before further annotation work.",
            }
        )
    if missing_cards:
        alerts.append(
            {
                "level": "risk",
                "title": "Card generation backlog",
                "detail": f"{missing_cards} tracked papers still have no card artifact.",
                "action": "Run card generation for PDF-ready papers to keep the reading surface current.",
            }
        )
    for project in projects:
        if project["blockers"]:
            alerts.append(
                {
                    "level": "watch",
                    "title": f"{project['short_title']} has active blockers",
                    "detail": project["blockers"][0],
                    "action": project["next_steps"][0] if project["next_steps"] else "Review the project handoff and clear the top blocker.",
                }
            )
    if not alerts:
        alerts.append(
            {
                "level": "ok",
                "title": "No critical risks detected",
                "detail": "Theme-level coverage and project blockers look stable.",
                "action": "Keep cycling cards, documents, and topic notes to maintain momentum.",
            }
        )
    return alerts[:6]


def theme_recent_trends(theme_slug: str, papers: list[dict[str, Any]], projects: list[dict[str, Any]], days: int = 7) -> list[dict[str, Any]]:
    today = datetime.utcnow().date()
    buckets: dict[str, dict[str, int]] = {}
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        buckets[day.isoformat()] = {"papers": 0, "cards": 0, "docs": 0}

    for paper in papers:
        created = parse_datetime(paper.get("created_at"))
        if created:
            key = created.date().isoformat()
            if key in buckets:
                buckets[key]["papers"] += 1
        if paper.get("card_path"):
            card_path = Path(paper["card_path"])
            if card_path.exists():
                key = datetime.utcfromtimestamp(card_path.stat().st_mtime).date().isoformat()
                if key in buckets:
                    buckets[key]["cards"] += 1

    for project in projects:
        for doc in project_documents(project["slug"]):
            updated = parse_datetime(doc.get("updated_at"))
            if not updated:
                continue
            key = updated.date().isoformat()
            if key in buckets:
                buckets[key]["docs"] += 1

    return [
        {
            "date": date_key,
            "papers": counts["papers"],
            "cards": counts["cards"],
            "docs": counts["docs"],
        }
        for date_key, counts in buckets.items()
    ]


def theme_overview(theme_slug: str) -> dict[str, Any]:
    theme = THEMES[theme_slug]
    papers = list_theme_papers(theme_slug)
    assignments = assign_project_papers(theme_slug, papers)
    projects = [
        load_project_summary(project_slug, assignments.get(project_slug, []))
        for project_slug in theme["project_slugs"]
    ]
    total_cards = sum(1 for paper in papers if paper["card_status"] != "missing")
    annotated = sum(1 for paper in papers if paper["status"] == "annotated")
    with_pdf = sum(1 for paper in papers if paper["has_pdf"])
    health = theme_health_summary(projects, papers)
    risks = theme_risk_alerts(projects, papers)
    stages = theme_stage_summary(projects)
    trends = theme_recent_trends(theme_slug, papers, projects)
    return {
        "slug": theme_slug,
        "title": theme["title"],
        "summary": theme["summary"],
        "status": theme["status"],
        "project_count": len(projects),
        "paper_count": len(papers),
        "annotated_count": annotated,
        "card_count": total_cards,
        "pdf_count": with_pdf,
        "card_coverage": round((total_cards / len(papers)) * 100, 1) if papers else 0.0,
        "pdf_coverage": round((with_pdf / len(papers)) * 100, 1) if papers else 0.0,
        "health": health,
        "risk_alerts": risks,
        "stage_summary": stages,
        "recent_trends": trends,
        "projects": projects,
    }


def build_activity_feed(theme_slug: str, assignments: dict[str, list[dict[str, Any]]], limit: int = 20) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    papers = list_theme_papers(theme_slug)
    paper_to_project: dict[int, str] = {}
    for slug, project_papers in assignments.items():
        for paper in project_papers:
            paper_to_project[paper["id"]] = slug

    for paper in papers[:12]:
        if paper["card_status"] != "missing":
            card_mtime = Path(paper["card_path"]).stat().st_mtime if paper["card_path"] else None
            activities.append(
                {
                    "kind": "card",
                    "title": f"Card ready: {paper['title']}",
                    "description": f"{paper['card_status']} card available for paper #{paper['id']}",
                    "timestamp": to_iso_from_ts(card_mtime),
                    "project_slug": paper_to_project.get(paper["id"], "unknown"),
                    "paper_id": paper["id"],
                }
            )
        if paper["created_at"]:
            activities.append(
                {
                    "kind": "paper",
                    "title": f"Paper tracked: {paper['title']}",
                    "description": f"Status {paper['status']}, venue {paper['venue'] or 'unknown venue'}",
                    "timestamp": paper["created_at"],
                    "project_slug": paper_to_project.get(paper["id"], "unknown"),
                    "paper_id": paper["id"],
                }
            )

    for project_slug in THEMES[theme_slug]["project_slugs"]:
        project = PROJECTS[project_slug]
        paths = [
            project["path"] / "README.md",
            project["path"] / "session_handoff.md",
        ]
        doc_dirs = [project["path"] / "docs", project["path"] / "references"]
        for doc_path in paths:
            if doc_path.exists():
                activities.append(
                    {
                        "kind": "doc",
                        "title": f"{project_slug} document updated",
                        "description": doc_path.name,
                        "timestamp": to_iso_from_ts(doc_path.stat().st_mtime),
                        "project_slug": project_slug,
                        "paper_id": None,
                    }
                )
        for doc_dir in doc_dirs:
            if not doc_dir.exists():
                continue
            doc_files = sorted(doc_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)[:2]
            for doc_path in doc_files:
                activities.append(
                    {
                        "kind": "doc",
                        "title": f"{project_slug} doc updated",
                        "description": f"{doc_dir.name}/{doc_path.name}",
                        "timestamp": to_iso_from_ts(doc_path.stat().st_mtime),
                        "project_slug": project_slug,
                        "paper_id": None,
                    }
                )

    annotations = recent_annotations(theme_slug, limit=6)
    for row in annotations:
        activities.append(
            {
                "kind": "annotation",
                "title": f"Annotation on paper #{row['paper_id']}",
                "description": f"{row['section']} · {row['title']}",
                "timestamp": row["created_at"],
                "project_slug": paper_to_project.get(row["paper_id"], "unknown"),
                "paper_id": row["paper_id"],
            }
        )

    activities = [item for item in activities if item.get("timestamp")]
    activities.sort(key=lambda item: item["timestamp"], reverse=True)
    return dedupe_activities(activities, limit=limit)


def dedupe_activities(activities: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str, str]] = set()
    for item in activities:
        dedupe_key = (item.get("project_slug"), item["kind"], item["description"])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/themes")
def api_themes():
    payload = []
    for slug in THEMES:
        overview = theme_overview(slug)
        payload.append(
            {
                "slug": overview["slug"],
                "title": overview["title"],
                "summary": overview["summary"],
                "status": overview["status"],
                "project_count": overview["project_count"],
                "paper_count": overview["paper_count"],
                "annotated_count": overview["annotated_count"],
                "card_count": overview["card_count"],
                "pdf_count": overview["pdf_count"],
                "card_coverage": overview["card_coverage"],
                "pdf_coverage": overview["pdf_coverage"],
            }
        )
    return jsonify(payload)


@app.route("/api/themes/<theme_slug>/overview")
def api_theme_overview(theme_slug: str):
    if theme_slug not in THEMES:
        return jsonify({"error": f"Unknown theme: {theme_slug}"}), 404
    overview = theme_overview(theme_slug)
    overview["generated_at"] = iso_now()
    return jsonify(overview)


@app.route("/api/themes/<theme_slug>/projects")
def api_theme_projects(theme_slug: str):
    if theme_slug not in THEMES:
        return jsonify({"error": f"Unknown theme: {theme_slug}"}), 404
    papers = list_theme_papers(theme_slug)
    assignments = assign_project_papers(theme_slug, papers)
    payload = [
        load_project_summary(project_slug, assignments.get(project_slug, []))
        for project_slug in THEMES[theme_slug]["project_slugs"]
    ]
    return jsonify(payload)


@app.route("/api/projects/<project_slug>")
def api_project_detail(project_slug: str):
    if project_slug not in PROJECTS:
        return jsonify({"error": f"Unknown project: {project_slug}"}), 404
    papers = list_theme_papers(PROJECTS[project_slug]["theme_slug"])
    assignments = assign_project_papers(PROJECTS[project_slug]["theme_slug"], papers)
    summary = load_project_summary(project_slug, assignments.get(project_slug, []))
    docs = project_documents(project_slug)
    monitor = project_monitor(project_slug, assignments.get(project_slug, []), docs)
    project_path = PROJECTS[project_slug]["path"]
    readme_path = project_path / "README.md"
    handoff_path = project_path / "session_handoff.md"
    readme_text = readme_path.read_text() if readme_path.exists() else ""
    handoff_text = handoff_path.read_text() if handoff_path.exists() else ""
    detail = {
        **summary,
        "research_theme": " ".join(extract_heading_section(readme_text, "## 研究主题")),
        "status_lines": summary["status_lines"],
        "blockers": summary["blockers"],
        "next_steps": summary["next_steps"],
        "docs_path": str(project_path / "docs"),
        "references_path": str(project_path / "references"),
        "documents": docs,
        "monitor": monitor,
        "handoff_path": str(handoff_path),
        "readme_path": str(readme_path),
    }
    return jsonify(detail)


@app.route("/api/projects/<project_slug>/papers")
def api_project_papers(project_slug: str):
    if project_slug not in PROJECTS:
        return jsonify({"error": f"Unknown project: {project_slug}"}), 404
    papers = list_theme_papers(PROJECTS[project_slug]["theme_slug"])
    assignments = assign_project_papers(PROJECTS[project_slug]["theme_slug"], papers)
    return jsonify(attach_project_groups(project_slug, assignments.get(project_slug, [])))


@app.route("/api/projects/<project_slug>/documents/<doc_id>")
def api_project_document(project_slug: str, doc_id: str):
    if project_slug not in PROJECTS:
        return jsonify({"error": f"Unknown project: {project_slug}"}), 404
    doc_path = resolve_project_document(project_slug, doc_id)
    if doc_path is None or not doc_path.exists():
        return jsonify({"error": f"Document not found: {doc_id}"}), 404
    return jsonify(
        {
            "id": doc_id,
            "path": str(doc_path),
            "content": doc_path.read_text(),
            "updated_at": to_iso_from_ts(doc_path.stat().st_mtime),
        }
    )


@app.route("/api/papers/<int:paper_id>/card")
def api_paper_card(paper_id: int):
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            p.id,
            p.title,
            p.venue,
            p.year,
            p.doi,
            p.arxiv_id,
            p.url,
            p.pdf_path,
            p.status,
            p.created_at,
            p.affiliations,
            GROUP_CONCAT(t.name, '|') AS topic_names
        FROM papers p
        LEFT JOIN paper_topics pt ON pt.paper_id = p.id
        LEFT JOIN topics t ON t.id = pt.topic_id
        WHERE p.id = ?
        GROUP BY p.id
        """,
        (paper_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": f"Paper not found: {paper_id}"}), 404

    paper = serialize_paper_row(row)
    card_payload, card_status, card_path = load_card_payload(paper_id, row["arxiv_id"] or "")
    return jsonify(
        {
            "paper": paper,
            "card_status": card_status,
            "card_path": card_path,
            "card": card_payload,
        }
    )


@app.route("/api/pipeline/events")
def api_pipeline_events():
    """Return recent pipeline events and summary counts."""
    limit = 50
    conn = get_db_connection()
    try:
        # Check if pipeline_events table exists
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pipeline_events'"
        ).fetchone()
        if not table_exists:
            return jsonify({"events": [], "summary": {}})

        rows = conn.execute(
            """
            SELECT pe.id, pe.paper_id, pe.event_type, pe.detail, pe.provider, pe.created_at,
                   p.title, p.arxiv_id
            FROM pipeline_events pe
            LEFT JOIN papers p ON p.id = pe.paper_id
            ORDER BY pe.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        events = [
            {
                "id": row["id"],
                "paper_id": row["paper_id"],
                "event_type": row["event_type"],
                "detail": row["detail"] or "",
                "provider": row["provider"] or "",
                "created_at": row["created_at"] or "",
                "paper_title": row["title"] or "",
                "arxiv_id": row["arxiv_id"] or "",
            }
            for row in rows
        ]

        # Summary counts (last 7 days)
        summary_rows = conn.execute(
            """
            SELECT event_type, COUNT(*) as cnt
            FROM pipeline_events
            WHERE created_at >= datetime('now', '-7 days')
            GROUP BY event_type
            """
        ).fetchall()
        summary = {row["event_type"]: row["cnt"] for row in summary_rows}
    finally:
        conn.close()

    return jsonify({"events": events, "summary": summary})


@app.route("/api/activity")
def api_activity():
    # Aggregate activity across all configured themes
    all_activities: list[dict[str, Any]] = []
    for theme_slug in THEMES:
        papers = list_theme_papers(theme_slug)
        assignments = assign_project_papers(theme_slug, papers)
        all_activities.extend(build_activity_feed(theme_slug, assignments))
    all_activities.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return jsonify(all_activities[:20])


if __name__ == "__main__":
    port = 18080
    print("=" * 60)
    print("Research Hub Monitoring Dashboard")
    print("=" * 60)
    print(f"Dashboard: http://localhost:{port}")
    print(f"Database: {DB_PATH}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=True)
