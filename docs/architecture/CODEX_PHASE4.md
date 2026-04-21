# CODEX Phase 4: Validation & Comparison

**Goal**: Generate evaluation data for S3 paper by replaying Phase 2 tasks through Research Harness backend.

## Context

- Phase 3 (Claude Code Extensions) is **COMPLETE**
- Topic `cross-budget-rebalancing` has **23 papers** ingested
- 6 paper cards already generated
- Phase 2 dogfooding log is empty, but we have actual research artifacts

## Phase 4 Architecture

```
Phase 4A: Current State Assessment
    ├── Check topic status and existing artifacts
    ├── Inventory generated cards, claims, gaps
    └── Document baseline (Claude Code) metrics

Phase 4B: Replay Experiment Design
    ├── Select representative tasks from existing work
    ├── Design experiment protocol
    └── Setup data collection templates

Phase 4C: Replay Execution
    ├── Run tasks via Research Harness backend
    ├── Record metrics: cost, time, quality, coverage
    └── Compare with baseline

Phase 4D: Ablation Studies
    ├── Routing vs All-Kimi vs All-Opus
    ├── Evidence-gated vs Fixed-step
    └── Provenance tracking overhead
```

## Tasks

### A1: Current State Assessment

**Check existing research artifacts:**

```bash
# Topic overview
python -m research_harness.cli topic show cross-budget-rebalancing

# List all papers
python -m research_harness.cli paper list --topic cross-budget-rebalancing

# Check existing cards
ls -la paper_library/papers/card_*.json

# Check tasks
python -m research_harness.cli task list --topic cross-budget-rebalancing

# Check provenance
python -m research_harness.cli provenance summary --topic cross-budget-rebalancing
```

**Document in** `docs/dogfooding_log.md`:
- Number of papers ingested: 23
- Paper cards generated: 6
- Tasks created: (to check)
- Current research stage: (to determine)

### A2: Replay Experiment Design

**Create** `docs/experiments/phase4_replay_protocol.md`:

Select 3-5 representative tasks based on existing work:

| Task | Baseline Source | Harness Execution | Metrics |
|------|----------------|-------------------|---------|
| paper_summarize | 6 existing cards | Re-run on 3 papers | time, cost, quality(1-5) |
| claim_extract | (none yet) | Run on 5 papers | time, cost, coverage |
| gap_detect | (none yet) | Run on topic | time, cost, gaps found |
| section_draft | (none yet) | Draft intro section | time, cost, word count |

**Quality Evaluation Protocol:**
- Blind comparison: Human rates outputs 1-5
- Coverage: Claim-evidence graph density
- Time: Wall-clock from task start to result
- Cost: API spend (logged by provenance system)

### A3: Replay Execution

**Execute via Research Harness backend:**

Use `python -m research_harness.cli` commands or MCP tools with backend routing.

Key primitives to replay:
1. `paper_summarize` - Long context comprehension
2. `claim_extract` - Structured extraction
3. `gap_detect` - Cross-paper analysis
4. `section_draft` - Generation task

**Record in** `docs/experiments/phase4_results.md`:

```markdown
## Experiment Run: YYYY-MM-DD

### Task: paper_summarize
- Paper: [arxiv_id]
- Backend: Research Harness (Kimi routing)
- Time: X seconds
- Cost: $Y
- Output quality: [rate 1-5]
- Baseline comparison: [if available]

### Task: claim_extract
...
```

### A4: Ablation Studies

**Study 1: Model Routing Strategy**

Run same task with 3 configurations:
- Config A: Task-aware routing (default)
- Config B: All-Kimi
- Config C: All-Opus

Metrics: cost, quality, time

**Study 2: Evidence Gating**

Compare:
- With evidence gates (manual mode)
- Without gates (proceed regardless)

Metrics: researcher time, output quality

**Study 3: Provenance Overhead**

Compare:
- With full provenance logging
- With minimal logging

Metrics: execution time, storage cost, debugging efficiency

## Verification

After Phase 4:

```bash
# All tests still pass
python -m pytest packages/ -q --tb=short
# Expected: 154 passed

# Experiment artifacts exist
ls docs/experiments/phase4_*.md
# Expected: protocol, results, analysis

# Dogfooding log updated
grep -c "Date:" docs/dogfooding_log.md
# Expected: >= 5 entries

# Provenance has new records
python -m research_harness.cli provenance summary --topic cross-budget-rebalancing
```

## Deliverables

| File | Description |
|------|-------------|
| `docs/experiments/phase4_replay_protocol.md` | Experiment design |
| `docs/experiments/phase4_results.md` | Raw results |
| `docs/experiments/phase4_analysis.md` | Comparison analysis |
| `docs/dogfooding_log.md` | Updated with Phase 4 entries |

## Success Criteria

- [ ] 3+ tasks replayed through Research Harness
- [ ] Comparison metrics collected (cost, time, quality)
- [ ] Ablation study results documented
- [ ] All 154 tests still pass
- [ ] Analysis ready for S3 paper Section 5

## Next Phase

Phase 5: Paper Assembly - Write S2 and S3 papers using collected data.
