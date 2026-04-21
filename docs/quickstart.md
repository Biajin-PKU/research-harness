# Quick Start Guide

## Prerequisites

- Python 3.10+
- SQLite 3.35+ (bundled with macOS / most Linux distributions)
- At least one LLM API key — OpenAI, Anthropic, or Kimi / Moonshot

## Installation

```bash
git clone https://github.com/your-org/research-harness.git
cd research-harness
./setup.sh
```

`setup.sh` installs all three packages in editable mode, creates `.env` from
`.env.example`, and runs a smoke import test. It works with both `venv` and
`conda`.

### Manual install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e packages/paperindex[dev]
pip install -e "packages/research_harness[dev]"
pip install -e "packages/research_harness_mcp[dev]"
cp .env.example .env
```

## Configuration

Edit `.env` and set at least one LLM provider key. The minimum required block:

```bash
# Pick one (more than one is fine too)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
KIMI_API_KEY=sk-...                # Kimi / Moonshot — domestic-friendly option
```

More domestic providers (Qwen, DeepSeek, GLM, etc.) will follow. If you want
one added, open an issue.

Recommended (free, improves paper retrieval):

```bash
S2_API_KEY=...                   # Semantic Scholar — higher rate limits
UNPAYWALL_EMAIL=you@example.com  # Unpaywall — free OA PDF lookup by DOI
```

Optional (only if you want figure rendering):

```bash
FAL_KEY=...   # fal.ai — required by figure_generate for paper-ready diagrams
              # (skip unless you plan to render figures)
```

### Tier-based LLM routing

Research Harness routes primitives to models by tier:

| Tier | Use case | Default |
|------|----------|---------|
| `light` | summarize, classify, format | cheapest configured model |
| `medium` | claim extraction, gap detection | balanced model |
| `heavy` | consistency check, adversarial review | highest-quality model |

Override routing with `LLM_ROUTE_{TIER}=provider:model`:

```bash
LLM_ROUTE_LIGHT=openai:gpt-4o-mini
LLM_ROUTE_MEDIUM=openai:gpt-4o
LLM_ROUTE_HEAVY=anthropic:claude-opus-4-5
```

See `.env.example` for the full list of optional variables.

## Verify Installation

```bash
rh --json doctor
# or equivalently: rhub --json doctor
```

## Using with Claude Code

Add to `.claude/settings.json` (project-level) or `~/.claude/settings.json`
(global). **Use an absolute path to the Python interpreter** so the MCP server
works regardless of which shell has your venv activated:

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "/absolute/path/to/research-harness/.venv/bin/python",
      "args": ["-m", "research_harness_mcp"],
      "env": {
        "RESEARCH_HARNESS_DB_PATH": "/absolute/path/to/research-harness/.research-harness/pool.db"
      }
    }
  }
}
```

If you installed via conda, point `command` at the env's Python
(`~/miniconda3/envs/research-harness/bin/python` or similar).

Once configured, Claude Code has direct access to all 112 MCP tools — no other
setup required.

## First Research Project

```bash
# 1. Initialize a topic
rh topic init "my-research-topic"

# 2. Search and ingest papers
rh paper search "my research query" --topic-id 1 --auto-ingest

# 3. Start the orchestrated workflow
rh orchestrator init --project-id 1 --topic-id 1 --mode standard

# 4. Check status
rh orchestrator status --project-id 1

# 5. Advance through evidence-gated stages
rh orchestrator advance --project-id 1
```

## Autonomous Mode

```bash
# Run with autonomous gate resolution (for well-defined tasks)
rh auto-runner start --project-id 1 --autonomy autonomous --task-profile bounded
```

## Launch the Dashboard

```bash
pip install -r web_dashboard/requirements.txt
python web_dashboard/app.py
```

Open <http://127.0.0.1:18080>.

## Run Tests

```bash
python -m pytest packages/ -q --ignore=packages/research_harness_eval
```

## Plugin Development

See [`docs/plugin-guide.md`](plugin-guide.md) for writing custom primitives.
The plugin manifest schema is at
`packages/research_harness/research_harness/plugin/manifest.py`.
