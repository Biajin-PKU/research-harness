---
name: research-harness
description: Main entry skill for Research Harness workflows in Codex. Trigger on phrases like "research-harness", "/research-harness", "用 Research Harness", "进入科研工作流", "开始科研流程", or equivalent requests to route the task to topic initialization, literature search, citation tracing, claim extraction, gap analysis, evidence gating, section drafting, paper verification, or provenance review.
---

# Research Harness

Use this skill as the default entry point when the user wants to work inside the Research Harness workflow but does not name a more specific skill.

## First Step

Read `~/code/research-harness/docs/agent-guide.md` if the repo or topic context is incomplete.

## Routing Rules

Route to the most specific matching workflow:

- topic or project bootstrap: `research-init`
- broad paper discovery: `literature-search`
- topic-level clustering and baseline coverage: `literature-mapping`
- seed-paper expansion: `citation-trace`
- extract claims and evidence: `claim-extraction`
- identify research opportunities: `gap-analysis`
- decide readiness to advance: `evidence-gating`
- write evidence-backed sections: `section-drafting`
- verify paper identity or metadata: `paper-verify`
- audit recorded history and artifacts: `provenance-review`

If the request spans multiple stages, execute them in dependency order instead of asking the user to split the request.

## Defaults

- Prefer explicit ingestion over keeping ad hoc paper lists in chat only.
- Prefer concrete next actions over abstract workflow summaries.
- If Research Harness tools are unavailable, still follow the same workflow shape and state the missing tool plainly.
