---
name: literature-search
description: Run comprehensive literature search for Research Harness. Trigger on phrases like "literature-search", "/literature-search", "文献检索", "系统检索论文", "帮我搜相关论文", or equivalent requests to search, shortlist, and ingest relevant papers.
---

# Literature Search

Use this skill for broad paper discovery.

## Workflow

1. Read `~/code/research-harness/docs/agent-guide.md` if topic context is unclear.
2. Clarify or infer:
   - research topic
   - time range
   - venue or domain constraints
3. Use `paper_search` or `rhub`-compatible search flow.
4. Deduplicate and rank results by relevance.
5. Recommend which papers to ingest and ingest them when the user intent is clearly operational rather than exploratory.

## Output

- concise search query formulation
- top relevant papers
- ingestion decision or next-step recommendation
