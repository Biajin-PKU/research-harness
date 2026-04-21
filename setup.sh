#!/usr/bin/env bash
set -euo pipefail

# Research Harness — first-time setup
# Usage: ./setup.sh
#
# Installs all three packages in editable mode, creates .env if missing.
# Supports both pip (venv) and conda workflows.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Research Harness Setup ==="
echo ""

# ---------------------------------------------------------------------------
# 1. Check Python version
# ---------------------------------------------------------------------------

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required but not found."
  echo "Install Python 3.10+ from https://www.python.org/downloads/"
  exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; }; then
  echo "Error: Python 3.10+ required, found $PYTHON_VERSION"
  exit 1
fi

echo "Found Python $PYTHON_VERSION"

# ---------------------------------------------------------------------------
# 2. Choose install method
# ---------------------------------------------------------------------------

# If already inside a conda env, use it directly
if [ -n "${CONDA_DEFAULT_ENV:-}" ] && [ "${CONDA_DEFAULT_ENV}" != "base" ]; then
  echo "Active conda environment detected: $CONDA_DEFAULT_ENV"
  PYTHON="python3"
  PIP="pip3"
  echo "Using existing conda environment."
elif command -v conda >/dev/null 2>&1; then
  echo ""
  echo "conda detected. Choose setup method:"
  echo "  1) conda  — create/activate 'research-harness' conda env (recommended)"
  echo "  2) venv   — create .venv in this directory"
  echo ""
  read -r -p "Enter 1 or 2 [default: 1]: " CHOICE
  CHOICE="${CHOICE:-1}"

  if [ "$CHOICE" = "1" ]; then
    if conda env list | grep -q "^research-harness "; then
      echo "Conda env 'research-harness' already exists, reusing it."
    else
      echo "Creating conda env 'research-harness' (Python 3.11)..."
      conda create -n research-harness python=3.11 -y
    fi
    # shellcheck disable=SC1091
    eval "$(conda shell.bash hook)"
    conda activate research-harness
    PYTHON="python"
    PIP="pip"
  else
    if [ ! -d "$REPO_ROOT/.venv" ]; then
      echo "Creating .venv..."
      python3 -m venv "$REPO_ROOT/.venv"
    fi
    PYTHON="$REPO_ROOT/.venv/bin/python"
    PIP="$REPO_ROOT/.venv/bin/pip"
    echo ""
    echo "Note: activate with:  source .venv/bin/activate"
  fi
else
  # No conda — use venv
  if [ ! -d "$REPO_ROOT/.venv" ]; then
    echo "Creating .venv..."
    python3 -m venv "$REPO_ROOT/.venv"
  fi
  PYTHON="$REPO_ROOT/.venv/bin/python"
  PIP="$REPO_ROOT/.venv/bin/pip"
  echo ""
  echo "Note: activate with:  source .venv/bin/activate"
fi

# ---------------------------------------------------------------------------
# 3. Upgrade pip
# ---------------------------------------------------------------------------

echo ""
echo "Upgrading pip..."
"$PIP" install --quiet --upgrade pip

# ---------------------------------------------------------------------------
# 4. Install packages (editable)
# ---------------------------------------------------------------------------

echo "Installing paperindex..."
"$PIP" install --quiet -e "$REPO_ROOT/packages/paperindex[dev]"

echo "Installing research_harness..."
"$PIP" install --quiet -e "$REPO_ROOT/packages/research_harness[dev]"

echo "Installing research_harness_mcp..."
"$PIP" install --quiet -e "$REPO_ROOT/packages/research_harness_mcp[dev]"

# ---------------------------------------------------------------------------
# 5. Environment file
# ---------------------------------------------------------------------------

if [ ! -f "$REPO_ROOT/.env" ]; then
  if [ -f "$REPO_ROOT/.env.example" ]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    echo ""
    echo "Created .env from .env.example"
    echo "  -> Edit .env and add at least one LLM provider API key before running."
  else
    echo ""
    echo "Warning: .env.example not found. Create .env manually with your API keys."
  fi
else
  echo ""
  echo ".env already exists, skipping."
fi

# ---------------------------------------------------------------------------
# 6. Smoke test
# ---------------------------------------------------------------------------

echo ""
echo "Verifying installation..."
"$PYTHON" -c "import research_harness; import paperindex; import research_harness_mcp; print('All packages importable.')"

# ---------------------------------------------------------------------------
# 7. Summary
# ---------------------------------------------------------------------------

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)"
echo "  2. Run tests:         python -m pytest packages/ -q"
echo "  3. Health check:      rhub --json doctor"
echo "  4. Initialize topic:  rh topic init \"my-research-topic\""
echo "  5. Start dashboard:   python web_dashboard/app.py"
echo "     Open:              http://127.0.0.1:18080"
echo ""
echo "Using Claude Code? CLAUDE.md has all the context."
echo "Using Codex?       AGENTS.md has agent integration instructions."
echo ""
echo "MCP server config for Claude Code (.claude/settings.json):"
echo '  {'
echo '    "mcpServers": {'
echo '      "research-harness": {'
echo '        "command": "python",'
echo '        "args": ["-m", "research_harness_mcp"]'
echo '      }'
echo '    }'
echo '  }'
