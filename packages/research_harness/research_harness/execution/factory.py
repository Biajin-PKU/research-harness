"""Backend factory — creates execution backend from configuration."""

from __future__ import annotations

from typing import Any

from .backend import ExecutionBackend
from .claude_code import ClaudeCodeBackend
from .harness import ResearchHarnessBackend
from .local import LocalBackend


_BACKEND_CLASSES = {
    "local": LocalBackend,
    "claude_code": ClaudeCodeBackend,
    "research_harness": ResearchHarnessBackend,
}


def create_backend(name: str, **kwargs: Any) -> ExecutionBackend:
    """Create an execution backend by name."""

    cls = _BACKEND_CLASSES.get(name)
    if cls is None:
        valid = ", ".join(sorted(_BACKEND_CLASSES.keys()))
        raise ValueError(f"Unknown backend: {name!r}. Valid: {valid}")
    return cls(**kwargs)


def get_backend_names() -> list[str]:
    """Return list of registered backend names."""

    return sorted(_BACKEND_CLASSES.keys())
