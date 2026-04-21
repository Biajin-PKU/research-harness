"""Three grader types for eval cases.

1. Deterministic: exact match, set containment, numeric thresholds
2. LLM-based: model judges output quality against rubric
3. Human: stores reference labels for calibration
"""

from __future__ import annotations

import re
from typing import Any

from .models import EvalCase, EvalResult


def grade(case: EvalCase, actual_output: Any) -> EvalResult:
    """Route to appropriate grader based on case.grader_type."""
    if case.grader_type == "deterministic":
        return grade_deterministic(case, actual_output)
    if case.grader_type == "llm":
        return grade_llm(case, actual_output)
    if case.grader_type == "human":
        return grade_human_reference(case, actual_output)
    return EvalResult(case_id=case.id, passed=False, details=f"Unknown grader: {case.grader_type}")


def grade_deterministic(case: EvalCase, actual: Any) -> EvalResult:
    """Grade using deterministic checks: exact match, containment, thresholds."""
    expected = case.expected
    checks_passed = 0
    checks_total = 0
    details: list[str] = []

    # Check 1: required fields present
    if "required_fields" in expected and isinstance(actual, dict):
        checks_total += 1
        missing = [f for f in expected["required_fields"] if f not in actual]
        if not missing:
            checks_passed += 1
        else:
            details.append(f"Missing fields: {missing}")

    # Check 2: minimum count
    if "min_count" in expected:
        checks_total += 1
        key = expected.get("count_key", "items")
        items = actual.get(key, []) if isinstance(actual, dict) else actual
        count = len(items) if hasattr(items, "__len__") else 0
        if count >= expected["min_count"]:
            checks_passed += 1
        else:
            details.append(f"Count {count} < min {expected['min_count']}")

    # Check 3: numeric threshold
    if "min_score" in expected:
        checks_total += 1
        score_key = expected.get("score_key", "score")
        score = actual.get(score_key, 0.0) if isinstance(actual, dict) else 0.0
        if score >= expected["min_score"]:
            checks_passed += 1
        else:
            details.append(f"Score {score} < min {expected['min_score']}")

    # Check 4: contains substring
    if "contains" in expected:
        checks_total += 1
        text = str(actual)
        if all(s.lower() in text.lower() for s in expected["contains"]):
            checks_passed += 1
        else:
            details.append(f"Missing substrings in output")

    # Check 5: regex match
    if "regex" in expected:
        checks_total += 1
        text = str(actual)
        if re.search(expected["regex"], text):
            checks_passed += 1
        else:
            details.append(f"Regex {expected['regex']} not found")

    # Check 6: output type
    if "output_type" in expected:
        checks_total += 1
        expected_type = expected["output_type"]
        actual_type = type(actual).__name__
        if actual_type == expected_type:
            checks_passed += 1
        else:
            details.append(f"Type {actual_type} != expected {expected_type}")

    if checks_total == 0:
        return EvalResult(case_id=case.id, passed=True, score=1.0,
                          grader_type="deterministic", details="No checks defined")

    score = checks_passed / checks_total
    return EvalResult(
        case_id=case.id,
        passed=score >= 0.8,
        score=score,
        grader_type="deterministic",
        details="; ".join(details) if details else "All checks passed",
    )


def grade_llm(case: EvalCase, actual: Any) -> EvalResult:
    """Grade using LLM judge (stub — requires LLM client in Phase 3)."""
    # Phase 2: stub that always passes with a note
    return EvalResult(
        case_id=case.id,
        passed=True,
        score=0.5,
        grader_type="llm",
        details="LLM grader stub — real implementation in Phase 3",
    )


def grade_human_reference(case: EvalCase, actual: Any) -> EvalResult:
    """Compare against human-labeled reference output."""
    expected = case.expected
    reference = expected.get("reference_output")
    if reference is None:
        return EvalResult(case_id=case.id, passed=False, score=0.0,
                          grader_type="human", details="No reference output provided")

    # Simple overlap check for now
    ref_text = str(reference).lower()
    actual_text = str(actual).lower()

    # Token overlap ratio
    ref_tokens = set(ref_text.split())
    actual_tokens = set(actual_text.split())
    if not ref_tokens:
        return EvalResult(case_id=case.id, passed=True, score=1.0,
                          grader_type="human", details="Empty reference")

    overlap = len(ref_tokens & actual_tokens) / len(ref_tokens)
    return EvalResult(
        case_id=case.id,
        passed=overlap >= 0.5,
        score=round(overlap, 3),
        grader_type="human",
        details=f"Token overlap: {overlap:.1%}",
    )
