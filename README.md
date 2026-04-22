<p align="center">
  <img src="docs/assets/hero.png" alt="Research Harness" width="720"/>
</p>

<h1 align="center">Research Harness</h1>

<p align="center">
  <a href="README.md"><b>English</b></a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  An agent harness for scientific literature work — persistent state, typed primitives, stage-gated progression, and provenance on every recorded call.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-PolyForm_Noncommercial_1.0.0-red.svg" alt="License"/></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/tests-987%2B-green.svg" alt="Tests"/>
  <img src="https://img.shields.io/badge/primitives-69-purple.svg" alt="Primitives"/>
  <img src="https://img.shields.io/badge/MCP-112_tools-orange.svg" alt="MCP tools"/>
</p>

---

## What It Is

Research Harness is the execution and state layer underneath an agent that does literature review, proposal writing, experiment coordination, and paper drafting. It runs the loop — gather evidence, act on it, verify the result — and persists every step so the next session (human or agent) can pick up where the last one stopped.

Concretely, it is:

- a **state layer** — one SQLite `pool.db` holding papers, cards, deep-reading notes, claims, artifacts, and provenance records;
- a **primitive layer** — 69 typed research operations (`paper_search`, `claim_extract`, `gap_detect`, `adversarial_review`, `section_draft`, `paper_verify_numbers`, …) registered once and exposed as 112 MCP tools, a Python API, and a `rh` CLI;
- a **control layer** — six stages (`init → build → analyze → propose → experiment → write`), each advancing only when the previous stage has produced typed artifacts that satisfy the gate at the boundary.

The word *harness* follows Anthropic's engineering framing[^1]: it is the system that turns a model into an agent by orchestrating tool calls, preserving state across turns, and recording what happened. Research Harness applies that framing to research work.

[^1]: See Anthropic Engineering, *Demystifying evals for AI agents* (Jan 2026) and *Effective harnesses for long-running agents* (Nov 2025) for the underlying definition of an agent harness.

## Why It Exists

The design targets three recurring needs in literature-heavy research:

1. **Continuity.** A paper project runs for weeks or months. Ingested papers, extracted claims, and marked gaps have to survive session boundaries, model swaps, and human hand-offs.
2. **Auditability.** Every claim that lands in a draft should trace back to something concrete — a paper, an extracted quote, an experiment run, a verified number.
3. **Reviewability at stage boundaries.** Between literature survey and proposal, between proposal and experiment, between experiment and write-up, a human needs a clean checkpoint: typed artifacts they can review directly.

Research Harness makes those three requirements first-class: state persists in the database, tracked primitive calls are recorded with provenance, and stages only advance when the required evidence is typed and present.

## Who It's For

- **Researchers** running literature-heavy projects (PhD, applied labs, industry research) who want an agent in the loop while keeping the loop reviewable.
- **Agent engineers** building domain harnesses on top of MCP clients (Claude Code, Codex, custom runners) who need a worked reference for state, gates, and provenance.
- **Reproducibility-minded teams** that need citation integrity and number-to-experiment traceability on artifacts an agent produced.

Best fit when a human reviews artifacts at stage boundaries — that is where the design effort is concentrated.

## Quickstart

Requires Python 3.10+. One LLM API key (OpenAI, Anthropic, or Kimi) is enough to start.

```bash
git clone https://github.com/your-org/research-harness.git
cd research-harness
./setup.sh                    # creates venv, installs the three packages
cp .env.example .env          # add one API key
rh topic init "my-topic"      # registers a research topic
```

Verify the install:

```bash
python -m pytest packages/ -q --ignore=packages/research_harness_eval
# 987+ passed
```

See [`docs/quickstart.md`](docs/quickstart.md) for the full setup walkthrough, including Conda, GPU, and offline notes.

## A First End-to-End Run

Same autonomous workflow, three entry points — pick the one that fits your session. All three drive the project through the six stages and pause at the same human-only checkpoints (direction selection, experiment-design approval, finalize). All three write to the same `pool.db`, so you can start in one and resume in another.

Running example below: a two-seed project on *diffusion-bidding*, running `init → build → analyze → propose`, then stopping before `experiment` for human review.

### 1. Vibe-coding — Claude Code / Codex over MCP

With the `research-harness` MCP server configured (see [MCP — Claude Code](#mcp--claude-code)), drive the run in natural language. The agent calls `orchestrator_resume` with `stop_before="experiment"`:

```
You:   Start a research project "paper-01" under topic "diffusion-bidding".
       Seed papers: arXiv 2407.15686 and 2404.10702. Run the pipeline up to
       the experiment stage, then stop for me to review the direction.

Agent: [calls paper_ingest twice, orchestrator_init, orchestrator_resume
        with mode="standard", stop_before="experiment"]
       Ran init → build → analyze → propose. Paused before `experiment`.
       direction_ranking artifact has 3 candidates (scored 4.6 / 4.1 / 3.8);
       gap_detect found 7 open gaps; adversarial_review raised 2 objections
       on candidate #1. Want me to open them?

You:   Show candidate #2's artifact, then resume to the next checkpoint.

Agent: [calls orchestrator_artifacts, reads candidate #2, then
        orchestrator_resume with stop_before="finalize"]
       ...
```

This is the canonical flow when the driver is an agent. Every tool call the agent makes is recorded in `pool.db` alongside the artifacts, so a teammate opening the same database later sees the full trail.

### 2. CLI — `rh auto-runner`

Same flow, scripted. No MCP client required — suited for CI, cron, or remote shells.

```bash
# Seed the topic and ingest starter papers
rh topic init "diffusion-bidding"
rh paper ingest --arxiv-id 2407.15686 --topic diffusion-bidding
rh paper ingest --arxiv-id 2404.10702 --topic diffusion-bidding

# Create the project and launch the autonomous runner
rh project add --topic diffusion-bidding --name paper-01
rh auto-runner start --project-id 1 --mode standard \
  --direction "Hierarchical diffusion planner for cross-channel budget allocation"

# Runner advances init → build → analyze → propose, then pauses at a human
# checkpoint. Review the artifacts it produced:
rh auto-runner status     --project-id 1
rh orchestrator artifacts --topic diffusion-bidding --project paper-01 --stage propose

# Resume — runner continues until the next human checkpoint.
rh auto-runner resume --project-id 1
```

### 3. Python — `run_project` directly

Same flow as a function call. Useful inside a notebook, a larger training pipeline, or any code that already imports `research_harness`.

```python
from research_harness.auto_runner.runner import run_project, resume_project, get_status
from research_harness.api import ResearchAPI

api = ResearchAPI()                                    # resolves pool.db from env
topic_id   = api.topic_init("diffusion-bidding")
api.paper_ingest(arxiv_id="2407.15686", topic_id=topic_id)
api.paper_ingest(arxiv_id="2404.10702", topic_id=topic_id)
project_id = api.project_add(topic_id=topic_id, name="paper-01")

result = run_project(
    project_id,
    topic_id=topic_id,
    direction="Hierarchical diffusion planner for cross-channel budget allocation",
    mode="standard",
)
# result = {"status": "paused", "current_stage": "propose", ...}

# human review here — inspect artifacts, edit, decide
print(get_status(project_id))

# resume to the next checkpoint (or to completion)
run_again = resume_project(project_id)
```

---

What makes this more than a scripted `for`-loop, regardless of entry point:

- Each stage writes **typed artifacts** into `pool.db` — gap maps, claim tables, proposals, draft sections — and the runner will not cross a stage boundary unless the gate at that boundary accepts them.
- Every LLM call routed by the runner goes through `TrackedBackend`, so `rh provenance list` can show exactly which model produced which artifact, at what cost, and from which inputs.
- The runner is resumable: stop it, swap the model, clone the database to another machine — `resume` picks up at the last checkpoint, whichever entry point launched the run.

For a purely manual walkthrough (one primitive at a time, no runner), see [`docs/quickstart.md`](docs/quickstart.md).

## Interfaces

All three clients call the same primitive registry against the same `pool.db`. Pick whichever fits the task.

| Surface | Best for | Entry point |
|---------|----------|-------------|
| **MCP server** | Claude Code / Codex / any MCP client | `python -m research_harness_mcp` |
| **Python API** | Notebooks, pipelines, existing code | `from research_harness import ResearchAPI` |
| **`rh` CLI** | Terminal workflows, scripts, CI | `rh --help` |

Provenance note: MCP server and `rh primitive exec` route calls through `TrackedBackend`, which records every execution. Direct Python API calls go straight to primitive implementations — wrap them in `TrackedBackend` yourself when auditability is required. See [`docs/python-api.md`](docs/python-api.md).

### MCP — Claude Code

`.claude/settings.json` (project) or `~/.claude/settings.json` (global):

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "/absolute/path/to/research-harness/.venv/bin/python",
      "args": ["-m", "research_harness_mcp"],
      "env": { "RESEARCH_HARNESS_DB_PATH": "/absolute/path/to/pool.db" }
    }
  }
}
```

### MCP — Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.research-harness]
command = "/absolute/path/to/research-harness/.venv/bin/python"
args = ["-m", "research_harness_mcp"]
env = { "RESEARCH_HARNESS_DB_PATH" = "/absolute/path/to/pool.db" }
startup_timeout_sec = 30.0
```

Or via CLI: `codex mcp add research-harness -- /abs/path/python -m research_harness_mcp`.

## Skills for Vibe Coding

In Claude Code or Codex the usual driver is natural language — you describe the task and the agent routes to the right skill, which in turn calls the right MCP tools. Fourteen skills ship in [`codex-skills/`](codex-skills/) as portable Claude Code skill files (standard YAML-frontmatter format); drop the folder into your skills directory and triggers from the table below start working.

### Catalog

| Skill | What it does | Example natural-language trigger |
|-------|--------------|----------------------------------|
| [`research-harness`](codex-skills/research-harness/SKILL.md) | Router — picks the right sub-skill when intent is broad | "let's start a research workflow" |
| [`research-init`](codex-skills/research-init/SKILL.md) | Bootstrap a topic and scaffold project files | "initialize a new topic on X" |
| [`literature-search`](codex-skills/literature-search/SKILL.md) | Broad paper discovery from a query | "find recent work on diffusion bidding" |
| [`literature-mapping`](codex-skills/literature-mapping/SKILL.md) | Cluster papers, identify baselines, build topic map | "build a literature map of this topic" |
| [`citation-trace`](codex-skills/citation-trace/SKILL.md) | Expand from seed papers via references and citations | "expand the pool from these three seeds" |
| [`paper-sync`](codex-skills/paper-sync/SKILL.md) | Health-check the pool: metadata, PDFs, dismissals | "sync my paper pool" |
| [`paper-verify`](codex-skills/paper-verify/SKILL.md) | Verify a paper exists and matches claimed metadata | "is this DOI real?" |
| [`claim-extraction`](codex-skills/claim-extraction/SKILL.md) | Extract structured claims from papers | "pull the key claims out of paper 42" |
| [`gap-analysis`](codex-skills/gap-analysis/SKILL.md) | Surface open questions and missing baselines | "what are the gaps here?" |
| [`evidence-gating`](codex-skills/evidence-gating/SKILL.md) | Decide whether a stage can advance | "am I ready to move to the propose stage?" |
| [`section-drafting`](codex-skills/section-drafting/SKILL.md) | Draft paper sections from linked evidence | "draft the related-work section" |
| [`provenance-review`](codex-skills/provenance-review/SKILL.md) | Audit what was run, recorded, and linked | "review provenance for this project" |
| [`research-primitives`](codex-skills/research-primitives/SKILL.md) | Reference — every MCP primitive at a glance | "show me the primitive reference" |
| [`task-taxonomy`](codex-skills/task-taxonomy/SKILL.md) | Reference — model routing and task classification | "which tier should I use for claim extraction?" |

### Examples — natural language to skill routing

- "Start a new project on hierarchical diffusion bidding and pull 20–30 recent papers" → `research-init` → `literature-search`
- "Grow the pool from these two seed arXiv IDs" → `citation-trace`
- "I've ingested 80 papers — where are the research gaps?" → `claim-extraction` → `gap-analysis`
- "Draft the related-work section from the extracted claims" → `section-drafting`
- "Have I recorded enough to advance to the experiment stage?" → `evidence-gating`
- "Audit what was done on this project last week" → `provenance-review`

### Installing into Claude Code

```bash
# Option A: symlink the shipped skills into your user-global skills directory
mkdir -p ~/.claude/skills
ln -s "$(pwd)/codex-skills"/* ~/.claude/skills/

# Option B: project-local
mkdir -p .claude/skills
cp -r codex-skills/* .claude/skills/
```

Codex picks them up from `codex-skills/` directly. Both clients respect the same `SKILL.md` format — the triggers in the catalog above work in either.

## Trust Model

Three mechanisms, each specified in more detail in [`docs/architecture.md`](docs/architecture.md).

**Provenance.** Calls routed through `TrackedBackend` (MCP server and `rh primitive exec`) are recorded with model, tier, cost, input/output hash, and dependency edges (`derived_from`, `consumed_by`). Inspect via `rh provenance list` or plain SQL. Direct Python API calls go to primitive implementations directly; wrap them in `TrackedBackend` when auditability is required.

**Stage gates.** A stage is a named step in `init → build → analyze → propose → experiment → write`; a gate is the typed check that runs at the stage boundary. Gates inspect the artifacts the current stage produced and keep the pipeline from advancing when required evidence is missing. A gate is a check over artifact types, evaluated by code.

**Verified number registry.** During the `write` stage, numbers appearing in draft text can be checked against a registry built from recorded experiment metrics. `paper_verify_numbers` compares draft numbers to the registry with configurable tolerance and section-specific strictness (strict sections flag unmatched numbers as errors; lenient sections flag as warnings). Always-allowed values (common constants, years, dataset sizes once registered) are excluded from the check. This catches fabricated numerics at review time; it does not replace the reviewer.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│   MCP server (112 tools, stdio transport)                    │
├──────────────────────────────────────────────────────────────┤
│   Orchestrator                                               │
│     init → build → analyze → propose → experiment → write    │
│     gates: approval · coverage · adversarial · review ·      │
│            experiment                                        │
├──────────────────────────────────────────────────────────────┤
│   Primitives (69)      Provenance         Observation        │
│   typed operations     audit trail        strategy evolution │
├──────────────────────────────────────────────────────────────┤
│   Execution backends (LLM routing, local, plugin)            │
├──────────────────────────────────────────────────────────────┤
│   SQLite pool.db (papers · artifacts · provenance · tasks)   │
└──────────────────────────────────────────────────────────────┘
```

**Dual-axis execution.** Two independent dials:

- `workflow_mode` ∈ {`explore`, `standard`, `strict`, `demo`} — controls depth, coverage, and quality thresholds.
- `autonomy_mode` ∈ {`supervised`, `autonomous`} — controls who resolves gates. High-risk stages (direction selection, finalize) always require human approval, even in autonomous mode.

**Cross-model adversarial review.** Proposals and drafts pass through an independent challenger model at checkpoints where self-consistency is insufficient (e.g. `propose → experiment`). The challenge, response, and resolution are each recorded as first-class artifacts.

## Extensibility

New capabilities ship as plugins described by a `plugin.yaml` manifest.

```yaml
# plugin.yaml
name: my-paper-source
version: 0.1.0
description: Custom paper source integration
author: Your Name
license: PolyForm-Noncommercial-1.0.0
schema_version: 1
min_harness_version: 0.1.0
extension_points:
  primitives:
    - name: my_search
      category: RETRIEVAL
      module: my_plugin.search
      function: search_impl
      requires_llm: false
```

Primitives are registered via `@register_primitive(spec)`; gates subclass `GateEvaluator`; backends implement `ExecutionBackend`. Full manifest schema, extension-point reference, and discovery flow live in [`docs/plugin-guide.md`](docs/plugin-guide.md).

## Documentation

| Document | What's in it |
|----------|--------------|
| [`docs/quickstart.md`](docs/quickstart.md) | Install, API keys, first topic |
| [`docs/architecture.md`](docs/architecture.md) | Stages, gates, artifact types, storage model |
| [`docs/agent-guide.md`](docs/agent-guide.md) | Driving the harness from Claude Code / Codex |
| [`docs/python-api.md`](docs/python-api.md) | Using the harness without an MCP client |
| [`docs/plugin-guide.md`](docs/plugin-guide.md) | Writing custom primitives, gates, backends |
| [`docs/PAPER_MANAGEMENT.md`](docs/PAPER_MANAGEMENT.md) | Canonical paper-storage protocol |

## Recent Updates

A running log of the iterations that shape the public fork. Most recent first.

### 2026-04-22 — CI green on public fork

- Dropped Python 3.10 from the CI matrix; `research_harness_mcp` already required `>=3.11`.
- Cleaned up 212 ruff findings (`F401`, `F541`, `E402`, `F821`, `F841`, `E741`) across `llm_primitives.py`, `orchestrator/service.py`, `auto_runner/*`, `paper_source_clients.py`, and several test files; applied `ruff format`.
- Restored missing re-exports so `from writing_checks import REVIEW_DIMENSIONS` and `from orchestrator.review import REVIEW_DIMENSIONS` resolve to the unified dimension sources.
- Taught tests to run without a real LLM key: module-level `skipif` on the paperindex LLM tests and on `TestE2ELiteratureReview`, plus an autouse conftest fixture that stubs `PaperIndexer.build_card` when no provider is configured. Previously 22 CI tests failed with `401` / `No LLM provider`; now all 987+ pass in a keyless runner.

## Status

**Version 0.1.0** — first public release. 987+ tests across the three packages, 69 primitives, 112 MCP tools, 6 stages. See [`CHANGELOG.md`](CHANGELOG.md) for the release notes.

Supported LLM providers: OpenAI, Anthropic, Kimi/Moonshot. Qwen, DeepSeek, and GLM through the tier-routing system are on the near-term roadmap.

Known limits:

- The experiment stage requires user-supplied compute; Research Harness does not provision training jobs.
- `figure_generate` requires a fal.ai API key.
- Number verification covers values emitted by recorded experiments; numbers originating outside the system (e.g. cited baselines) need to be registered as always-allowed or reviewed manually.

## Citation

If you use Research Harness in academic work, please cite:

```bibtex
@software{research_harness_2026,
  title        = {Research Harness: an agent harness for scientific literature},
  author       = {Research Harness Contributors},
  year         = {2026},
  version      = {0.1.0},
  url          = {https://github.com/your-org/research-harness},
  license      = {PolyForm-Noncommercial-1.0.0}
}
```

## License

[PolyForm Noncommercial License 1.0.0](LICENSE). Contributions are licensed under the same.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Issues and PRs are welcome; small fixes can skip RFC, while new primitives, gates, or stages should open an issue first.

## Acknowledgements

Built on [MCP](https://modelcontextprotocol.io). Literature data from [Semantic Scholar](https://www.semanticscholar.org), [OpenAlex](https://openalex.org), [arXiv](https://arxiv.org), and [Unpaywall](https://unpaywall.org).

## Related Projects

Related work in the agent-harness space — each targets a different workload:

- [`anthropics/claude-code`](https://github.com/anthropics/claude-code) — agentic coding in the terminal.
- [`SWE-agent/SWE-agent`](https://github.com/SWE-agent/SWE-agent) — issue-solving harness for software benchmarks.
- [`All-Hands-AI/OpenHands`](https://github.com/All-Hands-AI/OpenHands) — general developer agent platform.
- [`langchain-ai/langgraph`](https://github.com/langchain-ai/langgraph) — low-level orchestration framework for stateful agents.
