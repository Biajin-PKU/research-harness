---
name: research-primitives
description: Reference guide for all 9 research primitive operations
allowed-tools: [Read]
---

# Research Primitives

Reference guide for all research primitive operations available via MCP tools.

---

## paper_search

| Attribute | Value |
|-----------|-------|
| **Category** | RETRIEVAL |
| **LLM Required** | No |
| **Idempotent** | Yes |

**Description:** Search for papers by query across configured providers (arXiv, Semantic Scholar, etc.)

**Input:**
- `query` (string, required): Search query
- `topic_id` (integer): Associate with topic
- `max_results` (integer): Default 20
- `year_from/year_to` (integer): Year range filter
- `venue_filter` (string): Venue substring filter

**Output:** `PaperSearchOutput`
- `papers`: List of `PaperRef` objects
- `provider`: Which provider served the query
- `query_used`: Actual query sent

**Example:**
```
mcp__research-harness__paper_search with query="transformer attention mechanism"
```

---

## paper_ingest

| Attribute | Value |
|-----------|-------|
| **Category** | RETRIEVAL |
| **LLM Required** | No |
| **Idempotent** | Yes |

**Description:** Ingest a paper into the pool by arxiv_id, doi, or pdf_path

**Input:**
- `source` (string, required): arxiv_id, DOI, or file path
- `topic_id` (integer): Associate with topic
- `relevance` (string): "high", "medium", or "low"

**Output:** `PaperIngestOutput`
- `paper_id`: Assigned ID
- `title`: Paper title
- `status`: "created" or "merged"
- `merged_fields`: Fields updated if merged

**Example:**
```
mcp__research-harness__paper_ingest with source="arxiv:2401.12345" relevance="high"
```

---

## paper_summarize

| Attribute | Value |
|-----------|-------|
| **Category** | COMPREHENSION |
| **LLM Required** | Yes |

**Description:** Generate a focused summary of a paper

**Input:**
- `paper_id` (integer, required): Paper to summarize
- `focus` (string): Specific aspect to focus on

**Output:** `SummaryOutput`
- `paper_id`: Source paper
- `summary`: Generated summary text
- `focus`: Focus area used
- `confidence`: Quality score
- `model_used`: Which model generated it

**Example:**
```
mcp__research-harness__paper_summarize with paper_id=123 focus="methodology"
```

---

## claim_extract

| Attribute | Value |
|-----------|-------|
| **Category** | EXTRACTION |
| **LLM Required** | Yes |

**Description:** Extract research claims from papers within a topic

**Input:**
- `paper_ids` (list[int], required): Papers to analyze
- `topic_id` (integer, required): Topic context
- `focus` (string): Optional focus area

**Output:** `ClaimExtractOutput`
- `claims`: List of `Claim` objects
- `papers_processed`: Count processed

**Example:**
```
mcp__research-harness__claim_extract with paper_ids=[1,2,3] topic_id=1
```

---

## evidence_link

| Attribute | Value |
|-----------|-------|
| **Category** | EXTRACTION |
| **LLM Required** | No |
| **Idempotent** | Yes |

**Description:** Link a claim to supporting evidence

**Input:**
- `claim_id` (string, required): Claim to link
- `source_type` (string, required): "paper" or "external"
- `source_id` (string, required): Source identifier
- `strength` (string): "strong", "moderate", or "weak"
- `notes` (string): Explanation

**Output:** `EvidenceLinkOutput`
- `link`: Created `EvidenceLink`
- `created`: Whether new link was created

**Example:**
```
mcp__research-harness__evidence_link with claim_id="claim_abc123" source_type="paper" source_id="1"
```

---

## gap_detect

| Attribute | Value |
|-----------|-------|
| **Category** | ANALYSIS |
| **LLM Required** | Yes |

**Description:** Detect research gaps in a topic's literature

**Input:**
- `topic_id` (integer, required): Topic to analyze
- `focus` (string): Optional focus area

**Output:** `GapDetectOutput`
- `gaps`: List of `Gap` objects
- `papers_analyzed`: Count analyzed

**Example:**
```
mcp__research-harness__gap_detect with topic_id=1 focus="evaluation methods"
```

---

## baseline_identify

| Attribute | Value |
|-----------|-------|
| **Category** | EXTRACTION |
| **LLM Required** | Yes |

**Description:** Identify baseline methods for comparison in a topic

**Input:**
- `topic_id` (integer, required): Topic to analyze
- `focus` (string): Optional focus area

**Output:** `BaselineIdentifyOutput`
- `baselines`: List of `Baseline` objects

**Example:**
```
mcp__research-harness__baseline_identify with topic_id=1
```

---

## section_draft

| Attribute | Value |
|-----------|-------|
| **Category** | GENERATION |
| **LLM Required** | Yes |

**Description:** Draft a paper section using linked evidence

**Input:**
- `section` (string, required): Section name/type
- `topic_id` (integer, required): Topic context
- `evidence_ids` (list[string]): Claims/evidence to include
- `outline` (string): Section outline
- `max_words` (integer): Target length (default 2000)

**Output:** `SectionDraftOutput`
- `draft`: `DraftText` object with content

**Example:**
```
mcp__research-harness__section_draft with section="related_work" topic_id=1
```

---

## consistency_check

| Attribute | Value |
|-----------|-------|
| **Category** | VERIFICATION |
| **LLM Required** | Yes |

**Description:** Check consistency across drafted sections

**Input:**
- `topic_id` (integer, required): Topic to check
- `sections` (list[string]): Specific sections to check (empty = all)

**Output:** `ConsistencyCheckOutput`
- `issues`: List of `ConsistencyIssue` objects
- `sections_checked`: List of sections analyzed

**Example:**
```
mcp__research-harness__consistency_check with topic_id=1 sections=["method", "results"]
```
