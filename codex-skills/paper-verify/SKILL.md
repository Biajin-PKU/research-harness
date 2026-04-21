---
name: paper-verify
description: Verify whether papers actually exist and match the claimed metadata before or after ingestion. Trigger on phrases like "paper-verify", "/paper-verify", "验证论文存在性", "核对 DOI arxiv", or equivalent requests to validate titles, identifiers, and source consistency.
---

# Paper Verify

Use this skill when paper identity or metadata may be unreliable.

## Workflow

1. Collect the candidate title, DOI, arXiv ID, authors, or PDF.
2. Cross-check metadata across available sources.
3. Highlight mismatches explicitly.
4. Only recommend ingestion when identity is sufficiently verified.
