"""Eval data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalCase:
    """A single evaluation case (frozen input + expected behavior)."""

    id: str
    stage: str
    description: str
    input_data: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    grader_type: str = "deterministic"  # deterministic|llm|human
    tags: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Result of running one eval case."""

    case_id: str
    passed: bool
    score: float = 0.0  # 0.0-1.0
    grader_type: str = ""
    details: str = ""
    model_used: str = ""
    prompt_hash: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0


@dataclass
class EvalSuiteResult:
    """Aggregated results from running an eval suite."""

    suite_name: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    mean_score: float = 0.0
    results: list[EvalResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"{self.suite_name}: {self.passed}/{self.total} passed "
            f"({self.pass_rate:.0%}), mean score {self.mean_score:.3f}"
        )
