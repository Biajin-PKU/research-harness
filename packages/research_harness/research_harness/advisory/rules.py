"""Heuristic advisory rules for topic and project health."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

from ..orchestrator.models import DEFAULT_MIN_PAPER_COUNT
from ..storage.db import Database
from .models import Advisory, AdvisoryStore


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _column_exists(conn, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return False
    return any(row["name"] == column for row in rows)


class AdvisoryEngine:
    """Run lightweight topic-health checks and persist the resulting advisories."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._store = AdvisoryStore(db)

    def run(self, topic_id: int) -> list[Advisory]:
        advisories = (
            self._coverage_low(topic_id)
            + self._recency_gap(topic_id)
            + self._source_bias(topic_id)
            + self._dependency_stale(topic_id)
            + self._missing_stage(topic_id)
            + self._claim_contradiction(topic_id)
        )
        saved: list[Advisory] = []
        for advisory in advisories:
            if self._store.has_active_advisory(
                advisory.topic_id, advisory.category, advisory.message
            ):
                continue
            saved.append(self._store.save(advisory))
        return saved

    def list(self, topic_id: int, level: str | None = None) -> list[Advisory]:
        return self._store.list_advisories(topic_id=topic_id, level=level)

    def acknowledge(self, advisory_id: int) -> Advisory | None:
        return self._store.acknowledge(advisory_id)

    def _coverage_low(self, topic_id: int) -> list[Advisory]:
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT pt.paper_id) AS cnt
                FROM paper_topics pt
                WHERE pt.topic_id = ?
                """,
                (topic_id,),
            ).fetchone()
        finally:
            conn.close()
        count = int(row["cnt"] if row and row["cnt"] is not None else 0)
        if count >= DEFAULT_MIN_PAPER_COUNT:
            return []
        return [
            Advisory(
                topic_id=topic_id,
                level="info",
                category="coverage_low",
                message=f"Topic has only {count} papers; recommended minimum is {DEFAULT_MIN_PAPER_COUNT} before deeper analysis.",
                details={
                    "paper_count": count,
                    "recommended_minimum": DEFAULT_MIN_PAPER_COUNT,
                },
            )
        ]

    def _recency_gap(self, topic_id: int) -> list[Advisory]:
        current_year = datetime.now().year
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT MAX(p.year) AS latest_year
                FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                """,
                (topic_id,),
            ).fetchone()
        finally:
            conn.close()
        latest_year = row["latest_year"] if row else None
        if latest_year is None or int(latest_year) >= current_year - 1:
            return []
        return [
            Advisory(
                topic_id=topic_id,
                level="info",
                category="recency_gap",
                message=f"Latest paper is from {latest_year}; recent work may be missing.",
                details={"latest_year": int(latest_year), "current_year": current_year},
            )
        ]

    def _source_bias(self, topic_id: int) -> list[Advisory]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT p.authors
                FROM papers p
                JOIN paper_topics pt ON pt.paper_id = p.id
                WHERE pt.topic_id = ?
                """,
                (topic_id,),
            ).fetchall()
        finally:
            conn.close()
        authors: list[str] = []
        for row in rows:
            try:
                parsed = json.loads(row["authors"]) if row["authors"] else []
            except (TypeError, json.JSONDecodeError):
                parsed = []
            authors.extend(
                str(author).strip() for author in parsed if str(author).strip()
            )
        if len(authors) < 6:
            return []
        counts = Counter(authors)
        top_author, top_count = counts.most_common(1)[0]
        share = top_count / max(len(authors), 1)
        if share <= 0.5:
            return []
        return [
            Advisory(
                topic_id=topic_id,
                level="info",
                category="source_bias",
                message=f"Author concentration is high: {top_author} appears in {share:.0%} of author slots.",
                details={
                    "top_author": top_author,
                    "share": round(share, 3),
                    "author_slots": len(authors),
                },
            )
        ]

    def _dependency_stale(self, topic_id: int) -> list[Advisory]:
        conn = self._db.connect()
        try:
            if not _table_exists(conn, "artifact_dependencies"):
                return []
            if not _column_exists(conn, "project_artifacts", "stale"):
                return []
            rows = conn.execute(
                """
                SELECT id, artifact_type, stage, stale_reason
                FROM project_artifacts
                WHERE topic_id = ? AND status = 'active' AND stale = 1
                ORDER BY updated_at DESC
                LIMIT 5
                """,
                (topic_id,),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return []
        sample = [
            {
                "artifact_id": int(row["id"]),
                "artifact_type": row["artifact_type"],
                "stage": row["stage"],
                "stale_reason": row["stale_reason"] or "",
            }
            for row in rows
        ]
        return [
            Advisory(
                topic_id=topic_id,
                level="info",
                category="dependency_stale",
                message=f"{len(rows)} active artifacts are marked stale and should be refreshed.",
                details={"stale_artifacts": sample},
            )
        ]

    def _missing_stage(self, topic_id: int) -> list[Advisory]:
        conn = self._db.connect()
        try:
            run = conn.execute(
                """
                SELECT current_stage FROM orchestrator_runs
                WHERE topic_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
            if run is None:
                return []
            current_stage = str(run["current_stage"] or "").strip()
            if current_stage in ("init", "build", ""):
                return []
            has_build = conn.execute(
                """
                SELECT 1 FROM project_artifacts
                WHERE topic_id = ?
                  AND stage IN ('build', 'literature_mapping', 'paper_acquisition')
                  AND status = 'active'
                LIMIT 1
                """,
                (topic_id,),
            ).fetchone()
        finally:
            conn.close()
        if has_build is not None:
            return []
        return [
            Advisory(
                topic_id=topic_id,
                level="info",
                category="missing_stage",
                message=f"Topic is at stage '{current_stage}' without active Build-stage artifacts.",
                details={"current_stage": current_stage},
            )
        ]

    def _claim_contradiction(self, topic_id: int) -> list[Advisory]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ? AND artifact_type IN ('claim_candidate_set', 'claims', 'claim_set')
                  AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 4
                """,
                (topic_id,),
            ).fetchall()
        finally:
            conn.close()

        positives = ("improve", "increase", "better", "gain", "boost")
        negatives = ("decrease", "worse", "hurt", "drop", "reduce")
        seen_positive = False
        seen_negative = False
        matched_claims: list[str] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            for claim in payload.get("claims", []):
                if not isinstance(claim, dict):
                    continue
                content = str(claim.get("content", "")).strip().lower()
                if not content:
                    continue
                has_pos = any(word in content for word in positives)
                has_neg = any(word in content for word in negatives)
                if has_pos:
                    seen_positive = True
                if has_neg:
                    seen_negative = True
                if has_pos or has_neg:
                    matched_claims.append(content[:140])
        if not (seen_positive and seen_negative):
            return []
        return [
            Advisory(
                topic_id=topic_id,
                level="warning",
                category="claim_contradiction",
                message="Claim set contains potentially contradictory directional findings.",
                details={"sample_claims": matched_claims[:4]},
            )
        ]
