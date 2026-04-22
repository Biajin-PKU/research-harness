# Orchestrator Implementation Plan

Updated: 2026-04-07

## Purpose

This document turns [`06_orchestrator.md`](06_orchestrator.md) into an implementation-oriented plan for the current repository.

The goal is to let Claude Code implement the orchestrator incrementally without:

- destabilizing the existing CLI
- blocking on a full schema redesign
- duplicating logic already present in `research_harness`
- overcoupling the first version to any one LLM host

This plan assumes the current repository state as of 2026-04-07.

## Current Codebase Fit

The existing repository already contains the core building blocks needed for an orchestrator:

- `packages/research_harness/research_harness/storage/`
  - database access and base models
- `packages/research_harness/research_harness/core/`
  - project, paper, and review management
- `packages/research_harness/research_harness/primitives/`
  - research primitive registry
- `packages/research_harness/research_harness/execution/`
  - backend abstraction and research harness backend
- `packages/research_harness/research_harness/provenance/`
  - provenance persistence and summaries
- `packages/research_harness_mcp/research_harness_mcp/`
  - MCP tool surface
- `.claude/agents/`
  - proposer, challenger, adversarial-resolver, literature-mapper, synthesizer

The missing layer is a single control module that coordinates these components around stages, gates, and structured review objects.

## Recommended Module Layout

Add a new top-level package subtree:

```text
packages/research_harness/research_harness/orchestrator/
├── __init__.py
├── models.py
├── service.py
├── stages.py
├── gates.py
├── artifacts.py
├── review.py
├── adversarial.py
├── transitions.py
└── serializers.py
```

### Module Responsibilities

`models.py`

- orchestrator dataclasses and enums
- stage enum
- stage status enum
- gate result enum
- workflow mode enum
- review issue severity enum

`service.py`

- high-level orchestration API used by CLI, MCP, and dashboard
- create orchestrator state
- advance stage
- run gate evaluation
- run adversarial loop
- start review cycle

`stages.py`

- stage metadata registry
- predecessor rules
- required artifact types by stage
- fallback stage rules

`gates.py`

- coverage gate evaluators
- readiness gate evaluators
- review gate evaluators
- integrity gate evaluators

`artifacts.py`

- typed helpers for reading and writing orchestrator artifacts
- versioning logic
- parent-child artifact links

`review.py`

- review bundle creation
- issue tracking
- response-to-review handling
- re-review helpers

`adversarial.py`

- proposer/auditor/resolver protocol
- round persistence
- convergence scoring

`transitions.py`

- central stage transition validator
- mode-aware bypass logic

`serializers.py`

- JSON-safe output for CLI and MCP
- dashboard summary payloads

## Storage Strategy

The current schema is too thin to support full orchestrator semantics as first-class normalized tables.

To avoid over-design in the first implementation, use a two-phase storage strategy.

### Phase A: Minimal Schema Expansion + JSON Payloads

Add a small number of generic tables that allow fast iteration.

Recommended new tables:

1. `orchestrator_runs`
2. `orchestrator_stage_events`
3. `project_artifacts`
4. `review_issues`
5. `review_responses`

This is enough to implement:

- canonical stage tracking
- typed artifact persistence
- blocking review issue management
- response-to-review traceability

### Phase B: Promote Stable JSON Shapes into First-Class Tables

Only after real usage stabilizes:

- split artifact families into more specific schemas
- normalize adversarial rounds and review bundles further if needed

This keeps the initial implementation fast and reversible.

## Proposed Schema Additions

Create a new migration after `005_add_paper_url.sql`.

Recommended file:

- `packages/research_harness/migrations/006_orchestrator_core.sql`

### `orchestrator_runs`

Purpose:

- one row per project-level orchestrated workflow

Suggested columns:

- `id INTEGER PRIMARY KEY`
- `project_id INTEGER NOT NULL`
- `topic_id INTEGER NOT NULL`
- `mode TEXT NOT NULL`
- `current_stage TEXT NOT NULL`
- `stage_status TEXT NOT NULL`
- `gate_status TEXT NOT NULL DEFAULT ''`
- `blocking_issue_count INTEGER NOT NULL DEFAULT 0`
- `unresolved_issue_count INTEGER NOT NULL DEFAULT 0`
- `latest_plan_artifact_id INTEGER`
- `latest_draft_artifact_id INTEGER`
- `created_at TEXT DEFAULT (datetime('now'))`
- `updated_at TEXT DEFAULT (datetime('now'))`

Indexes:

- `UNIQUE(project_id)`
- index on `topic_id`

### `orchestrator_stage_events`

Purpose:

- append-only history of stage transitions and gate outcomes

Suggested columns:

- `id INTEGER PRIMARY KEY`
- `run_id INTEGER NOT NULL`
- `project_id INTEGER NOT NULL`
- `topic_id INTEGER NOT NULL`
- `from_stage TEXT NOT NULL`
- `to_stage TEXT NOT NULL`
- `event_type TEXT NOT NULL`
- `status TEXT NOT NULL`
- `gate_type TEXT NOT NULL DEFAULT ''`
- `actor TEXT NOT NULL DEFAULT ''`
- `rationale TEXT NOT NULL DEFAULT ''`
- `payload_json TEXT NOT NULL DEFAULT '{}'`
- `created_at TEXT DEFAULT (datetime('now'))`

### `project_artifacts`

Purpose:

- stage outputs for project-level orchestration

Suggested columns:

- `id INTEGER PRIMARY KEY`
- `project_id INTEGER NOT NULL`
- `topic_id INTEGER NOT NULL`
- `stage TEXT NOT NULL`
- `artifact_type TEXT NOT NULL`
- `status TEXT NOT NULL DEFAULT 'active'`
- `version INTEGER NOT NULL DEFAULT 1`
- `title TEXT NOT NULL DEFAULT ''`
- `path TEXT NOT NULL DEFAULT ''`
- `payload_json TEXT NOT NULL DEFAULT '{}'`
- `metadata_json TEXT NOT NULL DEFAULT '{}'`
- `parent_artifact_id INTEGER`
- `provenance_record_id INTEGER`
- `created_at TEXT DEFAULT (datetime('now'))`
- `updated_at TEXT DEFAULT (datetime('now'))`

Indexes:

- `(project_id, stage, artifact_type)`
- `(topic_id, artifact_type)`

### `review_issues`

Purpose:

- blocking and non-blocking findings from integrity and scholarly review

Suggested columns:

- `id INTEGER PRIMARY KEY`
- `project_id INTEGER NOT NULL`
- `topic_id INTEGER NOT NULL`
- `review_artifact_id INTEGER`
- `stage TEXT NOT NULL`
- `review_type TEXT NOT NULL`
- `severity TEXT NOT NULL`
- `category TEXT NOT NULL`
- `affected_object_type TEXT NOT NULL DEFAULT ''`
- `affected_object_id TEXT NOT NULL DEFAULT ''`
- `blocking INTEGER NOT NULL DEFAULT 0`
- `status TEXT NOT NULL DEFAULT 'open'`
- `summary TEXT NOT NULL`
- `details TEXT NOT NULL DEFAULT ''`
- `recommended_action TEXT NOT NULL DEFAULT ''`
- `created_at TEXT DEFAULT (datetime('now'))`
- `updated_at TEXT DEFAULT (datetime('now'))`

### `review_responses`

Purpose:

- track how each review issue was addressed

Suggested columns:

- `id INTEGER PRIMARY KEY`
- `issue_id INTEGER NOT NULL`
- `project_id INTEGER NOT NULL`
- `response_type TEXT NOT NULL DEFAULT 'change'`
- `status TEXT NOT NULL DEFAULT 'proposed'`
- `artifact_id INTEGER`
- `response_text TEXT NOT NULL DEFAULT ''`
- `evidence_json TEXT NOT NULL DEFAULT '{}'`
- `created_at TEXT DEFAULT (datetime('now'))`
- `updated_at TEXT DEFAULT (datetime('now'))`

## Dataclass Plan

Add dataclasses in `orchestrator/models.py`.

Minimum objects:

- `WorkflowMode`
- `StageName`
- `StageStatus`
- `GateType`
- `GateStatus`
- `GateDecision`
- `OrchestratorRun`
- `StageEvent`
- `ProjectArtifact`
- `ReviewIssue`
- `ReviewResponse`
- `AdversarialRound`
- `AdversarialResolution`

### Modeling Guidance

- use string enums or `Literal`-like constants compatible with SQLite storage
- keep dataclasses frozen only where mutation is not required
- make JSON payload fields explicit dictionaries rather than opaque strings in memory
- keep DB row conversion helpers close to repository or manager classes

## Service Layer Plan

Create `research_harness/orchestrator/service.py` as the public integration surface.

Recommended class:

- `OrchestratorService`

Dependencies:

- `Database`
- `ProvenanceRecorder`
- existing managers
- execution backend factory

Suggested methods:

- `init_run(topic_name: str, project_name: str, mode: str) -> OrchestratorRun`
- `get_run(project_id: int) -> OrchestratorRun | None`
- `get_status(project_id: int) -> dict`
- `advance(project_id: int, actor: str, auto_run_gates: bool = True) -> dict`
- `check_gate(project_id: int, stage: str | None = None) -> GateDecision`
- `record_artifact(...) -> ProjectArtifact`
- `list_artifacts(project_id: int, stage: str | None = None) -> list[ProjectArtifact]`
- `run_adversarial_loop(project_id: int, artifact_id: int, actor: str) -> dict`
- `run_formal_review(project_id: int, actor: str) -> dict`
- `record_review_response(issue_id: int, ...) -> ReviewResponse`
- `run_re_review(project_id: int, actor: str) -> dict`
- `run_final_integrity(project_id: int, actor: str) -> dict`
- `finalize(project_id: int, actor: str) -> dict`

The service should be the only layer allowed to mutate orchestrator state.

## Repositories and Managers

Do not overload existing managers such as `ReviewManager` with all orchestrator responsibilities.

Add dedicated repository or manager classes:

- `OrchestratorRunManager`
- `ProjectArtifactManager`
- `ReviewIssueManager`
- `ReviewResponseManager`

Location:

- `packages/research_harness/research_harness/core/` is acceptable
- alternatively create `packages/research_harness/research_harness/orchestrator/repository.py`

Recommended approach:

- keep orchestration-specific persistence under `orchestrator/`
- leave older managers unchanged except where small extensions are necessary

## Artifact Strategy

The orchestrator lives or dies on artifact discipline.

### Rule 1

Every stage must produce at least one typed project artifact before it can complete.

### Rule 2

Artifact payloads should be stored as JSON in Phase A, but helper functions must expose typed Python structures.

### Rule 3

Artifacts should support versioning rather than in-place overwrite.

### Rule 4

Artifacts should store parent references to preserve derivation chains.

### Immediate Artifact Families

Implement first:

- `topic_brief`
- `literature_map`
- `evidence_pack`
- `direction_proposal`
- `adversarial_round`
- `adversarial_resolution`
- `approved_plan`
- `study_spec`
- `draft_pack`
- `integrity_review_report`
- `scholarly_review_report`
- `review_bundle`
- `revision_package`
- `response_to_review`
- `re_review_report`
- `final_integrity_report`
- `final_bundle`

Delay until later if needed:

- `paper_pool_snapshot`
- `baseline_matrix`
- `claim_candidate_set`
- `process_summary`

## Gate Evaluator Plan

Implement gate logic as pure evaluators where possible.

Recommended interface:

```python
class GateEvaluator(Protocol):
    def evaluate(self, db: Database, run: OrchestratorRun) -> GateDecision: ...
```

Add one evaluator per gate family:

- `CoverageGateEvaluator`
- `AdversarialGateEvaluator`
- `ReviewGateEvaluator`
- `IntegrityGateEvaluator`
- `ApprovalGateEvaluator`

### Why pure evaluators

- easier to test
- easier to expose via CLI and MCP
- easier to run in dashboard status refresh

## Adversarial Loop Implementation

Create `orchestrator/adversarial.py`.

This should not require full autonomous multi-agent infrastructure in the first version.

### Version 1 Protocol

Input:

- target artifact id
- target stage
- proposer prompt or generated candidate
- auditor findings
- resolver judgment

Output:

- one `adversarial_round` artifact
- one `adversarial_resolution` artifact
- optional `approved_plan` artifact

### Execution Model

Support three execution modes from the start:

- `manual`
  - human supplies proposal or responses
- `single_backend`
  - one backend plays all roles with different prompts
- `dual_backend`
  - proposer and auditor can be routed differently

This keeps the implementation aligned with your Claude Code plus Codex workflow without hardcoding either product.

### Minimal internal API

- `run_round(target_artifact, mode, config) -> AdversarialRound`
- `resolve_round(round_id, config) -> AdversarialResolution`
- `should_repeat(resolution) -> bool`

## Review System Upgrade Plan

Current `ReviewManager` stores one flat review row with:

- `gate`
- `reviewer`
- `verdict`
- `score`
- `findings`

This is not enough for orchestrator-grade review.

### Recommended upgrade path

Keep the existing `reviews` table for backwards compatibility.

Add orchestrator-level review support using:

- `project_artifacts` for report payloads
- `review_issues` for findings
- `review_responses` for traceable fixes

This allows:

- old commands to keep working
- new orchestrator review flow to be richer

### Formal review flow

1. generate integrity review report artifact
2. generate scholarly review report artifact
3. explode reports into `review_issues`
4. generate revision tasks
5. move stage to `revision`

### Re-review flow

1. inspect unresolved issues
2. validate linked responses
3. emit `re_review_report`
4. either advance or return to `revision`

## Provenance Integration Plan

The orchestrator should not reinvent provenance.

Instead:

- use existing `TrackedBackend` and `ProvenanceRecorder` for primitive execution
- add orchestrator stage events as separate records in `orchestrator_stage_events`
- cross-link artifacts to provenance record ids whenever a backend execution produced them

### Required additions

When orchestrator service changes stage:

- record a stage event row
- optionally create a light provenance record if no primitive call occurred

When artifacts are created from backend results:

- attach `provenance_record_id`

This keeps current provenance tools useful without forcing all control-plane events into the primitive provenance table.

## CLI Plan

Do not bury the orchestrator behind many unrelated commands.

Add a new top-level CLI group under existing `rhub`:

- `rhub orchestrator ...`

Recommended first commands:

- `rhub orchestrator init --topic ... --project ... --mode standard`
- `rhub orchestrator status --topic ... --project ...`
- `rhub orchestrator artifacts --topic ... --project ...`
- `rhub orchestrator gate-check --topic ... --project ...`
- `rhub orchestrator advance --topic ... --project ...`
- `rhub orchestrator adversarial-run --topic ... --project ... --artifact-id ...`
- `rhub orchestrator review-run --topic ... --project ...`
- `rhub orchestrator re-review --topic ... --project ...`
- `rhub orchestrator finalize --topic ... --project ...`

### CLI design rules

- return JSON when `--json` is enabled
- avoid requiring users to know internal artifact ids unless using advanced commands
- show current stage, blocking issues, and next required artifact by default

## MCP Plan

Add orchestration convenience tools to `packages/research_harness_mcp/research_harness_mcp/tools.py`.

Recommended new tool names:

- `orchestrator_status`
- `orchestrator_advance`
- `orchestrator_gate_check`
- `orchestrator_artifacts`
- `orchestrator_review_summary`

Do not expose full mutation-heavy review editing via MCP in version 1.
Keep MCP focused on visibility and safe control actions.

## Dashboard Plan

The dashboard should become the inspection surface for the orchestrator.

Recommended initial panels:

- project current stage
- stage status and gate status
- latest artifact by stage
- blocking issues by severity
- adversarial loop history
- latest review bundle
- provenance cost summary

### Implementation advice

- start with read-only dashboard support
- avoid writable dashboard actions in the first orchestrator release

## Suggested File-Level Write Scope

This section is intended to guide Claude Code implementation order.

### New files

- `packages/research_harness/research_harness/orchestrator/__init__.py`
- `packages/research_harness/research_harness/orchestrator/models.py`
- `packages/research_harness/research_harness/orchestrator/stages.py`
- `packages/research_harness/research_harness/orchestrator/artifacts.py`
- `packages/research_harness/research_harness/orchestrator/adversarial.py`
- `packages/research_harness/research_harness/orchestrator/review.py`
- `packages/research_harness/research_harness/orchestrator/transitions.py`
- `packages/research_harness/research_harness/orchestrator/service.py`
- `packages/research_harness/tests/test_orchestrator_service.py`
- `packages/research_harness/tests/test_orchestrator_gates.py`
- `packages/research_harness/tests/test_orchestrator_cli.py`
- `packages/research_harness/migrations/006_orchestrator_core.sql`

### Existing files to extend

- `packages/research_harness/research_harness/cli.py`
- `packages/research_harness/research_harness/storage/models.py`
- `packages/research_harness_mcp/research_harness_mcp/tools.py`
- `web_dashboard/app.py`
- relevant dashboard templates

### Existing files to avoid destabilizing early

- primitive registry and primitive implementations
- current paper ingestion flow
- paperindex adapter internals
- existing provenance schema

## Recommended Delivery Slices

Implement in this exact order.

### Slice 1: Orchestrator State Skeleton

Deliver:

- migration `006_orchestrator_core.sql`
- dataclasses and enums
- run manager
- stage event persistence
- `orchestrator init`
- `orchestrator status`

Tests:

- run creation
- default stage is `topic_framing`
- transition guard rejects skipping stages

### Slice 2: Artifact Persistence and Stage Advancement

Deliver:

- project artifact persistence
- stage registry
- transition service
- `orchestrator artifacts`
- `orchestrator advance`

Tests:

- cannot complete stage without required artifact
- artifact version increments
- fallback stage behavior

### Slice 3: Gate Framework

Deliver:

- coverage gate evaluator
- approval gate evaluator
- gate check command

Tests:

- literature mapping threshold logic
- evidence structuring threshold logic
- manual approval handling

### Slice 4: Adversarial Optimization MVP

Deliver:

- adversarial round artifact flow
- resolution scoring
- repeat or approve logic
- `orchestrator adversarial-run`

Tests:

- unresolved critical objections block stage
- approved resolution advances target
- max rounds fallback path works

### Slice 5: Formal Review Loop MVP

Deliver:

- review issues table support
- review bundle artifacts
- response-to-review records
- `orchestrator review-run`
- `orchestrator re-review`

Tests:

- blocking issues open revision stage
- responses close issues
- re-review returns unresolved cases to revision

### Slice 6: Final Integrity and Finalize

Deliver:

- final integrity report artifact
- finalize command
- final bundle creation

Tests:

- integrity failure blocks finalization
- final bundle requires approval

### Slice 7: MCP and Dashboard Surfaces

Deliver:

- orchestration MCP tools
- read-only dashboard panels

Tests:

- MCP returns stage summaries
- dashboard routes render without breaking existing pages

## Backward Compatibility Rules

The orchestrator must not break current users who still rely on:

- direct topic and project commands
- paper ingest and annotation commands
- older review logging commands
- provenance summary and export

Rules:

1. new orchestration commands wrap existing functionality where possible
2. old review records remain readable
3. dashboard additions must not remove current views
4. migration must be additive only

## Testing Plan

Testing should be added in three layers.

### Unit tests

Focus on:

- stage transition validation
- gate evaluators
- artifact versioning
- adversarial scoring

### Integration tests

Focus on:

- CLI end-to-end stage progression
- review issue lifecycle
- finalization path

### MCP tests

Focus on:

- orchestration convenience tool outputs
- status serialization

### Suggested command

Current likely command target:

```bash
pytest packages/research_harness/tests -q
```

If new MCP tests are added, run the package-specific test suite as well.

## Open Design Decisions

Claude Code should resolve these during implementation, but the current recommendation is included.

### 1. Project vs topic run granularity

Recommendation:

- one orchestrator run per project

Reason:

- aligns with current `project` abstraction
- easier to support multiple papers under one topic

### 2. Artifact payload storage

Recommendation:

- JSON in SQLite for version 1

Reason:

- fast iteration
- easy dashboard rendering
- avoids premature schema fragmentation

### 3. Review issue generation

Recommendation:

- start with deterministic parser over structured review payloads

Reason:

- issue lifecycle needs stable identifiers
- free-form text extraction should be minimized early

### 4. Adversarial execution host

Recommendation:

- make it backend-agnostic

Reason:

- product should not depend on one vendor pairing
- your Claude Code plus Codex workflow should remain a supported policy, not a hard dependency

## Definition of Done

The orchestrator implementation is not done when a document exists.
It is done when all of the following are true:

1. a project can be initialized into orchestrator mode
2. stage status is queryable through CLI and MCP
3. stage completion requires typed artifacts
4. adversarial optimization blocks weak plans
5. review issues are tracked individually
6. re-review can close or reopen issues
7. final integrity can block finalize
8. dashboard can show the workflow state without manual DB inspection

## Recommended Immediate Next Step

Claude Code should start with `Slice 1` and `Slice 2`.

Reason:

- they establish the control plane without requiring LLM-heavy implementation
- they give a visible workflow state quickly
- they unblock later adversarial and review features

After that, implement `Slice 4` before the full review loop if time is limited.

That preserves the core differentiator:

> research progression cannot skip structured challenge and resolution.
