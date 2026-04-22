"""Paper Card Schema v2 — final, post-adversarial-review.

Changes from v1 (35 fields, plain dict):
  - Frozen dataclasses with typed fields and from_dict()/to_dict() (Obj 6)
  - Consolidated overlaps: research_background→motivation, target_problem→problem_definition,
    main_contributions+claimed_novelties→contributions (v1 35 → v2 34 top-level keys)
  - citation_anchors → key_references: list[str] flat free-text (Obj 1)
  - mathematical_formulation: optional MathFormulation dataclass (Obj 2)
  - All content fields default to None, not "" (Obj 3)
  - key_results stays freeform; structured_results optional overlay (Obj 4)
  - reproducibility flattened to 3 scalar fields (Obj 5)
  - method_type → method_family (5 broad) + method_tags (open) (Obj 8)

CARD_FIELD_CONSUMERS — which downstream primitive reads which card field:

  claim_extract:
      core_idea, contributions, key_results, evidence
  gap_detect:
      related_work_positioning, key_references, limitations, assumptions
  baseline_identify:
      baselines, metrics, key_results, structured_results, datasets
  paper_summarize:
      core_idea, method_summary, motivation, problem_definition
  section_draft:
      method_summary, method_pipeline, algorithmic_view, mathematical_formulation,
      contributions, key_results, evidence
  consistency_check:
      contributions, key_results, assumptions, limitations, evidence

  Fields consumed by NO current primitive (kept for card display / future use):
      paper_id, title, authors, venue, year, pdf_path, source_url,
      artifact_links, domain_tags, technical_tags, application_scenarios,
      method_family, method_tags, future_directions, tasks, ablation_focus,
      efficiency_signals, code_url, reproduction_notes, reproducibility_score
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


METHOD_FAMILIES: tuple[str, ...] = (
    "learning_based",
    "optimization_based",
    "probabilistic",
    "game_theoretic",
    "heuristic",
)

REPRODUCIBILITY_SCORES: tuple[str, ...] = ("high", "medium", "low", "unknown")


@dataclass(frozen=True)
class MathFormulation:
    """Optional structured math — skip when PDF OCR is unreliable."""

    objective: str | None = None
    constraints: list[str] = field(default_factory=list)
    key_equations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "constraints": list(self.constraints),
            "key_equations": list(self.key_equations),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> MathFormulation | None:
        if data is None:
            return None
        return cls(
            objective=data.get("objective"),
            constraints=list(data.get("constraints") or []),
            key_equations=list(data.get("key_equations") or []),
        )


@dataclass(frozen=True)
class StructuredResult:
    """One quantitative result row, best-effort populated."""

    metric: str
    value: str
    baseline: str | None = None
    delta: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "baseline": self.baseline,
            "delta": self.delta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructuredResult:
        return cls(
            metric=str(data.get("metric", "")),
            value=str(data.get("value", "")),
            baseline=data.get("baseline"),
            delta=data.get("delta"),
        )


@dataclass(frozen=True)
class EvidenceEntry:
    """One extraction-evidence record linking a card field to source text."""

    section: str
    confidence: float = 0.0
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "confidence": self.confidence,
            "snippet": self.snippet,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceEntry:
        raw_confidence = data.get("confidence", 0.0)
        if isinstance(raw_confidence, str):
            confidence_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
            confidence = confidence_map.get(raw_confidence.strip().lower(), 0.0)
        else:
            confidence = float(raw_confidence or 0.0)
        return cls(
            section=str(data.get("section", "")),
            confidence=confidence,
            snippet=str(data.get("snippet", "")),
        )


@dataclass(frozen=True)
class PaperCard:
    """Frozen structured representation of a single paper."""

    paper_id: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    year: str | None = None
    pdf_path: str | None = None
    source_url: str | None = None

    artifact_links: list[str] = field(default_factory=list)
    domain_tags: list[str] = field(default_factory=list)
    technical_tags: list[str] = field(default_factory=list)

    motivation: str | None = None
    problem_definition: str | None = None
    application_scenarios: list[str] = field(default_factory=list)

    core_idea: str | None = None
    method_summary: str | None = None
    method_pipeline: list[str] = field(default_factory=list)
    method_family: str | None = None
    method_tags: list[str] = field(default_factory=list)
    algorithmic_view: str | None = None
    mathematical_formulation: MathFormulation | None = None

    contributions: list[str] = field(default_factory=list)
    related_work_positioning: str | None = None
    key_references: list[str] = field(default_factory=list)

    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    future_directions: str | None = None

    tasks: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    baselines: list[str] = field(default_factory=list)
    key_results: list[str] = field(default_factory=list)
    structured_results: list[StructuredResult] = field(default_factory=list)
    ablation_focus: list[str] = field(default_factory=list)
    efficiency_signals: list[str] = field(default_factory=list)

    code_url: str | None = None
    reproduction_notes: str | None = None
    reproducibility_score: str | None = None

    evidence: list[EvidenceEntry] = field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def keys(self):
        return self.to_dict().keys()

    def items(self):
        return self.to_dict().items()

    def values(self):
        return self.to_dict().values()

    def __iter__(self):
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(PAPER_CARD_FIELDS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": list(self.authors),
            "venue": self.venue,
            "year": self.year,
            "pdf_path": self.pdf_path,
            "source_url": self.source_url,
            "artifact_links": list(self.artifact_links),
            "domain_tags": list(self.domain_tags),
            "technical_tags": list(self.technical_tags),
            "motivation": self.motivation,
            "problem_definition": self.problem_definition,
            "application_scenarios": list(self.application_scenarios),
            "core_idea": self.core_idea,
            "method_summary": self.method_summary,
            "method_pipeline": list(self.method_pipeline),
            "method_family": self.method_family,
            "method_tags": list(self.method_tags),
            "algorithmic_view": self.algorithmic_view,
            "mathematical_formulation": (
                self.mathematical_formulation.to_dict()
                if self.mathematical_formulation is not None
                else None
            ),
            "contributions": list(self.contributions),
            "related_work_positioning": self.related_work_positioning,
            "key_references": list(self.key_references),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "future_directions": self.future_directions,
            "tasks": list(self.tasks),
            "datasets": list(self.datasets),
            "metrics": list(self.metrics),
            "baselines": list(self.baselines),
            "key_results": list(self.key_results),
            "structured_results": [r.to_dict() for r in self.structured_results],
            "ablation_focus": list(self.ablation_focus),
            "efficiency_signals": list(self.efficiency_signals),
            "code_url": self.code_url,
            "reproduction_notes": self.reproduction_notes,
            "reproducibility_score": self.reproducibility_score,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaperCard:
        math_raw = data.get("mathematical_formulation")
        math_obj = (
            MathFormulation.from_dict(math_raw) if isinstance(math_raw, dict) else None
        )

        structured = [
            StructuredResult.from_dict(item)
            for item in (data.get("structured_results") or [])
            if isinstance(item, dict)
        ]

        evidence = [
            EvidenceEntry.from_dict(item)
            for item in (data.get("evidence") or [])
            if isinstance(item, dict)
        ]

        return cls(
            paper_id=data.get("paper_id"),
            title=data.get("title"),
            authors=list(data.get("authors") or []),
            venue=data.get("venue"),
            year=data.get("year"),
            pdf_path=data.get("pdf_path"),
            source_url=data.get("source_url"),
            artifact_links=list(data.get("artifact_links") or []),
            domain_tags=list(data.get("domain_tags") or []),
            technical_tags=list(data.get("technical_tags") or []),
            motivation=data.get("motivation") or data.get("research_background"),
            problem_definition=data.get("problem_definition")
            or data.get("target_problem"),
            application_scenarios=list(data.get("application_scenarios") or []),
            core_idea=data.get("core_idea"),
            method_summary=data.get("method_summary"),
            method_pipeline=list(data.get("method_pipeline") or []),
            method_family=data.get("method_family") or data.get("method_type"),
            method_tags=list(data.get("method_tags") or []),
            algorithmic_view=data.get("algorithmic_view"),
            mathematical_formulation=math_obj,
            contributions=list(
                data.get("contributions")
                or data.get("main_contributions")
                or data.get("claimed_novelties")
                or []
            ),
            related_work_positioning=data.get("related_work_positioning"),
            key_references=list(
                data.get("key_references") or data.get("citation_anchors") or []
            ),
            assumptions=list(data.get("assumptions") or []),
            limitations=list(data.get("limitations") or []),
            future_directions=data.get("future_directions"),
            tasks=list(data.get("tasks") or []),
            datasets=list(data.get("datasets") or []),
            metrics=list(data.get("metrics") or []),
            baselines=list(data.get("baselines") or []),
            key_results=list(data.get("key_results") or []),
            structured_results=structured,
            ablation_focus=list(data.get("ablation_focus") or []),
            efficiency_signals=list(data.get("efficiency_signals") or []),
            code_url=data.get("code_url"),
            reproduction_notes=data.get("reproduction_notes"),
            reproducibility_score=data.get("reproducibility_score"),
            evidence=evidence,
        )


PAPER_CARD_FIELDS: tuple[str, ...] = tuple(PaperCard().to_dict().keys())


def build_empty_paper_card() -> PaperCard:
    """Return a PaperCard with all fields at defaults."""
    return PaperCard()


_ORIGINAL_JSON_ENCODER_DEFAULT = json.JSONEncoder.default


def _paperindex_json_default(self: json.JSONEncoder, obj: Any):
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return obj.to_dict()
    return _ORIGINAL_JSON_ENCODER_DEFAULT(self, obj)


if getattr(json.JSONEncoder.default, "__name__", "") != "_paperindex_json_default":
    json.JSONEncoder.default = _paperindex_json_default
