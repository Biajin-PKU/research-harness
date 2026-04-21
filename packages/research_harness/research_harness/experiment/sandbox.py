"""Local subprocess sandbox for experiment execution.

Runs experiment code in an isolated subprocess with timeout,
captures stdout/stderr, and parses metrics.

Adapted from AutoResearchClaw (MIT license).
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metric_parser import detect_nan_divergence, parse_metrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SandboxResult:
    """Result of running an experiment in the sandbox."""

    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float
    metrics: dict[str, float] = field(default_factory=dict)
    timed_out: bool = False
    divergence: str = ""
    code_hash: str = ""


def run_experiment(
    code: str,
    *,
    entry_point: str = "main.py",
    timeout_sec: float = 300.0,
    work_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> SandboxResult:
    """Execute experiment code in a subprocess sandbox.

    Creates a temporary directory, writes the code, and runs it with
    the specified timeout. Returns a SandboxResult with captured output
    and parsed metrics.
    """
    import time

    code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]

    # Create work directory
    if work_dir is None:
        tmp = tempfile.mkdtemp(prefix="rh_experiment_")
        work_dir = Path(tmp)

    # Write code
    entry_path = work_dir / entry_point
    entry_path.write_text(code, encoding="utf-8")

    # Run
    start = time.monotonic()
    timed_out = False
    try:
        result = subprocess.run(
            ["python", str(entry_path)],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(work_dir),
            env=env,
        )
        elapsed = time.monotonic() - start
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        returncode = result.returncode
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        timed_out = True
        stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        returncode = -1

    # Parse metrics and detect divergence
    metrics = parse_metrics(stdout)
    divergence = detect_nan_divergence(stdout, stderr)

    return SandboxResult(
        returncode=returncode,
        stdout=stdout[-5000:],  # Cap to avoid memory issues
        stderr=stderr[-2000:],
        elapsed_sec=elapsed,
        metrics=metrics,
        timed_out=timed_out,
        divergence=divergence,
        code_hash=code_hash,
    )


def is_improvement(
    new_value: float,
    best_value: float,
    *,
    direction: str = "maximize",
    min_delta: float = 0.0,
) -> bool:
    """Check if new_value improves over best_value."""
    if direction == "maximize":
        return new_value > best_value + min_delta
    return new_value < best_value - min_delta
