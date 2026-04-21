---
name: claim-extraction
description: Extract core claims from papers for Research Harness evidence structuring. Trigger on phrases like "claim-extraction", "/claim-extraction", "提取论文声明", "claim extract", or equivalent requests to identify key claims, evidence, assumptions, and limitations from ingested papers.
---

# Claim Extraction

Use this skill when the user needs structured claims from papers.

## Workflow

1. Identify the target papers and topic focus.
2. Use `claim_extract` when available.
3. Organize outputs into:
   - key claims
   - supporting evidence
   - assumptions
   - limitations or contradictions
4. Preserve paper identifiers so later steps can cite them.
