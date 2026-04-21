"""claude-admin: headless Claude Code runner with no confirmation prompts.

All operations execute directly to completion without interactive questions.
Uses `claude -p` with `--dangerously-skip-permissions` under the hood.

Auto-escalation: start with a cheap model (sonnet/haiku), automatically
escalate to a stronger model (opus) when the weak model signals it's stuck.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import click

# ---------------------------------------------------------------------------
# Escalation config
# ---------------------------------------------------------------------------

ESCALATION_SYSTEM_PROMPT_HEADLESS = """\
You are running in auto-escalation mode (headless).
If at ANY point you determine that the current task exceeds your capability — \
for example, you need deeper reasoning, more creative research insight, \
complex architectural decisions, or you are uncertain about your answer quality — \
output exactly this marker on its own line:

ESCALATE: <one-line reason why you need a stronger model>

After outputting the marker, continue with your best-effort attempt. \
The system will automatically re-run the task with a stronger model using \
your attempt as context.

Do NOT escalate for mechanical tasks (search, file reading, formatting). \
Only escalate when genuine reasoning depth is the bottleneck."""

ESCALATION_SYSTEM_PROMPT_INTERACTIVE = """\
You are running in COST-SAVING interactive mode with auto-escalation.
Your model is {weak_model} (cheap). You have access to a stronger model ({strong_model}) \
via the Agent tool.

## ESCALATION RULE (CRITICAL — follow this at all times)

For EVERY task or sub-task, first assess: can I handle this well at my current capability level?

**Handle yourself** (do NOT escalate):
- Literature search, paper retrieval, metadata operations
- File reading, code formatting, data extraction
- Simple summaries, list generation, status checks
- Mechanical CLI operations, database queries
- Following clear instructions step by step

**Escalate to {strong_model}** (use Agent tool):
- Deep reasoning: novel research proposals, complex method design, architectural decisions
- Quality-critical judgment: evaluating paper novelty, assessing method soundness, comparing approaches
- Creative synthesis: generating research directions, designing experiments, writing key arguments
- Uncertainty: when you are not confident your answer meets the quality bar

## HOW TO ESCALATE

When you need the stronger model, use the Agent tool like this:

```
Agent(
  subagent_type="general-purpose",
  model="{strong_model}",
  prompt="<detailed task description with all necessary context>"
)
```

Include ALL relevant context in the prompt — the subagent has no memory of this conversation. \
After receiving the subagent's result, integrate it into your response.

## COST AWARENESS

Every opus call costs ~5x your cost. Escalate only when the quality gap genuinely matters. \
If you can produce a 90%+ quality answer yourself, do it yourself. \
Escalate when your answer would be below 70% quality for the task."""

ESCALATION_PATTERN = re.compile(r"^ESCALATE:\s*(.+)$", re.MULTILINE)

# Model escalation chain: each model maps to the next stronger one
ESCALATION_CHAIN: dict[str, str] = {
    "haiku": "sonnet",
    "claude-haiku-4-5-20251001": "sonnet",
    "sonnet": "opus",
    "claude-sonnet-4-6": "opus",
}

# Default starting model for escalation mode
DEFAULT_WEAK_MODEL = "sonnet"
DEFAULT_STRONG_MODEL = "opus"


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


def _find_claude_bin() -> str:
    """Locate the claude CLI binary."""
    for candidate in [
        "claude",
        os.path.expanduser("~/.claude/local/claude"),
        "/usr/local/bin/claude",
    ]:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    raise click.ClickException("claude CLI not found. Install Claude Code first.")


def _run_claude(
    prompt: str,
    *,
    cwd: str | None = None,
    max_turns: int = 0,
    output_format: str = "text",
    model: str | None = None,
    append_system: str | None = None,
    verbose: bool = False,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run claude in headless mode with full permissions."""
    claude_bin = _find_claude_bin()

    cmd = [
        claude_bin,
        "-p", prompt,
        "--dangerously-skip-permissions",
    ]

    if max_turns > 0:
        cmd += ["--max-turns", str(max_turns)]

    if output_format != "text":
        cmd += ["--output-format", output_format]

    if model:
        cmd += ["--model", model]

    if append_system:
        cmd += ["--append-system-prompt", append_system]

    if verbose:
        cmd += ["--verbose"]

    # When capturing for escalation, we need stdout in a pipe
    if capture:
        stdout_target = subprocess.PIPE
    else:
        stdout_target = sys.stdout if output_format == "text" else subprocess.PIPE

    return subprocess.run(
        cmd,
        cwd=cwd or os.getcwd(),
        text=True,
        stdout=stdout_target,
        stderr=sys.stderr,
        env=os.environ.copy(),
    )


def _detect_escalation(output: str) -> str | None:
    """Check if output contains an ESCALATE marker. Returns reason or None."""
    match = ESCALATION_PATTERN.search(output)
    if match:
        return match.group(1).strip()
    return None


def _get_stronger_model(current: str) -> str | None:
    """Get the next model in the escalation chain."""
    return ESCALATION_CHAIN.get(current)


def _run_with_escalation(
    prompt: str,
    *,
    cwd: str | None = None,
    max_turns: int = 0,
    start_model: str = DEFAULT_WEAK_MODEL,
    strong_model: str = DEFAULT_STRONG_MODEL,
    max_escalations: int = 1,
    verbose: bool = False,
) -> int:
    """Run with auto-escalation: start cheap, upgrade if model signals difficulty."""
    current_model = start_model
    escalation_count = 0
    previous_attempt: str | None = None

    while True:
        # Build prompt — include previous attempt as context if escalating
        effective_prompt = prompt
        if previous_attempt:
            effective_prompt = (
                f"A weaker model attempted this task but flagged it needs escalation.\n\n"
                f"--- PREVIOUS ATTEMPT (from {start_model}) ---\n"
                f"{previous_attempt[:8000]}\n"
                f"--- END PREVIOUS ATTEMPT ---\n\n"
                f"Please complete this task with your stronger capabilities. "
                f"Build on the previous attempt where it was correct, fix where it was wrong.\n\n"
                f"Original task:\n{prompt}"
            )

        is_final = (current_model == strong_model) or (escalation_count >= max_escalations)

        # Only inject escalation system prompt for non-final models
        system = ESCALATION_SYSTEM_PROMPT_HEADLESS if not is_final else None

        click.echo(
            f"[escalation] Running with model={current_model} "
            f"(escalation {escalation_count}/{max_escalations})",
            err=True,
        )

        result = _run_claude(
            effective_prompt,
            cwd=cwd,
            max_turns=max_turns,
            model=current_model,
            append_system=system,
            verbose=verbose,
            capture=not is_final,  # capture output for non-final runs to check escalation
        )

        # If this is the final model, output went to stdout already, done
        if is_final:
            if result.stdout:
                sys.stdout.write(result.stdout)
            return result.returncode

        output = result.stdout or ""
        reason = _detect_escalation(output)

        if reason is None:
            # No escalation needed — weak model handled it, print output
            sys.stdout.write(output)
            return result.returncode

        # Escalation triggered
        escalation_count += 1
        previous_attempt = output
        next_model = _get_stronger_model(current_model) or strong_model
        click.echo(
            f"[escalation] {current_model} requested escalation: {reason}",
            err=True,
        )
        click.echo(
            f"[escalation] Upgrading to {next_model}...",
            err=True,
        )
        current_model = next_model


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group()
@click.option("--cwd", default=None, help="Working directory for claude (defaults to current)")
@click.option("--model", default=None, help="Model override (e.g. sonnet, opus, haiku)")
@click.option("--verbose", is_flag=True, default=False)
@click.pass_context
def main(ctx: click.Context, cwd: str | None, model: str | None, verbose: bool) -> None:
    """claude-admin: Run Claude Code tasks with no confirmation prompts.

    All operations execute headlessly with full tool permissions.
    Supports auto-escalation from cheap to strong models.
    """
    ctx.ensure_object(dict)
    ctx.obj["cwd"] = cwd
    ctx.obj["model"] = model
    ctx.obj["verbose"] = verbose


@main.command()
@click.argument("prompt")
@click.option("--max-turns", type=int, default=0, help="Max agent turns (0=unlimited)")
@click.option("--json-output", is_flag=True, default=False, help="Output as JSON")
@click.option("--system", "append_system", default=None, help="Append to system prompt")
@click.pass_context
def run(
    ctx: click.Context,
    prompt: str,
    max_turns: int,
    json_output: bool,
    append_system: str | None,
) -> None:
    """Run a prompt directly through Claude Code (no questions asked)."""
    result = _run_claude(
        prompt,
        cwd=ctx.obj["cwd"],
        max_turns=max_turns,
        output_format="json" if json_output else "text",
        model=ctx.obj["model"],
        append_system=append_system,
        verbose=ctx.obj["verbose"],
    )
    if json_output and result.stdout:
        click.echo(result.stdout)
    sys.exit(result.returncode)


@main.command()
@click.argument("prompt")
@click.option("--max-turns", type=int, default=0, help="Max agent turns (0=unlimited)")
@click.option("--weak", "weak_model", default=DEFAULT_WEAK_MODEL, help=f"Starting cheap model (default: {DEFAULT_WEAK_MODEL})")
@click.option("--strong", "strong_model", default=DEFAULT_STRONG_MODEL, help=f"Escalation target model (default: {DEFAULT_STRONG_MODEL})")
@click.option("--max-escalations", type=int, default=1, help="Max times to escalate (default: 1)")
@click.pass_context
def smart(
    ctx: click.Context,
    prompt: str,
    max_turns: int,
    weak_model: str,
    strong_model: str,
    max_escalations: int,
) -> None:
    """Run with auto-escalation: starts cheap, upgrades if the model is stuck.

    Example:
        claude-admin smart "分析这篇论文的创新点" --weak haiku --strong opus
    """
    rc = _run_with_escalation(
        prompt,
        cwd=ctx.obj["cwd"],
        max_turns=max_turns,
        start_model=ctx.obj["model"] or weak_model,
        strong_model=strong_model,
        max_escalations=max_escalations,
        verbose=ctx.obj["verbose"],
    )
    sys.exit(rc)


@main.command()
@click.argument("prompt_file", type=click.Path(exists=True))
@click.option("--max-turns", type=int, default=0, help="Max agent turns (0=unlimited)")
@click.option("--json-output", is_flag=True, default=False, help="Output as JSON")
@click.pass_context
def run_file(
    ctx: click.Context,
    prompt_file: str,
    max_turns: int,
    json_output: bool,
) -> None:
    """Run a prompt from a file through Claude Code."""
    prompt = Path(prompt_file).read_text().strip()
    if not prompt:
        raise click.ClickException("Prompt file is empty")

    result = _run_claude(
        prompt,
        cwd=ctx.obj["cwd"],
        max_turns=max_turns,
        output_format="json" if json_output else "text",
        model=ctx.obj["model"],
        verbose=ctx.obj["verbose"],
    )
    if json_output and result.stdout:
        click.echo(result.stdout)
    sys.exit(result.returncode)


@main.command()
@click.argument("prompt")
@click.option("--max-turns", type=int, default=0, help="Max agent turns (0=unlimited)")
@click.pass_context
def run_json(ctx: click.Context, prompt: str, max_turns: int) -> None:
    """Run a prompt and return structured JSON output."""
    result = _run_claude(
        prompt,
        cwd=ctx.obj["cwd"],
        max_turns=max_turns,
        output_format="json",
        model=ctx.obj["model"],
        verbose=ctx.obj["verbose"],
    )
    if result.stdout:
        click.echo(result.stdout)
    sys.exit(result.returncode)


@main.command()
@click.argument("prompts", nargs=-1, required=True)
@click.option("--max-turns", type=int, default=0, help="Max agent turns per prompt")
@click.pass_context
def batch(ctx: click.Context, prompts: tuple[str, ...], max_turns: int) -> None:
    """Run multiple prompts sequentially, stopping on first failure."""
    for i, prompt in enumerate(prompts, 1):
        click.echo(f"\n{'='*60}")
        click.echo(f"[{i}/{len(prompts)}] {prompt[:80]}...")
        click.echo(f"{'='*60}\n")

        result = _run_claude(
            prompt,
            cwd=ctx.obj["cwd"],
            max_turns=max_turns,
            model=ctx.obj["model"],
            verbose=ctx.obj["verbose"],
        )
        if result.returncode != 0:
            click.echo(f"\nFailed at step {i}, aborting batch.", err=True)
            sys.exit(result.returncode)

    click.echo(f"\nAll {len(prompts)} prompts completed successfully.")


@main.command()
@click.argument("prompts", nargs=-1, required=True)
@click.option("--max-turns", type=int, default=0, help="Max agent turns per prompt")
@click.option("--weak", "weak_model", default=DEFAULT_WEAK_MODEL, help=f"Starting cheap model (default: {DEFAULT_WEAK_MODEL})")
@click.option("--strong", "strong_model", default=DEFAULT_STRONG_MODEL, help=f"Escalation target model (default: {DEFAULT_STRONG_MODEL})")
@click.pass_context
def smart_batch(
    ctx: click.Context,
    prompts: tuple[str, ...],
    max_turns: int,
    weak_model: str,
    strong_model: str,
) -> None:
    """Run multiple prompts with auto-escalation, stopping on first failure."""
    for i, prompt in enumerate(prompts, 1):
        click.echo(f"\n{'='*60}")
        click.echo(f"[{i}/{len(prompts)}] {prompt[:80]}...")
        click.echo(f"{'='*60}\n")

        rc = _run_with_escalation(
            prompt,
            cwd=ctx.obj["cwd"],
            max_turns=max_turns,
            start_model=ctx.obj["model"] or weak_model,
            strong_model=strong_model,
            verbose=ctx.obj["verbose"],
        )
        if rc != 0:
            click.echo(f"\nFailed at step {i}, aborting batch.", err=True)
            sys.exit(rc)

    click.echo(f"\nAll {len(prompts)} prompts completed successfully.")


@main.command()
@click.argument("skill_name")
@click.option("--args", "skill_args", default="", help="Arguments to pass to the skill")
@click.option("--max-turns", type=int, default=0, help="Max agent turns")
@click.option("--smart", "use_escalation", is_flag=True, default=False, help="Enable auto-escalation")
@click.pass_context
def skill(ctx: click.Context, skill_name: str, skill_args: str, max_turns: int, use_escalation: bool) -> None:
    """Invoke a research-harness skill directly (e.g. literature-search)."""
    prompt = f"/{skill_name}"
    if skill_args:
        prompt += f" {skill_args}"

    if use_escalation:
        rc = _run_with_escalation(
            prompt,
            cwd=ctx.obj["cwd"],
            max_turns=max_turns,
            start_model=ctx.obj["model"] or DEFAULT_WEAK_MODEL,
            verbose=ctx.obj["verbose"],
        )
        sys.exit(rc)

    result = _run_claude(
        prompt,
        cwd=ctx.obj["cwd"],
        max_turns=max_turns,
        model=ctx.obj["model"],
        verbose=ctx.obj["verbose"],
    )
    sys.exit(result.returncode)


@main.command()
@click.argument("initial_prompt", required=False, default=None)
@click.pass_context
def interactive(ctx: click.Context, initial_prompt: str | None) -> None:
    """Start an interactive Claude session with no permission prompts.

    All tool calls are auto-approved. Claude operates with full autonomy.

    \b
    Examples:
        claude-admin interactive                    # start session
        claude-admin interactive "专注 Paper 1"     # start with initial prompt
        claude-admin --model opus interactive       # use specific model
    """
    claude_bin = _find_claude_bin()
    cmd = [
        claude_bin,
        "--dangerously-skip-permissions",
    ]

    if ctx.obj["model"]:
        cmd += ["--model", ctx.obj["model"]]

    if ctx.obj["verbose"]:
        cmd += ["--verbose"]

    if initial_prompt:
        cmd.append(initial_prompt)

    click.echo("Starting admin session (all permissions granted)", err=True)
    click.echo("─" * 60, err=True)

    os.execvp(claude_bin, cmd)
