"""Codex bridge — invoke codex review/exec and parse responses.

Codex is an independent CLI (OpenAI API) that works regardless of
ANTHROPIC_* env vars. Used for adversarial review at quality gates.

Fallback chain (tried in order):
  1. ``codex`` CLI — preferred, independent cross-model review
  2. Opus via joycode (joy_gpt) — when codex times out or is unavailable
  3. Anthropic API (claude-opus-4-6) — when running inside Codex sandbox

How to invoke adversarial review in other sessions:
  - From Claude Code: use Agent tool with subagent_type="codex:codex-rescue"
  - From any session: set RESEARCH_HARNESS_ADVERSARIAL_BACKEND=joycode|anthropic
  - Programmatically: call run_codex_review() which handles the fallback chain
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ADVERSARIAL_OPUS_MODEL = "claude-opus-4-6"

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


def _adversarial_via_joycode(
    *,
    artifact_path: Path,
    stage: str,
    focus: str,
    evidence_summary: str = "",
) -> dict[str, Any]:
    """Run adversarial review via Opus (joycode/joy_gpt).

    Second-choice fallback when codex CLI times out or is unavailable.
    Uses the joy_gpt router (task_name="stage_planner") for cost-effective
    Opus-level review.
    """
    try:
        from ..execution.llm_primitives import _client_chat, _get_client
    except ImportError:
        return {
            "success": False,
            "error": "LLM primitives not available for joycode fallback",
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
        client = _get_client(tier="medium", task_name="stage_planner")
        raw = _client_chat(client, prompt)
        parsed = _parse_codex_output(raw)
        parsed["success"] = True
        parsed["raw_output"] = raw
        parsed["backend"] = "joycode"
        logger.info("Adversarial review completed via joycode (Opus fallback)")
        return parsed
    except Exception as exc:
        return {
            "success": False,
            "error": f"Joycode adversarial review failed: {exc}",
            "verdict": "",
            "issues": [],
            "scores": {},
            "notes": "",
            "raw_output": "",
        }


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
        from paperindex.llm.client import LLMClient, ResolvedLLMConfig
    except ImportError:
        return {
            "success": False,
            "error": "paperindex not installed; cannot use Anthropic fallback",
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
        logger.info("Adversarial review completed via Anthropic %s", model)
        return parsed
    except Exception as exc:
        return {
            "success": False,
            "error": f"Anthropic adversarial review failed: {exc}",
            "verdict": "",
            "issues": [],
            "scores": {},
            "notes": "",
            "raw_output": "",
        }


def run_codex_review(
    *,
    artifact_path: Path,
    stage: str,
    focus: str,
    evidence_summary: str = "",
    cwd: Path | None = None,
    timeout_seconds: int = 300,
    effort: str = "medium",
) -> dict[str, Any]:
    """Run adversarial review on an artifact and return parsed response.

    Fallback chain:
      1. ``codex`` CLI — independent cross-model review (preferred)
      2. Opus via joycode — when codex times out or CLI not found
      3. Anthropic API — when ``RESEARCH_HARNESS_ADVERSARIAL_BACKEND=anthropic``

    Set ``RESEARCH_HARNESS_ADVERSARIAL_BACKEND`` to force a specific backend:
      - ``codex`` (default): try codex CLI first
      - ``joycode``: skip codex, use joy_gpt Opus directly
      - ``anthropic``: use Anthropic API directly

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

    if backend_env == "joycode":
        return _adversarial_via_joycode(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )

    codex = _find_codex()
    if codex is None:
        logger.info(
            "codex CLI not found — falling back to joycode (Opus) for adversarial review"
        )
        return _adversarial_via_joycode(
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

    import tempfile

    out_file = tempfile.NamedTemporaryFile(
        suffix=".txt", prefix="codex_review_", delete=False
    )
    out_path = out_file.name
    out_file.close()

    cmd = [
        codex, "exec",
        "--full-auto",
        "-o", out_path,
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(cwd) if cwd else None,
        )
        try:
            raw = Path(out_path).read_text(encoding="utf-8").strip()
        except OSError:
            raw = result.stdout.strip()
        finally:
            Path(out_path).unlink(missing_ok=True)

        if result.returncode != 0 and not raw:
            return {
                "success": False,
                "error": f"codex exited with code {result.returncode}: {result.stderr[:500]}",
                "verdict": "",
                "issues": [],
                "scores": {},
                "notes": "",
                "raw_output": raw,
            }

        parsed = _parse_codex_output(raw)
        parsed["success"] = True
        parsed["raw_output"] = raw
        parsed["backend"] = "codex"
        return parsed

    except subprocess.TimeoutExpired:
        Path(out_path).unlink(missing_ok=True)
        logger.warning(
            "codex timed out after %ds — falling back to joycode (Opus)",
            timeout_seconds,
        )
        return _adversarial_via_joycode(
            artifact_path=artifact_path,
            stage=stage,
            focus=focus,
            evidence_summary=evidence_summary,
        )
    except Exception as exc:
        Path(out_path).unlink(missing_ok=True)
        logger.warning(
            "codex subprocess failed: %s — falling back to joycode (Opus)", exc,
        )
        return _adversarial_via_joycode(
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
        "issues": data.get("issues", []) if isinstance(data.get("issues"), list) else [],
        "scores": data.get("scores", {}) if isinstance(data.get("scores"), dict) else {},
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
        json.dumps({
            "stage": stage,
            "artifact_path": artifact_path,
            "focus": focus,
            "evidence_summary": evidence_summary[:3000],
        }, indent=2, ensure_ascii=False),
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
        objections.append({
            "category": str(issue.get("category", "general")),
            "severity": str(issue.get("severity", "minor")),
            "target": str(issue.get("target", "")),
            "reasoning": str(issue.get("reasoning", "")),
            "suggested_fix": str(issue.get("suggested_fix", "")),
        })
    return objections
