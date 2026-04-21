# 03 Provenance System

## 设计目标

每次 research primitive 调用自动记录来源追踪信息。Provenance 是论文的核心贡献之一 — 它使研究过程可复现、可比较（Claude Code vs Research Harness 的评估数据来自这里）。

## 设计逻辑

### 为什么 Provenance 是 mandatory 的？

1. **论文评估需要** — Phase 4 要比较两个 backend 的成本/质量/时间，数据来自 provenance
2. **可复现性** — 知道每个 claim/draft 是哪个模型生成的、输入是什么
3. **成本分析** — 精确追踪每个 primitive 的 API 花费
4. **不是 logging** — Provenance 是结构化数据，存在 DB 中，可查询、可导出

### 架构位置

```
CLI 命令
    ↓
ExecutionBackend.execute(primitive, **kwargs)
    ↓
PrimitiveResult (包含 timing, cost, model)
    ↓
ProvenanceRecorder.record(result)  ← 自动触发，不需要调用方关心
    ↓
provenance_records 表 (SQLite)
```

关键设计：**Provenance 是 ExecutionBackend 的装饰器，不是 primitive 实现的一部分**。Primitive 实现不需要知道 provenance 的存在。

---

## 数据库 Schema

### 文件: `packages/research_harness/migrations/004_provenance.sql`

```sql
-- Provenance tracking for research primitive executions

CREATE TABLE IF NOT EXISTS provenance_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- What was executed
    primitive   TEXT NOT NULL,                -- primitive name (e.g., "paper_search")
    category    TEXT NOT NULL DEFAULT '',     -- PrimitiveCategory value
    -- When
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    -- How
    backend     TEXT NOT NULL,                -- "local", "claude_code", "research_harness"
    model_used  TEXT NOT NULL DEFAULT 'none',
    -- Context
    topic_id    INTEGER,                      -- optional topic association
    stage       TEXT NOT NULL DEFAULT '',     -- pipeline stage (Phase 3)
    -- Hashes for reproducibility
    input_hash  TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    -- Cost
    cost_usd    REAL NOT NULL DEFAULT 0.0,
    -- Result
    success     INTEGER NOT NULL DEFAULT 1,  -- 0 = failed
    error       TEXT NOT NULL DEFAULT '',
    -- Metadata
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    -- Chain provenance: which previous record produced input for this one
    parent_id   INTEGER REFERENCES provenance_records(id),

    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_provenance_primitive ON provenance_records(primitive);
CREATE INDEX IF NOT EXISTS idx_provenance_backend ON provenance_records(backend);
CREATE INDEX IF NOT EXISTS idx_provenance_topic ON provenance_records(topic_id);
CREATE INDEX IF NOT EXISTS idx_provenance_created ON provenance_records(created_at);
```

---

## ProvenanceRecorder

### 文件: `packages/research_harness/research_harness/provenance/__init__.py`

```python
"""Provenance tracking for research operations."""

from .recorder import ProvenanceRecorder
from .models import ProvenanceRecord, ProvenanceSummary

__all__ = ["ProvenanceRecorder", "ProvenanceRecord", "ProvenanceSummary"]
```

### 文件: `packages/research_harness/research_harness/provenance/models.py`

```python
"""Provenance data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProvenanceRecord:
    """A single provenance record stored in DB."""

    id: int
    primitive: str
    category: str
    started_at: str
    finished_at: str
    backend: str
    model_used: str
    topic_id: int | None
    stage: str
    input_hash: str
    output_hash: str
    cost_usd: float
    success: bool
    error: str
    parent_id: int | None = None
    created_at: str = ""


@dataclass(frozen=True)
class ProvenanceSummary:
    """Aggregated provenance statistics."""

    total_operations: int = 0
    total_cost_usd: float = 0.0
    operations_by_backend: dict[str, int] = field(default_factory=dict)
    operations_by_primitive: dict[str, int] = field(default_factory=dict)
    cost_by_backend: dict[str, float] = field(default_factory=dict)
    cost_by_primitive: dict[str, float] = field(default_factory=dict)
    success_rate: float = 1.0
    time_range: tuple[str, str] = ("", "")
```

### 文件: `packages/research_harness/research_harness/provenance/recorder.py`

```python
"""ProvenanceRecorder — records every primitive execution to DB."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..primitives.types import PrimitiveResult
from .models import ProvenanceRecord, ProvenanceSummary


class ProvenanceRecorder:
    """Records provenance for every research primitive execution.

    Usage:
        recorder = ProvenanceRecorder(db)
        record_id = recorder.record(result, input_kwargs, topic_id=1)

    The recorder is injected into TrackedBackend (see execution/tracked.py)
    and fires automatically — callers never need to call it directly.
    """

    def __init__(self, db):
        self._db = db

    def record(
        self,
        result: PrimitiveResult,
        input_kwargs: dict[str, Any],
        topic_id: int | None = None,
        stage: str = "",
        parent_id: int | None = None,
    ) -> int:
        """Record a primitive execution. Returns the provenance record ID."""
        conn = self._db.connect()
        input_hash = self._hash_dict(input_kwargs)
        output_hash = result.output_hash()

        cursor = conn.execute(
            """
            INSERT INTO provenance_records
                (primitive, category, started_at, finished_at, backend, model_used,
                 topic_id, stage, input_hash, output_hash, cost_usd, success, error, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.primitive,
                self._get_category(result.primitive),
                result.started_at,
                result.finished_at,
                result.backend,
                result.model_used,
                topic_id,
                stage,
                input_hash,
                output_hash,
                result.cost_usd,
                1 if result.success else 0,
                result.error,
                parent_id,
            ),
        )
        conn.commit()
        return cursor.lastrowid

    def get(self, record_id: int) -> ProvenanceRecord | None:
        """Retrieve a single provenance record."""
        conn = self._db.connect()
        row = conn.execute(
            "SELECT * FROM provenance_records WHERE id = ?", (record_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_records(
        self,
        topic_id: int | None = None,
        primitive: str | None = None,
        backend: str | None = None,
        limit: int = 100,
    ) -> list[ProvenanceRecord]:
        """Query provenance records with optional filters."""
        conn = self._db.connect()
        clauses: list[str] = []
        params: list[Any] = []

        if topic_id is not None:
            clauses.append("topic_id = ?")
            params.append(topic_id)
        if primitive:
            clauses.append("primitive = ?")
            params.append(primitive)
        if backend:
            clauses.append("backend = ?")
            params.append(backend)

        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT * FROM provenance_records WHERE {where} ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def summarize(
        self,
        topic_id: int | None = None,
        backend: str | None = None,
    ) -> ProvenanceSummary:
        """Generate aggregate statistics from provenance records."""
        records = self.list_records(topic_id=topic_id, backend=backend, limit=10000)

        if not records:
            return ProvenanceSummary()

        ops_by_backend: dict[str, int] = {}
        ops_by_prim: dict[str, int] = {}
        cost_by_backend: dict[str, float] = {}
        cost_by_prim: dict[str, float] = {}
        successes = 0

        for r in records:
            ops_by_backend[r.backend] = ops_by_backend.get(r.backend, 0) + 1
            ops_by_prim[r.primitive] = ops_by_prim.get(r.primitive, 0) + 1
            cost_by_backend[r.backend] = cost_by_backend.get(r.backend, 0.0) + r.cost_usd
            cost_by_prim[r.primitive] = cost_by_prim.get(r.primitive, 0.0) + r.cost_usd
            if r.success:
                successes += 1

        return ProvenanceSummary(
            total_operations=len(records),
            total_cost_usd=sum(r.cost_usd for r in records),
            operations_by_backend=ops_by_backend,
            operations_by_primitive=ops_by_prim,
            cost_by_backend=cost_by_backend,
            cost_by_primitive=cost_by_prim,
            success_rate=successes / len(records) if records else 1.0,
            time_range=(records[-1].started_at, records[0].finished_at),
        )

    def _get_category(self, primitive_name: str) -> str:
        from ..primitives.registry import get_primitive_spec
        spec = get_primitive_spec(primitive_name)
        return spec.category.value if spec else ""

    def _hash_dict(self, d: dict) -> str:
        raw = json.dumps(d, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _row_to_record(self, row) -> ProvenanceRecord:
        return ProvenanceRecord(
            id=row[0],
            primitive=row[1],
            category=row[2],
            started_at=row[3],
            finished_at=row[4],
            backend=row[5],
            model_used=row[6],
            topic_id=row[7],
            stage=row[8],
            input_hash=row[9],
            output_hash=row[10],
            cost_usd=row[11],
            success=bool(row[12]),
            error=row[13],
            parent_id=row[15] if len(row) > 15 else None,
            created_at=row[14] if len(row) > 14 else "",
        )
```

---

## TrackedBackend — 自动 Provenance 的装饰器

### 文件: `packages/research_harness/research_harness/execution/tracked.py`

```python
"""TrackedBackend — wraps any ExecutionBackend with automatic provenance recording."""

from __future__ import annotations

from typing import Any

from ..primitives.types import PrimitiveResult
from ..provenance.recorder import ProvenanceRecorder
from .backend import BackendInfo, ExecutionBackend


class TrackedBackend:
    """Decorator that adds provenance recording to any ExecutionBackend.

    Usage:
        raw_backend = LocalBackend(db)
        recorder = ProvenanceRecorder(db)
        backend = TrackedBackend(raw_backend, recorder)
        result = backend.execute("paper_search", query="attention")
        # ↑ automatically records provenance

    This is the preferred way to create backends in production.
    The factory should wrap backends with TrackedBackend by default.
    """

    def __init__(
        self,
        inner: ExecutionBackend,
        recorder: ProvenanceRecorder,
        default_topic_id: int | None = None,
    ):
        self._inner = inner
        self._recorder = recorder
        self._default_topic_id = default_topic_id

    def execute(self, primitive: str, **kwargs: Any) -> PrimitiveResult:
        topic_id = kwargs.pop("_topic_id", self._default_topic_id)
        parent_id = kwargs.pop("_parent_id", None)
        stage = kwargs.pop("_stage", "")

        result = self._inner.execute(primitive, **kwargs)

        # Record provenance (fire-and-forget, never block on failure)
        try:
            self._recorder.record(
                result=result,
                input_kwargs=kwargs,
                topic_id=topic_id,
                stage=stage,
                parent_id=parent_id,
            )
        except Exception:
            pass  # Provenance failure must never block research work

        return result

    def get_info(self) -> BackendInfo:
        return self._inner.get_info()

    def estimate_cost(self, primitive: str, **kwargs: Any) -> float:
        return self._inner.estimate_cost(primitive, **kwargs)

    def supports(self, primitive: str) -> bool:
        return self._inner.supports(primitive)
```

---

## CLI 集成

### 新增命令: `rhub provenance`

```python
@main.group()
def provenance():
    """Provenance tracking for research operations."""
    pass

@provenance.command("list")
@click.option("--topic", type=int, default=None)
@click.option("--primitive", type=str, default=None)
@click.option("--backend", type=str, default=None)
@click.option("--limit", type=int, default=20)
@click.pass_context
def provenance_list(ctx, topic, primitive, backend, limit):
    """List provenance records."""
    from .provenance import ProvenanceRecorder
    recorder = ProvenanceRecorder(ctx.obj["db"])
    records = recorder.list_records(
        topic_id=topic, primitive=primitive, backend=backend, limit=limit
    )
    # 输出 records

@provenance.command("summary")
@click.option("--topic", type=int, default=None)
@click.option("--backend", type=str, default=None)
@click.pass_context
def provenance_summary(ctx, topic, backend):
    """Show provenance statistics."""
    from .provenance import ProvenanceRecorder
    recorder = ProvenanceRecorder(ctx.obj["db"])
    summary = recorder.summarize(topic_id=topic, backend=backend)
    # 输出 summary

@provenance.command("show")
@click.argument("record_id", type=int)
@click.pass_context
def provenance_show(ctx, record_id):
    """Show a single provenance record."""
    from .provenance import ProvenanceRecorder
    recorder = ProvenanceRecorder(ctx.obj["db"])
    record = recorder.get(record_id)
    # 输出 record
```

---

## 测试要求

### 文件: `packages/research_harness/tests/test_provenance.py`

```python
"""Tests for provenance system."""

# 1. test_record_and_retrieve
#    - 创建 PrimitiveResult，录入 provenance，验证 get() 返回正确

# 2. test_list_with_filters
#    - 录入多条 records，按 topic_id/primitive/backend 过滤

# 3. test_summarize
#    - 录入多条 records，验证 summary 的统计正确
#    - cost_by_backend, operations_by_primitive, success_rate

# 4. test_tracked_backend_auto_records
#    - TrackedBackend 包装 LocalBackend
#    - 执行 paper_search
#    - 验证 provenance_records 表有一条记录

# 5. test_tracked_backend_provenance_failure_does_not_block
#    - Mock recorder.record 抛异常
#    - 验证 execute() 仍然返回结果 (provenance 失败不阻塞)

# 6. test_input_output_hashes_consistent
#    - 相同输入 → 相同 input_hash
#    - 不同输入 → 不同 input_hash

# 7. test_parent_chain
#    - record A → record B (parent_id = A.id)
#    - 验证 B.parent_id == A.id
```

---

## Codex 实现注意事项

1. **Migration 004 必须能在现有 DB 上增量执行** — db.py 的 migration runner 已支持
2. **TrackedBackend 是装饰器模式** — 不要在 LocalBackend 里直接写 provenance 逻辑
3. **`_topic_id`, `_parent_id`, `_stage` 是 kwargs 中的特殊键** — 用 `pop` 取出，不传给 inner backend
4. **Provenance 失败不能阻塞** — TrackedBackend 中 record() 的异常被 swallow
5. **_row_to_record 的列索引要与 migration 的列顺序对齐** — 或改用 `row_factory` 命名列
