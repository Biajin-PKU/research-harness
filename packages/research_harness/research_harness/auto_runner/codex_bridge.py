"""Codex bridge — invoke codex review/exec and parse responses.

Codex is an independent CLI (OpenAI API) that works regardless of
ANTHROPIC_* env vars. Used for adversarial review at quality gates.

Fallback chain (tried in order):
  1. ``codex`` CLI — preferred, independent cross-model review
  2. Anthropic API (claude-opus-4-6) — when codex CLI is unavailable or times out

Stability hardening (Phase 2):
  - Pre-flight check skips codex when binary is missing or breaker is tripped,
    avoiding ``timeout_seconds`` stalls on obviously-dead paths.
  - Per-backend graded timeouts replace the hardcoded 300s ceiling. Codex gets
    a larger budget (cold start ~40s); Anthropic gets a tighter one.
  - ``stdin=subprocess.DEVNULL`` prevents ``codex exec`` from hanging waiting
    for stdin in environments that don't close it automatically.
  - A per-backend circuit breaker trips after ``_BREAKER_THRESHOLD`` consecutive
    failures and cools off for ``_BREAKER_COOL_OFF_SECONDS``. Only codex is
    skipped when tripped; anthropic is always attempted as last resort.

How to invoke adversarial review in other sessions:
  - From Claude Code: use Agent tool with subagent_type="codex:codex-rescue"
  - From any session: set RESEARCH_HARNESS_ADVERSARIAL_BACKEND=anthropic
  - Programmatically: call run_codex_review() which handles the fallback chain
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ADVERSARIAL_OPUS_MODEL = "claude-opus-4-6"

# Per-backend timeouts. Codex needs a larger budget for cold starts; Anthropic
# is an HTTP call that almost always returns within a minute.
_BACKEND_TIMEOUTS: dict[str, int] = {
    "codex": 180,
    "anthropic": 90,
}

# Circuit breaker config: trip after N consecutive failures, cool off for T s.
_BREAKER_THRESHOLD = 3
_BREAKER_COOL_OFF_SECONDS = 60.0

# Default codex review prompt template
ADVERSARIAL_REVIEW_TEMPLATE = """\
Review the research artifact at: {artifact_path}

Stage: {stage}
Focus: {focus}

Evidence summary:
{evidence_summary}

Evaluate on these dimensions:
- novelty: Is the contribution genuinely new?
- evidence_coverage: Are claims supported by sufficient evidence?
- method_validity: Is the methodology sound?
- baseline_completeness: Are key baselines included?
- scope_discipline: Is the scope well-bounded?
- falsifiability: Can claims be tested/refuted?
- clarity: Is the writing clear and precise?

Return your review as structured JSON:
{{
  "verdict": "approve" or "revise",
  "issues": [
    {{
      "severity": "critical|major|minor",
      "category": "<dimension>",
      "target": "<what specifically>",
      "reasoning": "<why this is a problem>",
      "suggested_fix": "<how to fix>"
    }}
  ],
  "scores": {{
    "novelty": <1-5>,
    "evidence_coverage": <1-5>,
    "method_validity": <1-5>,
    "baseline_completeness": <1-5>,
    "scope_discipline": <1-5>,
    "falsifiability": <1-5>,
    "clarity": <1-5>
  }},
  "notes": "<overall assessment>"
}}
"""


# ---------------------------------------------------------------------------
# Circuit breaker (per-backend)
# ---------------------------------------------------------------------------


@dataclass
class _BackendState:
    failures: int = 0
    tripped_until: float = 0.0


class _CircuitBreaker:
    """Track consecutive failures per backend and skip tripped backends.

    Thread-safe. State is process-local; restarts reset everything.
    """

    def __init__(
        self,
        threshold: int = _BREAKER_THRESHOLD,
        cool_off_seconds: float = _BREAKER_COOL_OFF_SECONDS,
    ) -> None:
        self._threshold = threshold
        self._cool_off = cool_off_seconds
        self._state: dict[str, _BackendState] = {}
        self._lock = threading.Lock()

    def is_open(self, backend: str) -> bool:
        """True while the backend is in cool-off."""
        with self._lock:
            s = self._state.get(backend)
            if s is None:
                return False
            return s.tripped_until > time.time()

    def record_success(self, backend: str) -> None:
        with self._lock:
            self._state[backend] = _BackendState()

    def record_failure(self, backend: str) -> None:
        with self._lock:
            s = self._state.setdefault(backend, _BackendState())
            s.failures += 1
            if s.failures >= self._threshold:
                s.tripped_until = time.time() + self._cool_off

    def reset(self) -> None:
        with self._lock:
            self._state.clear()


_BREAKER = _CircuitBreaker()


def _reset_breaker_for_tests() -> None:
    """Reset the module-level breaker. Intended for pytest fixtures only."""
    _BREAKER.reset()


# ---------------------------------------------------------------------------
# Codex discovery + pre-flight
# ---------------------------------------------------------------------------


def _find_codex() -> str | None:
    """Find the codex CLI binary."""
    try:
        result = subprocess.run(
            ["which", "codex"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _codex_preflight() -> tuple[bool, str]:
    """Cheap check before spending a 180s timeout on ``codex exec``.

    Returns ``(ok, reason)``. When ``ok`` is False, callers should fall
    through to the anthropic backend without invoking the subprocess.
    """
    if _BREAKER.is_open("codex"):
        return False, "codex circuit breaker open (recent failures)"
    if _find_codex() is None:
        return False, "codex CLI not found in PATH"
    return True, ""


# ---------------------------------------------------------------------------
# Anthropic backend (fallback and RESEARCH_HARNESS_ADVERSARIAL_BACKEND=anthropic)
# ---------------------------------------------------------------------------


def _adversarial_via_anthropic(
    *,
    artifact_path: Path,
    stage: str,
    focus: str,
    evidence_summary: str = "",
    model: str = _ADVERSARIAL_OPUS_MODEL,
) -> dict[str, Any]:
    """Run adversarial review via Anthropic API (used when codex CLI unavailable).

    Intended for use inside Codex sandbox where calling `codex exec` would
    be recursive or unavailable.
    """
    try:
        from llm_router.client import LLMClient, ResolvedLLMConfig
    except ImportError:
        return {
            "success": False,
            "error": "llm_router not installed; cannot use Anthropic fallback",
            "verdict": "",
            "issues": [],
            "scores": {},
            "notes": "",
            "raw_output": "",
        }

    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or ""
    )
    if not api_key:
        return {
            "success": False,
            "error": "ANTHROPIC_API_KEY not set; cannot run adversarial review via Anthropic",
            "verdict": "",
            "issues": [],
            "scores": {},
            "notes": "",
            "raw_output": "",
        }

    prompt = ADVERSARIAL_REVIEW_TEMPLATE.format(
        artifact_path=artifact_path,
        stage=stage,
        focus=focus,
        evidence_summary=evidence_summary[:3000],
    )

    try:
        cfg = ResolvedLLMConfig(provider="anthropic", model=model, api_key=api_key)
        client = LLMClient(cfg)
        raw = client.chat(prompt)
        parsed = _parse_codex_output(raw)
        parsed["success"] = True
        parsed["raw_output"] = raw
        parsed["backend"] = "anthropic"
        parsed["model"] = model
        _BREAKER.record_success("anthropic")
        logger.info("Adversarial review completed via Anthropic %s", model)
        return parsed
    except Exception as exc:
        _BREAKER.record_failure("anthropic")
        return {
            "success": False,
            "error": f"Anthropic adversarial review failed: {exc}",
            "verdict": "",
            "issues": [],
            "scores": {},
            "notes": "",
            "raw_output": "",
        }


# ---------------------------------------------------------------------------
# Main entry: run_codex_review
# ---------------------------------------------------------------------------


def run_codex_review(
    *,
    artifact_path: Path,
    stage: str,
    focus: str,
    evidence_summary: str = "",
    cwd: Path | None = None,
    timeout_seconds: int | None = None,
    effort: str = "medium",
) -> dict[str, Any]:
    """Run adversarial review on an artifact and return parsed response.

    Fallback chain:
      1. ``codex`` CLI — independent cross-model review (preferred)
      2. Anthropic API (Opus) — when codex times out or CLI not found

    Set ``RESEARCH_HARNESS_ADVERSARIAL_BACKEND`` to force a specific backend:
      - ``codex`` (default): try codex CLI first
      - ``anthropic``: use Anthropic API directly

    ``timeout_seconds`` overrides both per-backend defaults. When None, each
    backend uses its entry in ``_BACKEND_TIMEOUTS``.

    Returns a dict with keys: success, verdict, issues, scores, notes,
    raw_output, backend.
    """
    backend_env = os.environ.get("RESEARCH_HARNESS_ADVERSARIAL_BACKEND", "").lower()

    if backend_env == "anthropic":
        return _adversarial_via_anthropic(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )

    ok, reason = _codex_preflight()
    if not ok:
        logger.info(
            "codex pre-flight failed (%s) — using Anthropic API for adversarial review",
            reason,
        )
        return _adversarial_via_anthropic(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )

    # _codex_preflight already verified the binary exists.
    codex = _find_codex()
    if codex is None:
        # Race: binary disappeared between preflight and here. Treat as fallback.
        _BREAKER.record_failure("codex")
        return _adversarial_via_anthropic(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )

    prompt = ADVERSARIAL_REVIEW_TEMPLATE.format(
        artifact_path=artifact_path,
        stage=stage,
        focus=focus,
        evidence_summary=evidence_summary[:3000],
    )

    codex_timeout = timeout_seconds or _BACKEND_TIMEOUTS["codex"]

    import tempfile

    out_file = tempfile.NamedTemporaryFile(
        suffix=".txt", prefix="codex_review_", delete=False
    )
    out_path = out_file.name
    out_file.close()

    cmd = [
        codex,
        "exec",
        "--full-auto",
        "-o",
        out_path,
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=codex_timeout,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
        )
        try:
            raw = Path(out_path).read_text(encoding="utf-8").strip()
        except OSError:
            raw = result.stdout.strip()
        finally:
            Path(out_path).unlink(missing_ok=True)

        if result.returncode != 0 and not raw:
            _BREAKER.record_failure("codex")
            logger.warning(
                "codex exited with code %s: %s — falling back to Anthropic",
                result.returncode,
                (result.stderr or "")[:500],
            )
            return _adversarial_via_anthropic(
                artifact_path=artifact_path,
                stage=stage,
                focus=focus,
                evidence_summary=evidence_summary,
            )

        parsed = _parse_codex_output(raw)
        parsed["success"] = True
        parsed["raw_output"] = raw
        parsed["backend"] = "codex"
        _BREAKER.record_success("codex")
        return parsed

    except subprocess.TimeoutExpired:
        Path(out_path).unlink(missing_ok=True)
        _BREAKER.record_failure("codex")
        logger.warning(
            "codex timed out after %ds — falling back to Anthropic API",
            codex_timeout,
        )
        return _adversarial_via_anthropic(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )
    except Exception as exc:
        Path(out_path).unlink(missing_ok=True)
        _BREAKER.record_failure("codex")
        logger.warning(
            "codex subprocess failed: %s — falling back to Anthropic API",
            exc,
        )
        return _adversarial_via_anthropic(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )


def _parse_codex_output(raw: str) -> dict[str, Any]:
    """Parse codex output, trying JSON extraction."""
    # Try direct JSON parse
    try:
        data = json.loads(raw)
        return _normalize_review(data)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown fences
    for marker in ("```json", "```"):
        start = raw.find(marker)
        if start < 0:
            continue
        start += len(marker)
        end = raw.find("```", start)
        block = raw[start:] if end < 0 else raw[start:end]
        try:
            data = json.loads(block.strip())
            return _normalize_review(data)
        except json.JSONDecodeError:
            continue

    # Fallback: extract verdict from text
    verdict = ""
    lower = raw.lower()
    if "verdict: approve" in lower or '"verdict": "approve"' in lower:
        verdict = "approve"
    elif "verdict: revise" in lower or '"verdict": "revise"' in lower:
        verdict = "revise"

    return {
        "verdict": verdict,
        "issues": [],
        "scores": {},
        "notes": raw[:1000],
    }


def _normalize_review(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize parsed review data to expected schema."""
    return {
        "verdict": str(data.get("verdict", "")).strip().lower(),
        "issues": data.get("issues", [])
        if isinstance(data.get("issues"), list)
        else [],
        "scores": data.get("scores", {})
        if isinstance(data.get("scores"), dict)
        else {},
        "notes": str(data.get("notes", "")),
    }


def save_handoff_request(
    handoff_dir: Path,
    *,
    stage: str,
    artifact_path: str,
    focus: str,
    evidence_summary: str,
) -> Path:
    """Write handoff request file for codex."""
    handoff_dir.mkdir(parents=True, exist_ok=True)
    request_path = handoff_dir / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "stage": stage,
                "artifact_path": artifact_path,
                "focus": focus,
                "evidence_summary": evidence_summary[:3000],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return request_path


def save_handoff_response(handoff_dir: Path, response: dict[str, Any]) -> Path:
    """Write codex response to handoff file."""
    handoff_dir.mkdir(parents=True, exist_ok=True)
    response_path = handoff_dir / "response.json"
    response_path.write_text(
        json.dumps(response, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return response_path


def load_handoff_response(handoff_dir: Path) -> dict[str, Any] | None:
    """Load a previously saved codex response."""
    response_path = handoff_dir / "response.json"
    if not response_path.exists():
        return None
    try:
        return json.loads(response_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def codex_issues_to_objections(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert codex review issues to orchestrator adversarial objections format."""
    objections = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        objections.append(
            {
                "category": str(issue.get("category", "general")),
                "severity": str(issue.get("severity", "minor")),
                "target": str(issue.get("target", "")),
                "reasoning": str(issue.get("reasoning", "")),
                "suggested_fix": str(issue.get("suggested_fix", "")),
            }
        )
    return objections
