"""Pytest integration for running evals as tests."""

import pytest

from .fixtures import ALL_CASES
from .runner import EvalRunner


@pytest.fixture
def eval_runner() -> EvalRunner:
    runner = EvalRunner(name="pytest-regression")
    runner.add_cases(ALL_CASES)
    return runner


def pytest_generate_tests(metafunc):
    if "eval_case" in metafunc.fixturenames:
        metafunc.parametrize(
            "eval_case",
            ALL_CASES,
            ids=[c.id for c in ALL_CASES],
        )
