# Research Harness Operating Model

Updated: 2026-04-02

## Document Purpose

This document defines the product direction for `research-harness` when treated as a standalone research system rather than a companion to external coding agents such as Codex or Claude Code.

The goal is to answer one practical question:

> If a researcher starts with only a rough idea such as "I want to write an EMNLP paper about automated paper writing", how should `research-harness` help that person move from idea to submission in a disciplined, high-efficiency way?

This document is intentionally product-facing rather than implementation-first. It sets the boundary between:

- core system capabilities
- the built-in research agent
- external development agents
- the human researcher

It also explains how `research-harness` can deliver substantial value even when external coding agents are not present.

## Executive Summary

`research-harness` should not be framed as an "automatic paper writing agent".

That positioning is too broad, too fragile, and too dependent on whichever frontier model happens to be available. A stronger and more durable positioning is:

> `research-harness` is a Research Operating System for structured paper production.

Its job is not to replace the researcher. Its job is to make research work:

- organized instead of scattered
- traceable instead of opaque
- incremental instead of chaotic
- evidence-linked instead of intuition-only
- workflow-driven instead of note-driven

In that framing, the built-in agent is a research operator and research assistant, not the scientist of record.

## Product Thesis

Research productivity is usually lost in five places:

1. Context fragmentation: papers, notes, ideas, tasks, and experiment results live in different places.
2. Weak provenance: people forget why a claim was made, where a result came from, or which paper motivated a method choice.
3. Research drift: the project loses a stable center as more reading and experiments accumulate.
4. Experiment disorder: runs are difficult to compare, reproduce, and connect back to hypotheses.
5. Writing disconnect: draft text is often not explicitly backed by literature or experimental evidence.

`research-harness` should be optimized to solve those five problems.

The product promise is not "we do the science for you".
The product promise is:

> We help you run a research project like a disciplined lab rather than an improvised folder of PDFs and notes.

## Core Positioning

Recommended positioning statement:

> From idea to submission, `research-harness` structures the research process.

Recommended short product description:

> `research-harness` is a research workflow system that organizes literature, hypotheses, experiments, evidence, and drafting into one traceable workspace.

Positioning to avoid:

- fully automatic paper generation
- autonomous scientist replacement
- one-shot paper writing
- submission without human judgment

Those claims create the wrong expectations and weaken the architecture.

## Standalone Value Without External Coding Agents

When Codex or Claude Code are absent, `research-harness` should still provide strong value by doing three things well.

### 1. Keep research state coherent

A researcher should always be able to answer:

- What is the current topic?
- What is the current research question?
- What papers matter most?
- What claims are we considering?
- What evidence supports each claim?
- Which experiments are pending or complete?
- What remains before a draft is submission-ready?

If the system can answer those questions reliably, it already saves a large amount of time.

### 2. Turn literature into structured research material

The system should not stop at paper search and summarization.
It should convert papers into structured project assets such as:

- relevance judgments
- baseline candidates
- method comparisons
- limitations databases
- citation-ready notes
- claim-supporting evidence
- gap candidates

This is where the paper understanding and retrieval stack becomes product infrastructure rather than a demo.

### 3. Turn experiments and writing into evidence-linked workflows

The strongest long-term product differentiation is not just storing text. It is storing the links between:

- hypotheses
- experiments
- results
- tables and figures
- claims
- draft sections

That is what makes the product a research operating system rather than a note-taking layer.

## System Roles

The full environment may involve four roles.

### Human Researcher

The human researcher remains the owner of:

- research goals
- final hypothesis selection
- contribution framing
- acceptance of evidence
- paper-level judgment
- submission decisions

This is the decision-making authority.

### Research Harness Core

This is the product infrastructure layer.
It owns:

- data models
- storage
- task state
- paper ingestion and indexing
- retrieval and reranking
- experiment records
- provenance tracking
- writing artifact management
- approval gates and workflow state

This layer must be deterministic where possible, typed, inspectable, and testable.

### Built-In Research Agent

This is the product runtime assistant.
It should help with:

- literature triage
- clustering and summarization
- note drafting
- query expansion
- experiment checklist generation
- candidate claim extraction
- outline drafting
- evidence gap detection
- consistency review of drafts

It should not own final research direction.
Its role is operator, organizer, and assistant.

### External Development Agents

Codex or Claude Code belong outside the product runtime.
They are best used for:

- building the system
- modifying architecture
- implementing features
- debugging experiments and code
- extending workflows
- improving prompts and tool interfaces

They are part of the development plane, not the core research runtime.

## Boundary Design

A clean boundary model for the project is:

### Layer 1: Research Control Plane

Owned by the human researcher.
May be assisted by external development agents.

Responsibilities:

- define topic and target venue
- decide project goals
- approve major workflow transitions
- choose final hypotheses and claims
- approve experimental scope
- approve final draft framing

### Layer 2: Research Runtime Plane

Owned by the built-in `research-harness` agent.

Responsibilities:

- execute structured research tasks
- call product tools
- summarize and organize results
- prepare candidate outputs for review
- maintain workflow progress
- raise conflicts or missing evidence

### Layer 3: Research Infrastructure Plane

Owned by `research-harness` core code.

Responsibilities:

- expose stable APIs and CLI operations
- manage data integrity
- maintain provenance
- persist records and artifacts
- support retrieval, analysis, and drafting workflows

Key rule:

> The runtime agent should only use public product capabilities and structured internal APIs. It should not be allowed to mutate arbitrary internal state through ad hoc shortcuts.

This keeps the product inspectable and maintainable.

## Product Design Principle

The built-in agent should be optimized for research acceleration, not unrestricted autonomy.

That implies these principles:

1. The agent proposes; the system records; the human approves.
2. Every important output should have provenance.
3. Every major workflow stage should have explicit entry and exit criteria.
4. Free-form LLM outputs should be attached to structured state.
5. The system should prefer recoverable workflows over clever one-shot automation.

## Canonical User Journey

This is the recommended default journey for a standalone user.

### Stage 1: Topic Initialization

Input:

- topic idea
- target venue
- rough keywords
- optional constraints such as data, compute, or timeline

System responsibilities:

- create topic workspace
- record venue and objective
- generate initial reading agenda
- suggest topic decomposition and sub-questions
- create an initial task board

Primary output:

- topic workspace with a clear research brief

### Stage 2: Literature Mapping

Input:

- search queries
- seed papers
- imported PDFs or bibliography

System responsibilities:

- ingest papers
- extract metadata and paper cards
- cluster by theme
- identify likely baselines, adjacent work, and inspiration papers
- generate relevance and gap notes
- surface duplicate or low-value reading candidates

Primary output:

- curated paper pool and literature map

### Stage 3: Research Question and Claim Formation

Input:

- literature map
- key notes
- candidate problem statements

System responsibilities:

- turn reading evidence into candidate research questions
- summarize open gaps and unresolved tensions in prior work
- propose claim candidates and assumptions
- mark which claims are currently unsupported

Primary output:

- candidate research questions and claim graph

Human checkpoint:

- select the working research question
- reject weak or derivative directions

### Stage 4: Method Planning

Input:

- chosen research question
- target claims
- constraints and resources

System responsibilities:

- generate method design checklists
- connect design decisions to motivating literature
- record alternatives considered and rejected
- draft an implementation and evaluation plan

Primary output:

- method plan with rationale and linked evidence

Human checkpoint:

- approve the planned method and scope

### Stage 5: Experiment Planning

Input:

- method plan
- baseline candidates
- datasets and metrics

System responsibilities:

- define experiment registry entries
- map hypotheses to required experiments
- create ablation checklist
- create risk list for missing controls
- prepare result slots for tables and figures

Primary output:

- experiment matrix linked to hypotheses

### Stage 6: Experiment Execution and Tracking

Input:

- experiment definitions
- run configurations
- artifacts and metrics

System responsibilities:

- track run status
- capture config, seed, artifact paths, and metrics
- attach free-form run notes
- highlight missing or contradictory results
- summarize deltas across runs

Primary output:

- reproducible experiment registry and result summaries

### Stage 7: Evidence Consolidation

Input:

- completed run records
- literature-derived notes
- draft claims

System responsibilities:

- build claim-to-evidence links
- identify unsupported or weakly supported claims
- group evidence for tables, figures, and narrative sections
- flag inconsistent results

Primary output:

- claim-evidence graph

### Stage 8: Drafting

Input:

- topic brief
- literature map
- method plan
- experiment evidence

System responsibilities:

- generate section outlines
- produce draft paragraphs tied to evidence
- suggest citations from local paper notes
- warn when sentences lack support
- maintain section-level revision status

Primary output:

- evidence-backed draft package

### Stage 9: Submission Readiness

Input:

- mature draft
- final experiments
- venue requirements

System responsibilities:

- run completeness checks
- verify all major claims have support
- verify baseline coverage
- verify figures and tables are linked to runs
- check writing consistency across abstract, introduction, experiments, and conclusion
- produce a final readiness checklist

Primary output:

- submission checklist and unresolved issue list

## Core Product Modules

To maximize standalone value, the product should prioritize the following modules.

### 1. Topic Workspace

This is the top-level operating unit.

It should hold:

- topic brief
- target venue
- status
- core research question
- candidate claims
- project-level tasks
- reading queue
- experiment status summary
- draft status summary

Why it matters:

Without a workspace abstraction, the rest of the system becomes a pile of records.

### 2. Paper Intelligence Layer

This extends paper storage into structured research understanding.

It should represent at least:

- metadata
- structured paper card
- method summary
- task and setting
- datasets and metrics
- key contributions
- limitations
- relevance to current topic
- citation snippets
- related baseline tags

Why it matters:

This turns literature review into reusable project infrastructure.

### 3. Claim-Evidence Graph

This should become a signature asset of the product.

Core objects:

- claim
- supporting paper note
- supporting experiment result
- supporting figure or table
- draft section reference
- confidence or support status

Why it matters:

This is the mechanism that connects reading, experimentation, and writing.

### 4. Experiment Registry

This should exist even if execution happens outside the system.

Core fields:

- experiment id
- hypothesis linkage
- dataset
- baseline set
- config summary
- run status
- metrics
- artifact locations
- comparison notes
- linked table or figure

Why it matters:

Most research projects lose time not from running experiments, but from failing to compare and reuse them correctly.

### 5. Writing Workspace

This is not a generic editor. It is a research drafting surface.

It should support:

- outline objects
- section-level status
- draft text with provenance hooks
- citation suggestions from local knowledge
- unsupported-claim detection
- section completeness checks

Why it matters:

Writing is where the entire project must come together. The system should make that integration explicit.

### 6. Built-In Research Assistant

The built-in agent should be designed around specific high-value actions:

- summarize this paper for my topic
- compare these methods
- identify likely baselines for this claim
- draft related work bullets
- identify missing evidence in this section
- suggest next experiments
- rewrite this paragraph to align with available evidence

Why it matters:

Users get leverage from a focused assistant. They do not need a vague autonomous scientist.

## Data Model Recommendations

The following product objects should be treated as first-class records.

### Topic

Fields:

- topic_id
- title
- target_venue
- objective
- status
- primary_question
- constraints
- created_at
- updated_at

### Claim

Fields:

- claim_id
- topic_id
- text
- claim_type such as novelty, empirical, efficiency, or analysis
- status such as candidate, supported, weak, rejected
- owner
- notes

### Evidence Link

Fields:

- evidence_link_id
- claim_id
- source_type such as paper_note, experiment_run, figure, table, draft_section
- source_id
- support_strength
- rationale

### Experiment

Fields:

- experiment_id
- topic_id
- hypothesis
- purpose
- status
- metric_targets
- linked_claim_ids

### Run

Fields:

- run_id
- experiment_id
- config_hash
- seed
- artifact_path
- metrics
- notes
- commit_or_version
- executed_at

### Draft Section

Fields:

- section_id
- topic_id
- section_name
- version
- content
- status
- linked_claim_ids
- linked_citation_note_ids

### Paper Note

Fields:

- note_id
- paper_id
- topic_id
- note_type
- content
- structured_tags
- source
- confidence

## What the Built-In Agent Should Do

Recommended built-in agent responsibilities:

- convert raw search results into structured reading queues
- draft paper cards and topic-aware notes
- rank papers for a topic or claim
- generate comparison matrices across papers
- convert notes into candidate claims
- convert hypotheses into experiment checklists
- convert results into table-ready summaries
- convert evidence into outline candidates
- detect unsupported draft statements
- suggest missing baselines or missing ablations

This is enough to create major value without pretending the agent can autonomously finish the entire research process.

## What the Built-In Agent Should Not Own

To keep the product credible and controllable, the built-in agent should not be the final authority on:

- topic selection
- acceptance of research claims
- novelty judgment at submission standard
- final baseline sufficiency
- final paper framing
- final submission readiness

The system can support these decisions, but should not silently make them.

## Success Criteria For a Strong Standalone Product

If the product is working well without external coding agents, a user should be able to:

1. Start with a vague topic idea and quickly form a structured workspace.
2. Build a literature map without losing track of why papers matter.
3. Maintain a stable set of candidate claims and see which ones have evidence.
4. Track experiments in a way that supports reproducibility and paper writing.
5. Draft sections that are grounded in literature and results rather than memory.
6. See a clear next step at every stage of the project.

That is already a strong and defensible product.

## Roadmap Recommendation

A practical roadmap for standalone value is:

### Phase 1: Research State Discipline

Priority:

- topic workspace
- paper ingest and note system
- task and review workflow
- search and provenance logging

Goal:

- stop research state from fragmenting

### Phase 2: Paper Intelligence

Priority:

- stronger paper cards
- paper comparison views
- baseline and limitation extraction
- topic-aware reranking and retrieval

Goal:

- turn paper storage into research understanding

### Phase 3: Claim-Evidence Layer

Priority:

- claim records
- evidence links
- support status
- draft support warnings

Goal:

- connect reading, experimentation, and writing

### Phase 4: Experiment Registry

Priority:

- experiment definitions
- run logging
- metric comparison
- artifact linkage
- table and figure traceability

Goal:

- make experiments reusable and defensible

### Phase 5: Drafting Workspace

Priority:

- outline objects
- evidence-backed drafting
- citation suggestions
- consistency and completeness checks

Goal:

- turn evidence into a paper draft without losing provenance

### Phase 6: Guided Research Assistant

Priority:

- high-value assistant tasks tied to structured records
- workflow-aware next-step suggestions
- consistency and risk reviews

Goal:

- add agent leverage on top of a strong operating system

## Implication For Near-Term Development

In the near term, the most valuable strategic move is not to chase maximum autonomy.
It is to make the product's core records richer and better connected.

Concrete implications:

- strengthen topic and project records before building more free-form agent flows
- treat claim and evidence objects as first-class schema, not derived text blobs
- make experiment and draft linkage explicit
- ensure every agent-generated artifact can be attached to structured state
- optimize the built-in agent for research operations, not broad general intelligence behavior

## Final Recommendation

The cleanest way to maximize `research-harness` as a standalone product is:

> Build it as the operating system for a research project, with a built-in assistant that accelerates structured work, rather than an agent that tries to replace the researcher.

That gives the system value in three different futures:

- without Codex or Claude Code
- alongside Codex or Claude Code
- with stronger built-in agents later

In all three cases, the durable asset remains the same:

- structured research state
- explicit provenance
- evidence-linked workflows
- a stable path from idea to submission
