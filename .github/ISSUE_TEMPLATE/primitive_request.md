---
name: Primitive request
about: Request a new research primitive (MCP tool)
title: 'feat: new primitive — '
labels: primitive-request
assignees: ''
---

## Research operation to add

Name the operation you need. This will become the primitive name (snake_case), e.g. `citation_graph_build`, `venue_rank`, `ablation_summarize`.

## What stage(s) would use it

Which orchestrator stage(s) would call this primitive?
- [ ] init
- [ ] build
- [ ] analyze
- [ ] propose
- [ ] experiment
- [ ] write
- [ ] any / utility

## Proposed input/output contract

```python
# Input
{
    "topic_id": int,
    "param_a": "...",
}

# Output
{
    "result": "...",
}
```

## Why this cannot be composed from existing primitives

List the existing primitives you considered and why they fall short.

## Example use case

Describe a concrete research scenario where this primitive would be called and what it would return.

## Requires LLM call

- [ ] Yes (requires an LLM provider)
- [ ] No (deterministic / pure computation)

## Additional context

Papers, prior tools, or references that describe the operation.
