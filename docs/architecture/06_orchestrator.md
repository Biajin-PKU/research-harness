# Research Orchestrator Specification

Updated: 2026-04-07

## Purpose

This document defines the canonical research pipeline orchestrator for `research-harness`.

It replaces the current fragmented state where workflow logic is split across:

- CLI operations
- roadmap phases
- MCP primitives
- Claude Code extension concepts
- manual research habits

The orchestrator defined here is intended to be:

- product-facing enough to explain to users
- concrete enough for Claude Code to implement
- compatible with the current `research_harness` storage and provenance model
- strict enough to gate progression on evidence, review, and adversarial resolution

This is not a "prompt chain".
It is a stateful control system for advancing a research project from topic framing to final artifact export.

## Design Goals

The orchestrator must satisfy six goals:

1. Give `research-harness` one canonical workflow rather than many loosely related commands.
2. Encode research progression as explicit stage transitions with entry and exit criteria.
3. Add a formal adversarial optimization mechanism for high-risk research decisions.
4. Adopt a stronger review loop inspired by academic peer review workflows.
5. Persist all intermediate outputs as typed artifacts linked to provenance.
6. Reuse existing `research-harness` objects and capabilities rather than replacing them.

## Product Thesis

`research-harness` should not position itself as an autonomous paper-writing agent.

Its durable product advantage is:

> a research operating system with evidence-gated progression, adversarial decision control, and review-closed-loop execution.

The orchestrator is the control plane that turns the current repository's primitives into a disciplined research process.

## Non-Goals

This design does not attempt to:

- replace the human researcher as final decision maker
- fully automate submission without approval
- bind the system to any one model vendor
- force every stage to use multi-agent debate
- turn all conversations into long review simulations

## Core Model

The orchestrator is a finite-state workflow with three embedded control layers:

1. `Workflow Layer`
   - advances the project through canonical research stages
2. `Adversarial Layer`
   - forces high-risk decisions through structured proposal, challenge, and resolution
3. `Review Layer`
   - blocks publication-facing progression until integrity and scholarly review pass

This yields the following operating pattern:

```text
work -> gate -> challenge if needed -> resolve -> review when draft exists -> revise
     -> re-review -> final integrity -> finalize
```

## Canonical Pipeline

The orchestrator defines 12 canonical stages:

1. `topic_framing`
2. `literature_mapping`
3. `evidence_structuring`
4. `research_direction`
5. `adversarial_optimization`
6. `study_design`
7. `draft_preparation`
8. `formal_review`
9. `revision`
10. `re_review`
11. `final_integrity`
12. `finalize`

The stages are intentionally product-level, not implementation-level.
Multiple primitives, commands, or agent actions may run inside one stage.

## Stage Summary

| Stage | Objective | Primary output | Gate type |
|------|-----------|----------------|-----------|
| `topic_framing` | define topic, venue, goals, constraints | topic brief | approval gate |
| `literature_mapping` | build broad and credible paper pool | literature map | coverage gate |
| `evidence_structuring` | transform papers into structured claims, baselines, and support links | evidence pack | coverage gate |
| `research_direction` | propose candidate research direction and contributions | direction proposal | adversarial trigger |
| `adversarial_optimization` | challenge and resolve the proposed direction | approved plan | adversarial gate |
| `study_design` | define experiment or study plan | study spec | adversarial gate |
| `draft_preparation` | prepare outline, citation pack, section evidence, figures/tables plan | draft pack | readiness gate |
| `formal_review` | run integrity + scholarly review on draft pack or draft | review report bundle | review gate |
| `revision` | address required changes and produce response log | revision package | review gate |
| `re_review` | confirm issues are resolved and no major regressions exist | re-review report | review gate |
| `final_integrity` | final factual and citation verification before export | final integrity report | integrity gate |
| `finalize` | export submission-ready bundle | final bundle | approval gate |

## Workflow Modes

The same orchestrator supports four modes.

### `explore`

Use for topic discovery and early research.

Properties:

- lighter coverage thresholds
- adversarial loop only on direction selection
- formal review may be skipped unless draft exists

### `standard`

Default mode for normal paper work.

Properties:

- all 12 stages available
- mandatory adversarial loop on direction and study design
- one formal review round and one re-review round

### `strict`

Use for high-value papers, grant proposals, or internal flagship demos.

Properties:

- higher coverage thresholds
- adversarial loop also required for critical draft sections
- stricter integrity checks
- more issues classified as blocking

### `demo`

Use for product showcase and automated demonstrations.

Properties:

- may auto-advance on satisfied gates
- keeps all artifacts and provenance
- emphasizes visible outputs and summaries

## State Machine

Each project tracked by the orchestrator should maintain:

- current stage
- stage status
- gate status
- required artifacts
- unresolved issues count
- blocking review items count
- latest approved plan
- latest approved draft package

### Stage Status

Allowed per-stage status values:

- `not_started`
- `in_progress`
- `blocked`
- `awaiting_review`
- `awaiting_resolution`
- `approved`
- `rejected`
- `completed`

### Transition Rules

General rules:

1. A stage may begin only if all predecessor stages are `completed` or explicitly bypassed by mode policy.
2. A stage may exit only when its mandatory artifacts exist and its gate passes.
3. A gate failure sends the stage to `blocked` or sends the project back to the designated fallback stage.
4. Adversarial stages cannot auto-pass without a recorded resolution object.
5. Review stages cannot auto-pass while blocking issues remain open.

## Stage Specifications

The sections below define the canonical behavior expected from implementation.

### 1. `topic_framing`

Objective:

- create a stable project anchor before search and drafting begin

Inputs:

- topic name
- target venue or output type
- research motivation
- constraints
- optional seed papers or seed hypotheses

Required artifacts:

- `topic_brief`

Recommended `topic_brief` fields:

- topic slug
- working title
- target venue
- problem statement
- scope boundaries
- inclusion criteria
- exclusion criteria
- success definition
- open questions

Exit criteria:

- topic brief exists
- venue or output type exists
- scope boundaries recorded
- human approval recorded

Fallback on failure:

- remain in `topic_framing`

### 2. `literature_mapping`

Objective:

- build a credible literature base rather than a shallow paper list

Inputs:

- approved topic brief
- user queries
- generated queries
- seed papers

Required artifacts:

- `literature_map`
- `paper_pool_snapshot`

Recommended `literature_map` fields:

- paper clusters
- baseline papers
- method families
- evaluation patterns
- conflicting papers
- recency distribution
- venue distribution
- uncovered subtopics

Coverage gate criteria:

- minimum paper count by mode
- minimum high-relevance paper count
- minimum baseline coverage
- at least one contradiction or competing approach captured when available
- source provenance recorded for search and ingest actions

Suggested thresholds:

| Mode | Min papers | Min high relevance | Min baseline candidates |
|------|------------|--------------------|-------------------------|
| `explore` | 12 | 4 | 3 |
| `standard` | 20 | 6 | 5 |
| `strict` | 30 | 8 | 6 |

Fallback on failure:

- remain in `literature_mapping`
- optionally expand or refine queries

### 3. `evidence_structuring`

Objective:

- convert literature into reusable research assets

Inputs:

- literature map
- ingested papers
- paper cards
- notes

Required artifacts:

- `evidence_pack`
- `baseline_matrix`
- `claim_candidate_set`

Recommended `evidence_pack` fields:

- claim candidates
- evidence links
- support strength
- contradiction links
- baseline comparisons
- limitations inventory
- dataset mentions
- metric mentions

Coverage gate criteria:

- claim candidates extracted from multiple papers
- baseline matrix populated
- unsupported claims ratio below threshold
- each retained high-priority claim linked to evidence

Suggested thresholds:

- minimum 3 candidate claims in `standard`
- minimum 1 evidence link per candidate claim before direction selection
- unsupported claim ratio under 0.5 in `standard`, under 0.3 in `strict`

Fallback on failure:

- return to `literature_mapping` if the issue is missing papers
- remain in `evidence_structuring` if the issue is extraction quality

### 4. `research_direction`

Objective:

- generate candidate research directions from the structured evidence base

Inputs:

- evidence pack
- baseline matrix
- project constraints

Required artifacts:

- `direction_proposal`

Recommended `direction_proposal` fields:

- candidate research question
- candidate hypothesis
- expected contribution
- evidence basis
- baseline relation
- main risks
- assumptions
- falsification path

Exit criteria:

- at least one direction proposal exists
- proposal is evidence-linked
- proposal is marked ready for adversarial review

Transition:

- successful completion moves immediately into `adversarial_optimization`

### 5. `adversarial_optimization`

Objective:

- prevent premature advancement of weak proposals

This stage is the primary product innovation added to the existing design.

It formalizes the empirical workflow discovered through Claude Code and Codex collaboration:

- one side proposes
- another side audits
- iteration continues until objections are resolved or the proposal is rejected

Required artifacts:

- `adversarial_round`
- `adversarial_resolution`
- `approved_plan` or `rejected_plan`

#### Roles

`Proposer`

- produces candidate research direction, method plan, or argument
- owns the current proposal revision
- must respond with evidence or concrete reasoning

`Auditor`

- attacks weaknesses rather than polishing language
- searches for unsupported novelty, logical jumps, missing baselines, invalid evaluation assumptions, and scope inflation
- outputs structured objections

`Resolver`

- determines which objections are valid
- decides whether responses sufficiently address them
- records convergence outcome

The implementation may bind these roles to:

- different models
- the same model with different prompts
- model plus human
- model plus external reviewer

The product specification does not hardcode vendor identities.

#### Trigger Points

The adversarial loop is mandatory for:

- research direction approval
- study design approval

It is additionally mandatory in `strict` mode for:

- major contribution claims
- core draft sections such as introduction and method

#### Adversarial Round Schema

Each `adversarial_round` should include:

- round number
- target object type
- target object id
- proposal snapshot
- objection list
- proposer responses
- unresolved objections
- resolver decision
- severity summary

#### Objection Categories

At minimum, support these objection types:

- `novelty`
- `evidence_gap`
- `baseline_gap`
- `method_validity`
- `scope_drift`
- `falsifiability`
- `writing_clarity`
- `implementation_feasibility`

#### Scoring Rubric

Each resolution should score the proposal on:

- novelty
- evidence coverage
- method validity
- baseline completeness
- scope discipline
- falsifiability
- clarity

Recommended range:

- integer `0-5`

Suggested pass rule:

- no critical unresolved objections
- novelty, evidence coverage, and method validity each at least `4` in `standard`
- all key dimensions at least `4` in `strict`
- mean score at least `4.0`

#### Outcomes

Allowed adversarial outcomes:

- `approved`
- `approved_with_conditions`
- `revise_and_repeat`
- `reject_and_return`

Fallback:

- `revise_and_repeat` stays in `adversarial_optimization`
- `reject_and_return` sends project back to `research_direction` or `study_design`, depending on target

### 6. `study_design`

Objective:

- turn the approved direction into an executable study or experiment plan

Inputs:

- approved plan from adversarial stage
- baseline matrix
- evidence pack

Required artifacts:

- `study_spec`

Recommended `study_spec` fields:

- research question
- hypotheses
- datasets
- baselines
- metrics
- ablations
- evaluation protocol
- threats to validity
- resource constraints
- stop conditions

Exit criteria:

- study spec exists
- baselines and metrics populated
- risks recorded
- study spec passes adversarial gate

Fallback on failure:

- return to `adversarial_optimization`

### 7. `draft_preparation`

Objective:

- prepare a draft package that is reviewable before long-form writing expands

Inputs:

- approved study spec
- evidence pack
- notes
- citation data

Required artifacts:

- `draft_pack`

Recommended `draft_pack` fields:

- paper outline
- section goals
- claim-to-evidence mapping
- citation pack
- figure plan
- table plan
- open risks
- unresolved assumptions

Readiness gate criteria:

- each major section has purpose and evidence source
- each major claim has linked support
- citation pack generated
- figures/tables plan exists when relevant

Suggested rule:

- no major section may be marked ready without at least one evidence-backed claim

Fallback on failure:

- return to `study_design` or `evidence_structuring`

### 8. `formal_review`

Objective:

- run a structured quality review before the project advances toward finalization

This stage adopts the strongest reusable idea from the reference project:

- review is not a single opinion
- it is a typed bundle of checks with blocking outcomes

Required artifacts:

- `integrity_review_report`
- `scholarly_review_report`
- `review_bundle`

#### Review Types

`Integrity Review`

Checks:

- citations exist and resolve to real sources
- claims are supported by cited evidence
- numbers and tables do not overstate evidence
- no obvious unsupported factual assertions
- source attribution is preserved

This is a hard gate.

`Scholarly Review`

Checks:

- novelty framing
- method soundness
- baseline completeness
- evaluation rigor
- contribution clarity
- limitation acknowledgment

This is a blocking quality gate.

`Revision Coaching`

Checks:

- how to address issues
- what evidence is missing
- which claims must be narrowed, removed, or rewritten

This is advisory, but it generates required actions.

#### Review Issue Model

Every review issue should include:

- issue id
- review type
- severity
- category
- affected object
- explanation
- recommended action
- blocking flag

Required severity levels:

- `critical`
- `high`
- `medium`
- `low`

Blocking rules:

- `critical` always blocks
- `high` blocks in `standard` and `strict`
- `medium` may block in `strict` if tied to integrity or validity

Exit criteria:

- review bundle exists
- all blocking issues converted into revision tasks
- project enters `revision`

### 9. `revision`

Objective:

- implement required changes while preserving traceability to review feedback

Required artifacts:

- `revision_package`
- `response_to_review`

Required `response_to_review` fields:

- issue id
- action taken
- evidence added
- text changed
- rationale if not adopted
- status

Exit criteria:

- every blocking issue has a response record
- changes linked to artifacts or draft sections
- unresolved blocking items explicitly marked

Transition:

- successful revision moves to `re_review`

### 10. `re_review`

Objective:

- verify that revisions solved the intended problems and did not introduce regressions

Required artifacts:

- `re_review_report`

Checks:

- previous blocking issues resolved
- no major regressions introduced
- no new integrity issues introduced by revision

Exit criteria:

- no unresolved blocking issue remains
- resolver marks the package ready for final integrity

Fallback on failure:

- return to `revision`

### 11. `final_integrity`

Objective:

- perform the last verification pass before export or submission packaging

Required artifacts:

- `final_integrity_report`

Checks:

- citations still valid after revisions
- claims still match evidence after wording changes
- tables/figures consistent with narrative
- no unresolved placeholders remain
- required disclosures or provenance metadata attached

This is a hard gate.

Exit criteria:

- zero blocking integrity issues
- final integrity report approved

Fallback on failure:

- return to `revision`

### 12. `finalize`

Objective:

- produce a submission-ready bundle and project summary

Required artifacts:

- `final_bundle`
- `process_summary`

Recommended `final_bundle` contents:

- final manuscript or structured export
- bibliography export
- figures/tables export
- review reports
- response-to-review log
- provenance export

Exit criteria:

- final bundle generated
- human approval recorded

## Gate Types

The orchestrator uses five gate classes.

### `approval_gate`

Human confirms the stage output is acceptable.

Used in:

- `topic_framing`
- `finalize`

### `coverage_gate`

Checks that the project has enough structured material to advance.

Used in:

- `literature_mapping`
- `evidence_structuring`

### `adversarial_gate`

Checks that structured challenge and resolution have converged.

Used in:

- `adversarial_optimization`
- `study_design`

### `review_gate`

Checks that blocking review findings have been addressed.

Used in:

- `formal_review`
- `revision`
- `re_review`

### `integrity_gate`

Checks that publication-facing outputs are evidence-safe and source-safe.

Used in:

- `formal_review` via integrity review
- `final_integrity`

## Artifact Model

The orchestrator should persist stage outputs as typed artifacts, not loose text blobs.

Minimum new artifact types recommended:

- `topic_brief`
- `literature_map`
- `paper_pool_snapshot`
- `evidence_pack`
- `baseline_matrix`
- `claim_candidate_set`
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
- `process_summary`

Each artifact should include:

- artifact type
- project id
- topic id
- stage
- status
- version
- source references
- creation provenance
- parent artifact ids where applicable

## Review Object Model

Current `review` support in `research_harness` is useful but too thin for the orchestrator.

The orchestrator should evolve review storage from a single verdict record into a richer structure with:

- review bundle
- issue list
- severity
- affected objects
- response status
- blocking state

Recommended object families:

- `ReviewBundle`
- `ReviewIssue`
- `ReviewResponse`
- `ResolutionDecision`

These may map initially to existing tables plus JSON payloads, then later to first-class schema objects.

## Provenance Requirements

This orchestrator depends on provenance being mandatory rather than optional.

Every stage transition should record:

- project id
- topic id
- previous stage
- next stage
- trigger
- gate result
- actor
- rationale

Every adversarial round should record:

- proposer identity
- auditor identity
- resolver identity
- proposal hash
- objection hashes
- resolution outcome

Every review cycle should record:

- review inputs
- issue counts by severity
- responses
- final resolution

The existing provenance system under `research_harness.provenance` and the MCP provenance tools should be reused as the primary audit layer.

## Mapping to Existing `research-harness` Capabilities

The orchestrator should be implemented as a unifying layer over current capabilities.

### Existing assets to reuse

From the current repository:

- topic and project management
- paper ingest and listing
- paper annotation and card generation
- note drafting
- task tracking
- review logging
- provenance recording
- `paperindex` structure and card extraction
- MCP tools in `packages/research_harness_mcp`
- dashboard views in `web_dashboard`
- Claude Code agents in `.claude/agents`

### Immediate role mapping

Current agents:

- `.claude/agents/proposer.md` -> `Proposer`
- `.claude/agents/challenger.md` -> `Auditor`
- `.claude/agents/adversarial-resolver.md` -> `Resolver`
- `.claude/agents/literature-mapper.md` -> stage helper for `literature_mapping`
- `.claude/agents/synthesizer.md` -> stage helper for `evidence_structuring` and `draft_preparation`

### Primitive and MCP mapping

Likely mappings:

- `paper_search` -> `literature_mapping`
- `paper_ingest` -> `literature_mapping`
- `paper_summarize` -> `evidence_structuring`
- `claim_extract` -> `evidence_structuring`
- `baseline_identify` -> `evidence_structuring` and `study_design`
- `gap_detect` -> `research_direction`
- `section_draft` -> `draft_preparation` and `revision`
- `consistency_check` -> `formal_review` and `final_integrity`
- provenance summary/export tools -> all reviewable stages

### CLI mapping direction

The orchestrator should add a stage-aware interface instead of forcing users to call isolated commands.

Recommended future CLI families:

- `rhub orchestrator init`
- `rhub orchestrator status`
- `rhub orchestrator advance`
- `rhub orchestrator gate check`
- `rhub orchestrator adversarial run`
- `rhub orchestrator review run`
- `rhub orchestrator finalize`

These should wrap existing commands rather than replace them.

## Dashboard Requirements

The dashboard should expose orchestrator state directly.

Minimum dashboard panels recommended:

- current stage and stage status
- gate health
- blocking issues
- latest approved plan
- adversarial round history
- review severity summary
- revision progress
- provenance summary

This is important because the orchestrator is only product-visible if users can inspect its control state.

## Failure and Retry Policy

The orchestrator should define explicit failure paths.

### Failure classes

- `missing_input`
- `insufficient_coverage`
- `adversarial_non_convergence`
- `blocking_review_findings`
- `integrity_failure`
- `execution_failure`

### Retry rules

- coverage failures retry within the current stage
- adversarial non-convergence retries within the same target object, up to a configurable round limit
- integrity failure always blocks progression and returns to `revision` or earlier
- repeated execution failure may mark the stage `blocked` and require human intervention

Recommended adversarial retry cap:

- `standard`: 3 rounds
- `strict`: 5 rounds

Exceeding the cap should force one of:

- scope reduction
- proposal rejection
- human arbitration

## Human Authority Model

The orchestrator must preserve researcher authority.

Human approval is required for:

- initial topic framing
- final accepted research direction when mode requires manual approval
- final export in `finalize`
- any override of a failed integrity gate

The system may recommend, challenge, and organize.
It does not become scientist of record.

## Implementation Priorities

Implementation should proceed in four slices.

### Slice 1: Control Model

Implement:

- orchestrator state object
- stage enum
- status enum
- transition rules
- gate evaluation framework

### Slice 2: Artifact and Review Expansion

Implement:

- new artifact types
- richer review issue model
- response-to-review objects

### Slice 3: Adversarial Loop

Implement:

- proposer/auditor/resolver run protocol
- round persistence
- resolution scoring
- convergence policy

### Slice 4: UX Surfaces

Implement:

- CLI orchestrator commands
- dashboard orchestration panels
- MCP convenience tools for orchestrator state

## Minimum Viable Implementation

If implementation must start narrow, the minimum viable orchestrator should support:

- stages through `study_design`
- one adversarial loop on direction selection
- one formal review cycle
- typed artifact persistence
- stage-aware dashboard summary

That is enough to validate the orchestration model without waiting for full finalization support.

## Success Criteria

The orchestrator is successful when:

1. a project can be advanced through explicit stages rather than ad hoc command sequences
2. major decisions cannot bypass adversarial challenge
3. review findings produce actionable revision work rather than one-line verdicts
4. every stage output is inspectable as an artifact
5. provenance can explain why the project advanced or was blocked
6. dashboard and CLI expose the same orchestration state

## Final Positioning

This orchestrator should become the default way to explain `research-harness`.

Not:

- "a collection of research commands"
- "a paper-writing agent"
- "a Claude Code skill pack clone"

But:

> a research operating system with evidence-gated workflow, adversarial optimization, and review-closed-loop execution.
