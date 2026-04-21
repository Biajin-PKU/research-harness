# Research Harness Design

Updated: 2026-04-03

## Purpose

This document defines the architecture of the Research Harness — a domain-specific agent orchestration layer for research workflows. It serves two roles:

1. **Product component**: A lightweight, low-cost alternative to Claude Code for research-specific tasks within research-harness.
2. **Paper contribution**: A novel harness architecture demonstrating that domain-specific orchestration + lightweight models can match general-purpose agent performance in research workflows.

Users choose their execution backend:

```
research-harness
├── Core (data model, state, CLI)
├── Research Primitives (paper_search, claim_extract, evidence_link ...)
└── Execution Layer (user selects)
    ├── Research Harness (task-aware routing, Kimi default, evidence-gated)
    └── Claude Code (general purpose, higher cost)
```

Both backends implement the same `ExecutionBackend` interface; upper layers are agnostic.

---

## Reference Project Analysis

Three open-source projects were studied for harness engineering patterns. None is used directly — each contributes specific design ideas that are adapted for research workflows.

### Reference 1: claw-code-main

**What it is**: An independent agent harness with both Rust (production binary) and Python (clean-room port) implementations. Built to study harness engineering patterns.

**Architecture summary**:

| Layer | Rust crate | Key abstraction |
|-------|-----------|-----------------|
| Provider routing | `api/providers/mod.rs` | `Provider` trait + `MODEL_REGISTRY` static map; `detect_provider_kind()` fallback chain (model name → env vars → defaults) |
| Turn loop | `runtime/conversation.rs` | `ConversationRuntime<C: ApiClient, T: ToolExecutor>` — generic composition; loops until model stops calling tools |
| Tool system | `tools/lib.rs` | `ToolSpec` (name, description, input_schema, required_permission) + `ToolRegistry` manifest |
| Hook interception | `plugins/hooks.rs` | `HookRunner` with Pre/PostToolUse; hooks are subprocess commands receiving JSON on stdin; exit code 0=allow, 2=deny |
| Session | Python `session_store.py` | `StoredSession` (frozen dataclass) persisted to `.port_sessions/{id}.json` |

**Python harness details** (in `src/`):

- `PortRuntime` — orchestrates routing + bootstrap + turn loop
  - `route_prompt()`: tokenizes prompt, scores against command/tool registries by name/hint overlap
  - `bootstrap_session()`: context → setup → route → execute → persist → return `RuntimeSession`
  - `run_turn_loop()`: multi-turn with `stop_reason` checking (completed / max_turns / max_budget)
- `QueryEnginePort` — session management + turn submission
  - `QueryEngineConfig`: max_turns=8, max_budget_tokens=2000, compact_after_turns=12
  - `submit_message()` → `TurnResult` with usage tracking and compaction
  - `stream_submit_message()` → SSE-like event generator
  - `persist_session()` → JSON serialization
- `ExecutionRegistry` — wraps commands/tools as `MirroredCommand`/`MirroredTool` with `.execute()` shims
- `TranscriptStore` — append-only conversation history with `.compact(keep_last=N)`
- `ToolPermissionContext` — deny by name or prefix, used for gating destructive tools
- `CostTracker` — mutable event log with `record(label, units)`
- `BootstrapGraph` — 7-stage startup pipeline (prefetch → env guards → CLI parse → setup → deferred init → mode routing → query loop)
- 31 subsystem packages, each with JSON snapshot metadata (archive_name, module_count, sample_files)
- Reference data: `commands_snapshot.json` (207 entries), `tools_snapshot.json` (184 entries)

**Provider routing (Rust)**:
- `ProviderKind` enum: ClawApi, Xai, OpenAi
- `ProviderMetadata`: provider + auth_env + base_url_env
- `resolve_model_alias()` maps short names ("opus" → "claude-opus-4-6")
- `detect_provider_kind()` fallback: explicit model → env credentials → default
- Supports custom base URLs via env vars

**What we take**: Provider trait pattern, turn loop composition, session persistence, permission gating concept, bootstrap pipeline pattern.

**What we change**: Turn loop termination (evidence gate, not tool exhaustion), routing dimension (research task type, not model name), permission model (stage gates, not tool deny-lists).

---

### Reference 2: claude-code-main

**What it is**: A Python porting workspace that documents Claude Code's internal architecture. Not a runnable harness — a structural reference showing how Claude Code organizes its subsystems.

**Architecture summary**:

The project mirrors Claude Code's module structure through metadata and snapshot registries:

- `PortManifest` — scans Python file tree, counts modules, generates structural report
- `PortingModule` (frozen dataclass) — name, responsibility, source_hint (original TS path), status
- `PortingBacklog` — tracks which modules are planned/implemented/mirrored
- `ParityAuditResult` — compares Python port coverage against TypeScript archive
  - 18 root file mappings (TS → PY)
  - 31 directory mappings
  - Produces coverage ratios and missing-target lists
- Command/tool registries loaded from JSON snapshots (`commands_snapshot.json`: 207 entries, `tools_snapshot.json`: 184 entries)
- `CommandGraph` — segments commands into builtins / plugin_like / skill_like based on source_hint patterns
- Bootstrap stages documented: prefetch → env guards → CLI → setup → deferred init → mode routing → query loop
- `WorkspaceSetup` — captures Python version, platform, test command
- `SetupReport` — prefetch results + deferred init status + trust gate
- `ProjectOnboardingState` — has_readme, has_tests, python_first flags

**CLI subcommands** (30+ commands organized as):
- Informational: summary, manifest, parity-audit, setup-report, command-graph, tool-pool, bootstrap-graph, subsystems, commands, tools
- Execution: route, bootstrap, turn-loop, flush-transcript, load-session
- Remote modes: remote-mode, ssh-mode, teleport-mode, direct-connect, deep-link
- Inspection: show-command, show-tool, exec-command, exec-tool

**What we take**: JSON-snapshot registry pattern for research primitives, parity audit methodology (can measure our harness vs Claude Code capability coverage), bootstrap stage pipeline design, command segmentation (builtins vs plugins vs skills → our: core primitives vs domain skills vs user extensions).

**What we change**: Registry content (research ops not file I/O), parity targets (research task coverage not TS module coverage), onboarding (topic context loading not project detection).

---

### Reference 3: everything-claude-code (ECC)

**What it is**: A production plugin ecosystem for Claude Code (v1.8.0, 997 tests, 50K+ stars). Provides skills, agents, commands, hooks, rules, and MCP configs.

**Architecture summary**:

| Component | Count | Format | Purpose |
|-----------|-------|--------|---------|
| Skills | 65+ | `SKILL.md` with YAML frontmatter | Domain knowledge injection |
| Agents | 13 | `.md` with YAML (name, tools, model) | Specialized subagent roles |
| Commands | 40 | `.md` with description frontmatter | User-invocable workflows |
| Hooks | 6 events | `hooks.json` + JS scripts | Lifecycle automation |
| Rules | layered | `common/` + language dirs | Constraint enforcement |
| MCP configs | 14 | JSON | External tool integration |

**Key patterns extracted**:

1. **Cost-aware LLM pipeline** (`skills/cost-aware-llm-pipeline/SKILL.md`):
   - Routes by task complexity thresholds (text_length >= 10K → Sonnet, else Haiku)
   - Immutable cost tracking with frozen dataclasses
   - Prompt caching for repeated system prompts
   - Budget guardrails with narrow retry logic

2. **Iterative retrieval** (`skills/iterative-retrieval/SKILL.md`):
   - 4-phase cycle: DISPATCH (broad query) → EVALUATE (relevance scoring) → REFINE (update criteria) → LOOP
   - Terminates when high-relevance context reaches threshold (3+ items at 0.7+ relevance)
   - Learns domain terminology in first cycle, refines in subsequent cycles
   - Max 3 cycles to bound cost

3. **Autonomous loops** (`skills/autonomous-loops/SKILL.md`):
   - Sequential pipeline: break into steps, each fresh context
   - NanoClaw REPL: session persistence + skill hot-loading
   - De-sloppify: separate drafting pass from cleanup pass (positive instruction to cleanup agent)
   - Ralphinho/RFC-DAG: decompose spec into dependency DAG, parallel execution, eviction + context management

4. **NanoClaw REPL** (`scripts/claw.js`):
   - ~300 lines, zero external dependencies
   - Orchestrates via `spawnSync('claude', ['-p', prompt, '--model', model])`
   - Session persistence as Markdown files (`~/.claude/claw/{session}.md`)
   - Skill hot-loading: reads `SKILL.md` files into system prompt
   - Commands: `/search`, `/branch`, `/compact`, `/export`
   - Model selection via `CLAW_MODEL` env var

5. **Hook system** (`hooks/hooks.json`):
   - Events: PreToolUse, PostToolUse, PreCompact, SessionStart, Stop, SessionEnd
   - Each hook: matcher (tool name or `*`) + command (shell) + optional async/timeout
   - Profiles: minimal/standard/strict via `ECC_HOOK_PROFILE`
   - Scripts in `scripts/hooks/`: session-start.js, session-end.js, quality-gate.js, post-edit-format.js, evaluate-session.js, cost-tracker.js

6. **Agent definitions** (YAML frontmatter pattern):
   - Role + constrained tool list + model tier + structured process
   - Example: planner (Read/Grep/Glob only), code-reviewer (Read/Grep/Glob/Bash), architect (Read/Grep/Glob)
   - Severity tiers: CRITICAL/HIGH/MEDIUM/LOW
   - Confidence thresholds: "Only report issues >80% confident"

**What we take**: Skill definition format (SKILL.md + frontmatter), hook lifecycle model (6 events), iterative retrieval cycle pattern, autonomous loop architecture choices, cost tracking methodology, agent role definition format.

**What we change**: Skills are research-domain (literature analysis, methodology critique, not coding patterns). Hooks include mandatory provenance recording. Iterative retrieval terminates on literature coverage metrics not file relevance. Loop pipeline is evidence-gated stages not CI/CD cycles. Agents are research roles (synthesizer, critic, literature mapper) not coding roles.

**Limitation**: ECC cannot run without Claude Code CLI as host. Not suitable as standalone harness foundation.

---

## Material Extraction Summary

| Material | Source | Our adaptation |
|----------|--------|---------------|
| Provider trait + registry | claw-code Rust | Route by research task semantics, not model name |
| Turn loop composition | claw-code Rust | Terminate on evidence gate, not tool exhaustion |
| Session persistence | claw-code Python | Add branch/merge for investigation threads |
| Permission gating | claw-code Python | Replace tool deny-list with stage gate criteria |
| Bootstrap pipeline | claw-code Python + claude-code-main | Load topic context + paper library at startup |
| JSON snapshot registry | claude-code-main | Register research primitives, not coding tools |
| Parity audit | claude-code-main | Measure harness vs Claude Code research task coverage |
| Command segmentation | claude-code-main | Core primitives / domain skills / user extensions |
| Skill definition format | ECC | Research-domain SKILL.md (literature analysis, etc.) |
| Hook lifecycle | ECC | Add provenance hook as mandatory, not optional |
| Iterative retrieval | ECC | Literature coverage metrics as termination condition |
| Autonomous loop patterns | ECC | Evidence-gated pipeline stages |
| Cost-aware routing | ECC | Route by research stage semantics, not token count |
| Agent role format | ECC | Research roles (synthesizer, critic, mapper) |

---

## Innovation Layer (Not From Any Reference)

These are the novel contributions that differentiate Research Harness from general-purpose agent harnesses:

### 1. Research Task Taxonomy

A classification of research workflow tasks by model capability requirements, derived empirically from real research usage (Phase 2 dogfooding):

```python
TASK_TAXONOMY = {
    # Category: (default_provider, reasoning_depth, context_need)
    "retrieval":      ("kimi",   "low",    "low"),     # paper_search, keyword expansion
    "comprehension":  ("kimi",   "medium", "high"),    # paper_summarize, section extract
    "extraction":     ("kimi",   "medium", "medium"),  # claim_extract, baseline_identify
    "analysis":       ("sonnet", "high",   "high"),    # gap_detect, method_compare
    "synthesis":      ("opus",   "high",   "high"),    # hypothesis_gen, cross-paper synthesis
    "generation":     ("sonnet", "medium", "medium"),  # section_draft, outline_gen
    "verification":   ("opus",   "high",   "high"),    # consistency_check, novelty_assess
}
```

**Paper contribution**: Empirical evidence that research tasks cluster into categories with distinct model requirements, enabling cost-efficient routing.

### 2. Evidence-Gated Pipeline

Stage progression controlled by evidence sufficiency, not turn count or tool exhaustion:

```python
STAGE_GATES = {
    "literature_mapping": {
        "min_papers": 20,
        "min_high_relevance": 5,
        "required_categories": ["baseline", "method", "evaluation"],
    },
    "claim_formation": {
        "min_claims": 3,
        "min_supported_claims": 1,
        "max_unsupported_ratio": 0.5,
    },
    "method_planning": {
        "min_baseline_coverage": 0.8,
        "required_fields": ["dataset", "metric", "hypothesis"],
    },
    "drafting": {
        "required_sections": ["introduction", "related_work", "method"],
        "min_evidence_per_claim": 2,
        "min_citation_coverage": 0.8,
    },
}
```

Gate mode switch:
- `manual`: pause for human approval (product mode)
- `auto`: agent evaluates gate criteria, logs rationale (paper demo mode)

**Paper contribution**: Evidence-gated orchestration as an alternative to turn-limited or tool-exhaustion loops.

### 3. Research Primitives

Native research operations replacing generic file I/O tools:

```
paper_search(query, filters) -> list[PaperRef]
paper_ingest(source) -> PaperRecord
paper_summarize(paper_id, focus) -> Summary
claim_extract(paper_ids, topic) -> list[Claim]
evidence_link(claim_id, source_type, source_id) -> EvidenceLink
gap_detect(topic_id) -> list[Gap]
baseline_identify(topic_id) -> list[Baseline]
method_compare(paper_ids, dimensions) -> ComparisonMatrix
section_draft(section, evidence_ids) -> DraftText
consistency_check(draft_sections) -> list[Issue]
novelty_assess(claims, literature) -> NoveltyReport
```

These map directly to research-harness core APIs — the harness calls structured operations, not arbitrary shell commands.

**Paper contribution**: Domain-specific tool vocabulary that constrains agent behavior to valid research operations.

### 4. Provenance-First Design

Every harness operation automatically records:

```python
@dataclass(frozen=True)
class ProvenanceRecord:
    operation: str           # research primitive name
    timestamp: str
    backend: str             # "research_harness" or "claude_code"
    model: str               # actual model used
    task_category: str       # from taxonomy
    input_hash: str          # SHA256 of input
    output_hash: str         # SHA256 of output
    cost: float              # API cost in USD
    stage: str               # current pipeline stage
    topic_id: str
    parent_record_id: str | None  # chain provenance
```

Not optional logging — provenance is a mandatory hook that fires on every primitive execution.

**Paper contribution**: Provenance as a first-class architectural concern enabling reproducibility and cost analysis.

### 5. Investigation Thread

Sessions that support branching and merging for hypothesis exploration:

```
main thread: literature review on auto-bidding
  ├── branch: "explore reinforcement learning approaches"
  │   └── findings merged back with confidence scores
  ├── branch: "explore game-theoretic approaches"
  │   └── branch abandoned (low relevance)
  └── continues with merged findings
```

**Paper contribution**: Structured exploration with branch/merge semantics, enabling systematic hypothesis testing.

### 6. Dual-Mode Gate System

Same architecture, different autonomy levels:

```python
class GateMode(Enum):
    MANUAL = "manual"   # Human approves stage transitions
    AUTO = "auto"       # Agent evaluates criteria, logs rationale

class StageGate:
    mode: GateMode
    criteria: dict

    def evaluate(self, state: ResearchState) -> GateResult:
        result = self._check_criteria(state)
        if self.mode == GateMode.AUTO:
            result.rationale = self._generate_rationale(state)
        return result
```

**Paper contribution**: Demonstrates that human-in-the-loop and fully autonomous are configuration choices on the same architecture, not different systems.

### 7. Adversarial Convergence Protocol

Critical research decisions (innovation planning, experiment design, paper architecture, section writing) are resolved through a two-agent adversarial process instead of fixed-role review (reviewer/advisor).

**Why not fixed roles?**
- Fixed roles have authority bias — "reviewer" always criticizes, "advisor" always directs
- Adversarial peers must *persuade*, not *dictate* — argument quality drives convergence
- Both agents improve: Proposer anticipates challenges → stronger initial plan; Challenger must give specific objections → no rubber-stamping

**Protocol:**

```python
@dataclass(frozen=True)
class Objection:
    """A specific challenge raised by the Challenger agent."""
    target: str              # which part of the proposal
    severity: str            # "critical" | "major" | "minor"
    reasoning: str           # why this is a problem
    suggested_fix: str       # constructive alternative (required)

@dataclass(frozen=True)
class Resolution:
    """Outcome of an adversarial round."""
    proposal_version: int
    objections_raised: list[Objection]
    objections_addressed: list[str]   # objection indices resolved
    objections_rebutted: list[str]    # objection indices rebutted with justification
    converged: bool
    final_text: str

class AdversarialProtocol:
    """Two-agent dialectical resolution for critical research decisions.

    Neither agent has a privileged role — both are peers.
    Convergence requires mutual agreement, not authority override.
    """

    max_rounds: int = 5

    APPLICABLE_STAGES = [
        "innovation_planning",    # "Is this really a gap?"
        "experiment_design",      # "Can this experiment prove the claim?"
        "paper_architecture",     # "Is the related work coverage complete?"
        "section_writing",        # "Does this argument hold logically?"
    ]

    # NOT applicable (mechanical tasks, no judgment needed):
    # literature_search, paper_ingest, bibtex_management

    def resolve(self, task: str, context: dict) -> Resolution:
        """
        Round 1: Proposer generates plan/draft from context
        Round 2: Challenger critiques — must raise specific Objections
                 (each Objection requires a suggested_fix — no empty criticism)
        Round 3: Proposer addresses each objection:
                 - Accept + revise, OR
                 - Rebut with specific counter-argument
        Round 4: Challenger re-evaluates revised proposal + rebuttals
                 - Drop resolved objections
                 - Maintain or escalate unresolved ones
        ...repeat until convergence

        Convergence criteria (ALL must be true):
        - No "critical" severity objections remaining
        - All raised objections either addressed or rebutted
        - Challenger explicitly agrees (not just runs out of objections)

        Termination:
        - Converged → return final agreed version
        - max_rounds reached → return last version + unresolved objections
          (escalate to human for manual resolution)
        """
        ...
```

**Key design choices:**
1. **Challenger must propose fixes, not just criticize** — prevents the "I don't like it but I don't know why" trap
2. **Proposer can rebut, not just comply** — prevents over-correction from invalid objections
3. **No voting, no scoring** — convergence is argumentative, not numerical
4. **All rounds recorded in provenance** — every objection, rebuttal, and revision is traceable
5. **Escalation path** — if agents can't converge in max_rounds, human decides (this is the `manual` gate mode)

**Relation to Dual-Mode Gate System:**
- `auto` gate mode = adversarial convergence resolves the gate
- `manual` gate mode = human resolves after seeing the adversarial transcript

**Paper contribution**: Peer-adversarial convergence as a quality mechanism for autonomous research workflows — distinct from role-based review (AutoGPT/MetaGPT) and phase-gated review (ChatDev). Quality is driven by argument strength, not authority.

---

## Route 2: Claude Code Extensions Architecture (Active)

**Pivot (Session 3):** Instead of building a standalone `research_harness` REPL, we implement all innovations as Claude Code extensions. The existing `research_harness` package (primitives, provenance, execution backends) is preserved unchanged.

### Innovation → Extension Mapping

| Innovation | Extension Type | Location |
|-----------|---------------|----------|
| Research Task Taxonomy | MCP Server (internal routing) | `packages/research_harness_mcp/tools.py` |
| Evidence-Gated Pipeline | Skill | `.claude/skills/evidence-gating/SKILL.md` |
| Research Primitives | MCP Tools | `packages/research_harness_mcp/tools.py` |
| Provenance-First | Hook (PostToolUse) | `.claude/hooks/record-provenance.py` |
| Investigation Thread | Storage layer | `research_harness/storage/` (branch/merge on topics) |
| Adversarial Convergence | Agents | `.claude/agents/adversarial-resolver.md` |
| Dual-Mode Gates | Skill config | `.claude/skills/evidence-gating/SKILL.md` |

### Extension Architecture

```
Claude Code REPL
  ├── Skills (.claude/skills/)        — 8 research domain skills
  ├── Agents (.claude/agents/)        — 5 research agents
  ├── Hooks (.claude/hooks/)          — provenance + cost tracking
  └── MCP Server (research-harness)       — stdio transport
        ├── Primitive tools            — 9 ops from PRIMITIVE_REGISTRY
        ├── Convenience tools          — topic/paper/task/provenance queries
        ├── Paperindex tools           — PDF search/structure/cards
        └── Internal routing           — ROUTING_TABLE → LLMClient dispatch
              └── paperindex LLMClient — Kimi / Anthropic / OpenAI
```

### ExecutionBackend Interface (Preserved)

```python
class ExecutionBackend(Protocol):
    def execute(self, primitive: str, **kwargs) -> PrimitiveResult: ...
    def get_info(self) -> BackendInfo: ...
    def estimate_cost(self, primitive: str, **kwargs) -> float: ...
    def supports(self, primitive: str) -> bool: ...
```

Three backends: `LocalBackend`, `ResearchHarnessBackend`, `ClaudeCodeBackend` (composite).

---

## Module Architecture (Superseded)

<details>
<summary>Original standalone architecture (Route 1, abandoned)</summary>

The original plan was to build `packages/research_harness/` as a standalone REPL. This was abandoned in Session 3 in favor of Claude Code extensions. The design below is preserved for reference only.

```
packages/research_harness/   # ABANDONED — not being built
├── harness.py, router.py, pipeline.py, providers/, primitives/,
│   hooks/, session/, adversarial/, skills/, audit/
```

</details>

research-harness core calls the ExecutionBackend interface without knowing which backend is active.

---

## Evaluation Design (For Paper)

### Primary comparison

| Dimension | Research Harness + Kimi | Claude Code (Opus) |
|-----------|------------------------|-------------------|
| Cost | Measured per stage | Baseline |
| Quality | Blind human evaluation (1-5) | Baseline |
| Coverage | Claim-evidence graph density | Baseline |
| Time | Wall-clock per stage | Baseline |

### Ablation studies

1. Research Harness with task-aware routing vs. all-Kimi vs. all-Opus
2. Evidence-gated pipeline vs. fixed-step pipeline
3. With provenance tracking vs. without (researcher efficiency)

### Evaluation cases

- **S2 (auto-bidding)**: Real research topic, replay Phase 2 tasks on both backends
- **S3 (harness paper)**: Meta-case, the harness paper itself produced using the system
