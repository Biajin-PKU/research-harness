# Deep Reading Architecture Design

## Decision: Separate DeepReadingNote layer (Option B)

PaperCard = objective extraction (34 fields, frozen, single-PDF scope).
DeepReadingNote = subjective analysis (7 fields, context-dependent, pool-aware).

These are fundamentally different concerns — don't mix them.

## Storage

Reuse `paper_annotations` table:

```sql
-- One row per deep-read paper
INSERT INTO paper_annotations (paper_id, section, content, source, confidence, extractor_version)
VALUES (?, 'deep_reading', ?, 'codex:gpt-5.4', 0.85, 'v1');
```

`content` is JSON-serialized `DeepReadingNote`.

## Schema: DeepReadingNote

```python
@dataclass(frozen=True)
class IndustrialFeasibility:
    viability: str  # "high" | "medium" | "low"
    latency_constraints: str | None = None
    data_requirements: str | None = None
    engineering_challenges: list[str] = field(default_factory=list)
    deployment_prerequisites: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class CrossPaperLink:
    target_paper_id: int
    relation_type: str  # "extends" | "contradicts" | "applies" | "improves" | "competes"
    evidence: str  # one-sentence justification

@dataclass(frozen=True)
class DeepReadingNote:
    # --- Pass 1: Deep Extraction (medium tier) ---
    algorithm_walkthrough: str          # full algorithm steps, pseudo-code level detail
    limitation_analysis: str            # author-stated limitations, deeply extracted
    reproducibility_assessment: str     # can we reproduce? datasets public? code? hyperparams?

    # --- Pass 2: Critical Analysis (heavy tier) ---
    critical_assessment: str            # method soundness, experiment fairness, novelty evaluation
    industrial_feasibility: IndustrialFeasibility
    research_implications: list[str]    # what this means for OUR research direction (topic-aware)
    cross_paper_links: list[CrossPaperLink]  # relations to other papers in the pool
```

## Affiliation Enrichment: Separate Primitive

```python
def enrich_affiliations(paper_id: int, pdf_first_page_text: str, existing_affiliations: list[str]) -> list[str]:
    """
    1. Extract email domains from PDF text (body + footer)
       e.g., @google.com → Google, @tsinghua.edu.cn → Tsinghua University
    2. Extract explicit affiliation text near author names
    3. Merge with existing S2/OpenAlex affiliations
    4. Deduplicate and write back to papers.affiliations
    """
```

- **LLM tier**: light (pattern matching + short merge prompt)
- **Trigger**: runs as part of deep reading pipeline, or standalone batch
- **Output**: updates `papers.affiliations` column directly

## Execution Pipeline

```
PDF available?
  ├── Yes → Step 1: PaperCard extraction (existing, medium tier)
  │         Step 2: Affiliation enrichment (light tier)
  │         Step 3: Deep Reading Pass 1 — extraction (medium tier)
  │              Reads: full PDF sections (not just card's 4000-char clips)
  │              Produces: algorithm_walkthrough, limitation_analysis, reproducibility_assessment
  │         Step 4: Deep Reading Pass 2 — analysis (heavy tier)
  │              Reads: card + pass 1 output + topic context + pool summary
  │              Produces: critical_assessment, industrial_feasibility, research_implications, cross_paper_links
  │         Step 5: Store DeepReadingNote as paper_annotation
  └── No → Skip (need PDF first)
```

## LLM Tier Routing

| Step | Tier | Default Route | Why |
|------|------|--------------|-----|
| Card extraction | medium | cursor_agent:gpt-5.4-medium | Structured extraction, well-constrained |
| Affiliation enrichment | light | cursor_agent:composer-2-fast | Pattern matching |
| Deep reading pass 1 | medium | cursor_agent:gpt-5.4-medium | Deep extraction, no judgment needed |
| Deep reading pass 2 | heavy | codex:gpt-5.4 | Requires critical judgment + cross-paper synthesis |

## Primitive Consumption

How existing primitives benefit from deep reading data:

| Primitive | Current Input | + Deep Reading |
|-----------|--------------|----------------|
| claim_extract | card.core_idea, contributions, key_results | + algorithm_walkthrough (richer claims) |
| gap_detect | card.related_work, limitations, assumptions | + critical_assessment, limitation_analysis, cross_paper_links |
| baseline_identify | card.baselines, metrics, results | + reproducibility_assessment, industrial_feasibility |
| section_draft | card.method_summary, pipeline, math | + algorithm_walkthrough (more detailed method writing) |
| consistency_check | card.contributions, results, evidence | + critical_assessment (known issues to check against) |

Implementation: modify `_get_paper_text()` in `llm_primitives.py` to include `deep_reading` annotation sections when available.

## Paper Selection for Deep Reading

Not every paper gets deep-read. Selection criteria:

1. **Relevance >= 0.9** (12 papers) → always deep read
2. **Relevance >= 0.85 AND citation_count >= 10** → deep read
3. **Relevance >= 0.8 AND citation_count >= 50** → deep read
4. **User-flagged** → manual selection via MCP tool

Estimated: ~25-30 papers for auto-bidding topic.

## New MCP Tools

```
deep_read_paper(paper_id, topic_id)     → runs full pipeline, returns DeepReadingNote
deep_read_batch(topic_id, criteria)     → batch deep reading for selected papers
enrich_affiliations(paper_id)           → email domain extraction + merge
get_deep_reading(paper_id)              → retrieve stored DeepReadingNote
```

## File Changes Required

1. `packages/paperindex/paperindex/cards/deep_reading.py` — DeepReadingNote schema + prompts
2. `packages/research_harness/research_harness/execution/prompts.py` — add deep reading prompt templates
3. `packages/research_harness/research_harness/execution/llm_primitives.py` — add deep_read primitive + affiliation enrichment
4. `packages/research_harness/research_harness/primitives/registry.py` — register new primitives
5. `packages/research_harness_mcp/research_harness_mcp/server.py` — expose new MCP tools
6. `packages/research_harness/research_harness/execution/llm_primitives.py` — modify `_get_paper_text()` to include deep reading data
