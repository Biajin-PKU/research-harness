"""LocalBackend — executes non-LLM primitives directly."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..primitives.registry import get_primitive_impl, get_primitive_spec, list_primitives
from ..primitives.types import PrimitiveResult
from .backend import BackendInfo


class LocalBackend:
    """Executes primitives that do not require LLM calls."""

    def __init__(self, db: Any):
        self._db = db

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        spec = get_primitive_spec(primitive)
        if spec is None:
            return PrimitiveResult(
                primitive=primitive,
                success=False,
                output=None,
                error=f"Unknown primitive: {primitive}",
                backend="local",
            )

        if spec.requires_llm:
            raise NotImplementedError(
                f"Primitive '{primitive}' requires LLM. Use ClaudeCodeBackend or ResearchHarnessBackend."
            )

        impl = get_primitive_impl(primitive)
        if impl is None:
            return PrimitiveResult(
                primitive=primitive,
                success=False,
                output=None,
                error=f"No implementation registered for: {primitive}",
                backend="local",
            )

        started = datetime.now(timezone.utc).isoformat()
        try:
            output = impl(db=self._db, **kwargs)
            finished = datetime.now(timezone.utc).isoformat()
            return PrimitiveResult(
                primitive=primitive,
                success=True,
                output=output,
                started_at=started,
                finished_at=finished,
                backend="local",
                model_used="none",
                cost_usd=0.0,
            )
        except Exception as exc:
            finished = datetime.now(timezone.utc).isoformat()
            return PrimitiveResult(
                primitive=primitive,
                success=False,
                output=None,
                error=str(exc),
                started_at=started,
                finished_at=finished,
                backend="local",
            )

    def get_info(self) -> BackendInfo:
        supported = [spec.name for spec in list_primitives() if not spec.requires_llm]
        return BackendInfo(
            name="local",
            supported_primitives=supported,
            requires_api_key=False,
            description="Executes non-LLM primitives directly via local DB",
        )

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        return 0.0

    def supports(self, primitive: str) -> bool:
        spec = get_primitive_spec(primitive)
        return spec is not None and not spec.requires_llm
