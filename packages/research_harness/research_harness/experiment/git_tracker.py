"""Git-based experiment tracking — Karpathy autoresearch style.

keep = git add + commit (with metrics in message)
discard = git checkout . (revert changes)

Uses a dedicated experiment branch for isolation.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def init_experiment_branch(work_dir: Path, branch_name: str = "experiment") -> bool:
    """Create and checkout an experiment branch."""
    try:
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(work_dir), capture_output=True, text=True, check=True,
        )
        return True
    except subprocess.CalledProcessError:
        # Branch may already exist
        try:
            subprocess.run(
                ["git", "checkout", branch_name],
                cwd=str(work_dir), capture_output=True, text=True, check=True,
            )
            return True
        except subprocess.CalledProcessError as exc:
            logger.warning("Failed to checkout branch %s: %s", branch_name, exc)
            return False


def commit_experiment(
    work_dir: Path,
    iteration: int,
    primary_metric: float | None = None,
    metric_name: str = "",
    description: str = "",
) -> str | None:
    """Commit current experiment state. Returns commit hash or None."""
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(work_dir), capture_output=True, check=True,
        )
        metric_str = f" {metric_name}={primary_metric:.6f}" if primary_metric is not None else ""
        msg = f"experiment iter {iteration}{metric_str}"
        if description:
            msg += f"\n\n{description}"
        result = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(work_dir), capture_output=True, text=True, check=True,
        )
        # Extract commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(work_dir), capture_output=True, text=True, check=True,
        )
        return hash_result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        logger.warning("Git commit failed: %s", exc.stderr if hasattr(exc, 'stderr') else exc)
        return None


def discard_experiment(work_dir: Path) -> bool:
    """Revert all uncommitted changes."""
    try:
        subprocess.run(
            ["git", "checkout", "."],
            cwd=str(work_dir), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=str(work_dir), capture_output=True, check=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("Git discard failed: %s", exc)
        return False
