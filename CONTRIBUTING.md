# Contributing to Research Harness

Thank you for your interest in contributing. This document covers development setup, conventions, and the process for adding new primitives and MCP tools.

## Table of Contents

- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Commit Convention](#commit-convention)
- [How to Add a New Primitive](#how-to-add-a-new-primitive)
- [How to Add a New MCP Tool](#how-to-add-a-new-mcp-tool)
- [Using Claude Code](#using-claude-code)
- [Pull Request Flow](#pull-request-flow)
- [Reporting Issues](#reporting-issues)

## Development Setup

```bash
git clone https://github.com/your-org/research-harness.git
cd research-harness
./setup.sh
```

`setup.sh` installs all three packages in editable mode and creates `.env` from `.env.example`. You can also use conda:

```bash
conda env create -f environment.yml
conda activate research-harness
```

Verify the installation:

```bash
python -m pytest packages/ -q --ignore=packages/research_harness_eval
rhub --json doctor
```

## Running Tests

```bash
# Full suite (fast, ~987 tests)
python -m pytest packages/ -q --ignore=packages/research_harness_eval

# Single package
python -m pytest packages/research_harness/tests -q
python -m pytest packages/paperindex/tests -q

# Single test file
python -m pytest packages/research_harness/tests/test_primitives.py -v

# With coverage
python -m pytest packages/ --cov=packages --cov-report=term-missing -q \
    --ignore=packages/research_harness_eval
```

Target: maintain ≥80% line coverage on new code. Check coverage before submitting a PR.

## Code Style

- Python 3.10+ with full type annotations
- `from __future__ import annotations` at the top of every module
- Dataclasses over plain dicts for structured data; frozen dataclasses for value objects
- `ruff` for linting and formatting

```bash
# Lint
ruff check packages/

# Format (check only, no auto-fix on CI)
ruff format --check packages/

# Auto-fix locally
ruff check --fix packages/
ruff format packages/
```

The `ruff` configuration is inherited from each package's `pyproject.toml`. Do not introduce `pylint` or `flake8` — `ruff` is the single linter.

## Commit Convention

Format: `<type>: <description>`

| Type | Use for |
|------|---------|
| `feat` | New primitive, MCP tool, or user-facing capability |
| `fix` | Bug fix |
| `refactor` | Internal restructuring with no behavior change |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `chore` | Dependency bumps, CI changes, tooling |
| `perf` | Performance improvement |

Examples:

```
feat: add contradiction_detect primitive
fix: paper_ingest fails when arxiv_id contains version suffix
test: add coverage for orchestrator gate transitions
docs: add plugin development guide
```

Keep the description under 72 characters. Add a body if the change needs explanation.

## How to Add a New Primitive

Primitives are the core research operations. Every primitive auto-exposes as an MCP tool.

### 1. Define a PrimitiveSpec in the registry

Add your spec to the appropriate `*_impls.py` file (or create a new one) in `packages/research_harness/research_harness/primitives/`:

```python
# packages/research_harness/research_harness/primitives/my_impls.py
from __future__ import annotations

from .registry import register_primitive
from .types import PrimitiveCategory, PrimitiveResult, PrimitiveSpec

MY_SPEC = PrimitiveSpec(
    name="my_primitive",
    category=PrimitiveCategory.ANALYSIS,
    description="One-sentence description visible in MCP tool list.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "param_a":  {"type": "string", "description": "What this does"},
        },
        "required": ["topic_id"],
    },
    output_type="MyPrimitiveResult",
    requires_llm=True,
    idempotent=False,
)

@register_primitive(MY_SPEC)
def my_primitive(*, topic_id: int, param_a: str = "", **kwargs) -> dict:
    # Implementation here
    return {"status": "ok", "result": "..."}
```

### 2. Import the module so the registry runs

Add the import to `packages/research_harness/research_harness/primitives/__init__.py`:

```python
from . import my_impls  # noqa: F401
```

### 3. Write tests

Create `packages/research_harness/tests/test_my_primitive.py`. Cover:
- Happy path with a mock backend
- Invalid input handling
- Edge cases specific to your primitive

### 4. Verify the MCP tool appears

```python
from research_harness.primitives.registry import list_primitives
names = [p.name for p in list_primitives()]
assert "my_primitive" in names
```

The MCP server auto-generates a `Tool` definition from the `PrimitiveSpec`, so no changes to `tools.py` are required for primitive-backed tools.

## How to Add a New MCP Tool

For tools that are not backed by a primitive (e.g., direct DB queries, orchestrator operations), add them to `packages/research_harness_mcp/research_harness_mcp/tools.py`.

Follow the pattern of existing hand-written tools:

```python
Tool(
    name="my_tool",
    description="What this tool does, one sentence.",
    inputSchema={
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "..."},
        },
        "required": ["param"],
    },
),
```

Add the corresponding handler in `call_tool()` and write tests in `packages/research_harness_mcp/research_harness_mcp/tests/`.

## Using Claude Code

This repository includes `CLAUDE.md` (quick reference) and `AGENTS.md` (agent integration). Claude Code reads `CLAUDE.md` automatically on startup.

For development tasks, Claude Code can:
- Navigate the primitive registry and find the right `*_impls.py` to edit
- Run tests via the bash tool
- Check which MCP tools exist by reading `tools.py`

Start a session:

```bash
claude    # reads CLAUDE.md automatically
```

## Pull Request Flow

1. Fork the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. Make your changes. Add tests. Run the full suite locally.

3. Run linting:
   ```bash
   ruff check packages/
   ruff format --check packages/
   ```

4. Commit with a conventional commit message.

5. Open a pull request against `main`. Fill in the PR template.

6. A maintainer will review. Address feedback with new commits (do not force-push during review).

7. Once approved, the PR is squash-merged.

## Reporting Issues

Use the GitHub issue templates:

- **Bug report** — for reproducible failures
- **Feature request** — for new capabilities
- **Primitive request** — for requesting a new research primitive

Before opening an issue, search existing issues and the `docs/` directory. For questions about using the platform, open a Discussion rather than an issue.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
