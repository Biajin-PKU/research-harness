# Research Harness — Monorepo

Agent-first research workflow platform for academic literature review, paper writing, and experiment orchestration.

## Repository Layout

```
research-harness/
├── packages/                        <- Tool packages
│   ├── paperindex/                  <- PDF understanding engine
│   ├── research_harness/            <- Workflow management
│   └── research_harness_mcp/        <- MCP server
├── .research-harness/
│   ├── pool.db                      <- Paper database (created on first run)
│   └── downloads/                   <- PDF storage
└── docs/                            <- Platform documentation
    └── PAPER_MANAGEMENT.md          <- Paper management protocol
```

## Paper Management

> See `docs/PAPER_MANAGEMENT.md` for the full protocol.

1. **Single DB**: `.research-harness/pool.db` (symlinked from `~/.research-harness/pool.db`)
2. **Single PDF dir**: `.research-harness/downloads/`
3. **Always specify topic on ingest**: `paper_ingest(source=..., topic_id=<N>)`
4. **Use absolute paths** for all PDF references

## CLI Entry Points

```bash
# Data management
rh topic list
rh topic init "my-research-topic"
rh paper ingest --arxiv-id 2401.12345 --topic my-topic
rh paper queue --topic my-topic
rh paper acquire <topic_id>           # batch download
rh paper resolve-pdfs --topic <name>  # discover PDFs on disk

# Tests
python -m pytest packages/ -q --tb=short

# MCP server (Claude Code auto-starts)
python -m research_harness_mcp.server
```

## Packages

- `packages/paperindex` — PDF understanding engine (structure extraction, search, paper card, multi-LLM provider)
- `packages/research_harness` — Workflow management (paper pool, tasks, reviews, primitives, provenance)
- `packages/research_harness_mcp` — MCP server (112 tools, stdio transport)

## Configuration

```bash
# DB path (default: .research-harness/pool.db)
export RESEARCH_HARNESS_DB_PATH=~/.research-harness/pool.db

# Execution backend
export RESEARCH_HARNESS_BACKEND=claude_code   # default: local
```

### LLM Provider Routing

```bash
# Enable providers
export CODEX_ENABLED=1
export CURSOR_AGENT_ENABLED=1

# Tier routing: light -> cheap/fast, medium -> balanced, heavy -> max quality
# Override: LLM_ROUTE_{TIER}=provider:model
```

## Conventions

- Research primitives -> MCP tools
- Data management -> `rh` CLI
- Primitive executions -> auto-tracked in provenance
- LLM primitives -> auto-route by tier
