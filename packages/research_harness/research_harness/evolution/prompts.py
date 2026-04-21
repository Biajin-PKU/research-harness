"""LLM prompt templates for the self-evolution pipeline.

All prompts expect JSON output for deterministic parsing.
"""

from __future__ import annotations


def aggregate_themes_prompt(stage: str, evidence_text: str) -> str:
    """Prompt to cluster lessons + trajectory evidence into themes."""
    return f"""\
You are a research workflow analyst. Given evidence from the "{stage}" stage
of a research workflow, identify 2-5 recurring themes or strategy patterns.

## Evidence
{evidence_text}

## Task
Group the evidence into themes. For each theme, provide:
- "theme_key": a short slug (e.g. "citation_expansion_strategy")
- "title": human-readable title (e.g. "Citation Expansion Strategy")
- "summary": 2-3 sentence description of the pattern
- "evidence_ids": list of lesson IDs that support this theme
- "scope": "global" if applicable across topics, "topic" if topic-specific

Return JSON: {{"themes": [...]}}"""


def distill_strategy_prompt(
    stage: str, theme_key: str, theme_title: str, theme_summary: str,
    supporting_evidence: str,
) -> str:
    """Prompt to distill a theme into an actionable strategy."""
    return f"""\
You are a research methodology expert. Write a concise, actionable strategy
document for the "{stage}" stage of a research workflow.

## Theme
Key: {theme_key}
Title: {theme_title}
Summary: {theme_summary}

## Supporting Evidence
{supporting_evidence}

## Task
Write a strategy in markdown format with these sections:
1. **When to Apply** — conditions under which this strategy is useful
2. **Steps** — concrete, numbered action steps
3. **Pitfalls** — common mistakes to avoid
4. **Evidence** — brief summary of what worked/failed in past runs

Keep it under 300 words. Be specific and actionable, not generic.

Return JSON: {{"content": "<markdown strategy text>"}}"""


def quality_gate_prompt(strategy_text: str, stage: str) -> str:
    """Prompt for 4-dimension quality gate evaluation."""
    return f"""\
You are a quality reviewer for research workflow strategies. Evaluate the
following strategy for the "{stage}" stage on 4 dimensions.

## Strategy
{strategy_text}

## Evaluation Dimensions (score each 0.0-1.0)

1. **evidence_grounded** — Is the strategy grounded in concrete evidence
   from actual workflow executions, not generic advice?
2. **preserves_existing** — Does it preserve existing known-good practices
   rather than replacing them with untested alternatives?
3. **specific_reusable** — Is it specific enough to be actionable yet
   general enough to be reusable across similar situations?
4. **safe_to_publish** — Is it safe to inject into future sessions without
   risk of degrading performance?

Return JSON:
{{
  "scores": {{
    "evidence_grounded": <float>,
    "preserves_existing": <float>,
    "specific_reusable": <float>,
    "safe_to_publish": <float>
  }},
  "overall": <float>,
  "decision": "accept" or "reject",
  "reasoning": "<1-2 sentences>"
}}"""
