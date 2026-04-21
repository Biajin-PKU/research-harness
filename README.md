<p align="center">
  <img src="docs/assets/hero.png" alt="Research Harness" width="720"/>
</p>

<h1 align="center">Research Harness</h1>

<p align="center">
  <a href="README.md"><b>English</b></a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <b>Engineering Trust into Autonomous Discovery.</b>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"/></a>
  <img src="https://img.shields.io/badge/tests-987%2B-green.svg" alt="Tests"/>
  <img src="https://img.shields.io/badge/MCP-112_tools-orange.svg" alt="MCP tools"/>
  <img src="https://img.shields.io/badge/primitives-69-purple.svg" alt="Primitives"/>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/status-v0.1.0-yellow.svg" alt="Status"/>
</p>

---

```text
   init  ─▶  build  ─▶  analyze  ─▶  propose  ─▶  experiment  ─▶  write
     │         │          │           │              │            │
     ▼         ▼          ▼           ▼              ▼            ▼
  ┌──gate──┬──gate──┬───gate───┬───gate───┬────gate────┬──gate──┐
  │artifact│ claims │   gaps   │ proposal │   results  │ paper  │
  └────────┴────────┴──────────┴──────────┴────────────┴────────┘
```

Every arrow is a **typed evidence gate**. No gate opens without the right artifact.
No primitive runs without a provenance record. **No number leaves the registry unverified.**

---

## Why Research Harness?

The AI-research space keeps shipping the same two things:

| Pattern | What it gives you | What it misses |
|---------|-------------------|----------------|
| 🤖 **The autonomous pipeline** (idea → paper in N stages) | Push-button automation | Black box, hallucinated citations, no checkpoint you can audit |
| 📚 **The skill library** (folder of markdown/TS prompts) | Composability, no lock-in | No state, no provenance, every session starts from zero |

**Research Harness is neither.** It's the **infrastructure** those apps could run on —
an engineering framework that makes research reproducible, queryable, and hand-off-able
between agents *and* humans.

We chose the name on purpose. A harness doesn't climb the mountain. **It makes sure you don't fall.**

---

## The Three Pillars

### 🛡️ 1. Evidence-Gated Orchestration
Six stages, typed gates between every one. A gate is not a prompt — it's a **contract**:
it inspects the artifacts produced by the previous stage and refuses to open if the
proof isn't there. Not a linear pipeline. A state machine with invariants.

### 🗄️ 2. A Paper Database That Outlives Your Sessions
A single **SQLite `pool.db`** that survives projects, restarts, collaborators:

- De-duplicated paper records (arXiv, DOI, S2 IDs all merged)
- Full-text PDFs, paper cards, deep-reading notes, claim extractions
- Affiliation enrichment, citation-graph expansion, coverage tracking
- Queryable from `sqlite3`, Pandas, DuckDB, or any SQL tool you already know

No markdown wiki to rebuild. No "dump folder" that rots.
**One database for your whole research life.**

### 🔬 3. Provenance on Every Call
Every primitive execution is recorded with model, cost, input/output hashes, and
artifact lineage (`derived_from`, `consumed_by`). When you ship a paper,
`paper_verify_numbers` cross-checks every figure against a **verified number registry**
built from your actual experiment runs. Fabrication is not a failure mode — it's impossible.

---

## Feature Highlights

- 🎯 **69 primitives → 112 MCP tools** — search, extract, gate, review, draft, verify
- ⚖️ **Dual-axis execution** — `workflow_mode` × `autonomy_mode` (dial your risk)
- 🔁 **Cross-model adversarial review** — independent challenge/response at high-stakes checkpoints
- 🧩 **Plugin manifest** — add primitives, gates, stages, backends via one YAML file
- 🌐 **Client-agnostic** — MCP / Python API / CLI, 100% primitive coverage on all three
- 🎨 **Figure generation** — `figure_plan` + `figure_generate` via fal.ai render paper-ready architecture diagrams straight into your LaTeX
- 🪶 **Domestic-friendly LLMs** — Kimi / Moonshot built in (Qwen, DeepSeek, GLM on the way)
- 📊 **Local web dashboard** — `http://127.0.0.1:18080` for live pipeline monitoring
- ✅ **987+ tests** across three packages

---

## Three Ways to Use

Pick your surface. All three share the same database and provenance trail.

| Path | Best for | How to start |
|------|----------|--------------|
| 🤖 **MCP client** (Claude Code, Codex) | Agentic sessions, chat-driven workflows | 5-line config — [jump ↓](#mcp-server) |
| 🐍 **Python API** | Notebooks, pipelines, existing codebases | `from research_harness import ResearchAPI` |
| ⌨️ **`rh` CLI** | Terminal, shell, CI | `rh topic init "my-topic"` |

> No MCP client required. The Python API and CLI expose 100% of the primitive surface;
> MCP is just one of three transports.

---

## Quick Start

```bash
git clone https://github.com/your-org/research-harness.git
cd research-harness
./setup.sh                          # venv or conda, auto-detected
cp .env.example .env                # add ONE LLM key (see below)
rh topic init "my-research-topic"   # you're in
```

**Minimum API keys — pick any one:**

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
KIMI_API_KEY=sk-...          # Kimi / Moonshot — works from mainland China
```

---

## MCP Server

### Claude Code

Add to `.claude/settings.json` (project) or `~/.claude/settings.json` (global):

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "/absolute/path/to/research-harness/.venv/bin/python",
      "args": ["-m", "research_harness_mcp"],
      "env": {
        "RESEARCH_HARNESS_DB_PATH": "/absolute/path/to/pool.db"
      }
    }
  }
}
```

### Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.research-harness]
command = "/absolute/path/to/research-harness/.venv/bin/python"
args = ["-m", "research_harness_mcp"]
env = { "RESEARCH_HARNESS_DB_PATH" = "/absolute/path/to/pool.db" }
startup_timeout_sec = 30.0
```

Or via CLI: `codex mcp add research-harness -- /abs/path/python -m research_harness_mcp`

Once configured, Claude Code / Codex get direct access to all 112 research tools.
Nothing else to install.

---

## How It Compares

|  | Autonomous pipelines | Skill libraries | **Research Harness** |
|---|:---:|:---:|:---:|
| Orchestration | N-stage run | — | **6 stages + typed gates** |
| State across sessions | run artifacts | markdown files | **SQLite `pool.db`** |
| Provenance (cost / model / hash) | partial | — | **every primitive call** |
| Number verification | registry (anti-hallucination) | — | **registry + strict gate** |
| Extensibility | fork & edit | fork & edit | **YAML plugin manifest** |
| Client reach | usually one | depends on agent | **MCP + Python + CLI** |
| Test suite | — | — | **987+** |

The others are great for push-button runs. We're the layer underneath:
**infrastructure built to be audited, extended, and trusted.**

---

## Repository Layout

```
research-harness/
├── packages/
│   ├── paperindex/              # PDF understanding engine
│   ├── research_harness/        # Orchestrator + primitives + provenance + plugins
│   └── research_harness_mcp/    # 112-tool MCP server (stdio)
├── docs/                        # agent-guide, architecture, plugin-guide, quickstart
├── web_dashboard/               # Flask monitor (http://127.0.0.1:18080)
└── .research-harness/pool.db    # your persistent paper database
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/quickstart.md](docs/quickstart.md) | Detailed setup walkthrough |
| [docs/agent-guide.md](docs/agent-guide.md) | How Claude Code / Codex should use this |
| [docs/architecture.md](docs/architecture.md) | System design and gate specs |
| [docs/python-api.md](docs/python-api.md) | Using the harness without an MCP client |
| [docs/plugin-guide.md](docs/plugin-guide.md) | Writing custom primitives / gates |

---

## Testing

```bash
python -m pytest packages/ -q --ignore=packages/research_harness_eval
```

## License

[Apache License 2.0](LICENSE) — all contributions licensed under the same.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

## Acknowledgements

Built on [MCP](https://modelcontextprotocol.io), with gratitude to
[Semantic Scholar](https://www.semanticscholar.org),
[OpenAlex](https://openalex.org),
[arXiv](https://arxiv.org), and
[Unpaywall](https://unpaywall.org) for the open bibliographic backbone.
