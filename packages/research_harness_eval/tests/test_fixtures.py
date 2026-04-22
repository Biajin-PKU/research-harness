"""Fixture integrity tests — validate every EvalCase is well-formed."""

from __future__ import annotations

import pytest

from research_harness_eval.fixtures import ALL_CASES
from research_harness_eval.models import EvalCase


_VALID_GRADERS = {"deterministic", "llm", "human"}
_VALID_STAGES = {
    "init",
    "build",
    "analyze",
    "propose",
    "experiment",
    "write",
}


def test_fixtures_non_empty():
    assert len(ALL_CASES) > 0, "Eval suite must ship at least one case"


def test_all_cases_are_EvalCase():
    for case in ALL_CASES:
        assert isinstance(case, EvalCase), f"Bad case type: {type(case).__name__}"


def test_case_ids_unique():
    ids = [c.id for c in ALL_CASES]
    assert len(ids) == len(set(ids)), (
        f"Duplicate case IDs: {[i for i in ids if ids.count(i) > 1]}"
    )


@pytest.mark.parametrize("case", ALL_CASES, ids=[c.id for c in ALL_CASES])
def test_case_schema(case: EvalCase):
    assert case.id, "id required"
    assert case.description, f"{case.id}: description required"
    assert case.grader_type in _VALID_GRADERS, (
        f"{case.id}: grader_type must be one of {_VALID_GRADERS}, got {case.grader_type}"
    )
    assert case.stage in _VALID_STAGES, (
        f"{case.id}: stage must be one of {_VALID_STAGES}, got {case.stage}"
    )
    assert isinstance(case.input_data, dict)
    assert isinstance(case.expected, dict)
    assert isinstance(case.tags, list)


def test_deterministic_cases_have_expected_contract():
    """Deterministic cases must encode at least one check (required_fields / min_count / ...)."""
    known_keys = {
        "required_fields",
        "min_count",
        "count_key",
        "contains",
        "max_cost_usd",
        "min_score",
        "score_key",
    }
    for case in ALL_CASES:
        if case.grader_type != "deterministic":
            continue
        if not case.expected:
            continue  # empty expected → smoke-only, allowed
        overlap = set(case.expected.keys()) & known_keys
        assert overlap, (
            f"{case.id}: deterministic grader needs at least one known expected key "
            f"({known_keys}); found keys {set(case.expected.keys())}"
        )
