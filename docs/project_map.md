# Project Map

Updated: 2026-04-08

## Project Purpose

`research-harness` is a local research operating system for managing literature ingestion, paper understanding, topic/project workflows, and a growing orchestration layer for end-to-end research execution.

## Key Directories

- `packages/research_harness/research_harness/`: primary application package, CLI, execution stack, data model, and orchestrator code
- `packages/paperindex/paperindex/`: PDF structure extraction, indexing, paper-card generation, and shared LLM client
- `packages/research_harness_mcp/`: MCP server exposing workspace and `paperindex` tools
- `web_dashboard/`: Flask dashboard for theme/project/paper visibility
- `paper_library/`: local paper PDFs and generated card JSON artifacts
- `.research-harness/`: local runtime data and generated artifacts
- `docs/`: active architecture notes, plans, release docs, and handoff state
- `scripts/`: one-off maintenance, regeneration, ingestion, and utility scripts

## Important Entry Points

- `packages/research_harness/research_harness/cli.py`: `rhub` / `python -m research_harness.cli` workflows
- `packages/research_harness/research_harness/orchestrator/service.py`: orchestrator service layer
- `packages/research_harness/research_harness/execution/`: execution primitives and prompt wiring
- `packages/research_harness/research_harness/integrations/paperindex_adapter.py`: bridge from workspace to `paperindex`
- `packages/paperindex/paperindex/indexer.py`: PDF indexing and card build path
- `packages/paperindex/paperindex/cards/extraction.py`: LLM-backed card extraction rules
- `web_dashboard/app.py`: dashboard app

## Current Status

- Paper ingestion, annotation, and card generation are functional.
- Dashboard v1 is documented as release-ready for the current `auto-bidding` theme.
- The repo has active uncommitted work on an orchestrator/control-plane expansion.
- Stable near-term product direction is documented in `docs/current_work_plan.md`.

## Known Pitfalls

- The worktree is dirty; do not assume `git status` reflects a single coherent feature.
- `docs/session_handoff.md` is partly stale relative to newer orchestrator/dashboard changes.
- `docs/project_map.md` did not exist before this session, so older handoffs may reference only the paper-indexing track.
- Generated paper assets under `paper_library/` and `.research-harness/` are large and should not be treated as hand-edited source by default.

## Recommended Read Order

1. `docs/session_handoff.md`
2. `docs/project_map.md`
3. `docs/current_work_plan.md`
4. `docs/dashboard_v1_release.md`
5. Current feature files touched in `git status`
