# Research Harness Development Roadmap

Updated: 2026-04-03

## Context

Three parallel work streams running on one system:

| Stream | Role | Dependency |
|--------|------|------------|
| **S1: System Development** | Build research-harness + Research Harness | Foundation for S2, S3 |
| **S2: Auto-Bidding Paper** | Real research topic, validates system as user | Needs S1 core functional |
| **S3: Research Harness Paper** | Meta-paper about the system itself | Needs S1 complete + S2 as second evaluation case |

Key constraint: S2 and S3 are not sequential — they interleave with S1, and S2's usage experience directly feeds S1's design decisions.

## Design Principles

1. **Dogfooding-first**: Every system feature must be validated through real research use (S2/S3) before being considered complete.
2. **Baseline-then-compare**: S2 runs first on Claude Code (generates baseline data), then replays on Research Harness (generates comparison data for S3).
3. **Incremental release**: Each phase produces a usable state; no phase depends on a future phase being complete.
4. **Dual execution path**: System architecture always supports both Claude Code and Research Harness as execution layers.

## Phase Overview

```
Phase 1 (Foundation)     ──── System core stable, Claude Code as execution layer
  │
Phase 2 (Dogfooding)     ──── Start S2 (auto-bidding) via Claude Code, log everything
  │                            Start S3 literature review via Claude Code
  │
Phase 3 (Harness Build)  ──── Build Research Harness informed by Phase 2 usage patterns
  │
Phase 4 (Validation)     ──── Replay S2 key tasks on Research Harness, collect comparison
  │                            Complete S2 paper drafting
  │
Phase 5 (Paper Assembly) ──── Complete S3 paper with evaluation data from Phase 2 vs 4
```

---

## Phase 1: Foundation

**Goal**: research-harness core stable enough for daily research use with Claude Code.

### 1.1 Core System Hardening

- [ ] Full test suite green (paperindex + research_harness)
- [ ] Topic workspace CRUD complete (init, show, list, status)
- [ ] Paper lifecycle complete (ingest → annotate → card → note → queue)
- [ ] Task tracker functional (generate, add, status, list)
- [ ] Review gate system working (add, list, check readiness)
- [ ] Search provenance logging operational

### 1.2 Execution Layer Abstraction

- [ ] Define `ExecutionBackend` interface (protocol/abstract class)
  - `execute_research_task(task: ResearchTask) -> TaskResult`
  - `route_model(task_type: str) -> ModelConfig`
  - `get_capabilities() -> list[str]`
- [ ] Implement `ClaudeCodeBackend` (delegates to Claude Code via CLI/MCP)
- [ ] Stub `ResearchHarnessBackend` (interface only, Phase 3 fills it)
- [ ] Config switch: `execution.backend: claude-code | research-harness`

### 1.3 Research Primitives Definition

Define the tool vocabulary that both backends must support:

```
paper_search(query, filters) -> list[PaperRef]
paper_ingest(source) -> PaperRecord
paper_summarize(paper_id, focus) -> Summary
claim_extract(paper_ids, topic) -> list[Claim]
evidence_link(claim_id, source_type, source_id) -> EvidenceLink
gap_detect(topic_id) -> list[Gap]
baseline_identify(topic_id) -> list[Baseline]
section_draft(section, evidence_ids) -> DraftText
consistency_check(draft_sections) -> list[Issue]
```

### 1.4 Provenance System

- [ ] Every research primitive call logged with: timestamp, backend, model, input hash, output hash
- [ ] Provenance records stored in DB alongside research state
- [ ] `rhub provenance show <entity-id>` — trace any claim/note/draft back to source

**Exit criteria**: Can run `rhub topic init`, ingest 5+ papers, generate tasks, run review gates — all via Claude Code.

---

## Phase 2: Dogfooding with Claude Code

**Goal**: Do real research on two topics, generating baseline data and usage feedback.

### 2.1 Auto-Bidding Research (S2)

Execute the full research workflow on auto-bidding:

```
Stage 1: Topic init (auto-bidding, target venue)
Stage 2: Literature mapping (50+ papers via MCP search tools)
Stage 3: Research question formation
Stage 4: Method planning
Stage 5: Experiment planning
--- (Stages 6-9 after Phase 4) ---
```

During this work:
- Use Claude Code as the execution layer exclusively
- Log all provenance (which model, which tool, cost, time)
- Record pain points and feature gaps in `docs/dogfooding_log.md`
- Note which tasks feel "overkill" for Claude Opus (candidates for Kimi routing)

### 2.2 Research Harness Literature Review (S3)

Start S3's literature work in parallel:

- Survey existing agent harness / orchestration frameworks
- Survey multi-model routing literature
- Survey research automation systems
- Build paper pool and literature map within research-harness

### 2.3 Feedback Loop

After 2-3 weeks of dogfooding:

- [ ] Categorize all research tasks by complexity tier (lightweight / medium / heavyweight)
- [ ] Identify which tasks Kimi could handle (Phase 3 routing table)
- [ ] Document Stage gate criteria that emerged from real usage
- [ ] List research primitives that are missing or need refinement

**Exit criteria**: S2 through Stage 5, S3 literature map complete, task complexity taxonomy documented.

---

## Phase 3: Claude Code Extensions Build ✅ COMPLETE

**Goal**: Build Claude Code extensions (MCP server, skills, agents, hooks) informed by Phase 2 patterns.

**Status**: **COMPLETE** (2026-04-03)
- MCP Server: 9 primitives + convenience tools + paperindex tools
- Skills: 10 research domain skills
- Agents: 5 research agents
- Hooks: provenance + cost tracking
- Tests: 154 passing

**Architecture change (Session 3 pivot):** Instead of building a standalone `research_harness` REPL package, we extend Claude Code itself. All 7 innovation points are implemented as domain-layer extensions, not infrastructure. See `docs/research_harness_design.md` Route 2 section.

### 3.1 MCP Server

Module: `packages/research_harness_mcp/`

```
research_harness_mcp/
├── __init__.py
├── pyproject.toml
├── server.py               # MCP server (stdio transport)
├── tools.py                # Tool definitions + execution
└── tests/
    └── test_tools.py
```

Exposes three categories of MCP tools:
1. **Primitive tools** — 9 operations from `PRIMITIVE_REGISTRY` (paper_search, claim_extract, etc.)
2. **Convenience tools** — topic/paper/task/provenance queries
3. **Paperindex tools** — PDF search, structure extraction, card building

Multi-model routing handled **inside** the MCP server using `paperindex.llm.client.LLMClient`. Claude Code sees only tool names.

### 3.2 Task-Aware Model Router (inside MCP Server)

```python
ROUTING_TABLE = {
    # task_type        → (default_model, fallback_model, rationale)
    "paper_search":      ("kimi",    None,     "keyword expansion, low reasoning"),
    "paper_summarize":   ("kimi",    None,     "long context strength, low cost"),
    "claim_extract":     ("kimi",    "sonnet", "structured extraction"),
    "baseline_identify": ("kimi",    "sonnet", "comparative analysis"),
    "gap_detect":        ("sonnet",  "opus",   "cross-paper reasoning"),
    "hypothesis_gen":    ("opus",    None,     "creative + deep reasoning"),
    "section_draft":     ("sonnet",  None,     "fluent writing, medium reasoning"),
    "consistency_check": ("opus",    None,     "full-document reasoning"),
    "evidence_link":     ("kimi",    None,     "structured matching"),
}
```

Key innovation: routing is **not by token count or generic complexity**, but by **research task semantics** derived from Phase 2's empirical categorization.

### 3.3 Skills, Agents, Hooks

```
.claude/
├── skills/                              # 8 research domain skills
│   ├── literature-mapping/SKILL.md
│   ├── claim-extraction/SKILL.md
│   ├── gap-analysis/SKILL.md
│   ├── section-drafting/SKILL.md
│   ├── evidence-gating/SKILL.md         # encodes STAGE_GATES criteria
│   ├── task-taxonomy/SKILL.md           # encodes ROUTING_TABLE
│   ├── research-primitives/SKILL.md
│   └── provenance-review/SKILL.md
├── agents/                              # 5 research agents
│   ├── proposer.md
│   ├── challenger.md
│   ├── adversarial-resolver.md
│   ├── literature-mapper.md
│   └── synthesizer.md
└── hooks/                               # provenance + cost tracking
    ├── hooks.json
    ├── record-provenance.py
    ├── cost-tracker.py
    └── session-summary.py
```

Evidence-gating criteria (encoded in `evidence-gating/SKILL.md`):
- `literature_mapping`: min_papers=20, min_high_relevance=5
- `claim_formation`: min_claims=3, min_supported_claims=1
- `drafting`: min_evidence_per_claim=2, min_citation_coverage=0.8

Gate mode: `manual` (product default) or `auto` (paper demo mode).

### 3.4 ClaudeCodeBackend (Complete)

- Fulfills the `ExecutionBackend` interface from Phase 1.2
- Routes each research primitive through the task-aware router
- Wraps results in provenance records
- Evaluates stage gates after each primitive batch

**Exit criteria**: Research Harness can independently run Stages 1-3 of a new topic without Claude Code.

---

## Phase 4: Validation & Comparison

**Goal**: Generate the evaluation data for S3 paper.

### 4.1 Replay Experiment

Take the S2 (auto-bidding) task log from Phase 2 and replay key stages through Research Harness:

| Stage | Claude Code (Phase 2) | Research Harness (Phase 4) |
|-------|----------------------|---------------------------|
| Literature search | Logged: model, cost, time, quality | Re-run: same queries, Kimi routing |
| Paper summarization | Logged | Re-run |
| Gap analysis | Logged | Re-run |
| Claim extraction | Logged | Re-run |
| Section drafting | Logged | Re-run |

Metrics to collect:
- **Cost**: API spend per stage (USD)
- **Quality**: human evaluation (blind comparison, 1-5 scale)
- **Coverage**: evidence completeness (claim-evidence graph density)
- **Time**: wall-clock per stage

### 4.2 Complete S2 Paper

With both backends validated, finish S2 (auto-bidding) paper drafting through Stages 6-9:
- Can use either backend (user choice)
- Document which backend was used for which stage (itself a data point)

### 4.3 Ablation Studies (for S3)

- Research Harness with routing vs. Research Harness all-Kimi vs. Research Harness all-Opus
- Evidence-gated pipeline vs. fixed-step pipeline
- With provenance tracking vs. without (researcher efficiency comparison)

**Exit criteria**: Comparison data collected, S2 draft complete.

---

## Phase 5: Paper Assembly

**Goal**: Complete both papers.

### 5.1 S3: Research Harness Paper

Structure:

```
1. Introduction: research workflows need domain-specific orchestration
2. Related Work: agent harnesses, multi-model routing, research automation
3. System Design: Research Harness architecture (router, pipeline, primitives, provenance)
4. Research Task Taxonomy: empirical categorization from Phase 2
5. Evaluation:
   5.1 Cost comparison (Research Harness vs Claude Code)
   5.2 Quality comparison (blind evaluation)
   5.3 Ablation studies
   5.4 Case study: auto-bidding paper produced by the system
6. Discussion: when domain-specific harness wins, limitations
7. Conclusion
```

Target venue: TBD (ACL / EMNLP / CHI — depends on framing angle)

### 5.2 S2: Auto-Bidding Paper

Standard research paper, produced using the system. The system's provenance log serves as supplementary material for S3.

### 5.3 Cross-Validation

- S2 exists as an independent research paper AND as evaluation evidence for S3
- S3's claim "the system works" is directly supported by S2's existence

**Exit criteria**: Both papers submission-ready.

---

## Timeline Guidance

Not giving time estimates, but phase dependencies are strict:

```
Phase 1 ─────→ Phase 2 ─────→ Phase 3 ─────→ Phase 4 ─────→ Phase 5
                  │                               │
                  └── S2 Stages 1-5 ──────────────┘── S2 Stages 6-9
                  └── S3 Lit Review ──────────────────── S3 Paper
```

Phase 2 is the longest (real research work). Phases 1 and 3 are engineering sprints.

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Kimi quality insufficient for some tasks | Harness paper claim weakened | Routing table allows fallback to stronger model; report as finding |
| Auto-bidding paper not accepted | Lose one evaluation case | System still validated by harness paper's own production process |
| Harness vs Claude Code quality gap too large | Core claim fails | Adjust routing table (more tasks to Sonnet); reframe as "cost-quality tradeoff" |
| Scope creep in system features | Delays Phase 2 start | Phase 1 exit criteria are minimal; feature gaps logged, not fixed immediately |
| Provenance logging overhead slows research | User frustration | Make provenance async and non-blocking; can disable for interactive use |
