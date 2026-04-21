# Claude Code Extensions Architecture

Updated: 2026-04-03

## Overview

Research Harness is extended via Claude Code's native extension mechanisms: Skills, Agents, Hooks, and MCP Server. This replaces the original plan to build a standalone Research Harness REPL.

## Architecture

```
Claude Code REPL (interaction layer — provided by Claude Code)
│
├── Skills (.claude/skills/)
│   ├── literature-mapping      — systematic lit search workflow
│   ├── claim-extraction        — extract claims from papers
│   ├── gap-analysis            — detect research gaps
│   ├── section-drafting        — draft paper sections
│   ├── evidence-gating         — stage transition criteria
│   ├── task-taxonomy           — model routing recommendations
│   ├── research-primitives     — all 9 primitives reference
│   └── provenance-review       — audit and cost analysis
│
├── Agents (.claude/agents/)
│   ├── proposer                — generates research proposals
│   ├── challenger              — adversarial critic
│   ├── adversarial-resolver    — orchestrates convergence
│   ├── literature-mapper       — systematic search
│   └── synthesizer             — cross-paper synthesis
│
├── Hooks (.claude/hooks/ in settings.json)
│   ├── PostToolUse: record-provenance.py  — auto-log MCP tool calls
│   └── Stop: session-summary.py           — print cost/ops summary
│
└── MCP Server (research-harness)
    ├── Primitive tools (9)     — paper_search, claim_extract, etc.
    ├── Convenience tools (5)   — topic_list, paper_list, etc.
    ├── Paperindex tools (3)    — PDF search, structure, cards
    └── Internal routing        — task taxonomy → provider selection
          └── paperindex LLMClient → Kimi / Anthropic / OpenAI
```

## Innovation → Extension Mapping

| # | Innovation | Extension | Implementation |
|---|-----------|-----------|---------------|
| 1 | Research Task Taxonomy | MCP Server internal | `tools.py` routing table |
| 2 | Evidence-Gated Pipeline | Skill | `evidence-gating/SKILL.md` |
| 3 | Research Primitives | MCP Tools | 9 tools from `PRIMITIVE_REGISTRY` |
| 4 | Provenance-First | Hook | `PostToolUse` → `record-provenance.py` |
| 5 | Investigation Thread | Storage | Topic branch/merge in DB |
| 6 | Adversarial Convergence | Agents | proposer ↔ challenger → resolver |
| 7 | Dual-Mode Gates | Skill config | `evidence-gating/SKILL.md` mode switch |

## Data Flow

```
User prompt
  → Claude Code interprets intent
  → Invokes Skill (workflow knowledge)
    → Calls MCP tool (e.g., paper_search)
      → MCP Server routes to backend
        → ResearchHarnessBackend selects model (routing table)
          → paperindex LLMClient calls Kimi/Claude/OpenAI
        → Result returned as JSON
      → Hook fires (provenance recorded)
    → Skill continues with next step
  → Claude Code presents result
```

## Paper Framing

> "We demonstrate that domain-specific research orchestration can be implemented as composable extensions to a general-purpose agent harness, achieving comparable quality at reduced cost through task-aware model routing."

Key claims:
1. **Composability**: All innovations as modular extensions, not monolithic system
2. **Reproducibility**: Others install extensions + Claude Code to replicate
3. **Cost efficiency**: Task taxonomy routing reduces API spend
4. **Quality parity**: Evidence gates ensure research output quality

## Evaluation Design

| Condition | Backend | Model Routing |
|-----------|---------|--------------|
| Baseline | Claude Code (vanilla, no extensions) | All Opus |
| Treatment | Claude Code + Research Extensions | Task taxonomy routing |
| Ablation 1 | Extensions, all-Kimi | No routing |
| Ablation 2 | Extensions, all-Opus | No routing |
| Ablation 3 | Extensions, no evidence gates | Routing only |
