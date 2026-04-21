# 02 ExecutionBackend Interface

## 设计目标

定义执行层的标准接口，使 research-harness 核心层对底层执行后端（Claude Code 或 Research Harness）完全无感知。

## 设计逻辑

### 为什么需要 ExecutionBackend？

research-harness 要同时支持两种执行方式：
1. **Claude Code** — 通过 CLI 调用，完整能力，高成本
2. **Research Harness** — 自建，task-aware routing，低成本

ExecutionBackend 是二者的公共接口。上层代码只调用接口，不关心具体实现。

### 与 Primitives 的关系

```
用户 CLI 命令
    ↓
ExecutionBackend.execute("paper_search", query="...", ...)
    ↓
    ├─ ClaudeCodeBackend: 委派给 Claude Code CLI
    ├─ ResearchHarnessBackend: 通过 task-aware router 选模型 (Phase 3)
    └─ LocalBackend: 直接调用 primitive 实现 (不需要 LLM 的操作)
    ↓
PrimitiveResult (标准化结果)
    ↓
Provenance 自动记录
```

### Phase 1 范围

- 定义 `ExecutionBackend` Protocol
- 实现 `LocalBackend` — 调用不需要 LLM 的 primitives
- Stub `ClaudeCodeBackend` — 接口定义 + NotImplementedError
- Stub `ResearchHarnessBackend` — 接口定义 + NotImplementedError
- 配置系统：选择后端

---

## 接口定义

### 文件: `packages/research_harness/research_harness/execution/__init__.py`

```python
"""Execution layer — backend-agnostic interface for research operations."""

from .backend import ExecutionBackend, BackendInfo
from .local import LocalBackend
from .factory import create_backend, get_backend_names

__all__ = [
    "ExecutionBackend", "BackendInfo",
    "LocalBackend",
    "create_backend", "get_backend_names",
]
```

### 文件: `packages/research_harness/research_harness/execution/backend.py`

```python
"""ExecutionBackend protocol — the contract all backends must fulfill."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..primitives.types import PrimitiveResult


@dataclass(frozen=True)
class BackendInfo:
    """Metadata about an execution backend."""

    name: str                                # "local", "claude_code", "research_harness"
    version: str = "0.1.0"
    supported_primitives: list[str] = field(default_factory=list)
    requires_api_key: bool = False
    description: str = ""


@runtime_checkable
class ExecutionBackend(Protocol):
    """Protocol that all execution backends must implement.

    This is the central abstraction enabling dual-path execution:
    the same research workflow can run on Claude Code (high capability, high cost)
    or Research Harness (domain-optimized, low cost).

    Design principles:
    - All methods return PrimitiveResult for uniform provenance tracking
    - Backends declare capabilities via get_info()
    - Backends that don't support a primitive raise NotImplementedError
    - Cost estimation is best-effort (may return 0.0 for unknown)
    """

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        """Execute a research primitive.

        Args:
            primitive: Name from PRIMITIVE_REGISTRY (e.g., "paper_search")
            **kwargs: Arguments matching the primitive's input_schema

        Returns:
            PrimitiveResult with success/failure, output, timing, cost

        Raises:
            NotImplementedError: If this backend doesn't support the primitive
            ValueError: If kwargs don't match input_schema
        """
        ...

    def get_info(self) -> BackendInfo:
        """Return metadata about this backend's capabilities."""
        ...

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        """Estimate cost in USD for executing a primitive.

        Returns 0.0 if cost cannot be estimated.
        """
        ...

    def supports(self, primitive: str) -> bool:
        """Check if this backend supports a specific primitive."""
        ...
```

---

## LocalBackend 实现

### 文件: `packages/research_harness/research_harness/execution/local.py`

```python
"""LocalBackend — executes non-LLM primitives directly."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..primitives.registry import get_primitive_impl, get_primitive_spec, list_primitives
from ..primitives.types import PrimitiveResult
from .backend import BackendInfo, ExecutionBackend


class LocalBackend:
    """Executes primitives that don't require LLM calls.

    This backend is always available and handles operations like
    paper_search (local DB), paper_ingest, evidence_link — anything
    that can be done with pure Python + database access.

    For LLM-dependent primitives (claim_extract, gap_detect, etc.),
    this backend raises NotImplementedError, signaling the caller
    to use ClaudeCodeBackend or ResearchHarnessBackend.
    """

    def __init__(self, db):
        self._db = db

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        spec = get_primitive_spec(primitive)
        if spec is None:
            return PrimitiveResult(
                primitive=primitive,
                success=False,
                output=None,
                error=f"Unknown primitive: {primitive}",
                backend="local",
            )

        if spec.requires_llm:
            raise NotImplementedError(
                f"Primitive '{primitive}' requires LLM. "
                f"Use ClaudeCodeBackend or ResearchHarnessBackend."
            )

        impl = get_primitive_impl(primitive)
        if impl is None:
            return PrimitiveResult(
                primitive=primitive,
                success=False,
                output=None,
                error=f"No implementation registered for: {primitive}",
                backend="local",
            )

        started = datetime.now(timezone.utc).isoformat()
        try:
            output = impl(db=self._db, **kwargs)
            finished = datetime.now(timezone.utc).isoformat()
            return PrimitiveResult(
                primitive=primitive,
                success=True,
                output=output,
                started_at=started,
                finished_at=finished,
                backend="local",
                model_used="none",
                cost_usd=0.0,
            )
        except Exception as e:
            finished = datetime.now(timezone.utc).isoformat()
            return PrimitiveResult(
                primitive=primitive,
                success=False,
                output=None,
                error=str(e),
                started_at=started,
                finished_at=finished,
                backend="local",
            )

    def get_info(self) -> BackendInfo:
        supported = [
            s.name for s in list_primitives() if not s.requires_llm
        ]
        return BackendInfo(
            name="local",
            supported_primitives=supported,
            requires_api_key=False,
            description="Executes non-LLM primitives directly via local DB",
        )

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        return 0.0  # Local operations are free

    def supports(self, primitive: str) -> bool:
        spec = get_primitive_spec(primitive)
        return spec is not None and not spec.requires_llm
```

---

## Backend Stubs (Phase 3 填充)

### 文件: `packages/research_harness/research_harness/execution/claude_code.py`

```python
"""ClaudeCodeBackend — delegates to Claude Code CLI (Phase 2+)."""

from __future__ import annotations

from typing import Any

from ..primitives.types import PrimitiveResult
from .backend import BackendInfo


class ClaudeCodeBackend:
    """Execution backend that delegates research primitives to Claude Code.

    Phase 1: Stub only — raises NotImplementedError for all operations.
    Phase 2: Will implement by invoking Claude Code CLI with structured prompts
             and parsing JSON output back into PrimitiveResult.

    Implementation plan (Phase 2):
    - Use subprocess to call `claude -p <prompt> --output-format json`
    - Map each primitive to a prompt template
    - Parse Claude's response into the appropriate *Output dataclass
    - Track cost via Claude Code's usage reporting
    """

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        raise NotImplementedError(
            "ClaudeCodeBackend not implemented yet. Available in Phase 2."
        )

    def get_info(self) -> BackendInfo:
        return BackendInfo(
            name="claude_code",
            supported_primitives=[],  # Will be filled in Phase 2
            requires_api_key=True,
            description="Delegates to Claude Code CLI (Phase 2+)",
        )

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        return 0.0  # Unknown until Phase 2

    def supports(self, primitive: str) -> bool:
        return False  # Nothing supported yet
```

### 文件: `packages/research_harness/research_harness/execution/harness.py`

```python
"""ResearchHarnessBackend — self-built task-aware orchestration (Phase 3+)."""

from __future__ import annotations

from typing import Any

from ..primitives.types import PrimitiveResult
from .backend import BackendInfo


class ResearchHarnessBackend:
    """Execution backend with task-aware model routing.

    Phase 1: Stub only.
    Phase 3: Will implement with:
    - TaskAwareRouter: routes primitives to models by category
    - EvidenceGatedPipeline: stage gates driven by evidence sufficiency
    - Multiple providers: Kimi (default), Anthropic (fallback), OpenAI-compatible

    See docs/research_harness_design.md for full architecture.
    """

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        raise NotImplementedError(
            "ResearchHarnessBackend not implemented yet. Available in Phase 3."
        )

    def get_info(self) -> BackendInfo:
        return BackendInfo(
            name="research_harness",
            supported_primitives=[],  # Will be filled in Phase 3
            requires_api_key=True,
            description="Task-aware model routing with Kimi default (Phase 3+)",
        )

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        return 0.0

    def supports(self, primitive: str) -> bool:
        return False
```

---

## Backend Factory

### 文件: `packages/research_harness/research_harness/execution/factory.py`

```python
"""Backend factory — creates execution backend from configuration."""

from __future__ import annotations

from typing import Any

from .backend import ExecutionBackend
from .local import LocalBackend
from .claude_code import ClaudeCodeBackend
from .harness import ResearchHarnessBackend


_BACKEND_CLASSES = {
    "local": LocalBackend,
    "claude_code": ClaudeCodeBackend,
    "research_harness": ResearchHarnessBackend,
}


def create_backend(name: str, **kwargs: Any) -> ExecutionBackend:
    """Create an execution backend by name.

    Args:
        name: One of "local", "claude_code", "research_harness"
        **kwargs: Backend-specific initialization arguments
                  (e.g., db for LocalBackend)

    Returns:
        An ExecutionBackend instance

    Raises:
        ValueError: If name is not recognized
    """
    cls = _BACKEND_CLASSES.get(name)
    if cls is None:
        valid = ", ".join(sorted(_BACKEND_CLASSES.keys()))
        raise ValueError(f"Unknown backend: {name!r}. Valid: {valid}")
    return cls(**kwargs)


def get_backend_names() -> list[str]:
    """Return list of registered backend names."""
    return sorted(_BACKEND_CLASSES.keys())
```

---

## 配置集成

### 在现有 `config.py` 中添加

```python
# 在 RuntimeConfig 中添加字段:
@dataclass
class RuntimeConfig:
    db_path: Path
    source: str
    workspace_root: Path | None = None
    config_path: Path | None = None
    execution_backend: str = "local"  # NEW: "local" | "claude_code" | "research_harness"
```

配置优先级：
1. CLI flag: `--backend local|claude_code|research_harness`
2. 环境变量: `RESEARCH_HUB_BACKEND`
3. 项目配置: `.research-harness/config.json` 中的 `execution_backend`
4. 默认值: `"local"`

---

## CLI 集成

### 在 `cli.py` 的 main group 中添加全局 option

```python
@click.group()
@click.option("--backend", type=click.Choice(["local", "claude_code", "research_harness"]),
              default=None, help="Execution backend")
@click.pass_context
def main(ctx, db, json_output, backend):
    # ... existing logic ...
    if backend:
        ctx.obj["backend_name"] = backend
    else:
        ctx.obj["backend_name"] = os.environ.get("RESEARCH_HUB_BACKEND", "local")
```

### 新增 CLI 命令: `rhub backend`

```python
@main.group()
def backend():
    """Execution backend management."""
    pass

@backend.command("info")
@click.pass_context
def backend_info(ctx):
    """Show current backend info and capabilities."""
    from .execution import create_backend
    be = create_backend(ctx.obj["backend_name"], db=ctx.obj.get("db"))
    info = be.get_info()
    # 输出 info 字段

@backend.command("list")
def backend_list():
    """List available backends."""
    from .execution import get_backend_names
    for name in get_backend_names():
        click.echo(name)

@backend.command("primitives")
@click.pass_context
def backend_primitives(ctx):
    """List primitives supported by current backend."""
    from .execution import create_backend
    be = create_backend(ctx.obj["backend_name"], db=ctx.obj.get("db"))
    info = be.get_info()
    for p in info.supported_primitives:
        click.echo(p)
```

---

## 测试要求

### 文件: `packages/research_harness/tests/test_execution.py`

```python
"""Tests for execution backend system."""

# 1. test_local_backend_supports_non_llm
#    - LocalBackend.supports("paper_search") == True
#    - LocalBackend.supports("claim_extract") == False (requires LLM)

# 2. test_local_backend_execute_paper_search
#    - 插入 papers 到 DB
#    - LocalBackend.execute("paper_search", query="...") 返回 PrimitiveResult
#    - result.success == True, result.backend == "local"

# 3. test_local_backend_execute_unknown_primitive
#    - execute("nonexistent") → result.success == False

# 4. test_local_backend_llm_primitive_raises
#    - execute("claim_extract", ...) → NotImplementedError

# 5. test_claude_code_stub_raises
#    - ClaudeCodeBackend().execute(...) → NotImplementedError

# 6. test_harness_stub_raises
#    - ResearchHarnessBackend().execute(...) → NotImplementedError

# 7. test_backend_factory
#    - create_backend("local", db=db) → LocalBackend instance
#    - create_backend("unknown") → ValueError

# 8. test_backend_info
#    - 每个 backend 的 get_info() 返回有效的 BackendInfo

# 9. test_execution_backend_protocol
#    - 验证 LocalBackend 是 ExecutionBackend 的 runtime-checkable 实例
```

---

## Codex 实现注意事项

1. **LocalBackend 需要 `db` 参数** — 传入现有的 Database 实例
2. **Protocol 使用 `@runtime_checkable`** — 可以用 `isinstance()` 检查
3. **factory.py 是扩展点** — Phase 2/3 只需要实现 backend 类并注册到 `_BACKEND_CLASSES`
4. **不要在 Phase 1 实现 ClaudeCodeBackend/ResearchHarnessBackend 的 execute()** — 只保留 stub
5. **`--backend` CLI option 不能破坏现有命令** — 作为全局 option 透传，现有命令不受影响
