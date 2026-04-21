"""Execution layer — backend-agnostic interface for research operations."""

from .backend import BackendInfo, ExecutionBackend
from .claude_code import ClaudeCodeBackend
from .factory import create_backend, get_backend_names
from .harness import ResearchHarnessBackend
from .local import LocalBackend
from .tracked import TrackedBackend

__all__ = [
    "ExecutionBackend",
    "BackendInfo",
    "ClaudeCodeBackend",
    "LocalBackend",
    "ResearchHarnessBackend",
    "TrackedBackend",
    "create_backend",
    "get_backend_names",
]
