# Research Harness

An agent-first research workflow platform that orchestrates the full academic research lifecycle — from literature search and evidence structuring through adversarial review and paper writing — with evidence-gated stage progression, provenance tracking, and a 112-tool MCP server for Claude Code and Codex.

> **Status:** v0.1.0 early release. Core primitives and MCP server are stable. CLI commands and plugin API may evolve between minor versions.

## Features

- **6-stage orchestrator** — `init → build → analyze → propose → experiment → write`, with typed gates between every stage
- **69 research primitives** exposed as **112 MCP tools** — paper search, claim extraction, gap detection, baseline identification, evidence linking, section drafting, figure planning, rebuttal formatting, and more
- **Evidence-gated progression** — each stage produces structured artifacts; the gate checks them before permitting advancement
- **Adversarial review** — independent cross-model challenge/response at high-stakes decision points
- **Dual-axis execution** — `workflow_mode` (explore/standard/strict/demo) x `autonomy_mode` (supervised/autonomous)
- **Provenance tracking** — every primitive execution is recorded with cost, model, output hash, and artifact lineage
- **Self-improving observation** — MCP-native middleware collects execution traces for offline skill evolution
- **Plugin extensible** — add custom primitives, gates, stages, and backends via a YAML manifest
- **Web dashboard** — local Flask dashboard at `http://127.0.0.1:18080` for pipeline monitoring
- **987+ tests** across three packages

## Packages

| Package | Description |
|---------|-------------|
| `packages/paperindex` | PDF understanding engine — structure extraction, section search, paper cards, multi-LLM provider |
| `packages/research_harness` | Workflow management — paper pool, orchestrator, primitives, provenance, plugin system |
| `packages/research_harness_mcp` | MCP server — 112 stdio tools wrapping all primitives plus orchestrator and provenance tools |

## Quick Start

### Option A — pip (minimal)

```bash
git clone https://github.com/your-org/research-harness.git
cd research-harness
./setup.sh
```

`setup.sh` installs all three packages in editable mode, copies `.env.example` to `.env`, and prints next steps.

### Option B — conda

```bash
conda env create -f environment.yml
conda activate research-harness
```

### Configure

```bash
# Edit .env with your API keys (copy created by setup.sh)
# Minimum required: at least one LLM provider key

# Verify installation
rhub --json doctor
```

### MCP Server — Claude Code

Add to `.claude/settings.json` (project-level) or `~/.claude/settings.json` (global):

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "python",
      "args": ["-m", "research_harness_mcp"],
      "env": {
        "RESEARCH_HARNESS_DB_PATH": "/absolute/path/to/your/pool.db"
      }
    }
  }
}
```

### MCP Server — Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "python",
      "args": ["-m", "research_harness_mcp"],
      "env": {
        "RESEARCH_HARNESS_DB_PATH": "/absolute/path/to/your/pool.db"
      }
    }
  }
}
```

### First Research Project

```bash
# Initialize a topic
rh topic init "my-research-topic"

# Search and ingest papers
rh paper ingest --arxiv-id 2401.12345 --topic my-research-topic

# Start the orchestrated workflow
rh orchestrator status --project-id 1

# Advance through evidence-gated stages
rh orchestrator advance --project-id 1
```

### Web Dashboard

```bash
pip install -r web_dashboard/requirements.txt
python web_dashboard/app.py
# Open http://127.0.0.1:18080
```

## CLI Entry Points

```bash
rh                    # main CLI (also: research-harness, rhub)
rh topic list
rh topic init "name"
rh paper ingest --arxiv-id 2401.12345 --topic <name>
rh paper acquire <topic_id>
rh paper resolve-pdfs --topic <name>
rh orchestrator status --project-id 1
rh orchestrator advance --project-id 1
rhub --json doctor    # health check
```

## Repository Layout

```
research-harness/
├── packages/
│   ├── paperindex/              # PDF understanding engine
│   ├── research_harness/        # Core workflow platform
│   │   └── research_harness/
│   │       ├── primitives/      # 69 research operations
│   │       ├── orchestrator/    # 6-stage pipeline + gates
│   │       ├── provenance/      # Audit trail
│   │       ├── plugin/          # Plugin manifest + loader
│   │       └── cli.py           # rh CLI entry point
│   └── research_harness_mcp/   # MCP server (112 tools)
├── docs/
│   ├── agent-guide.md          # How to use with Claude Code / Codex
│   ├── architecture.md         # System architecture
│   ├── quickstart.md           # Detailed setup guide
│   ├── plugin-guide.md         # Plugin development
│   └── PAPER_MANAGEMENT.md    # Paper storage protocol
├── web_dashboard/              # Flask monitoring dashboard
├── config/                     # LLM proxy config examples
├── environment.yml             # Conda environment
├── pytest.ini                  # Test configuration
└── setup.sh                    # One-command bootstrap
```

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and edit:

| Variable | Required | Description |
|----------|----------|-------------|
| `RESEARCH_HARNESS_DB_PATH` | No | SQLite database path (default: `.research-harness/pool.db`) |
| `RESEARCH_HARNESS_BACKEND` | No | Execution backend: `local` or `claude_code` |
| `OPENAI_API_KEY` | Conditional | Required for OpenAI-routed primitives |
| `ANTHROPIC_API_KEY` | Conditional | Required for Anthropic-routed primitives |
| `CODEX_ENABLED` | No | Set `1` to enable Codex provider routing |
| `CURSOR_AGENT_ENABLED` | No | Set `1` to enable Cursor Agent routing |
| `LLM_ROUTE_LIGHT` | No | Override light-tier routing: `provider:model` |
| `LLM_ROUTE_MEDIUM` | No | Override medium-tier routing: `provider:model` |
| `LLM_ROUTE_HEAVY` | No | Override heavy-tier routing: `provider:model` |

See `.env.example` for the full list.

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/agent-guide.md](docs/agent-guide.md) | How agents (Claude Code, Codex) should use this platform |
| [docs/architecture.md](docs/architecture.md) | System design and component overview |
| [docs/quickstart.md](docs/quickstart.md) | Detailed getting-started walkthrough |
| [docs/plugin-guide.md](docs/plugin-guide.md) | Writing custom primitives and gates |
| [docs/PAPER_MANAGEMENT.md](docs/PAPER_MANAGEMENT.md) | Paper ingestion and storage protocol |
| [CLAUDE.md](CLAUDE.md) | Quick-reference for Claude Code |
| [AGENTS.md](AGENTS.md) | Agent integration instructions |

## Testing

```bash
# Full suite (~987 tests)
python -m pytest packages/ -q --ignore=packages/research_harness_eval

# Single package
python -m pytest packages/research_harness/tests -q
python -m pytest packages/paperindex/tests -q

# With coverage
python -m pytest packages/ --cov=packages --cov-report=term-missing -q
```

## Using with Claude Code

This project includes `CLAUDE.md` and `AGENTS.md` that give Claude Code full context.

```bash
claude    # Start Claude Code — reads CLAUDE.md automatically
```

Once the MCP server is configured, Claude Code has direct access to all 112 research tools without any additional setup.

## Acknowledgements

- [Model Context Protocol](https://modelcontextprotocol.io) — MCP specification and SDK
- [Anthropic](https://anthropic.com) — Claude API
- [Semantic Scholar](https://www.semanticscholar.org) — Paper search API
- [OpenAlex](https://openalex.org) — Open bibliographic data
- [arXiv](https://arxiv.org) — Preprint search and PDF access

## License

[Apache License 2.0](LICENSE)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). All contributions are licensed under Apache-2.0.
