"""Eval suite runner — loads fixtures, executes cases, reports results."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Callable

from .graders import grade
from .models import EvalCase, EvalResult, EvalSuiteResult

logger = logging.getLogger(__name__)


class EvalRunner:
    """Runs eval suites and collects results."""

    def __init__(self, name: str = "default"):
        self._name = name
        self._cases: list[EvalCase] = []

    def add_case(self, case: EvalCase) -> None:
        self._cases.append(case)

    def add_cases(self, cases: list[EvalCase]) -> None:
        self._cases.extend(cases)

    @property
    def case_count(self) -> int:
        return len(self._cases)

    def run(
        self,
        executor: Callable[[EvalCase], Any],
        *,
        tags: list[str] | None = None,
        stage: str | None = None,
    ) -> EvalSuiteResult:
        """Run all cases (optionally filtered) through executor + grader.

        executor: function that takes an EvalCase and returns actual output.
        """
        cases = self._cases
        if tags:
            tag_set = set(tags)
            cases = [c for c in cases if tag_set & set(c.tags)]
        if stage:
            cases = [c for c in cases if c.stage == stage]

        results: list[EvalResult] = []
        for case in cases:
            start = time.monotonic()
            try:
                actual = executor(case)
                latency = int((time.monotonic() - start) * 1000)
                result = grade(case, actual)
                result.latency_ms = latency
            except Exception as exc:
                latency = int((time.monotonic() - start) * 1000)
                result = EvalResult(
                    case_id=case.id,
                    passed=False,
                    score=0.0,
                    grader_type=case.grader_type,
                    details=f"Executor error: {exc}",
                    latency_ms=latency,
                )
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            logger.info("[%s] %s: %s (%.3f)", status, case.id, result.details[:80], result.score)

        passed = sum(1 for r in results if r.passed)
        total = len(results)
        scores = [r.score for r in results if r.score > 0]
        mean_score = sum(scores) / len(scores) if scores else 0.0

        return EvalSuiteResult(
            suite_name=self._name,
            total=total,
            passed=passed,
            failed=total - passed,
            pass_rate=passed / total if total > 0 else 0.0,
            mean_score=round(mean_score, 3),
            results=results,
        )

    def run_regression(
        self,
        executor: Callable[[EvalCase], Any],
        baseline: EvalSuiteResult,
        tolerance: float = 0.05,
    ) -> dict[str, Any]:
        """Run and compare against a baseline. Flag regressions."""
        current = self.run(executor)
        regressions: list[str] = []

        if current.pass_rate < baseline.pass_rate - tolerance:
            regressions.append(
                f"Pass rate dropped: {baseline.pass_rate:.1%} -> {current.pass_rate:.1%}"
            )
        if current.mean_score < baseline.mean_score - tolerance:
            regressions.append(
                f"Mean score dropped: {baseline.mean_score:.3f} -> {current.mean_score:.3f}"
            )

        # Per-case regressions
        baseline_map = {r.case_id: r for r in baseline.results}
        for r in current.results:
            base = baseline_map.get(r.case_id)
            if base and base.passed and not r.passed:
                regressions.append(f"Case {r.case_id} regressed: was PASS, now FAIL")

        return {
            "regressed": len(regressions) > 0,
            "regressions": regressions,
            "current": current,
            "baseline": baseline,
        }
