"""TrackedBackend — wraps any ExecutionBackend with automatic provenance recording."""

from __future__ import annotations

import logging
from typing import Any

from ..primitives.types import PrimitiveResult
from ..provenance.recorder import ProvenanceRecorder
from .backend import BackendInfo, ExecutionBackend


class TrackedBackend:
    """Decorator that adds provenance recording to any ExecutionBackend."""

    def __init__(
        self,
        inner: ExecutionBackend,
        recorder: ProvenanceRecorder,
        default_topic_id: int | None = None,
    ):
        self._inner = inner
        self._recorder = recorder
        self._default_topic_id = default_topic_id

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        # Accept both _topic_id (internal) and topic_id (from MCP arguments)
        topic_id = (
            kwargs.pop("_topic_id", None)
            or kwargs.get("topic_id")
            or self._default_topic_id
        )
        parent_id = kwargs.pop("_parent_id", None)
        stage = kwargs.pop("_stage", "")

        result = self._inner.execute(primitive, **kwargs)
        try:
            self._recorder.record(
                result=result,
                input_kwargs=kwargs,
                topic_id=topic_id,
                stage=stage,
                parent_id=parent_id,
            )
        except Exception:
            logging.getLogger(__name__).debug(
                "Observation recording failed", exc_info=True
            )
        return result

    def get_info(self) -> BackendInfo:
        return self._inner.get_info()

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        return self._inner.estimate_cost(primitive, **kwargs)

    def supports(self, primitive: str) -> bool:
        return self._inner.supports(primitive)
