---
name: evidence-gating
description: Decide whether a research stage has enough evidence to advance in Research Harness. Trigger on phrases like "evidence-gating", "/evidence-gating", "证据门控", "现在能推进吗", or equivalent requests to check whether current literature, claims, and artifacts justify moving to the next stage.
---

# Evidence Gating

Use this skill when the user asks whether the work is ready to advance.

## Workflow

1. Identify the current stage or infer it from project state.
2. Review available papers, claims, artifacts, and unresolved objections.
3. Use orchestrator checks if available.
4. Return a clear decision:
   - pass
   - pass with caveats
   - fail
5. List the minimum missing evidence required to pass.
