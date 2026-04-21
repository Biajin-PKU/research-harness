# Local Multi-Agent Workflow

This project can support Claude Code, Codex, Cursor, and Kimi in a local-only
workflow without pushing to any remote repository.

## Goals

- Keep one shared task record across tools.
- Reduce context-switch cost between agents.
- Use local Git for isolation, diff, and rollback only.

## Recommended Operating Model

### Roles

- Claude Code: primary driver for the active task in the main working tree
- Codex: parallel implementation or deeper refactor in a separate local branch
- Cursor: IDE-heavy work or asynchronous background task
- Kimi: low-cost exploration, log triage, test-plan drafting, or first-pass code

### Shared Memory

All agents should read and update:

- `.agent/SESSION.md`
- `.agent/TODO.md`
- `.agent/LOCKS.md`
- `.agent/HANDOFF.md`
- `.agent/LOG.jsonl`

### Local Git Only

You do not need a remote repository for this workflow.

Suggested branch naming:

- `claude/<task>`
- `codex/<task>`
- `cursor/<task>`
- `kimi/<task>`

Suggested worktree naming:

- `../research-harness-claude-<task>`
- `../research-harness-codex-<task>`
- `../research-harness-cursor-<task>`
- `../research-harness-kimi-<task>`

Example commands:

```bash
git switch -c codex/refactor-search
git worktree add ../research-harness-codex-refactor-search -b codex/refactor-search
git worktree add ../research-harness-kimi-test-plan -b kimi/test-plan
```

## Daily SOP

1. Open the main repo in your terminal multiplexer.
2. Read `.agent/SESSION.md` and `.agent/TODO.md`.
3. Claim files in `.agent/LOCKS.md` before editing.
4. Run each agent in the branch or worktree assigned to it.
5. Record meaningful actions in `.agent/LOG.jsonl`.
6. Update `.agent/HANDOFF.md` before switching tools.
7. Merge or replay the accepted local changes into your main branch.

## tmux Layout

Recommended four-pane layout:

- Pane 1: Claude Code on main task
- Pane 2: Codex on isolated branch or worktree
- Pane 3: Cursor or Kimi on side task
- Pane 4: tests, diff, notes, and merge commands

## Minimal Concurrency Rules

- One active writer per file
- Prefer separate worktrees for risky or wide changes
- Merge only after validation
- Keep `TODO.md` small and current

## Suggested LOG.jsonl Events

```json
{"ts":"2026-04-04T09:30:00Z","agent":"claude","action":"lock","paths":["src/auth.ts"],"note":"Starting auth bug fix"}
{"ts":"2026-04-04T09:42:00Z","agent":"kimi","action":"analysis","note":"Drafted test cases for auth edge cases"}
{"ts":"2026-04-04T10:05:00Z","agent":"codex","action":"handoff","note":"Refactor ready for review on codex/refactor-search"}
```

## What This Solves

- Shared context across paid tools
- Lower switching overhead
- Local rollback and auditability
- Cleaner parallel work without depending on remote hosting
