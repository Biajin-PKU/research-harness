"""ExecutionBackend protocol — the contract all backends must fulfill."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..primitives.types import PrimitiveResult


@dataclass(frozen=True)
class BackendInfo:
    """Metadata about an execution backend."""

    name: str
    version: str = "0.1.0"
    supported_primitives: list[str] = field(default_factory=list)
    requires_api_key: bool = False
    description: str = ""


@runtime_checkable
class ExecutionBackend(Protocol):
    """Protocol that all execution backends must implement."""

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult: ...

    def get_info(self) -> BackendInfo: ...

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float: ...

    def supports(self, primitive: str) -> bool: ...
