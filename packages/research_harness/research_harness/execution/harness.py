"""ResearchHarnessBackend — LLM-powered research primitive execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from llm_router.client import resolve_llm_config

from ..primitives.registry import get_primitive_impl, get_primitive_spec
from ..primitives.types import EvidenceLink, EvidenceLinkOutput, PrimitiveResult
from ..storage.db import Database
from . import llm_primitives
from .backend import BackendInfo

PrimitiveImpl = Callable[..., Any]

_LLM_DISPATCH: dict[str, PrimitiveImpl] = {
    "paper_summarize": llm_primitives.paper_summarize,
    "claim_extract": llm_primitives.claim_extract,
    "gap_detect": llm_primitives.gap_detect,
    "query_refine": llm_primitives.query_refine,
    "paper_coverage_check": llm_primitives.paper_coverage_check,
    "baseline_identify": llm_primitives.baseline_identify,
    "competitive_learning": llm_primitives.competitive_learning,
    "section_draft": llm_primitives.section_draft,
    "consistency_check": llm_primitives.consistency_check,
    "deep_read": llm_primitives.deep_read,
    "outline_generate": llm_primitives.outline_generate,
    "section_review": llm_primitives.section_review,
    "section_revise": llm_primitives.section_revise,
    "code_generate": llm_primitives.code_generate,
    "method_taxonomy": llm_primitives.method_taxonomy,
    "evidence_matrix": llm_primitives.evidence_matrix,
    "contradiction_detect": llm_primitives.contradiction_detect,
    "table_extract": llm_primitives.table_extract,
    "figure_interpret": llm_primitives.figure_interpret,
    "rebuttal_format": llm_primitives.rebuttal_format,
    "lesson_extract": llm_primitives.lesson_extract,
    "iterative_retrieval_loop": llm_primitives.iterative_retrieval_loop,
    "topic_framing": llm_primitives.topic_framing,
    "direction_ranking": llm_primitives.direction_ranking,
    "method_layer_expansion": llm_primitives.method_layer_expansion,
    "writing_architecture": llm_primitives.writing_architecture,
    "writing_pattern_extract": llm_primitives.writing_pattern_extract,
    "figure_plan": llm_primitives.figure_plan,
    "figure_generate": llm_primitives.figure_generate,
    "design_brief_expand": llm_primitives.design_brief_expand,
    "design_gap_probe": llm_primitives.design_gap_probe,
    "algorithm_candidate_generate": llm_primitives.algorithm_candidate_generate,
    "originality_boundary_check": llm_primitives.originality_boundary_check,
    "algorithm_design_refine": llm_primitives.algorithm_design_refine,
    "algorithm_design_loop": llm_primitives.algorithm_design_loop,
}


def _writing_skill_aggregate_impl(
    *,
    db: Database,
    min_papers: int = 10,
    **_: Any,
) -> Any:
    from ..evolution.writing_skill import WritingSkillAggregator

    return WritingSkillAggregator(db).aggregate(min_papers=min_papers)


_LOCAL_DISPATCH: dict[str, PrimitiveImpl] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_link_impl(
    *,
    db: Database,
    claim_id: str,
    source_type: str,
    source_id: str,
    strength: str = "moderate",
    notes: str = "",
    **_: Any,
) -> EvidenceLinkOutput:
    del db
    return EvidenceLinkOutput(
        link=EvidenceLink(
            claim_id=claim_id,
            source_type=source_type,
            source_id=source_id,
            strength=strength,
            notes=notes,
        ),
        created=True,
    )


def _load_local_dispatch() -> None:
    if _LOCAL_DISPATCH:
        return
    _LOCAL_NAMES = (
        "paper_search",
        "paper_ingest",
        "get_deep_reading",
        "enrich_affiliations",
        # Topic-level config (no LLM)
        "topic_set_contributions",
        "topic_get_contributions",
        # Citation expansion (S2 API, no LLM)
        "select_seeds",
        "expand_citations",
        # Acquisition (no LLM)
        "paper_acquire",
        # Experiment primitives (registered via @register_primitive in experiment_impls)
        "code_validate",
        "experiment_run",
        "verified_registry_build",
        "verified_registry_check",
        # Phase 2 analysis (no LLM)
        "reading_prioritize",
        "experiment_design_checklist",
        "dataset_index",
        "author_coverage",
        # Phase 3 (no LLM)
        "metrics_aggregate",
        # Phase 4 (no LLM)
        "topic_export",
        "visualize_topic",
        # Write-stage integrity (no LLM)
        "paper_verify_numbers",
        "citation_verify",
        "evidence_trace",
        # Evolution (manages own LLM calls)
        "strategy_distill",
        "strategy_inject",
        "experiment_log",
        "meta_reflect",
        # Cold start protocol (no LLM — orchestrates other primitives)
        "cold_start_run",
        # LaTeX compilation (pure local)
        "latex_compile",
        "paper_finalize",
    )
    for name in _LOCAL_NAMES:
        impl = get_primitive_impl(name)
        if impl is not None:
            _LOCAL_DISPATCH[name] = impl
    _LOCAL_DISPATCH.setdefault("evidence_link", _evidence_link_impl)
    _LOCAL_DISPATCH.setdefault("writing_skill_aggregate", _writing_skill_aggregate_impl)


class ResearchHarnessBackend:
    """Execution backend that routes LLM primitives through the shared LLM client."""

    def __init__(self, db: Database | None = None, **_: Any) -> None:
        self._db = db
        self._llm_config = resolve_llm_config()
        self._provider = self._llm_config.provider
        self._model = self._llm_config.model
        self._has_api_key = bool(self._llm_config.api_key) or self._provider in (
            "cursor_agent",
            "codex",
        )

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        if self._db is None:
            raise NotImplementedError(
                "ResearchHarnessBackend not implemented yet. Available in Phase 3."
            )

        spec = get_primitive_spec(primitive)
        if spec is None:
            return PrimitiveResult(
                primitive=primitive,
                success=False,
                output=None,
                error=f"Unknown primitive: {primitive}",
                backend="research_harness",
            )

        started = _utc_now()
        call_kwargs = dict(kwargs)
        db = call_kwargs.pop("db", self._db)
        if db is None:
            finished = _utc_now()
            return PrimitiveResult(
                primitive=primitive,
                success=False,
                output=None,
                error="ResearchHarnessBackend requires a database instance",
                started_at=started,
                finished_at=finished,
                backend="research_harness",
                model_used=self._model if spec.requires_llm else "none",
            )

        if spec.requires_llm:
            impl = _LLM_DISPATCH.get(primitive)
            if impl is None:
                finished = _utc_now()
                return PrimitiveResult(
                    primitive=primitive,
                    success=False,
                    output=None,
                    error=f"LLM primitive '{primitive}' not implemented yet",
                    started_at=started,
                    finished_at=finished,
                    backend="research_harness",
                    model_used=self._model,
                )
            if not self._has_api_key:
                finished = _utc_now()
                return PrimitiveResult(
                    primitive=primitive,
                    success=False,
                    output=None,
                    error=(
                        "No LLM provider configured. Set CURSOR_AGENT_ENABLED=1, "
                        "ANTHROPIC_API_KEY, or OPENAI_API_KEY."
                    ),
                    started_at=started,
                    finished_at=finished,
                    backend="research_harness",
                    model_used=self._model,
                )
        else:
            _load_local_dispatch()
            impl = _LOCAL_DISPATCH.get(primitive)
            if impl is None:
                finished = _utc_now()
                return PrimitiveResult(
                    primitive=primitive,
                    success=False,
                    output=None,
                    error=f"No local implementation for: {primitive}",
                    started_at=started,
                    finished_at=finished,
                    backend="research_harness",
                    model_used="none",
                )

        # Reset the per-primitive token accumulator so multi-call primitives
        # (deep_read, claim_extract over chunks, ...) report *summed* usage.
        if spec.requires_llm:
            llm_primitives._reset_token_accumulator()

        try:
            output = impl(db=db, **call_kwargs)
            finished = _utc_now()
            model_used = getattr(output, "model_used", "") or (
                self._model if spec.requires_llm else "none"
            )
            prompt_tokens, completion_tokens = (
                llm_primitives._accumulated_tokens()
                if spec.requires_llm
                else (None, None)
            )
            return PrimitiveResult(
                primitive=primitive,
                success=True,
                output=output,
                started_at=started,
                finished_at=finished,
                backend="research_harness",
                model_used=model_used,
                cost_usd=self.estimate_cost(primitive, **call_kwargs),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        except Exception as exc:
            finished = _utc_now()
            prompt_tokens, completion_tokens = (
                llm_primitives._accumulated_tokens()
                if spec.requires_llm
                else (None, None)
            )
            return PrimitiveResult(
                primitive=primitive,
                success=False,
                output=None,
                error=str(exc),
                started_at=started,
                finished_at=finished,
                backend="research_harness",
                model_used=self._model if spec.requires_llm else "none",
                cost_usd=self.estimate_cost(primitive, **call_kwargs),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

    def get_info(self) -> BackendInfo:
        _load_local_dispatch()
        supported = sorted({*list(_LLM_DISPATCH.keys()), *_LOCAL_DISPATCH.keys()})
        description = (
            f"LLM-powered research primitives via {self._provider}/{self._model}"
            if self._model
            else f"LLM-powered research primitives via {self._provider}"
        )
        return BackendInfo(
            name="research_harness",
            supported_primitives=supported,
            requires_api_key=True,
            description=description,
        )

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        del kwargs
        spec = get_primitive_spec(primitive)
        if spec is None or not spec.requires_llm:
            return 0.0
        return 0.005

    def supports(self, primitive: str) -> bool:
        if primitive in _LLM_DISPATCH:
            return True
        _load_local_dispatch()
        return primitive in _LOCAL_DISPATCH
