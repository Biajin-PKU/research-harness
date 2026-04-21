#!/usr/bin/env bash
set -euo pipefail

SESSION_NAME="${1:-agents}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  exec tmux attach -t "$SESSION_NAME"
fi

cd "$PROJECT_DIR"

tmux new-session -d -s "$SESSION_NAME" -c "$PROJECT_DIR"
tmux rename-window -t "$SESSION_NAME":1 main

tmux send-keys -t "$SESSION_NAME":1.1 'printf "Pane 1: Claude Code main task\n"' C-m

tmux split-window -h -t "$SESSION_NAME":1 -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION_NAME":1.2 'printf "Pane 2: Codex parallel task\n"' C-m

tmux split-window -v -t "$SESSION_NAME":1.1 -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION_NAME":1.3 'printf "Pane 3: Kimi or Cursor side task\n"' C-m

tmux split-window -v -t "$SESSION_NAME":1.2 -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION_NAME":1.4 'printf "Pane 4: tests, git, and .agent notes\n"' C-m

tmux select-layout -t "$SESSION_NAME":1 tiled

tmux send-keys -t "$SESSION_NAME":1.4 'printf "Useful commands: agent-todo | agent-notes | agent-locks | agent-handoff\n"' C-m

exec tmux attach -t "$SESSION_NAME"
