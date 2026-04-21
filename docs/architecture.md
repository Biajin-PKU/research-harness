# Research Harness Architecture

## Overview

Research Harness is an MCP-based research automation system that orchestrates the full lifecycle from literature review to paper writing. It provides evidence-gated stage progression, adversarial review, provenance tracking, and self-improving skill evolution.

## Core Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   MCP Server                            │
│  (tools.py — 112 tools, stdio transport)                │
├─────────────────────────────────────────────────────────┤
│              Orchestrator Service                       │
│  ┌─────┐ ┌─────┐ ┌───────┐ ┌───────┐ ┌──────────┐ ┌─────┐│
│  │init │→│build│→│analyze│→│propose│→│experiment│→│write││
│  └─────┘ └─────┘ └───────┘ └───────┘ └──────────┘ └─────┘│
│  Gates: approval│coverage│adversarial│review│experiment │
├─────────────────────────────────────────────────────────┤
│  Primitives    │  Provenance  │  Observation            │
│  (69 ops)      │  (audit trail)│  (skill evolution)     │
├─────────────────────────────────────────────────────────┤
│  Execution Backends (LLM, Local, Plugin)                │
├─────────────────────────────────────────────────────────┤
│  SQLite Storage (pool.db)                               │
└─────────────────────────────────────────────────────────┘
```

## Dual-Axis Execution Model

- **workflow_mode** (explore|standard|strict|demo): Controls depth and quality thresholds
- **autonomy_mode** (supervised|autonomous): Controls who resolves gates
  - Supervised: Human approval at key checkpoints
  - Autonomous: Agent auto-resolves gates (with budget limits and safety rails)

## Key Design Principles

1. **Evidence-gated progression**: Advance only when structured artifacts prove readiness
2. **Separation of generation and evaluation**: Adversarial review via independent models
3. **Persistent artifacts over ephemeral outputs**: Typed, versioned artifacts in SQLite
4. **Provenance for audit**: Every primitive execution recorded with cost and lineage
5. **Human authority preserved**: Override capability at all stages
6. **Plugin-extensible**: New primitives, gates, stages, and backends via plugin manifests

## Extension Points

| Point | What It Extends | Registration |
|-------|----------------|-------------|
| Primitives | Paper sources, analysis tools | `@register_primitive(spec)` |
| Gates | Quality checks at stage boundaries | `GateEvaluator` subclass |
| Stages | Orchestrator pipeline steps | `STAGE_REGISTRY` + `STAGE_GRAPH` |
| Advisory Rules | Heuristic warnings | `AdvisoryEngine` methods |
| Backends | Execution providers | `ExecutionBackend` interface |

## License

PolyForm-Noncommercial-1.0.0
