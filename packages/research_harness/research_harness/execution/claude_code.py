"""ClaudeCodeBackend — composite backend for Claude Code extension mode.

Routes non-LLM primitives through LocalBackend logic and LLM primitives
through ResearchHarnessBackend, tagging all results as backend="claude_code"
so provenance can distinguish execution context.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..primitives.types import PrimitiveResult
from ..storage.db import Database
from .backend import BackendInfo
from .harness import ResearchHarnessBackend
from .local import LocalBackend


class ClaudeCodeBackend:
    """Execution backend that composes Local + Harness under a unified label."""

    def __init__(self, db: Database | None = None, **kwargs: Any) -> None:
        self._db = db
        self._local = LocalBackend(db) if db is not None else None
        self._harness = ResearchHarnessBackend(db=db, **kwargs)

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        if self._local is not None and self._local.supports(primitive):
            result = self._local.execute(primitive, **kwargs)
        else:
            result = self._harness.execute(primitive, **kwargs)
        return replace(result, backend="claude_code")

    def get_info(self) -> BackendInfo:
        harness_info = self._harness.get_info()
        local_info = self._local.get_info() if self._local else BackendInfo(name="local")
        all_primitives = sorted(
            set(harness_info.supported_primitives) | set(local_info.supported_primitives)
        )
        return BackendInfo(
            name="claude_code",
            supported_primitives=all_primitives,
            requires_api_key=True,
            description="Claude Code extension mode (local + LLM routing)",
        )

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        if self._local is not None and self._local.supports(primitive):
            return 0.0
        return self._harness.estimate_cost(primitive, **kwargs)

    def supports(self, primitive: str) -> bool:
        local_ok = self._local.supports(primitive) if self._local else False
        return local_ok or self._harness.supports(primitive)
