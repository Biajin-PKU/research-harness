"""V2 Self-Evolution Phase 3: Cold start via gold-standard paper comparison.

Uses published papers as "simulated human intervention" — compares system
drafts against gold sections and generates experience records capturing
the differences. These flow through the unified experience pipeline
(Phase 1) and are quality-gated (Phase 2).
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .experience import ExperienceRecord, ExperienceStore
from .gold_selector import GoldSelector

logger = logging.getLogger(__name__)

FIELD_DECAY_CONSTANTS: dict[str, float] = {
    "llm_systems": 18.0,
    "information_retrieval": 30.0,
    "data_mining": 30.0,
    "software_engineering": 36.0,
    "computer_vision": 24.0,
    "nlp": 20.0,
    "default": 30.0,
}


class TemporalRelevance:
    """Compute temporal relevance score for a paper or experience.

    Formula: exp(-age/τ) × venue_boost × citation_velocity_factor
    """

    def score(
        self,
        age_months: float,
        field: str = "default",
        venue_tier: str = "",
        citations: int = 0,
    ) -> float:
        tau = FIELD_DECAY_CONSTANTS.get(field, FIELD_DECAY_CONSTANTS["default"])
        base = math.exp(-age_months / tau)

        venue_boost = 1.0
        if venue_tier in ("ccf_a_star", "ccf_a"):
            venue_boost = 1.1
        elif venue_tier in ("ccf_b",):
            venue_boost = 1.05

        cite_factor = 1.0
        if citations > 0 and age_months > 0:
            velocity = citations / max(age_months, 1.0)
            cite_factor = min(1.2, 1.0 + velocity / 50.0)

        return min(1.0, base * venue_boost * cite_factor)


class ColdStartRunner:
    """Bootstrap the experience store using gold-standard papers."""

    def __init__(self, db: Any, gate: Any | None = None) -> None:
        self._db = db
        self._selector = GoldSelector(db)
        self._experience_store = ExperienceStore(db, gate=gate)

    def bootstrap(
        self,
        topic_id: int,
        max_papers: int = 5,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        gold_papers = self._selector.select(topic_id=topic_id, max_papers=max_papers)
        report = {
            "papers_evaluated": len(gold_papers),
            "experiences_generated": 0,
            "papers": [],
        }

        for gp in gold_papers:
            paper_info = {
                "paper_id": gp["paper_id"],
                "title": gp["title"],
                "sections_compared": [],
            }

            summaries = self._get_summaries(gp["paper_id"], topic_id)
            for section, text in summaries.items():
                if dry_run:
                    paper_info["sections_compared"].append(section)
                    continue

                records = self.run_comparison(
                    paper_id=gp["paper_id"],
                    section=section,
                    gold_text=text,
                    topic_id=topic_id,
                )
                paper_info["sections_compared"].append(section)
                report["experiences_generated"] += len(records)

            report["papers"].append(paper_info)

        return report

    def run_comparison(
        self,
        paper_id: int,
        section: str,
        gold_text: str,
        topic_id: int | None = None,
    ) -> list[ExperienceRecord]:
        if not gold_text.strip():
            return []

        record = ExperienceRecord(
            source_kind="gold_comparison",
            stage="section_draft",
            section=section,
            before_text="",
            after_text=gold_text,
            diff_summary=f"Gold standard for section '{section}' from paper {paper_id}",
            quality_delta=0.5,
            topic_id=topic_id,
            paper_id=paper_id,
            metadata={"gold_paper_id": paper_id, "comparison_type": "cold_start"},
        )

        self._experience_store.ingest(record)
        return [record]

    def _get_summaries(self, paper_id: int, topic_id: int) -> dict[str, str]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT summary, focus FROM compiled_summaries
                   WHERE paper_id = ? AND topic_id = ?""",
                (paper_id, topic_id),
            ).fetchall()
            result: dict[str, str] = {}
            for row in rows:
                focus = row["focus"] or "general"
                result[focus] = row["summary"]
            return result
        except Exception:
            return {}
        finally:
            conn.close()
