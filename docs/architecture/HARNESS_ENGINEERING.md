# Harness Engineering in Research Harness

> Agent = Model + Harness (2026 industry consensus: OpenAI / Anthropic / LangChain / Stanford)

Model 只做推理，Harness 拥有结构、状态、验证、编排的全部控制权。本文档记录 Research Harness 中 5 层 harness engineering 的具体实现。

## 5-Layer Architecture

```
┌─────────────────────────────────────────────┐
│  5. Tool Routing                            │  Harness 决定用哪个 Model
├─────────────────────────────────────────────┤
│  4. Validation / Guard                      │  Harness 验证 Model 输出
├─────────────────────────────────────────────┤
│  3. Memory / State                          │  Harness 持有全部持久状态
├─────────────────────────────────────────────┤
│  2. Orchestration                           │  状态机 + DAG + 门控
├─────────────────────────────────────────────┤
│  1. Structured I/O                          │  类型化契约，非自由文本
└─────────────────────────────────────────────┘
```

---

## Layer 1: Structured I/O

Model 的输入输出全部经过 `frozen dataclass` 定义，Harness 拥有 schema 解释权。

| 位置 | 内容 |
|------|------|
| `primitives/types.py` | 80+ frozen dataclass（`PaperSummarizeInput`, `ClaimExtractOutput` 等） |
| `storage/models.py` | 11 个 DB 行类型（`Paper`, `Topic`, `Project`, `ProvenanceRecord`） |
| `orchestrator/models.py` | 编排状态类型（`StageTransition`, `ArtifactRecord`, `GateDecision`） |
| `paperindex/cards/schema.py` | PaperCard 字段（claims, methods, results, limitations） |

**设计原则：** 每个 primitive 的 I/O 都是强类型。Model 不接触 raw dict，也不产出自由文本——所有输出必须 fit 进预定义的 dataclass。

---

## Layer 2: Orchestration

Harness 控制流程推进，Model 无法自行跳阶段。

### 状态机 + DAG

- `orchestrator/models.py` — `STAGE_GRAPH: dict[str, frozenset[str]]` 显式 DAG，定义允许的状态转移（含回环）
- `orchestrator/stages.py` — 每个 stage 声明 `required_artifacts` + `gate_type`

### 6 种门控类型

| Gate | 用途 |
|------|------|
| `approval_gate` | 人工审批 |
| `coverage_gate` | 论文覆盖率达标 |
| `adversarial_gate` | 对抗审查通过 |
| `review_gate` | 学术评审通过 |
| `integrity_gate` | 完整性校验 |
| `experiment_gate` | 实验指标达标 |

### 关键路径

- `orchestrator/service.py` — `advance()` 先检查 gate 再推进；`transition_to()` 校验 DAG 合法性
- `auto_runner/stage_policy.py` — `should_invoke_codex()` 按 stage 策略决定是否引入第二模型做对抗审查

---

## Layer 3: Memory / State

Model 是无状态的推理引擎，所有记忆由 Harness 管理。

| 组件 | 职责 |
|------|------|
| `storage/db.py` | SQLite + 自动迁移 + 完整性校验 + `.recover` 自恢复 |
| `provenance/recorder.py` | 每次 primitive 调用的输入/输出/耗时/花费持久化到 `provenance_records` 表 |
| `execution/compiled_summary.py` | 按论文缓存结构化 JSON（`papers.compiled_summary`），带失效感知的 topic 级缓存 |
| `core/search_cache.py` | SQLite-backed 搜索缓存，按 query hash + source TTL 管理 |

**设计原则：** Model 不持有任何跨调用状态。论文池、任务队列、审查记录、provenance——全部在 Harness 侧的 SQLite 中。

---

## Layer 4: Validation / Guard

不信任 Model 的原始输出，全部经过 Harness 层校验。

### 输出解析

- `llm_primitives.py` — `_parse_json()` 被调用 20+ 次，每个 primitive 输出必须通过结构化 JSON 解析，失败则 reject

### 成本红线

- `llm_primitives.py` — `_ANTHROPIC_BLOCKED_PRIMITIVES: frozenset` 编译时阻止特定 primitive 走 Anthropic 后端
- `paperindex/llm/client.py` — `_BLOCKED_PROVIDERS_BY_TIER` + `_TIER_FALLBACKS` 实现 tier 级红线守卫

### 不变量检查

- `orchestrator/invariants.py` — `InvariantChecker.check_all()` 在 gate 通过前跑确定性检查，产出 `InvariantViolation`；`is_blocking()` 遇到 critical violation 直接阻断推进

### 预算监控

- `auto_runner/budget.py` — `BudgetMonitor.check()` 多维限制（USD / tokens / time / iterations / Codex 轮次），超标返回 `action=halt`

### 熔断器

- `core/circuit_breaker.py` — 三态断路器（closed → open → half-open），外部服务故障时自动熔断，防止级联失败

### 守卫总结

```
Model Output
    │
    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ _parse_json  │───▶│ Invariant    │───▶│ Budget       │
│ (结构校验)    │    │ Checker      │    │ Monitor      │
└──────────────┘    │ (不变量)      │    │ (预算)        │
                    └──────────────┘    └──────────────┘
                           │                    │
                    ┌──────────────┐    ┌──────────────┐
                    │ Cost         │    │ Circuit      │
                    │ Red Line     │    │ Breaker      │
                    │ (成本阻断)    │    │ (熔断器)      │
                    └──────────────┘    └──────────────┘
```

---

## Layer 5: Tool Routing

Model 不选择自己，Harness 按任务特征分发。

### Tier-Based Routing

```python
TaskTier = Literal["light", "medium", "heavy"]

# paperindex/llm/client.py
_DEFAULT_ROUTES = {
    "light":  ("cursor", "composer-2-fast"),
    "medium": ("cursor", "gpt-5.4-medium"),
    "heavy":  ("anthropic", "claude-opus-4-6"),
}
```

### Primitive → Tier 映射

| Primitive | Tier | 典型 Provider |
|-----------|------|--------------|
| `paper_summarize` | light | Cursor basic |
| `claim_extract` | light | Cursor basic |
| `gap_detect` | medium | Cursor advanced |
| `deep_read_pass1` | medium | Cursor advanced |
| `deep_read_pass2` | heavy | Codex / Claude |
| `consistency_check` | heavy | Codex / Claude |

### 分发层次

| 组件 | 职责 |
|------|------|
| `llm_primitives.py` — `_PRIMITIVE_TIERS` | primitive name → tier |
| `paperindex/llm/client.py` — `resolve_route()` | tier → (provider, model)，含红线 fallback |
| `auto_runner/tool_dispatch.py` — `dispatch()` | 按四类分发（primitive / orchestrator / service / query） |
| `execution/factory.py` — `_BACKENDS` | 后端注册表，harness 选择实例 |
| `auto_runner/stage_policy.py` — `should_invoke_codex()` | 按 stage 策略决定是否引入 cross-model 审查 |

---

## One-Line Summary

> Model 被严格限制在 "给定结构化输入，产出结构化输出" 的角色中。类型系统约束 I/O、状态机控制流程、DB 持有记忆、多重守卫验证输出、tier routing 决定谁来推理——这就是 Harness Engineering。
