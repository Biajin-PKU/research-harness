# CODEX Phase 3: Claude Code Extensions

## Context

We pivoted from building a standalone Research Harness REPL to extending Claude Code with Skills, Agents, Hooks, and an MCP Server. Phase 3 creates the extension artifacts.

**Already completed (by Claude):**
- A1: `ClaudeCodeBackend` filled in (composite of Local + Harness)
- A2: `execution/__init__.py` exports updated
- A3: `CLAUDE.md` updated
- A4: Docs updated (roadmap, design, handoff)
- B1: MCP server scaffold created (`packages/research_harness_mcp/`)
- B2: MCP tools implemented with 10 tests passing
- B3: `.mcp.json` created

**Remaining (for Codex):**
- C1: Create 8 research domain skills
- D1: Create 5 research agents
- E1: Create hooks for provenance and cost tracking

## Safety Rules

1. **Do NOT modify** any file in `packages/research_harness/` or `packages/paperindex/`
2. **Do NOT modify** `packages/research_harness_mcp/` (already complete)
3. **All 151 tests must pass** after your changes: `python -m pytest packages/ -q --tb=short`
4. Only create files in `.claude/skills/`, `.claude/agents/`, `.claude/hooks/`
5. Follow YAML frontmatter format exactly as specified

## Read Before Coding

1. `docs/architecture/05_claude_code_extensions.md` — architecture overview
2. `docs/research_harness_design.md` — innovation points and stage gates
3. `packages/research_harness/research_harness/primitives/types.py` — PrimitiveCategory enum and all types
4. `packages/research_harness/research_harness/primitives/registry.py` — registered primitives
5. `packages/research_harness_mcp/research_harness_mcp/tools.py` — MCP tool names

## Task C1: Create 8 Research Domain Skills

Create `.claude/skills/` directory with 8 subdirectories, each containing a `SKILL.md`.

### Format

```yaml
---
name: skill-name
description: One-line description
allowed-tools: [tool1, tool2, ...]
---

# Skill Name

## When to Use
(trigger conditions)

## Process
(step-by-step using MCP tools and rhub CLI)

## Quality Checklist
(what to verify before completing)
```

### Skills to Create

**1. `.claude/skills/literature-mapping/SKILL.md`**
- Description: Systematic literature search and mapping workflow
- allowed-tools: `[mcp__research-harness__paper_search, mcp__research-harness__paper_ingest, mcp__research-harness__topic_list, mcp__research-harness__topic_show, Bash, Read]`
- When: User starts a new research topic or asks to find papers
- Process: (1) Use MCP academic search tools to find papers, (2) Ingest via `paper_ingest`, (3) Track coverage via `topic_show`, (4) Check evidence gate (min 20 papers, 5 high-relevance, categories covered)
- Quality: Coverage across baseline/method/evaluation categories

**2. `.claude/skills/claim-extraction/SKILL.md`**
- Description: Extract and organize research claims from ingested papers
- allowed-tools: `[mcp__research-harness__claim_extract, mcp__research-harness__paper_list, mcp__research-harness__evidence_link, Read]`
- When: Enough papers ingested, need to identify key claims
- Process: (1) List papers for topic, (2) Run `claim_extract`, (3) Link evidence, (4) Review claim quality
- Quality: Each claim has evidence, confidence > 0.5

**3. `.claude/skills/gap-analysis/SKILL.md`**
- Description: Detect research gaps in current literature
- allowed-tools: `[mcp__research-harness__gap_detect, mcp__research-harness__paper_list, mcp__research-harness__baseline_identify, Read]`
- When: Literature mapping complete, need research direction
- Process: (1) Run `gap_detect`, (2) Cross-reference with baselines, (3) Prioritize gaps by severity
- Quality: At least 1 gap with clear research opportunity

**4. `.claude/skills/section-drafting/SKILL.md`**
- Description: Draft paper sections with evidence-backed content
- allowed-tools: `[mcp__research-harness__section_draft, mcp__research-harness__consistency_check, mcp__research-harness__paper_list, Read, Write]`
- When: Claims formed, evidence linked, ready to write
- Process: (1) Draft section with evidence_ids, (2) Run consistency check, (3) Revise based on issues
- Quality: All claims cited, no consistency issues with severity "high"

**5. `.claude/skills/evidence-gating/SKILL.md`**
- Description: Evaluate readiness to advance research stages
- allowed-tools: `[mcp__research-harness__topic_show, mcp__research-harness__paper_list, mcp__research-harness__task_list, mcp__research-harness__provenance_summary, Read]`
- When: Before transitioning between research stages
- Process: Check stage-specific criteria:
  - `literature_mapping`: min_papers=20, min_high_relevance=5, categories=[baseline, method, evaluation]
  - `claim_formation`: min_claims=3, min_supported=1, max_unsupported_ratio=0.5
  - `method_planning`: min_baseline_coverage=0.8, required_fields=[dataset, metric, hypothesis]
  - `drafting`: required_sections=[introduction, related_work, method], min_evidence_per_claim=2
- Gate modes: `manual` (human approval) or `auto` (log rationale)
- Quality: All criteria met or documented justification for proceeding

**6. `.claude/skills/task-taxonomy/SKILL.md`**
- Description: Research task classification and model routing guidance
- allowed-tools: `[Read]`
- When: Deciding which model to use for a research task
- Content: Documents the 7 PrimitiveCategory values and recommended routing:
  - RETRIEVAL (paper_search): kimi — keyword expansion, low reasoning
  - COMPREHENSION (paper_summarize): kimi — long context, low cost
  - EXTRACTION (claim_extract, baseline_identify): kimi → sonnet fallback
  - ANALYSIS (gap_detect): sonnet → opus fallback — cross-paper reasoning
  - SYNTHESIS (hypothesis_gen): opus — creative + deep reasoning
  - GENERATION (section_draft): sonnet — fluent writing
  - VERIFICATION (consistency_check): opus — full-document reasoning
- Note: MCP server handles routing internally; this skill is for human reference

**7. `.claude/skills/research-primitives/SKILL.md`**
- Description: Reference guide for all 9 research primitive operations
- allowed-tools: `[Read]`
- Content: Documents each primitive with name, category, input/output types, example usage via MCP tool

**8. `.claude/skills/provenance-review/SKILL.md`**
- Description: Review execution provenance and cost analysis
- allowed-tools: `[mcp__research-harness__provenance_summary, Bash, Read]`
- When: Reviewing research cost, debugging execution issues, preparing paper evaluation data
- Process: (1) Get summary, (2) Analyze cost by primitive/backend, (3) Check success rate

## Task D1: Create 5 Research Agents

Create `.claude/agents/` directory with 5 `.md` files.

### Format

```yaml
---
name: agent-name
description: One-line description
tools: [tool1, tool2, ...]
model: opus|sonnet|haiku
---

# Agent Name

(Agent system prompt and behavior specification)
```

### Agents to Create

**1. `.claude/agents/proposer.md`**
- Description: Generates research proposals for adversarial review
- Tools: `[Read, Grep, Glob, mcp__research-harness__gap_detect, mcp__research-harness__paper_search, mcp__research-harness__claim_extract, mcp__research-harness__paper_list]`
- Model: opus
- Behavior: Given a research topic, generate a structured proposal with: research question, hypothesis, method outline, expected contribution. Must ground claims in evidence from the paper pool.

**2. `.claude/agents/challenger.md`**
- Description: Adversarial critic that raises structured objections
- Tools: `[Read, Grep, Glob, mcp__research-harness__paper_list, mcp__research-harness__paper_search, mcp__research-harness__baseline_identify]`
- Model: opus
- Behavior: Review a proposal and produce structured `Objection` items. Each objection MUST include: target (which part), severity (critical/major/minor), reasoning, and a suggested_fix. No empty criticism allowed.

**3. `.claude/agents/adversarial-resolver.md`**
- Description: Orchestrates proposer-challenger dialectic for research decisions
- Tools: `[Agent, Read, Grep, Glob]`
- Model: opus
- Behavior: Run up to 5 rounds of proposer↔challenger. Convergence when: no critical objections remain, all objections addressed or rebutted, challenger explicitly agrees. If max_rounds reached, present unresolved objections for human decision.
- Applicable stages: innovation_planning, experiment_design, paper_architecture, section_writing

**4. `.claude/agents/literature-mapper.md`**
- Description: Systematic literature search agent using iterative retrieval
- Tools: `[mcp__research-harness__paper_search, mcp__research-harness__paper_ingest, mcp__research-harness__topic_show, mcp__research-harness__paper_list, Read, Grep, Glob, mcp__arxiv__search_papers, mcp__semantic-scholar__search_papers]`
- Model: sonnet
- Behavior: Given a topic, iteratively search, evaluate relevance, refine queries. Target: 20+ papers with coverage across baseline/method/evaluation. Use 4-phase cycle: DISPATCH (broad) → EVALUATE (relevance) → REFINE (criteria) → LOOP. Max 3 cycles.

**5. `.claude/agents/synthesizer.md`**
- Description: Cross-paper synthesis and analysis agent
- Tools: `[mcp__research-harness__claim_extract, mcp__research-harness__section_draft, mcp__research-harness__evidence_link, mcp__research-harness__paper_list, Read, Write]`
- Model: sonnet
- Behavior: Given claims and evidence, produce synthesized analysis. Identify agreements, contradictions, and gaps across papers. Output structured sections with citations.

## Task E1: Create Hooks

### E1a: Create hooks in settings.json format

Hooks go in `.claude/settings.json` (project-level) under the `hooks` key:

**Create** `.claude/settings.json`:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__research-harness__*",
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/record-provenance.py",
            "timeout": 10,
            "statusMessage": "Recording provenance..."
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python .claude/hooks/session-summary.py",
            "timeout": 10,
            "statusMessage": "Generating session summary..."
          }
        ]
      }
    ]
  }
}
```

### E1b: Create hook scripts

**`.claude/hooks/record-provenance.py`**
- Reads JSON from stdin (Claude Code hook protocol)
- Extracts tool name and result from the hook payload
- If tool name starts with `mcp__research-harness__`, records to provenance
- Uses `ProvenanceRecorder` from `research_harness.provenance.recorder`
- Exits 0 on any error (non-blocking)

**`.claude/hooks/session-summary.py`**
- Reads provenance summary from DB
- Prints: total operations, total cost, operations by primitive, success rate
- Exits 0 on any error (non-blocking)

## Verification

After all tasks:

```bash
# Existing tests still pass
python -m pytest packages/ -q --tb=short
# Expected: 151 passed

# Skills exist
ls .claude/skills/*/SKILL.md
# Expected: 8 files

# Agents exist
ls .claude/agents/*.md
# Expected: 5 files

# Settings valid JSON
python -c "import json; json.load(open('.claude/settings.json'))"

# Hook scripts parse without error
python -c "import py_compile; py_compile.compile('.claude/hooks/record-provenance.py')"
python -c "import py_compile; py_compile.compile('.claude/hooks/session-summary.py')"
```
