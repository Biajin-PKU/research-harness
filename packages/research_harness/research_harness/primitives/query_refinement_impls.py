"""Query refinement primitive registration.

The LLM-backed implementation is dispatched by execution/llm_primitives.py.
This module keeps the registry complete and provides a conservative fallback.
"""

from __future__ import annotations

from typing import Any

from .registry import QUERY_REFINE_SPEC, register_primitive
from .types import QueryRefineOutput


@register_primitive(QUERY_REFINE_SPEC)
def query_refine(
    *, topic_id: int, max_candidates: int = 8, **_: Any
) -> QueryRefineOutput:
    return QueryRefineOutput(
        topic_id=topic_id,
        candidates=[],
        top_keywords=[],
        frequent_authors=[],
        venue_distribution=[],
        known_queries=[],
        gaps_considered=[],
        model_used="stub",
    )
