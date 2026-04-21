---
name: paper-sync
description: Check paper pool health, enrich metadata, download PDFs, and annotate — with relevance filtering to skip noise
allowed-tools:
  - mcp__research-harness__paper_list
  - mcp__research-harness__paper_coverage_check
  - mcp__research-harness__paper_acquire
  - mcp__research-harness__paper_dismiss
  - mcp__research-harness__topic_show
  - mcp__research-harness__topic_list
  - Read
---

# Paper Sync

Inspect the paper pool for a topic, enrich missing metadata, download available PDFs, annotate them, and produce a prioritized report of what's still missing. Filters out low-relevance noise before downloading.

## When to Use

- After `/literature-search` or `/citation-trace` to materialize newly ingested papers
- Before `/gap-analysis` or `/claim-extraction` to ensure full-text coverage
- Periodically to check pool health
- When the user asks to "sync papers", "download papers", or "check paper coverage"

## Invocation

```
/paper-sync [topic_name_or_id]
```

If no topic is specified, list topics and ask which one to sync.

## Workflow

### Phase 1: Diagnose

1. Call `mcp__research-harness__topic_show` to get topic details
2. Call `mcp__research-harness__paper_list` with the topic to get current pool state
3. Classify papers into:
   - **Complete**: status=annotated, has PDF + structure + annotations
   - **Needs download**: status=meta_only, has identifier (arxiv_id or doi), relevance != low
   - **Needs enrichment**: missing title or abstract, has identifier
   - **Noise candidates**: meta_only, relevance=low, no direct connection to topic focus
   - **Unreachable**: no identifier, no URL, no PDF

4. Report diagnosis to user:
   ```
   Paper Pool Health for "topic-name":
   - Complete: XX papers (XX%)
   - Needs download: XX papers
   - Needs enrichment: XX papers
   - Noise candidates: XX papers (suggest dismiss)
   - Unreachable: XX papers
   ```

### Phase 2: Filter Noise

Before downloading, review noise candidates:

1. For papers with relevance=low AND no annotations AND no PDF:
   - Check if their title/abstract mentions core topic keywords
   - If clearly unrelated, call `mcp__research-harness__paper_dismiss` with reason
   - If uncertain, keep and let the user decide

2. Report dismissals:
   ```
   Dismissed X noise papers: [list with reasons]
   ```

### Phase 3: Acquire

1. Call `mcp__research-harness__paper_acquire` with `topic_id`
   - This automatically: enriches metadata → downloads PDFs → annotates → builds unable list

2. Report results:
   ```
   Acquisition complete:
   - Enriched: X papers (metadata from S2)
   - Downloaded + Annotated: X papers
   - Failed: X papers
   - Needs manual download: X papers
   ```

### Phase 4: Report Unable-to-Acquire

If there are papers in the `unable_to_acquire` list:

1. Present them sorted by relevance (high first):
   ```
   Unable to acquire (sorted by importance):
   
   HIGH:
   - [paper_id] Title (DOI: xxx) — reason: paywalled
     Hint: https://doi.org/xxx
   
   MEDIUM:
   - [paper_id] Title — reason: no downloadable URL
   
   LOW:
   - (suggest dismissing these)
   ```

2. For high-relevance papers, suggest:
   - Manual download via institutional access
   - PKU proxy URLs if applicable
   - Alternative sources (preprint versions, author pages)

3. For low-relevance unable papers, suggest dismissing them

## Output

End with a summary table:

```
Paper Pool Summary (after sync):
| Status     | Count | % |
|------------|-------|---|
| Annotated  | XX    | X |
| Meta-only  | XX    | X |
| Total      | XX    |   |

Coverage: XX% of papers have full-text annotations
Next: /gap-analysis or /claim-extraction
```

## Notes

- `paper_acquire` respects S2 API rate limits (1 req/s with key)
- PDF annotation uses `skip_card=True` by default (fast, no LLM for card)
- Papers already annotated are skipped automatically (idempotent)
- Dismissed papers are excluded from future syncs and coverage checks
