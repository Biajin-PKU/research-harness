# Python API

Research Harness exposes a pure-Python API that does not require any agent tool
or MCP client. You can drive the full pipeline from a notebook, script, or
integration test.

## When to use this

- Jupyter notebooks during exploratory literature review
- Custom pipelines that embed research primitives alongside your own code
- CI checks (e.g., verify that a topic's paper pool hasn't regressed)
- Testing a new primitive you are developing

For agentic workflows, use an MCP client instead (see [main README](../README.md#mcp-server--claude-code)).
For shell scripting, use the `rh` CLI.

## Setup

```bash
pip install -e "packages/research_harness[dev]"
```

Make sure your `.env` has at least one LLM provider key (see `.env.example`).

## Minimal Example

```python
from research_harness import ResearchAPI

# Auto-resolves DB path from .env / env vars (default: .research-harness/pool.db)
api = ResearchAPI()

# 1. Search papers (returns a structured result dict)
hits = api.paper_search(
    query="instruction tuning for reasoning",
    max_results=5,
    auto_ingest=True,      # save top hits into the pool
)
print(f"Found {len(hits.get('papers', []))} papers")

# 2. Ingest a specific paper by arXiv ID
result = api.paper_ingest(source="2401.12345", topic_id=1, relevance="high")
print(result)

# 3. Run any primitive by name — `execute_primitive` is the escape hatch
gaps = api.execute_primitive("gap_detect", topic_id=1, focus="reasoning benchmarks")
print(gaps)

# 4. Check orchestrator status for a project
status = api.orchestrator_status(project_id=1)
print(status["current_stage"], status["gate_status"])
```

## API Surface

The `ResearchAPI` class in `packages/research_harness/research_harness/api.py` provides
convenience wrappers for the most common operations, plus a general escape hatch:

| Method | Purpose |
|--------|---------|
| `paper_search(query, **kwargs)` | Delegate to the `paper_search` primitive |
| `paper_ingest(source, **kwargs)` | Ingest a paper by arxiv ID, DOI, or PDF path |
| `record_artifact(project_id, topic_id, stage, artifact_type, payload)` | Write a project artifact |
| `orchestrator_status(project_id)` | Stage + gate status |
| `gate_check(project_id, stage=None)` | Run the gate for a specific stage |
| `add_artifact_dependency(from_id, to_id)` | Declare lineage between artifacts |
| `mark_artifact_stale(artifact_id, reason)` | Invalidate + optionally propagate downstream |
| `list_stale_artifacts(project_id)` | What needs refreshing |
| `execute_primitive(name, **kwargs)` | **Escape hatch** — run any of the 69 primitives |

All 69 primitives are reachable via `execute_primitive("<name>", ...)`. To enumerate:

```python
from research_harness.primitives.registry import list_primitives

for spec in list_primitives():
    print(f"{spec.name:30s}  {spec.category.value:12s}  {spec.description}")
```

## Using a Custom DB Path

```python
from research_harness import ResearchAPI

api = ResearchAPI(db_path="/path/to/my/pool.db")
```

Or set `RESEARCH_HARNESS_DB_PATH` in your environment before import.

## Notebook Pattern

```python
import pandas as pd
from research_harness import ResearchAPI

api = ResearchAPI()

# Pull all papers in topic 1 into a DataFrame for ad-hoc analysis
import sqlite3
conn = sqlite3.connect(api.db_path)
df = pd.read_sql_query(
    "SELECT id, title, venue, year, citation_count FROM papers "
    "JOIN topic_papers ON papers.id = topic_papers.paper_id "
    "WHERE topic_papers.topic_id = 1",
    conn,
)
df.head()
```

The database is a plain SQLite file — read-only queries from pandas, duckdb, or
your favorite tool are safe and do not conflict with the harness.

## Running Primitives in Bulk

```python
from research_harness import ResearchAPI
from research_harness.primitives.registry import list_primitives

api = ResearchAPI()

# Summarize every paper in topic 1
summaries = []
rows = api.db.query("SELECT id FROM topic_papers WHERE topic_id = ?", (1,))
for row in rows:
    paper_id = row["paper_id"]
    result = api.execute_primitive("paper_summarize", paper_id=paper_id)
    summaries.append(result)
```

## Differences vs. MCP

| Aspect | Python API | MCP |
|--------|-----------|-----|
| Transport | in-process function calls | stdio JSON-RPC |
| Auth/sandboxing | none (runs in your process) | managed by the MCP client |
| Error handling | Python exceptions bubble up | serialized in JSON response |
| Provenance tracking | still recorded | still recorded |
| Primitive coverage | 100% (via `execute_primitive`) | 100% (112 tools auto-generated) |

Both paths hit the same primitive registry and the same database, so you can
mix them freely — e.g., use the Python API in a Jupyter notebook to prep data,
then switch to Claude Code for an agentic write-up session.

## Further Reading

- [Primitive reference](../packages/research_harness/research_harness/primitives/) — every `*_impls.py` module lists its specs
- [Orchestrator stages](architecture/06_orchestrator.md) — gate and artifact specifications
- [Plugin guide](plugin-guide.md) — adding your own primitives
