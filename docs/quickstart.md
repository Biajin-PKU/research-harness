# Quick Start Guide

## Prerequisites

- Python 3.10+
- SQLite 3.35+
- An LLM API key (OpenAI, Anthropic, or local model)

## Installation

```bash
git clone https://github.com/your-org/research-harness.git
cd research-harness
pip install -e packages/research_harness
pip install -e packages/research_harness_mcp
```

## Configuration

```bash
# Set database path (default: ~/.research-harness/pool.db)
export RESEARCH_HARNESS_DB_PATH=~/.research-harness/pool.db

# Set LLM provider
export LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-...
```

## Using with Claude Code

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "python",
      "args": ["-m", "research_harness_mcp"]
    }
  }
}
```

## First Research Project

```bash
# 1. Initialize a topic
rh topic init "my-research-topic"

# 2. Search and ingest papers
rh paper search "my research query" --topic-id 1 --auto-ingest

# 3. Start orchestrated workflow
rh orchestrator init --project-id 1 --topic-id 1 --mode standard

# 4. Check status
rh orchestrator status --project-id 1

# 5. Advance through stages
rh orchestrator advance --project-id 1
```

## Autonomous Mode

```bash
# Run with autonomous gate resolution (for well-defined tasks)
rh auto-runner start --project-id 1 --autonomy autonomous --task-profile bounded
```

## Health Check

```bash
rhub --json doctor
```

## Launch Dashboard

```bash
cd ~/code/research-harness
python3 -m venv .venv
./.venv/bin/pip install -r web_dashboard/requirements.txt
./.venv/bin/python web_dashboard/app.py
```

Open `http://127.0.0.1:18080`.

## Run Tests

```bash
pytest packages/research_harness/tests -q
```

## Plugin Development

See `packages/research_harness/research_harness/plugin/manifest.py` for the plugin manifest schema.
