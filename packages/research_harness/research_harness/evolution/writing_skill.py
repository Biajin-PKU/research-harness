"""Writing Skill Aggregator — builds Universal Writing Skill from observations.

Reads writing_observations (extracted per-paper structural patterns),
aggregates them into per-dimension guidance, quality-gates via the
existing strategy system, and persists as strategies for injection
into section_draft prompts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..primitives.types import (
    ALL_WRITING_DIMENSIONS,
    WRITING_SKILL_DIMENSIONS,
    DimensionGuidance,
    WritingSkillAggregateOutput,
)
from ..storage.db import Database
from .injector import StrategyInjector

logger = logging.getLogger(__name__)

STAGE_KEY = "write"
STRATEGY_PREFIX = "writing_skill"
MIN_OBSERVATIONS = 5  # per dimension, for confidence


class WritingSkillAggregator:
    """Aggregate writing observations into reusable section-specific guidance."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def aggregate(
        self,
        *,
        min_papers: int = 10,
        _model: str | None = None,
    ) -> WritingSkillAggregateOutput:
        """Run aggregation pipeline: collect → stats → synthesize → persist."""
        # Phase 1: Collect all observations grouped by dimension
        obs_by_dim = self._collect_observations()
        total_papers = self._count_unique_papers()

        if total_papers < min_papers:
            logger.info(
                "Not enough papers for writing skill (%d < %d)",
                total_papers, min_papers,
            )
            return WritingSkillAggregateOutput(total_papers_analyzed=total_papers)

        # Phase 2: Build per-dimension guidance
        guidances: list[DimensionGuidance] = []
        created = 0
        updated = 0

        for dim in ALL_WRITING_DIMENSIONS:
            observations = obs_by_dim.get(dim, [])
            if len(observations) < MIN_OBSERVATIONS:
                logger.debug("Skipping %s: only %d observations", dim, len(observations))
                continue

            section = _dim_to_section(dim)
            guidance = self._build_dimension_guidance(dim, section, observations)
            guidances.append(guidance)

            # Persist as strategy
            is_new = self._persist_as_strategy(guidance)
            if is_new:
                created += 1
            else:
                updated += 1

        return WritingSkillAggregateOutput(
            dimensions=guidances,
            total_papers_analyzed=total_papers,
            strategies_created=created,
            strategies_updated=updated,
            model_used="deterministic",
        )

    def get_section_guidance(self, section: str) -> str:
        """Get aggregated writing guidance for a section, formatted for prompt injection.

        Returns empty string if no guidance available.
        """
        dims = WRITING_SKILL_DIMENSIONS.get(section, [])
        if not dims:
            return ""

        injector = StrategyInjector(self._db)
        strategies = injector.get_active_strategies(
            STAGE_KEY, max_strategies=20,
        )

        relevant = [
            s for s in strategies
            if s.strategy_key.startswith(f"{STRATEGY_PREFIX}.")
            and any(d in s.strategy_key for d in dims)
        ]

        if not relevant:
            return ""

        lines = [
            f"## Section-Specific Writing Requirements (Universal Writing Skill)\n",
            f"_Based on structural analysis of papers from top venues._\n",
        ]
        for s in relevant:
            lines.append(s.content)
            lines.append("")

        return "\n".join(lines)

    def get_all_guidance(self) -> dict[str, str]:
        """Get writing guidance for all sections."""
        result: dict[str, str] = {}
        for section in WRITING_SKILL_DIMENSIONS:
            guidance = self.get_section_guidance(section)
            if guidance:
                result[section] = guidance
        return result

    def get_venue_guidance(self, venue: str) -> str:
        """Load cached venue writing profiles and format as injectable guidance."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT dimension, top_pattern, paper_count, updated_at
                   FROM venue_writing_profiles
                   WHERE venue = ?
                   ORDER BY dimension""",
                (venue,),
            ).fetchall()
        except Exception:
            return ""
        finally:
            conn.close()
        if not rows:
            return ""
        lines = [f"## Venue-Specific Patterns: {venue}", ""]
        for r in rows:
            lines.append(f"**{r['dimension']}**: {r['top_pattern']}")
        return "\n".join(lines)

    # ---- Internal ----

    def _collect_observations(self) -> dict[str, list[dict[str, Any]]]:
        """Fetch all observations grouped by dimension."""
        conn = self._db.connect()
        try:
            rows = conn.execute(
                """SELECT dimension, section, observation, example_text,
                          paper_venue, paper_venue_tier, paper_year, paper_id
                   FROM writing_observations
                   ORDER BY dimension, paper_year DESC"""
            ).fetchall()
        finally:
            conn.close()

        grouped: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            dim = r["dimension"]
            grouped.setdefault(dim, []).append(dict(r))
        return grouped

    def _count_unique_papers(self) -> int:
        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT paper_id) as cnt FROM writing_observations"
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def _build_dimension_guidance(
        self,
        dim: str,
        section: str,
        observations: list[dict[str, Any]],
    ) -> DimensionGuidance:
        """Deterministically aggregate observations into guidance."""
        # Parse observations and build pattern distribution
        pattern_counts: dict[str, int] = {}
        examples: list[str] = []
        venues_seen: set[str] = set()

        for obs in observations:
            obs_text = obs.get("observation", "")

            # Try to extract pattern type from observation text
            # The observation is structured text, so we look for type indicators
            obs_lower = obs_text.lower()
            for pattern_type in _get_pattern_types(dim):
                if pattern_type.lower() in obs_lower:
                    pattern_counts[pattern_type] = pattern_counts.get(pattern_type, 0) + 1
                    break
            else:
                pattern_counts["other"] = pattern_counts.get("other", 0) + 1

            # Collect examples from tier-A venues first
            example = obs.get("example_text", "").strip()
            if example and obs.get("paper_venue_tier") == "A" and len(examples) < 3:
                venue = obs.get("paper_venue", "")
                examples.append(f"[{venue}] {example}")
            venues_seen.add(obs.get("paper_venue", ""))

        # Fill examples from non-A venues if needed
        if len(examples) < 2:
            for obs in observations:
                example = obs.get("example_text", "").strip()
                if example and example not in [e.split("] ", 1)[-1] for e in examples]:
                    venue = obs.get("paper_venue", "")
                    examples.append(f"[{venue}] {example}")
                    if len(examples) >= 3:
                        break

        # Compute distribution
        total = sum(pattern_counts.values()) or 1
        distribution = {k: round(v / total, 2) for k, v in sorted(
            pattern_counts.items(), key=lambda x: -x[1]
        )}

        # Build recommended approach
        top_pattern = max(pattern_counts, key=pattern_counts.get) if pattern_counts else "unknown"
        n_papers = len(observations)
        confidence = min(1.0, n_papers / 30)  # saturates at 30 papers

        recommended = _build_recommendation(dim, top_pattern, distribution, n_papers)
        anti_patterns = _get_anti_patterns(dim)

        return DimensionGuidance(
            dimension=dim,
            section=section,
            pattern_distribution=distribution,
            recommended_approach=recommended,
            examples=examples[:3],
            anti_patterns=anti_patterns,
            source_paper_count=n_papers,
            confidence=round(confidence, 2),
        )

    def _persist_as_strategy(self, guidance: DimensionGuidance) -> bool:
        """Persist guidance as a strategy. Returns True if new, False if updated."""
        strategy_key = f"{STRATEGY_PREFIX}.{guidance.dimension}"
        content = _format_guidance_as_markdown(guidance)

        conn = self._db.connect()
        try:
            existing = conn.execute(
                """SELECT id, version FROM strategies
                   WHERE strategy_key = ? AND status = 'active'
                   ORDER BY version DESC LIMIT 1""",
                (strategy_key,),
            ).fetchone()

            if existing:
                # Supersede old version, create new
                conn.execute(
                    "UPDATE strategies SET status = 'superseded' WHERE id = ?",
                    (existing["id"],),
                )
                version = existing["version"] + 1
                is_new = False
            else:
                version = 1
                is_new = True

            conn.execute(
                """INSERT INTO strategies
                   (stage, strategy_key, title, content, scope, version,
                    quality_score, gate_model, source_lesson_ids,
                    source_session_count, status)
                   VALUES (?, ?, ?, ?, 'global', ?, ?, 'deterministic', '[]', ?, 'active')""",
                (
                    STAGE_KEY,
                    strategy_key,
                    f"Writing Skill: {guidance.dimension}",
                    content,
                    version,
                    guidance.confidence,
                    guidance.source_paper_count,
                ),
            )
            conn.commit()
            return is_new
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dim_to_section(dim: str) -> str:
    for sec, dims in WRITING_SKILL_DIMENSIONS.items():
        if dim in dims:
            return sec
    return "overall"


def _get_pattern_types(dim: str) -> list[str]:
    """Known pattern types for each dimension."""
    return {
        "abstract_hook_type": [
            "statistic", "contradiction", "question", "failure_case", "trend", "definition",
        ],
        "abstract_structure": [
            "hook-gap-method-result", "background-gap-method-result",
            "hook-background-gap-method-result-implication",
        ],
        "intro_tension_building": [
            "concrete_failure", "running_example", "gap_accumulation", "question_driven",
        ],
        "intro_contribution_style": [
            "numbered_list", "inline", "insight_driven",
        ],
        "rw_taxonomy_type": [
            "by_method", "by_problem", "by_timeline", "hybrid", "table_comparison",
        ],
        "rw_positioning": [
            "subsection_end", "paragraph_end", "dedicated_paragraph", "none",
        ],
        "method_motivation_ratio": [
            "high_motivation", "balanced", "formula_heavy", "minimal_motivation",
        ],
        "method_design_justification": [
            "explicit_alternatives", "implicit_justification", "no_justification",
        ],
        "exp_post_table_analysis": [
            "detailed_multi_paragraph", "single_paragraph", "minimal", "none",
        ],
        "exp_result_narrative": [
            "hypothesis_first", "table_first", "domain_by_domain", "metric_by_metric",
        ],
        "conclusion_structure": [
            "summary_only", "summary_limitations", "summary_limitations_future",
            "summary_limitations_future_impact",
        ],
        "claim_calibration": [
            "well_hedged", "moderate_claims", "overclaiming", "appropriately_bold",
        ],
    }.get(dim, ["type_a", "type_b", "other"])


def _get_anti_patterns(dim: str) -> list[str]:
    """Known anti-patterns for each dimension."""
    return {
        "abstract_hook_type": [
            "Starting with 'X has attracted growing interest' or 'X is important'",
            "Starting with a definition that every reader already knows",
        ],
        "abstract_structure": [
            "All sentences roughly the same length",
            "No concrete result numbers in the abstract",
        ],
        "intro_tension_building": [
            "Jumping to contributions without building tension",
            "Listing methods without explaining why they're insufficient",
        ],
        "intro_contribution_style": [
            "Contributions that describe what you DID rather than what you FOUND",
            "Claiming 'the first' without 'to our knowledge' hedge",
        ],
        "rw_taxonomy_type": [
            "'X does A. Y does B. Z does C.' phone-book enumeration",
            "No positioning statement at subsection end",
        ],
        "rw_positioning": [
            "Missing explicit comparison with your method",
            "Generic 'Unlike prior work' without specifics",
        ],
        "method_motivation_ratio": [
            "Equations appearing without any preceding intuition",
            "Design choices presented without justification",
        ],
        "method_design_justification": [
            "Only describing WHAT, never WHY",
            "No mention of alternatives considered",
        ],
        "exp_post_table_analysis": [
            "Table followed immediately by next subsection heading",
            "'As shown in Table X' without explaining WHY results differ",
        ],
        "exp_result_narrative": [
            "Reading numbers from the table without interpretation",
            "Not connecting results back to hypotheses or contributions",
        ],
        "conclusion_structure": [
            "Conclusion that only repeats the abstract",
            "Missing limitations section (required by NeurIPS/ICML/KDD since 2023)",
        ],
        "claim_calibration": [
            "Using 'the first' without thorough literature search evidence",
            "Using 'novel' more than twice in the paper",
        ],
    }.get(dim, [])


def _build_recommendation(
    dim: str, top_pattern: str, distribution: dict[str, float], n_papers: int,
) -> str:
    """Build a concise recommendation for a dimension."""
    top_pct = int(distribution.get(top_pattern, 0) * 100)
    base = f"Based on {n_papers} papers: {top_pct}% use '{top_pattern}' pattern."

    extras = {
        "abstract_hook_type": " Open with a concrete fact, contradiction, or quantified gap — not a generic importance statement.",
        "abstract_structure": " Follow hook → gap → method summary → key result (with number). 4-6 sentences typical.",
        "intro_tension_building": " Build tension over 3-5 paragraphs before listing contributions. Use concrete evidence of existing method failures.",
        "intro_contribution_style": " Each contribution should state the INSIGHT, not just the artifact. Hedge novelty claims with 'to our knowledge'.",
        "rw_taxonomy_type": " Organize by method family or problem dimension with a clear taxonomy. End each subsection with explicit positioning.",
        "rw_positioning": " Every Related Work subsection must end with a sentence comparing prior work to yours.",
        "method_motivation_ratio": " Before each equation, provide 1-3 sentences of design intuition. Explain WHY this formulation, not just WHAT.",
        "method_design_justification": " Explicitly mention at least one alternative you considered and why you rejected it.",
        "exp_post_table_analysis": " EVERY result table must be followed by 1-2 paragraphs analyzing winners, losers, and why. Never leave a table uninterpreted.",
        "exp_result_narrative": " Lead with the claim/finding, then point to the table as evidence. Don't start with 'As shown in Table X'.",
        "conclusion_structure": " Must include: key finding restatement, limitations, and future work. NeurIPS/ICML require limitations.",
        "claim_calibration": " Use 'the first' at most once, always with 'to our knowledge'. Prefer 'among the first' or factual differentiation.",
    }
    return base + extras.get(dim, "")


def _format_guidance_as_markdown(g: DimensionGuidance) -> str:
    """Format DimensionGuidance as markdown for strategy content."""
    lines = [
        f"### {g.dimension.upper().replace('_', ' ')}",
        "",
        g.recommended_approach,
        "",
    ]
    if g.pattern_distribution:
        lines.append("**Pattern distribution:**")
        for pattern, pct in g.pattern_distribution.items():
            lines.append(f"- {pattern}: {int(pct * 100)}%")
        lines.append("")

    if g.examples:
        lines.append("**Examples from top papers:**")
        for ex in g.examples:
            lines.append(f"> {ex}")
            lines.append("")

    if g.anti_patterns:
        lines.append("**Anti-patterns to AVOID:**")
        for ap in g.anti_patterns:
            lines.append(f"- {ap}")
        lines.append("")

    lines.append(f"_Confidence: {g.confidence} (based on {g.source_paper_count} papers)_")
    return "\n".join(lines)
