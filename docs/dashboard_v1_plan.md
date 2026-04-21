# Dashboard v1.0 Plan

Updated: 2026-04-07

## Goal

Ship a usable `Research Control Plane v1.0` for the current `auto-bidding` research theme.

v1.0 is not "the final research operating system". It is the first version that is stable and useful enough for daily monitoring and reading work.

## Product Boundary

v1.0 covers:

- theme-level monitoring for `auto-bidding`
- project-level workspaces for `paper2` and `paper4`
- paper-level reading via cards
- document-level reading for project docs and references

v1.0 does **not** try to solve:

- experiment registry
- claim-evidence graph
- manuscript drafting workspace
- submission-readiness workflows
- multi-theme authoring UI

Those belong to later product milestones, not this dashboard release.

## Required v1.0 Scope

### 1. Theme Dashboard

The homepage must support:

- theme summary metrics
- project list with stage and health
- theme monitor with:
  - coverage signals
  - stage summary
  - recent trend strip
  - risk alerts with suggested actions
- activity feed across docs, cards, and tracked papers

### 2. Project Workspace

Each project page state inside the dashboard must support:

- project summary
- project monitor cards
- blocker list
- next-step list
- document list with timestamps
- in-dashboard document preview

### 3. Paper Console

The paper console must support:

- project-scoped paper list
- grouped literature buckets
- text search
- card-state filter
- group quick filter
- direct "Open Card" action

### 4. Card Reader

The paper card drawer must support:

- metadata
- core idea
- method summary
- key results
- structured results
- limitations
- evidence
- artifact links
- raw JSON fallback

## v1.0 Acceptance Criteria

The dashboard is v1.0-ready when all of the following are true:

1. The Flask app starts from the project `.venv` without ad hoc patching.
2. `GET /api/themes/auto-bidding/overview` returns a complete payload with health, stage summary, risks, and trends.
3. `GET /api/projects/paper2` and `GET /api/projects/paper4` return project monitor data plus document lists.
4. `GET /api/projects/<slug>/papers` returns grouped papers.
5. `GET /api/projects/<slug>/documents/<doc_id>` returns readable document content.
6. `GET /api/papers/<id>/card` returns a readable card payload for card-backed papers.
7. The homepage can be used end-to-end to:
   - understand current theme status
   - inspect a project
   - preview a project document
   - filter grouped papers
   - open a paper card

## Current Status

As of 2026-04-07, the implementation already includes most of the planned v1.0 scope:

- theme → project → paper hierarchy
- theme monitor
- project workspace
- grouped paper console
- card reader
- document preview

The remaining work should focus on stability and polish, not scope expansion.

## Remaining v1.0 Work

### P0: Stabilization

- add targeted tests for dashboard aggregation helpers and key Flask routes
- remove obvious response-shape fragility in route handlers
- verify the dashboard against the current local database without debug-only assumptions

### P1: Reading Experience Polish

- improve markdown preview rendering for more document patterns
- tune grouped paper ordering so the most important papers appear first within each group
- reduce noisy activity feed duplication when multiple docs update at once

### P2: Release Hygiene

- document the startup command and dependency expectations
- ensure `web_dashboard/requirements.txt` is sufficient for a clean setup
- decide whether `.venv.broken` should be kept or removed before release handoff

## Explicit Non-Goals for v1.0

The following are intentionally out of scope:

- trend charts beyond the current lightweight trend strip
- writable dashboard actions
- task editing UI
- research note editing UI
- experiment-run management UI
- claim and evidence editing UI
- manuscript section editing UI
- generalized multi-theme administration

## Versioning Rule

From this point forward:

- if a change is required to satisfy the acceptance criteria above, it belongs to `v1.0`
- if a change is useful but not required for the acceptance criteria, it should be deferred to `v1.1`

This rule is meant to stop endless iteration and force scope discipline.
