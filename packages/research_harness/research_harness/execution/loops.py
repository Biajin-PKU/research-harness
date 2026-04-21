"""Generate-Evaluate-Iterate loop controllers.

Implements the inner loop pattern from AI-Research-SKILLs and Anthropic's
harness design: generate -> evaluate -> iterate until quality threshold or max rounds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..storage.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision vocabulary (from AI-Research-SKILLs)
# ---------------------------------------------------------------------------

DIRECTION_DECISIONS = ("DEEPEN", "BROADEN", "PIVOT", "CONCLUDE")


@dataclass
class LoopIteration:
    """Record of one iteration in a generate-evaluate loop."""

    round: int
    score: float = 0.0
    passed: bool = False
    feedback: str = ""
    changes: list[str] = field(default_factory=list)


@dataclass
class LoopResult:
    """Final result of a generate-evaluate-iterate loop."""

    converged: bool
    final_score: float
    total_rounds: int
    iterations: list[LoopIteration] = field(default_factory=list)
    final_output: Any = None
    decision: str = ""  # DEEPEN|BROADEN|PIVOT|CONCLUDE


def run_section_loop(
    *,
    db: Database,
    section: str,
    topic_id: int,
    outline: str = "",
    max_words: int = 2000,
    max_rounds: int = 3,
    min_score: float = 0.7,
    evidence_ids: list[str] | None = None,
) -> LoopResult:
    """Generate-evaluate-iterate loop for paper section writing.

    1. section_draft -> generates content
    2. section_review -> scores on 10 dimensions + deterministic checks
    3. section_revise -> fixes issues from review
    4. Repeat until min_score reached or max_rounds exhausted.
    """
    from . import llm_primitives

    iterations: list[LoopIteration] = []
    content = ""
    final_score = 0.0

    for round_num in range(1, max_rounds + 1):
        logger.info("Section loop round %d/%d for '%s'", round_num, max_rounds, section)

        # Step 1: Draft (first round) or Revise (subsequent rounds)
        if round_num == 1:
            draft_result = llm_primitives.section_draft(
                db=db, section=section, topic_id=topic_id,
                outline=outline, max_words=max_words, evidence_ids=evidence_ids,
            )
            content = draft_result.draft.content
        else:
            # Build feedback from previous review
            feedback = "\n".join(
                f"- {s}" for s in review_result.suggestions  # noqa: F821
            )
            revise_result = llm_primitives.section_revise(
                db=db, section=section, content=content,
                review_feedback=feedback, target_words=max_words,
            )
            content = revise_result.revised_content
            iteration.changes = revise_result.changes_made  # noqa: F821

        # Step 2: Review
        review_result = llm_primitives.section_review(
            db=db, section=section, content=content,
            target_words=max_words,
        )

        score = review_result.overall_score
        passed = score >= min_score and not review_result.needs_revision
        final_score = score

        iteration = LoopIteration(
            round=round_num,
            score=score,
            passed=passed,
            feedback="; ".join(review_result.suggestions[:3]),
        )
        iterations.append(iteration)

        logger.info(
            "Round %d: score=%.3f, passed=%s, suggestions=%d",
            round_num, score, passed, len(review_result.suggestions),
        )

        if passed:
            return LoopResult(
                converged=True,
                final_score=score,
                total_rounds=round_num,
                iterations=iterations,
                final_output=content,
                decision="CONCLUDE",
            )

    # Did not converge
    decision = "DEEPEN" if final_score > 0.5 else "PIVOT"
    return LoopResult(
        converged=False,
        final_score=final_score,
        total_rounds=max_rounds,
        iterations=iterations,
        final_output=content,
        decision=decision,
    )


def run_experiment_loop(
    *,
    db: Database,
    topic_id: int,
    study_spec: str,
    max_iters: int = 5,
    target_metric: str = "",
    target_value: float | None = None,
) -> LoopResult:
    """Generate-evaluate-iterate loop for experiment code.

    1. code_generate -> produces experiment code
    2. code_validate -> checks syntax, security, imports
    3. experiment_run -> executes in sandbox
    4. Evaluate metrics -> decide continue or stop
    5. Feed metrics + feedback back to code_generate
    """
    from ..primitives.experiment_impls import code_validate, experiment_run
    from . import llm_primitives

    iterations: list[LoopIteration] = []
    code = ""
    metrics: dict[str, Any] = {}
    best_score = 0.0
    best_code = ""

    for iter_num in range(max_iters):
        logger.info("Experiment loop iteration %d/%d", iter_num + 1, max_iters)

        # Step 1: Generate code
        feedback = ""
        if iter_num > 0:
            feedback = _build_experiment_feedback(iterations[-1], metrics)

        gen_result = llm_primitives.code_generate(
            db=db,
            topic_id=topic_id,
            study_spec=study_spec,
            iteration=iter_num,
            previous_code=code,
            previous_metrics=metrics,
            feedback=feedback,
        )
        code = gen_result.files.get(gen_result.entry_point, "")
        if not code:
            iterations.append(LoopIteration(
                round=iter_num + 1, score=0.0, passed=False,
                feedback="Code generation produced empty output",
            ))
            continue

        # Step 2: Validate
        val_result = code_validate(code=code, auto_fix=True)
        if not val_result.ok:
            issues_str = "; ".join(i.message for i in val_result.issues[:3])
            iterations.append(LoopIteration(
                round=iter_num + 1, score=0.0, passed=False,
                feedback=f"Validation failed: {issues_str}",
            ))
            continue

        # Step 3: Run experiment
        try:
            run_result = experiment_run(code=code, timeout_sec=120.0, primary_metric=target_metric)
        except Exception as exc:
            iterations.append(LoopIteration(
                round=iter_num + 1, score=0.0, passed=False,
                feedback=f"Experiment execution failed: {exc}",
            ))
            continue

        if run_result.timed_out:
            iterations.append(LoopIteration(
                round=iter_num + 1, score=0.0, passed=False,
                feedback="Experiment timed out",
            ))
            continue

        metrics = run_result.metrics
        primary_value = run_result.primary_metric_value

        # Score this iteration
        score = 0.0
        passed = False
        if primary_value is not None:
            if target_value is not None:
                # Score relative to target
                score = min(1.0, primary_value / target_value) if target_value > 0 else 0.0
                passed = primary_value >= target_value
            else:
                score = 0.5  # Has metrics but no target
                passed = run_result.returncode == 0

            if score > best_score:
                best_score = score
                best_code = code
        elif run_result.returncode == 0:
            score = 0.3
            passed = False

        iteration = LoopIteration(
            round=iter_num + 1,
            score=score,
            passed=passed,
            feedback=f"metrics={metrics}, returncode={run_result.returncode}",
        )
        iterations.append(iteration)

        logger.info("Iteration %d: score=%.3f, passed=%s", iter_num + 1, score, passed)

        if passed:
            return LoopResult(
                converged=True,
                final_score=score,
                total_rounds=iter_num + 1,
                iterations=iterations,
                final_output=best_code or code,
                decision="CONCLUDE",
            )

    # Did not converge
    decision = "DEEPEN" if best_score > 0.3 else "PIVOT"
    return LoopResult(
        converged=False,
        final_score=best_score,
        total_rounds=max_iters,
        iterations=iterations,
        final_output=best_code or code,
        decision=decision,
    )


def _build_experiment_feedback(last_iteration: LoopIteration, metrics: dict[str, Any]) -> str:
    """Build feedback string from last iteration for code_generate."""
    parts = []
    if last_iteration.feedback:
        parts.append(f"Previous result: {last_iteration.feedback}")
    if not last_iteration.passed:
        parts.append("The experiment did not meet the target. Please improve.")
    if metrics:
        parts.append(f"Metrics from last run: {metrics}")
    return "\n".join(parts)
