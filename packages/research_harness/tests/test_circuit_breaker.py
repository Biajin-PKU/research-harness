"""Tests for core.circuit_breaker — 3-state machine with exponential recovery."""

from __future__ import annotations

import time

import pytest

from research_harness.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    State,
    get_breaker,
    reset_all_breakers,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_all_breakers()
    yield
    reset_all_breakers()


def _ok():
    return "ok"


def _fail():
    raise RuntimeError("boom")


# -- State transitions -------------------------------------------------------


def test_starts_closed():
    cb = CircuitBreaker("test")
    assert cb.state == State.CLOSED


def test_closed_allows_calls():
    cb = CircuitBreaker("test")
    assert cb.call(_ok) == "ok"


def test_closed_to_open_after_threshold():
    cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.call(_fail)
    assert cb.state == State.OPEN
    assert cb.trip_count == 1


def test_open_rejects_calls():
    cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=1))
    with pytest.raises(RuntimeError):
        cb.call(_fail)
    assert cb.state == State.OPEN
    with pytest.raises(CircuitOpenError) as exc_info:
        cb.call(_ok)
    assert exc_info.value.service == "test"
    assert exc_info.value.retry_after > 0


def test_open_to_half_open_after_cooldown():
    cfg = CircuitBreakerConfig(failure_threshold=1, initial_recovery_sec=0.1)
    cb = CircuitBreaker("test", cfg)
    with pytest.raises(RuntimeError):
        cb.call(_fail)
    assert cb.state == State.OPEN
    time.sleep(0.15)
    assert cb.state == State.HALF_OPEN


def test_half_open_success_to_closed():
    cfg = CircuitBreakerConfig(failure_threshold=1, initial_recovery_sec=0.1)
    cb = CircuitBreaker("test", cfg)
    with pytest.raises(RuntimeError):
        cb.call(_fail)
    time.sleep(0.15)
    assert cb.state == State.HALF_OPEN
    result = cb.call(_ok)
    assert result == "ok"
    assert cb.state == State.CLOSED


def test_half_open_failure_back_to_open():
    cfg = CircuitBreakerConfig(
        failure_threshold=1, initial_recovery_sec=0.1, backoff_multiplier=2.0
    )
    cb = CircuitBreaker("test", cfg)
    with pytest.raises(RuntimeError):
        cb.call(_fail)
    time.sleep(0.15)
    assert cb.state == State.HALF_OPEN
    with pytest.raises(RuntimeError):
        cb.call(_fail)
    assert cb.state == State.OPEN
    assert cb.trip_count == 2


def test_exponential_backoff_on_repeated_failures():
    cfg = CircuitBreakerConfig(
        failure_threshold=1,
        initial_recovery_sec=0.1,
        backoff_multiplier=2.0,
        max_recovery_sec=1.0,
    )
    cb = CircuitBreaker("test", cfg)

    # Trip 1: cooldown = 0.1s
    with pytest.raises(RuntimeError):
        cb.call(_fail)
    time.sleep(0.15)

    # Half-open probe fails → cooldown doubles to 0.2s
    with pytest.raises(RuntimeError):
        cb.call(_fail)
    assert cb.state == State.OPEN

    # 0.1s is not enough now
    time.sleep(0.1)
    assert cb.state == State.OPEN

    # After 0.25s total → should be half-open
    time.sleep(0.15)
    assert cb.state == State.HALF_OPEN


# -- Reset & Registry --------------------------------------------------------


def test_reset_returns_to_closed():
    cfg = CircuitBreakerConfig(failure_threshold=1)
    cb = CircuitBreaker("test", cfg)
    with pytest.raises(RuntimeError):
        cb.call(_fail)
    assert cb.state == State.OPEN
    cb.reset()
    assert cb.state == State.CLOSED
    assert cb.call(_ok) == "ok"


def test_get_breaker_singleton():
    b1 = get_breaker("svc-a")
    b2 = get_breaker("svc-a")
    assert b1 is b2


def test_get_breaker_different_services():
    b1 = get_breaker("svc-a")
    b2 = get_breaker("svc-b")
    assert b1 is not b2


# -- Failures below threshold don't trip ------------------------------------


def test_failures_below_threshold_stay_closed():
    cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(_fail)
    assert cb.state == State.CLOSED
    # A success resets the counter
    assert cb.call(_ok) == "ok"
    # 2 more failures still below threshold
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(_fail)
    assert cb.state == State.CLOSED
