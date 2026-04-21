# Codex 启动指令

## 任务

实现 research-harness Phase 1 Foundation 的全部新增模块。

## 上下文

你在 `/workspace/research-harness` 容器内工作，有完整权限。项目是一个 Python monorepo，包含两个包：`paperindex`（PDF处理引擎）和 `research_harness`（研究工作流平台）。你只修改 `research_harness` 包。

## 必读文件（按顺序）

1. `docs/architecture/CODEX_SAFETY.md` — **铁律和开发边界，先读这个**
2. `docs/architecture/README.md` — 总览和依赖顺序
3. `docs/architecture/01_research_primitives.md` — Step 1 的完整设计
4. `docs/architecture/02_execution_backend.md` — Step 2 的完整设计
5. `docs/architecture/03_provenance.md` — Step 3 的完整设计
6. `docs/architecture/04_core_hardening.md` — Step 4 的整合方案

## 执行命令

```
按 CODEX_SAFETY.md 的 4 个 Step 严格顺序执行。
每个 Step 完成后运行 pytest packages/ -q --tb=short 确认全绿。
每个 Step 完成后向用户汇报：新增文件、新增测试数、总测试数。
全部完成后运行最终验证命令（见 CODEX_SAFETY.md 底部）并汇报。
```

## 关键约束

- 现有 91 个测试不能 break
- 不修改 `packages/paperindex/` 下的任何文件
- 所有新 dataclass 必须 `frozen=True`
- 测试中不发送真实网络请求
- 遇到架构文档没覆盖的问题，停下来汇报
