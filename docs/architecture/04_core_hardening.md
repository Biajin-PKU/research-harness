# 04 Core Hardening — 系统整合与测试补全

## 设计目标

将前三个模块 (Primitives, ExecutionBackend, Provenance) 整合进现有 research-harness 系统，补全缺失功能，确保系统可用于日常研究。

## 设计逻辑

### 整合原则

1. **不破坏现有 CLI** — 所有新功能是增量添加，91 个现有测试必须持续通过
2. **渐进式采用** — 现有 CLI 命令不强制走 ExecutionBackend，新命令才走
3. **向后兼容** — 不改 paperindex 包的公开 API

---

## Task 1: 文件结构变更

### 新增目录结构

```
packages/research_harness/research_harness/
├── primitives/           # NEW — from 01_research_primitives.md
│   ├── __init__.py
│   ├── types.py
│   ├── registry.py
│   └── impls.py
├── execution/            # NEW — from 02_execution_backend.md
│   ├── __init__.py
│   ├── backend.py
│   ├── local.py
│   ├── claude_code.py
│   ├── harness.py
│   ├── tracked.py
│   └── factory.py
├── provenance/           # NEW — from 03_provenance.md
│   ├── __init__.py
│   ├── models.py
│   └── recorder.py
├── core/                 # EXISTING — minor changes
├── storage/              # EXISTING — no changes
├── integrations/         # EXISTING — no changes
├── config.py             # EXISTING — add execution_backend field
└── cli.py                # EXISTING — add new command groups
```

### 新增 Migration

```
migrations/
├── 001_initial_schema.sql
├── 002_topic_paper_notes_unique.sql
├── 003_tasks_paper_id.sql
└── 004_provenance.sql     # NEW — provenance_records table
```

---

## Task 2: CLI 新增命令

### 2.1 `rhub backend` group

```
rhub backend info          # 当前后端信息
rhub backend list          # 可用后端列表
rhub backend primitives    # 当前后端支持的 primitives
```

### 2.2 `rhub provenance` group

```
rhub provenance list [--topic N] [--primitive X] [--backend Y] [--limit N]
rhub provenance summary [--topic N] [--backend Y]
rhub provenance show <record_id>
```

### 2.3 `rhub primitive` group (新)

直接调用 primitive 的调试入口：

```
rhub primitive list                    # 列出所有注册的 primitives
rhub primitive exec <name> [--json-args '{}']  # 执行一个 primitive
```

实现指南：

```python
@main.group()
def primitive():
    """Research primitives management."""
    pass

@primitive.command("list")
@click.pass_context
def primitive_list(ctx):
    """List all registered research primitives."""
    from .primitives import list_primitives
    for spec in list_primitives():
        # 输出 name, category, description, requires_llm

@primitive.command("exec")
@click.argument("name")
@click.option("--args", "json_args", type=str, default="{}")
@click.option("--topic", type=int, default=None)
@click.pass_context
def primitive_exec(ctx, name, json_args, topic):
    """Execute a research primitive."""
    import json as json_mod
    from .execution import create_backend
    from .execution.tracked import TrackedBackend
    from .provenance import ProvenanceRecorder

    kwargs = json_mod.loads(json_args)
    raw_backend = create_backend(ctx.obj["backend_name"], db=ctx.obj["db"])
    recorder = ProvenanceRecorder(ctx.obj["db"])
    backend = TrackedBackend(raw_backend, recorder, default_topic_id=topic)
    result = backend.execute(name, **kwargs)
    # 输出 result
```

---

## Task 3: Config 扩展

### 修改 `config.py`

```python
@dataclass
class RuntimeConfig:
    db_path: Path
    source: str
    workspace_root: Path | None = None
    config_path: Path | None = None
    execution_backend: str = "local"  # NEW

def resolve_config(
    explicit_db: str | None = None,
    explicit_backend: str | None = None,  # NEW
) -> RuntimeConfig:
    # ... existing logic ...
    backend = explicit_backend or os.environ.get("RESEARCH_HUB_BACKEND", "local")
    return RuntimeConfig(
        db_path=db_path,
        source=source,
        workspace_root=workspace_root,
        config_path=config_path,
        execution_backend=backend,  # NEW
    )
```

### 修改 `cli.py` main group

```python
@click.group()
@click.option("--db", default=None, help="Database path")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
@click.option("--backend", type=click.Choice(["local", "claude_code", "research_harness"]),
              default=None, help="Execution backend")
@click.pass_context
def main(ctx, db, json_output, backend):
    ctx.ensure_object(dict)
    config = resolve_config(explicit_db=db, explicit_backend=backend)
    ctx.obj["config"] = config
    ctx.obj["json_output"] = json_output
    ctx.obj["backend_name"] = config.execution_backend
    # ... existing db setup ...
```

---

## Task 4: Doctor 命令扩展

在现有 `doctor` 命令中添加：

```python
# 新增检查项:
# - Execution backend status
# - Provenance table exists
# - Primitive registry count

checks["execution_backend"] = {
    "backend": config.execution_backend,
    "status": "ok",
}

checks["primitives"] = {
    "registered": len(list_primitives()),
    "status": "ok",
}

checks["provenance"] = {
    "table_exists": _table_exists(conn, "provenance_records"),
    "record_count": _count_records(conn, "provenance_records"),
    "status": "ok" if _table_exists(conn, "provenance_records") else "missing",
}
```

---

## Task 5: 测试补全计划

### 现有测试不动 — 新增测试文件

| 文件 | 测试内容 | 依赖 |
|------|----------|------|
| `test_primitives.py` | Primitive types, registry, impls | 01 |
| `test_execution.py` | Backend protocol, factory, LocalBackend | 01, 02 |
| `test_provenance.py` | Recorder, TrackedBackend, CLI | 01, 02, 03 |
| `test_backend_cli.py` | `rhub backend` 命令 | 02 |
| `test_provenance_cli.py` | `rhub provenance` 命令 | 03 |
| `test_primitive_cli.py` | `rhub primitive` 命令 | 01, 02, 03 |

### 测试总数目标

- 现有: 91 tests
- 新增: ~30-40 tests (per the test specs in 01/02/03)
- 目标: 120+ tests, 全部 pass

---

## Task 6: 开发顺序

Codex 应按以下顺序执行：

### Step 1: Primitives 模块
1. 创建 `primitives/` 目录和三个文件 (types.py, registry.py, impls.py, __init__.py)
2. 运行现有 91 tests — 必须全通过（新模块不应影响现有代码）
3. 编写并运行 `test_primitives.py`

### Step 2: Execution 模块
1. 创建 `execution/` 目录和文件
2. 运行全量测试
3. 编写并运行 `test_execution.py`

### Step 3: Provenance 模块
1. 创建 `migrations/004_provenance.sql`
2. 创建 `provenance/` 目录和文件
3. 创建 `execution/tracked.py`
4. 运行全量测试
5. 编写并运行 `test_provenance.py`

### Step 4: CLI 整合
1. 修改 `config.py` — 添加 `execution_backend` 字段
2. 修改 `cli.py` — 添加 `--backend` global option + 三个新 command groups
3. 扩展 `doctor` 命令
4. 运行全量测试
5. 编写并运行 CLI 测试

### Step 5: 全量验证
```bash
# 必须全部通过
python -m pytest packages/ -q --tb=short

# 手动 smoke test
rhub doctor --json
rhub backend list
rhub backend info
rhub primitive list
rhub primitive exec paper_search --args '{"query": "attention"}'
rhub provenance list
rhub provenance summary
```

---

## Phase 1 Exit Criteria 检查清单

Phase 1 完成标准（对照 `docs/roadmap.md`）：

### 1.1 Core System Hardening
- [x] Full test suite green (91 existing + new tests)
- [x] Topic workspace CRUD complete — **已实现** (init, show, list, status, overview)
- [x] Paper lifecycle complete — **已实现** (ingest → annotate → card → note → queue)
- [x] Task tracker functional — **已实现** (generate, add, status, list)
- [x] Review gate system working — **已实现** (add, list, check readiness)
- [ ] Search provenance logging operational — **本次实现**

### 1.2 Execution Layer Abstraction
- [ ] `ExecutionBackend` interface — **本次实现**
- [ ] `ClaudeCodeBackend` stub — **本次实现**
- [ ] `ResearchHarnessBackend` stub — **本次实现**
- [ ] Config switch — **本次实现**

### 1.3 Research Primitives Definition
- [ ] 9 primitives defined — **本次实现**
- [ ] `paper_search` + `paper_ingest` implemented — **本次实现**

### 1.4 Provenance System
- [ ] Every primitive call logged — **本次实现** (via TrackedBackend)
- [ ] Provenance records in DB — **本次实现** (migration 004)
- [ ] `rhub provenance show` CLI — **本次实现**

---

## 风险与注意事项

1. **`PaperPool.ingest()` 返回格式** — 当前返回 `int` (paper_id)，primitive 的 `paper_ingest` 需要 dict。Codex 需要确认实际返回格式并适配 `impls.py`
2. **SQLite 列索引** — `_row_to_record` 中硬编码列索引容易出错。建议 Codex 使用 `conn.row_factory = sqlite3.Row` 改为按名索引
3. **import 循环** — primitives ← execution ← provenance 之间可能有循环 import。确保 provenance 不 import execution，只通过 TrackedBackend 组合
4. **`--backend` option 向后兼容** — 现有命令不使用 backend，必须确保 `--backend` 作为 optional 不影响现有命令行为
