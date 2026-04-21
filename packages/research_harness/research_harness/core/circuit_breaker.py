"""Three-state circuit breaker for external service calls.

States: CLOSED (normal) → OPEN (rejecting) → HALF_OPEN (probing) → CLOSED or OPEN.

Usage::

    breaker = CircuitBreaker("semantic_scholar")
    result = breaker.call(fetch_fn, url, headers)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit is open."""

    def __init__(self, service: str, retry_after: float) -> None:
        self.service = service
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker for '{service}' is open; retry after {retry_after:.0f}s"
        )


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 3
    initial_recovery_sec: float = 60.0
    max_recovery_sec: float = 600.0
    backoff_multiplier: float = 2.0


@dataclass
class _BreakerState:
    state: State = State.CLOSED
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    current_recovery_sec: float = 60.0
    trip_count: int = 0


class CircuitBreaker:
    """Per-service circuit breaker with exponential recovery backoff."""

    def __init__(
        self,
        service: str,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        self.service = service
        self._cfg = config or CircuitBreakerConfig()
        self._state = _BreakerState(current_recovery_sec=self._cfg.initial_recovery_sec)
        self._lock = threading.Lock()

    # -- public API -----------------------------------------------------------

    @property
    def state(self) -> State:
        with self._lock:
            return self._effective_state()

    @property
    def trip_count(self) -> int:
        with self._lock:
            return self._state.trip_count

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute *fn* through the breaker. Raises `CircuitOpenError` if open."""
        with self._lock:
            effective = self._effective_state()
            if effective == State.OPEN:
                remaining = self._remaining_cooldown()
                raise CircuitOpenError(self.service, remaining)
            # CLOSED or HALF_OPEN → allow the call

        try:
            result = fn(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise

        self._on_success()
        return result

    def reset(self) -> None:
        """Force-reset to CLOSED (for tests)."""
        with self._lock:
            self._state = _BreakerState(
                current_recovery_sec=self._cfg.initial_recovery_sec,
            )

    # -- internal state transitions -------------------------------------------

    def _effective_state(self) -> State:
        """Return the logical state, promoting OPEN → HALF_OPEN when cooldown expires."""
        s = self._state
        if s.state == State.OPEN:
            elapsed = time.monotonic() - s.last_failure_time
            if elapsed >= s.current_recovery_sec:
                s.state = State.HALF_OPEN
                logger.info(
                    "Circuit '%s' → HALF_OPEN after %.0fs cooldown",
                    self.service,
                    elapsed,
                )
        return s.state

    def _remaining_cooldown(self) -> float:
        s = self._state
        elapsed = time.monotonic() - s.last_failure_time
        return max(0.0, s.current_recovery_sec - elapsed)

    def _on_success(self) -> None:
        with self._lock:
            s = self._state
            if s.state == State.HALF_OPEN:
                logger.info("Circuit '%s' → CLOSED (probe succeeded)", self.service)
            s.state = State.CLOSED
            s.consecutive_failures = 0
            s.current_recovery_sec = self._cfg.initial_recovery_sec

    def _on_failure(self) -> None:
        with self._lock:
            s = self._state
            s.consecutive_failures += 1
            s.last_failure_time = time.monotonic()

            if s.state == State.HALF_OPEN:
                # Probe failed → back to OPEN with doubled cooldown
                s.state = State.OPEN
                s.current_recovery_sec = min(
                    s.current_recovery_sec * self._cfg.backoff_multiplier,
                    self._cfg.max_recovery_sec,
                )
                s.trip_count += 1
                logger.warning(
                    "Circuit '%s' → OPEN (probe failed), cooldown %.0fs",
                    self.service,
                    s.current_recovery_sec,
                )
            elif (
                s.state == State.CLOSED
                and s.consecutive_failures >= self._cfg.failure_threshold
            ):
                # Trip the breaker
                s.state = State.OPEN
                s.trip_count += 1
                logger.warning(
                    "Circuit '%s' → OPEN after %d consecutive failures, cooldown %.0fs",
                    self.service,
                    s.consecutive_failures,
                    s.current_recovery_sec,
                )


# -- global registry ----------------------------------------------------------

_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    service: str,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreaker:
    """Get or create a circuit breaker for *service* (singleton per name)."""
    with _registry_lock:
        if service not in _breakers:
            _breakers[service] = CircuitBreaker(service, config)
        return _breakers[service]


def reset_all_breakers() -> None:
    """Reset all breakers (for tests)."""
    with _registry_lock:
        for b in _breakers.values():
            b.reset()
        _breakers.clear()
