-- Make `contributions` a project-level configuration rather than a
-- per-call argument. Before this, writing_architecture / outline_generate /
-- figure_plan / competitive_learning each required the caller to pass the
-- contributions string, which led to:
--   1. Repetition — same string copy-pasted across 4+ calls per paper.
--   2. Drift — easy to forget on follow-up calls, causing the LLM to
--      hallucinate unrelated paper titles (ModalGate "SAGE-Fuse" bug).
--   3. No single source of truth — changes in one call do not propagate.
--
-- Now each project has a single authoritative `contributions` field.
-- Downstream writing primitives read from here when the caller omits
-- the argument. Explicit argument still wins (for one-off overrides).

ALTER TABLE projects ADD COLUMN contributions TEXT NOT NULL DEFAULT '';
