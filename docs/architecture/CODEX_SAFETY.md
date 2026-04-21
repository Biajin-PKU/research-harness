# Codex 安全开发原则

本文档在 never-ask + full-permission 模式下约束 Codex 的行为边界。

---

## 铁律（违反任何一条必须停下来汇报）

1. **不删除现有文件** — 只新增或修改，不 `rm` 任何已有源码/测试/文档
2. **不修改 paperindex 包的公开 API** — `paperindex/__init__.py` 的 `__all__` 不动
3. **91 个现有测试必须始终通过** — 每完成一个 Step 都跑 `pytest packages/ -q`，失败了先修复再继续
4. **不安装架构文档以外的新依赖** — `pyproject.toml` 的 dependencies 不加新包，除非架构文档明确要求
5. **不碰 git 历史** — 不 rebase、不 force push、不 amend，只 add + commit
6. **不向外部发送任何请求** — 不 curl、不 pip install from URL、不调用外部 API（测试中 mock 所有外部调用）

---

## 开发节奏

### 每个 Step 的固定流程

```
1. 读架构文档 → 理解要做什么
2. 创建文件 / 修改文件
3. 运行: pytest packages/ -q --tb=short
4. 如果失败 → 修复 → 重新跑测试 → 循环直到全绿
5. 绿了 → 进入下一个 Step
```

### 必须汇报的时刻

| 触发条件 | 汇报内容 |
|----------|----------|
| 一个 Step 完成（测试全绿） | 新增了哪些文件，新增了几个测试，总测试数 |
| 遇到架构文档中没提到的问题 | 问题描述 + 你的临时方案 + 为什么这样做 |
| 需要修改现有代码的行为（不只是新增） | 改了什么 + 为什么必须改 + 对现有测试的影响 |
| 全部完成 | 总文件变更清单 + 总测试数 + `rhub doctor --json` 输出 |

### 不需要汇报的事

- 常规文件创建
- 测试编写过程中的中间失败
- import 调整、类型标注修复等琐碎变更

---

## 代码安全边界

### 允许

- 在 `packages/research_harness/research_harness/` 下创建新目录和文件
- 在 `packages/research_harness/tests/` 下创建新测试文件
- 在 `packages/research_harness/migrations/` 下创建新 migration SQL
- 修改 `research_harness/cli.py` — 添加新 command group 和 global option
- 修改 `research_harness/config.py` — 添加 `execution_backend` 字段
- 修改 `research_harness/__init__.py` — 更新 exports

### 禁止

- 修改 `packages/paperindex/` 下的任何文件
- 修改 `migrations/001_*.sql`, `002_*.sql`, `003_*.sql`（已有 migration 不可变）
- 修改 `pytest.ini`, `environment.yml`
- 在测试中使用真实 API key 或发送真实网络请求
- 在源码中硬编码任何密钥、token、URL
- 使用 `eval()`, `exec()`, `os.system()`, `subprocess` 执行任意命令

---

## 质量底线

- 所有新 dataclass 必须 `frozen=True`
- 所有新函数必须有类型标注（参数 + 返回值）
- 每个新模块必须有对应的测试文件
- 测试用 in-memory SQLite（复用现有 conftest.py 的 `db` fixture）
- 不要 mock 自己写的代码 — 只 mock 外部依赖和不存在的 backend

---

## 执行顺序（严格按序）

```
Step 1: primitives/types.py + registry.py + impls.py + __init__.py
        → test_primitives.py → pytest 全绿 → 汇报

Step 2: execution/backend.py + local.py + claude_code.py + harness.py + factory.py + __init__.py
        → test_execution.py → pytest 全绿 → 汇报

Step 3: migrations/004_provenance.sql + provenance/models.py + recorder.py + __init__.py
        + execution/tracked.py
        → test_provenance.py → pytest 全绿 → 汇报

Step 4: 修改 config.py + cli.py（新增 command groups + global option + doctor 扩展）
        → test_backend_cli.py + test_provenance_cli.py + test_primitive_cli.py
        → pytest 全绿 → 最终汇报
```

---

## 出错恢复

如果某个 Step 导致现有测试失败：

1. **不要继续下一个 Step**
2. 用 `git diff` 检查你改了什么
3. 如果是 import 顺序或模块加载问题 — 调整 `__init__.py`
4. 如果是现有代码被误改 — `git checkout -- <file>` 恢复
5. 如果是架构设计本身有冲突 — **停下来汇报**，描述冲突点

---

## 最终验证命令

全部完成后执行：

```bash
# 1. 全量测试
pytest packages/ -q --tb=short

# 2. 系统健康检查
python -m research_harness.cli doctor --json

# 3. 新功能 smoke test
python -m research_harness.cli backend list
python -m research_harness.cli backend info
python -m research_harness.cli primitive list
python -m research_harness.cli provenance list

# 4. 文件统计
find packages/research_harness/research_harness/primitives -name '*.py' | wc -l
find packages/research_harness/research_harness/execution -name '*.py' | wc -l
find packages/research_harness/research_harness/provenance -name '*.py' | wc -l
```

将以上命令的输出包含在最终汇报中。
