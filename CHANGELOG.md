# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-04-22

### Added

- **HTTP API + Web dashboard.** FastAPI-backed service exposing orchestrator
  state, topics/domains, papers, and artifacts with a React dashboard for
  navigation. Concurrent paper-search across configured providers.
- **Orchestrator stage gating.** Hardened gate mechanism — stages cannot
  advance until their typed evidence artifacts are recorded and verified.
- **`llm_router` standalone package.** Multi-provider LLM routing lifted out
  of `paperindex` into its own package. Task-tier routing (`light`/`medium`/
  `heavy`) is now usable anywhere without a paperindex dependency.
- **Plugin discovery for custom providers.** Drop a `.py` file in
  `~/.config/llm_router/plugins/` (or point `$LLM_ROUTER_PLUGINS` at one) and
  it is auto-loaded on import. Broken plugins are logged, not propagated.
- **Config file for `llm_router`.** Optional TOML at `$LLM_ROUTER_CONFIG` or
  `~/.config/llm_router/config.toml` supporting `[routing] provider_order`
  and tier route entries. Env vars still win when set.
- **Codex bridge stability hardening.** Pre-flight check, per-backend graded
  timeouts (codex 180s / anthropic 90s), `stdin=DEVNULL`, and a per-backend
  circuit breaker so repeat failures stop wasting 300s timeouts.

### Changed (breaking)

- **Data model: Domain → Topic → Papers.** The standalone `projects` table has been
  merged into `topics`. Orchestrator state, artifacts, reviews, and experiment runs
  now key off `topic_id`. The `projects` table and `project_id` columns remain in the
  SQLite schema for backward compat (SQLite cannot DROP COLUMN) but are no longer
  written by code. Migrations `037_domains_and_project_merge.sql` and
  `038_reviews_drop_project_not_null.sql` apply automatically on first DB open.
- **CLI:** `rh project add/list/show/update` removed. Use `rh topic init` (with optional
  `--domain`). Orchestrator commands that took `--project-id` now take `--topic` (by
  name) or `--topic-id`. New `rh domain init/list/show` commands added.
- **Python API:** `run_project`/`resume_project` renamed to `run_topic`/`resume_topic`.
  `ResearchAPI` methods (`record_artifact`, `orchestrator_status`, `gate_check`,
  `list_stage_artifacts`, `list_stale_artifacts`) take `topic_id` instead of `project_id`.
- **HTTP API:** `/api/projects` endpoints replaced by richer `/api/topics` endpoints
  (with orchestrator state inline) plus new `/api/domains`. Web dashboard updated to
  navigate Domain → Topic.
- **MCP tools:** all orchestrator/review/adversarial tools now take `topic_id`
  (no longer accept `project_id`).
- **Import paths:** LLM client code moved from `paperindex.llm.client` to
  `llm_router.client`. Update imports (`from llm_router import LLMClient,
  resolve_llm_config`).

### Fixed

- HTTP API uvicorn reload watcher scoped to the package directory to avoid
  reloading on unrelated file changes.

## [0.1.0] — 2026-04-21

### Added

**Core platform**

- 69 research primitives spanning retrieval, comprehension, extraction, analysis, synthesis, generation, and verification categories
- 112 MCP tools (stdio transport) wrapping all primitives plus orchestrator, provenance, advisory, and paperindex tools
- Primitive registry with `@register_primitive` decorator for registration and auto-MCP-exposure
- Provenance recorder that tracks every primitive execution with cost, model, output hash, and artifact lineage
- Plugin architecture: custom primitives, gates, stages, advisory rules, and backends via `plugin.yaml` manifest

**Orchestrator**

- 6-stage pipeline: `init → build → analyze → propose → experiment → write`
- Evidence-gated stage advancement — stages produce typed artifacts; gates verify them before permitting progression
- Dual-axis execution model: `workflow_mode` (explore/standard/strict/demo) × `autonomy_mode` (supervised/autonomous)
- Autonomous mode with auto-resolved gates; high-risk stages (direction selection, finalize) always require human approval
- `orchestrator_resume` tool for re-attaching to an in-progress project without restarting from scratch
- Stale artifact tracking and dependency graph for artifact lineage

**Adversarial review**

- `adversarial_review` primitive: independent cross-model challenge/response for high-stakes decisions
- Configurable challenger model separate from the orchestrating model
- Challenge/response/resolution recorded as first-class artifacts

**Literature tools**

- `paper_search` across multiple configured providers (Semantic Scholar, OpenAlex, arXiv)
- `paper_ingest` with arXiv ID, DOI, or local PDF path
- `paper_acquire` for batch PDF download
- `paper_summarize`, `claim_extract`, `evidence_link`, `gap_detect`, `baseline_identify`
- `iterative_retrieval_loop` for coverage-driven search expansion
- `paper_coverage_check` for gap-aware coverage scoring
- `deep_read` two-pass deep reading with `DeepReadingNote` output
- `enrich_affiliations` for author affiliation resolution

**Analysis tools**

- `method_taxonomy`, `evidence_matrix`, `contradiction_detect`
- `table_extract`, `figure_interpret`, `metrics_aggregate`
- `competitive_learning`, `reading_prioritize`

**Writing tools**

- `outline_generate`, `section_draft`, `section_review`, `section_revise`
- `writing_architecture`, `paper_finalize`
- `figure_plan`, `figure_generate` (via fal.ai integration)
- `rebuttal_format`, `topic_export`
- `consistency_check` for cross-section verification
- `latex_compile` with tectonic backend
- Writing skill aggregate and writing pattern extraction

**Algorithm design tools**

- `direction_ranking`, `design_brief_expand`, `design_gap_probe`
- `algorithm_candidate_generate`, `originality_boundary_check`
- `algorithm_design_refine`, `algorithm_design_loop`

**Self-improvement**

- Observation middleware for recording execution traces
- `experience_ingest`, `lesson_extract`, `lesson_overlay`
- `strategy_distill`, `strategy_inject`, `meta_reflect`
- `cold_start_run` for bootstrapping from a gold-standard trace

**Paperindex package**

- PDF structure extraction (sections, headings, figures, tables)
- Section-level full-text search
- Paper card generation (`paperindex_card` MCP tool)
- Multi-LLM provider routing for extraction tasks

**Web dashboard**

- Local Flask monitoring dashboard at `http://127.0.0.1:18080`
- Pipeline stage progress, provenance log, advisory notices, artifact browser

**Infrastructure**

- SQLite storage with incremental migrations (`pool.db`)
- `rh` / `rhub` / `research-harness` CLI entry points
- `claude-admin` CLI for administrative tasks
- `rhub --json doctor` health check
- Advisory engine with heuristic warnings and acknowledgement tracking
- Auto-runner for bounded autonomous task execution
- 987+ tests across `research_harness` and `paperindex` packages
- `environment.yml` for conda setup
- `setup.sh` one-command bootstrap

[Unreleased]: https://github.com/your-org/research-harness/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/research-harness/releases/tag/v0.1.0
