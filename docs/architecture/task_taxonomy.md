# Research Task Taxonomy

> Architecture reference for MCP server model routing. Not an invocable skill.
> Claude Code sees only tool names; routing decisions are made internally by the MCP server.

## Overview

Research primitives are organized into 7 categories based on cognitive complexity. The MCP
server uses this taxonomy to route each primitive to the optimal LLM provider, balancing
cost and quality.

## Primitive Categories

### 1. RETRIEVAL
**Primitives:** `paper_search`

**Characteristics:**
- Keyword-based search operations
- Low reasoning requirements
- Large result sets to filter

**Routing:** `kimi`
- Excellent for keyword expansion
- Cost-effective for high-volume operations
- Fast response times

---

### 2. COMPREHENSION
**Primitives:** `paper_summarize`

**Characteristics:**
- Long context understanding
- Information condensation
- Focused extraction

**Routing:** `kimi`
- Long context window (256k+)
- Low cost per token
- Good at following focus instructions

---

### 3. EXTRACTION
**Primitives:** `claim_extract`, `baseline_identify`, `evidence_link`

**Characteristics:**
- Structured output generation
- Pattern matching across text
- Precision required

**Routing:** `kimi` → `sonnet` fallback
- Kimi for initial extraction
- Sonnet for complex or ambiguous cases
- Fallback triggered on parsing failures

---

### 4. ANALYSIS
**Primitives:** `gap_detect`, `paper_coverage_check`

**Characteristics:**
- Cross-paper reasoning
- Synthesis of multiple sources
- Identifying patterns and gaps

**Routing:** `sonnet` → `opus` fallback
- Sonnet for standard analysis
- Opus for deep, complex analysis
- Higher reasoning requirements

---

### 5. SYNTHESIS
**Primitives:** `hypothesis_gen` (planned)

**Characteristics:**
- Creative generation
- Novel connection formation
- Deep reasoning required

**Routing:** `opus`
- Highest reasoning capability
- Best for creative research insights
- Worth the higher cost

---

### 6. GENERATION
**Primitives:** `section_draft`

**Characteristics:**
- Fluent text generation
- Academic writing style
- Coherent argument structure

**Routing:** `sonnet`
- Excellent writing quality
- Good academic tone
- Cost-effective for long outputs

---

### 7. VERIFICATION
**Primitives:** `consistency_check`

**Characteristics:**
- Full-document reasoning
- Cross-reference validation
- Quality assurance

**Routing:** `opus`
- Highest accuracy for verification
- Can handle complex consistency checks
- Critical for final quality gates

---

## Implementation

Routing is implemented in `packages/research_harness/research_harness/execution/` via the primitive
registry (`registry.py`) and harness dispatch. Each `PrimitiveSpec` carries a category tag;
the harness selects the provider based on this taxonomy.

This taxonomy is the authoritative reference for debugging routing decisions or adding new
primitives. When adding a new primitive, assign it to one of the 7 categories above and
update `registry.py` accordingly.
