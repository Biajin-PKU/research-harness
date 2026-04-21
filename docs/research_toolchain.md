# Research Toolchain — Unified Overview

This document provides a single source of truth for all research-oriented automation components in the `/workspace/research-harness` project.

## 1. Philosophy

All tooling follows an **evidence-driven, tracked, and staged** research workflow:
- **Retrieval** discovers papers.
- **Extraction** mines claims, baselines, and evidence.
- **Analysis** detects gaps and evaluates novelty.
- **Generation** drafts sections and proposals.
- **Verification** ensures consistency across outputs.
- **Provenance** records every operation automatically.

---

## 2. Agents (`.claude/agents/`)

Agents are specialized persona prompts used in multi-agent consensus or staged research tasks.

| Agent | Purpose |
|-------|---------|
| `adversarial-resolver` | Resolve conflicts between contradicting claims or baselines. |
| `challenger` | Critique weak evidence and demand stronger support. |
| `literature-mapper` | Systematic literature search using iterative retrieval. |
| `proposer` | Generate research proposals from mapped literature. |
| `synthesizer` | Synthesize fragmented findings into coherent narratives. |

---

## 3. Skills (`.claude/skills/`)

Skills are reusable workflow guides invoked via the Claude Code skill system.

| Skill | Stage | Core Operations |
|-------|-------|-----------------|
| `claim-extraction` | Extraction | Mine structured claims from paper sets. |
| `evidence-gating` | Verification | Attach and weight evidence to claims. |
| `gap-analysis` | Analysis | Detect missing comparisons and open problems. |
| `literature-mapping` | Retrieval | Iteratively search, ingest, and organize papers. |
| `provenance-review` | Meta | Review cost, success rate, and operation history. |
| `research-primitives` | Reference | Quick reference for all 9 primitive operations. |
| `section-drafting` | Generation | Draft sections backed by linked evidence. |
| *(task-taxonomy removed — see docs/architecture/task_taxonomy.md)* | Reference | MCP routing taxonomy; not an invocable skill. |

---

## 4. Hooks (`.claude/hooks/`)

Hooks run automatically during Claude Code sessions to maintain observability.

| Hook | Trigger | Purpose |
|------|---------|---------|
| `record-provenance.py` | After `mcp__research-harness__*` or `mcp__pasa_search__*` tool calls | Record operation history into the research pool DB. |
| `session-summary.py` | Session stop (`Stop` hook) | Generate a brief summary of the session. |

---

## 5. MCP Servers

### 5.1 `research-harness` (Local)
- **Entry point**: `packages/research_harness_mcp/research_harness_mcp/server.py`
- **Transport**: stdio
- **Purpose**: Exposes the full research-harness primitive and convenience API.

**Tool categories:**
- **Primitives** (auto-generated from `PRIMITIVE_REGISTRY`):
  - `paper_search`, `paper_ingest`, `paper_summarize`
  - `claim_extract`, `evidence_link`, `baseline_identify`
  - `gap_detect`, `section_draft`, `consistency_check`
- **Convenience queries**:
  - `topic_list`, `topic_show`, `paper_list`, `task_list`, `provenance_summary`
- **PaperIndex integration**:
  - `paperindex_search`, `paperindex_structure`, `paperindex_card`

### 5.2 `pasa_search` (PASA / ByteDance)
- **Entry point**: `/workspace/mcp-servers/pasa_search/server.py`
- **Transport**: stdio
- **Purpose**: Agent-based academic paper retrieval powered by PASA (`https://pasa-agent.ai`).

**Tools:**
- `search_papers(query, top_k=10)` — Single-query PASA search.
- `search_papers_multi(queries, top_k_per_query=10)` — Multi-query with deduplication.
- `generate_queries(idea, goal, max_queries, use_llm)` — Translate research ideas into search queries.
- `analyze_research_direction(idea, use_llm)` — Identify domains, methods, and search angles.
- `generate_and_search(idea, goal, max_queries, top_k_per_query, use_llm)` — End-to-end idea → queries → papers.

> **Note**: PASA search is slow by design (30–120s per query) because it executes an agentic browsing pipeline.

---

## 6. Configuration Files

### Claude Code (this project)
| File | Role |
|------|------|
| `.mcp.json` | Declares both `research-harness` and `pasa_search` MCP servers. |
| `.claude/settings.json` | Hooks: provenance recording for both MCP prefixes + session summary on stop. |
| `.claude/settings.local.json` | Permissions and explicitly enabled MCP servers (`research-harness`, `pasa_search`). |

### Codex (global)
| File | Role |
|------|------|
| `/root/.codex/config.toml` | Global MCP registration for `pasa_search` (formerly `scholarforge`). |

### ScholarForge (external reference project)
| File | Role |
|------|------|
| `/workspace/ScholarForge/.mcp.json` | Points `pasa_search` to the same server binary for ScholarForge users. |

---

## 7. Typical Workflow

1. **Scope** — Use `research-primitives` or `pasa_search.analyze_research_direction` to clarify the idea.
2. **Map** — Use `literature-mapping` skill + `pasa_search.generate_and_search` to bootstrap the paper pool.
3. **Ingest** — Use `research-harness.paper_ingest` to pull high-relevance PASA results into the local DB.
4. **Extract** — Use `claim-extraction` and `baseline_identify` to mine structured knowledge.
5. **Analyze** — Use `gap-analysis` to find what is missing.
6. **Draft** — Use `section-drafting` to write evidence-backed sections.
7. **Verify** — Use `consistency_check` and `provenance-review` to validate output quality.

Every MCP call is automatically logged into the provenance DB via the `record-provenance` hook.

---

## 8. Renaming History

- **2026-04-03**: The PASA MCP was renamed from `scholarforge` to `pasa_search` to avoid confusion with the broader `ScholarForge` framework and to make its purpose explicit.
