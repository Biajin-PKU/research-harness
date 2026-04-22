"""Cold Start Protocol — bootstrap a new topic from zero to analysis-ready.

Three phases:
  1. Seed   — ingest gold papers + keyword search + citation expansion → ≥50 papers
  2. Index  — paper cards + deep reads + writing pattern extraction
  3. Calibrate — coverage gate + gap detection + writing skill aggregate
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..orchestrator.models import DEFAULT_MIN_PAPER_COUNT
from ..storage.db import Database

logger = logging.getLogger(__name__)

SEED_SEARCH_BATCH = 30
SEED_EXPANSION_LIMIT = 30


class ColdStartPhase(Enum):
    SEED = "seed"
    INDEX = "index"
    CALIBRATE = "calibrate"


@dataclass
class PhaseTargets:
    min_papers: int = DEFAULT_MIN_PAPER_COUNT
    min_paper_cards: int = 30
    min_deep_reads: int = 15
    min_writing_observations: int = 10
    min_gaps: int = 3
    min_writing_dimensions: int = 8


@dataclass
class PhaseProgress:
    phase: ColdStartPhase
    targets: dict[str, int]
    current: dict[str, int]
    complete: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class ColdStartProtocolOutput:
    phases: dict[str, dict[str, Any]]
    complete: bool
    topic_id: int
    total_papers: int
    actions_taken: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


class ColdStartProtocol:
    """Orchestrate the three bootstrap phases for a new research topic."""

    def __init__(
        self,
        db: Database,
        topic_id: int,
        gold_papers: list[str] | None = None,
        targets: PhaseTargets | None = None,
    ) -> None:
        self._db = db
        self._topic_id = topic_id
        self._gold_papers = gold_papers or []
        self._targets = targets or PhaseTargets()

    def check_seed_phase(self) -> PhaseProgress:
        paper_count = self._count_topic_papers()
        targets = {"min_papers": self._targets.min_papers}
        current = {"min_papers": paper_count}
        complete = paper_count >= self._targets.min_papers
        notes = []
        if not complete:
            deficit = self._targets.min_papers - paper_count
            notes.append(
                f"Need {deficit} more papers (have {paper_count}/{self._targets.min_papers})"
            )
        return PhaseProgress(
            phase=ColdStartPhase.SEED,
            targets=targets,
            current=current,
            complete=complete,
            notes=notes,
        )

    def check_index_phase(self) -> PhaseProgress:
        card_count = self._count_paper_cards()
        deep_read_count = self._count_deep_reads()
        writing_obs_count = self._count_writing_observations()

        targets = {
            "min_paper_cards": self._targets.min_paper_cards,
            "min_deep_reads": self._targets.min_deep_reads,
            "min_writing_observations": self._targets.min_writing_observations,
        }
        current = {
            "min_paper_cards": card_count,
            "min_deep_reads": deep_read_count,
            "min_writing_observations": writing_obs_count,
        }
        complete = (
            card_count >= self._targets.min_paper_cards
            and deep_read_count >= self._targets.min_deep_reads
            and writing_obs_count >= self._targets.min_writing_observations
        )
        notes = []
        if card_count < self._targets.min_paper_cards:
            notes.append(
                f"Need {self._targets.min_paper_cards - card_count} more paper cards"
            )
        if deep_read_count < self._targets.min_deep_reads:
            notes.append(
                f"Need {self._targets.min_deep_reads - deep_read_count} more deep reads"
            )
        if writing_obs_count < self._targets.min_writing_observations:
            notes.append(
                f"Need {self._targets.min_writing_observations - writing_obs_count} more writing observations"
            )
        return PhaseProgress(
            phase=ColdStartPhase.INDEX,
            targets=targets,
            current=current,
            complete=complete,
            notes=notes,
        )

    def check_calibrate_phase(self) -> PhaseProgress:
        gap_count = self._count_gaps()
        writing_dims = self._count_writing_dimensions()

        targets = {
            "min_gaps": self._targets.min_gaps,
            "min_writing_dimensions": self._targets.min_writing_dimensions,
        }
        current = {
            "min_gaps": gap_count,
            "min_writing_dimensions": writing_dims,
        }
        complete = (
            gap_count >= self._targets.min_gaps
            and writing_dims >= self._targets.min_writing_dimensions
        )
        notes = []
        if gap_count < self._targets.min_gaps:
            notes.append(
                f"Need {self._targets.min_gaps - gap_count} more detected gaps"
            )
        if writing_dims < self._targets.min_writing_dimensions:
            notes.append(
                f"Writing skill covers {writing_dims}/{self._targets.min_writing_dimensions} dimensions"
            )
        return PhaseProgress(
            phase=ColdStartPhase.CALIBRATE,
            targets=targets,
            current=current,
            complete=complete,
            notes=notes,
        )

    def check_all(self) -> ColdStartProtocolOutput:
        seed = self.check_seed_phase()
        index = self.check_index_phase()
        calibrate = self.check_calibrate_phase()

        phases = {
            "seed": {
                "targets": seed.targets,
                "current": seed.current,
                "complete": seed.complete,
                "notes": seed.notes,
            },
            "index": {
                "targets": index.targets,
                "current": index.current,
                "complete": index.complete,
                "notes": index.notes,
            },
            "calibrate": {
                "targets": calibrate.targets,
                "current": calibrate.current,
                "complete": calibrate.complete,
                "notes": calibrate.notes,
            },
        }

        return ColdStartProtocolOutput(
            phases=phases,
            complete=seed.complete and index.complete and calibrate.complete,
            topic_id=self._topic_id,
            total_papers=self._count_topic_papers(),
        )

    # ------------------------------------------------------------------
    # run_* methods — execute each phase, return progress + actions taken
    # ------------------------------------------------------------------

    def run_seed_phase(self) -> PhaseProgress:
        """Execute seed phase: ingest gold papers via paper pool.

        Ingests gold papers directly; returns plan for remaining searches
        since search + citation expansion are better handled by the caller
        via paper_search and expand_citations primitives.
        """
        from ..core.paper_pool import Paper, PaperPool

        progress = self.check_seed_phase()
        if progress.complete:
            return progress

        pool = PaperPool(self._db)
        actions: list[str] = []

        for source in self._gold_papers:
            try:
                paper = Paper(
                    title=source,
                    arxiv_id=source if source.startswith("2") and "." in source else "",
                    doi=source if source.startswith("10.") else "",
                )
                pool.ingest(paper, topic_id=self._topic_id, relevance="high")
                actions.append(f"Ingested gold paper: {source}")
            except Exception as exc:
                logger.warning("Failed to ingest gold paper %s: %s", source, exc)

        topic_name = self._get_topic_name()
        queries = self._generate_seed_queries(topic_name) if topic_name else []

        if not progress.complete:
            deficit = self._targets.min_papers - progress.current.get("min_papers", 0)
            actions.append(
                f"Need {deficit} more papers. Run paper_search with queries: {queries}"
            )
            actions.append("Then run expand_citations on top-10 seed papers")
            actions.append("Then run paper_acquire to download PDFs")

        progress = self.check_seed_phase()
        progress.notes = actions + progress.notes
        return progress

    def run_index_phase(self) -> PhaseProgress:
        """Return execution plan for index phase (needs LLM execution).

        Caller should run these primitives via the execution backend.
        """
        progress = self.check_index_phase()
        if progress.complete:
            return progress

        paper_ids = self._get_unprocessed_paper_ids()
        plan: list[str] = []

        card_count = progress.current.get("min_paper_cards", 0)
        if card_count < self._targets.min_paper_cards:
            plan.append(
                f"Run paper_acquire for topic {self._topic_id} ({len(paper_ids)} papers)"
            )

        deep_count = progress.current.get("min_deep_reads", 0)
        if deep_count < self._targets.min_deep_reads:
            needed = self._targets.min_deep_reads - deep_count
            plan.append(f"Run deep_read on top-{needed} high-cited papers")

        writing_count = progress.current.get("min_writing_observations", 0)
        if writing_count < self._targets.min_writing_observations:
            needed = self._targets.min_writing_observations - writing_count
            plan.append(f"Run writing_pattern_extract on {needed} best-written papers")

        progress.notes = plan + progress.notes
        return progress

    def run_calibrate_phase(self) -> PhaseProgress:
        """Return execution plan for calibrate phase (needs LLM execution)."""
        progress = self.check_calibrate_phase()
        if progress.complete:
            return progress

        plan: list[str] = []
        gap_count = progress.current.get("min_gaps", 0)
        if gap_count < self._targets.min_gaps:
            plan.append(f"Run gap_detect for topic {self._topic_id}")

        dim_count = progress.current.get("min_writing_dimensions", 0)
        if dim_count < self._targets.min_writing_dimensions:
            plan.append(
                f"Run writing_skill_aggregate (need {self._targets.min_writing_dimensions - dim_count} more dims)"
            )

        progress.notes = plan + progress.notes
        return progress

    def run_all(self) -> ColdStartProtocolOutput:
        """Run seed phase directly, return plans for index + calibrate."""
        seed = self.run_seed_phase()
        index = self.run_index_phase()
        calibrate = self.run_calibrate_phase()

        actions: list[str] = []
        next_steps: list[str] = []

        if seed.notes:
            actions.extend(
                [n for n in seed.notes if n.startswith(("Ingested", "Searched"))]
            )
        if not index.complete:
            next_steps.extend([n for n in index.notes if n.startswith("Run ")])
        if not calibrate.complete:
            next_steps.extend([n for n in calibrate.notes if n.startswith("Run ")])

        phases = {
            "seed": {
                "targets": seed.targets,
                "current": seed.current,
                "complete": seed.complete,
                "notes": seed.notes,
            },
            "index": {
                "targets": index.targets,
                "current": index.current,
                "complete": index.complete,
                "notes": index.notes,
            },
            "calibrate": {
                "targets": calibrate.targets,
                "current": calibrate.current,
                "complete": calibrate.complete,
                "notes": calibrate.notes,
            },
        }

        return ColdStartProtocolOutput(
            phases=phases,
            complete=seed.complete and index.complete and calibrate.complete,
            topic_id=self._topic_id,
            total_papers=self._count_topic_papers(),
            actions_taken=actions,
            next_steps=next_steps,
        )

    def _count_topic_papers(self) -> int:
        conn = self._db.connect()
        try:
            row = conn.execute(
                """SELECT COUNT(DISTINCT paper_id) as cnt
                   FROM paper_topics
                   WHERE topic_id = ? AND relevance != 'dismissed'""",
                (self._topic_id,),
            ).fetchone()
            return int(row["cnt"]) if row else 0
        except Exception:
            return 0
        finally:
            conn.close()

    def _count_paper_cards(self) -> int:
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM paper_annotations
                WHERE paper_id IN (
                    SELECT paper_id FROM paper_topics WHERE topic_id = ?
                )
                """,
                (self._topic_id,),
            ).fetchone()
            return int(row["cnt"]) if row else 0
        except Exception:
            return 0
        finally:
            conn.close()

    def _count_deep_reads(self) -> int:
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM paper_annotations
                WHERE paper_id IN (
                    SELECT paper_id FROM paper_topics WHERE topic_id = ?
                ) AND section = 'deep_reading'
                """,
                (self._topic_id,),
            ).fetchone()
            return int(row["cnt"]) if row else 0
        except Exception:
            return 0
        finally:
            conn.close()

    def _count_writing_observations(self) -> int:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM writing_observations",
            ).fetchone()
            return int(row["cnt"]) if row else 0
        except Exception:
            return 0
        finally:
            conn.close()

    def _count_gaps(self) -> int:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """
                SELECT payload_json FROM project_artifacts
                WHERE topic_id = ?
                  AND artifact_type IN ('gap_detect', 'gap_analysis')
                  AND status = 'active'
                ORDER BY version DESC LIMIT 1
                """,
                (self._topic_id,),
            ).fetchall()
            if not rows:
                return 0
            try:
                payload = json.loads(rows[0]["payload_json"] or "{}")
            except (TypeError, ValueError):
                payload = {}
            return len(payload.get("gaps", []))
        except Exception:
            return 0
        finally:
            conn.close()

    def _count_writing_dimensions(self) -> int:
        conn = self._db.connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT strategy_key) as cnt FROM strategies
                WHERE strategy_key LIKE 'writing_skill.%' AND status = 'active'
                """,
            ).fetchone()
            return int(row["cnt"]) if row else 0
        except Exception:
            return 0
        finally:
            conn.close()

    def _get_topic_name(self) -> str:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT name FROM topics WHERE id = ?", (self._topic_id,)
            ).fetchone()
            return row["name"] if row else ""
        except Exception:
            return ""
        finally:
            conn.close()

    def _generate_seed_queries(self, topic_name: str) -> list[str]:
        words = topic_name.replace("-", " ").replace("_", " ")
        queries = [words]
        tokens = words.split()
        if len(tokens) >= 3:
            queries.append(" ".join(tokens[:3]))
        queries.append(f"{words} survey")
        return queries[:4]

    def _get_unprocessed_paper_ids(self) -> list[int]:
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT pt.paper_id FROM paper_topics pt
                   LEFT JOIN paper_annotations pa ON pt.paper_id = pa.paper_id
                   WHERE pt.topic_id = ? AND pa.id IS NULL
                   LIMIT 100""",
                (self._topic_id,),
            ).fetchall()
            return [r["paper_id"] for r in rows]
        except Exception:
            return []
        finally:
            conn.close()
