# Remote Dev SOP

This setup is designed for:

- Mac local terminal: kitty
- Network resilience: mosh
- Server/container session persistence: tmux
- Project context sharing: .agent/

## Recommended Connection Path

### If you connect to a server host first, then enter Docker

1. From your Mac:

```bash
mosh <user>@<server>
```

2. On the server host, enter the target container.

Example:

```bash
docker exec -it <container_name> bash
```

3. In the container:

```bash
cd /workspace/research-harness
source ~/.bashrc
direnv allow .
agents
```

Important:

- `mosh-server` must be installed on the first machine you log into.
- If your normal flow is `Mac -> host -> container`, then the host needs `mosh`.
- The container does not need to be the direct `mosh` target unless you log into it directly.

### If you connect directly to this environment

```bash
mosh <user>@<server>
cd /workspace/research-harness
source ~/.bashrc
direnv allow .
agents
```

## Daily Commands

Project bootstrap:

```bash
croot
source ~/.bashrc
direnv allow .
```

Start or attach the multi-agent tmux session:

```bash
agents
```

Useful note commands:

```bash
agent-notes
agent-todo
agent-locks
agent-handoff
```

## tmux Session Layout

The `agents` helper creates four panes:

- Pane 1: Claude Code main task
- Pane 2: Codex parallel task
- Pane 3: Kimi or Cursor side task
- Pane 4: tests, git, and `.agent` notes

## Minimal Working Rules

- Read `.agent/SESSION.md` and `.agent/TODO.md` before work.
- Claim files in `.agent/LOCKS.md` before editing.
- Use a separate local branch or worktree for risky changes.
- Write handoff notes before switching tools.

## Optional Host-Side Convenience Alias

If you want one command from the host to jump into the container, add an alias on the host machine, not inside this repo.

Example:

```bash
alias rh='docker exec -it <container_name> bash -lc "cd /workspace/research-harness && source ~/.bashrc && direnv allow . >/dev/null 2>&1 || true && agents"'
```

Adjust `<container_name>` to your real container.
