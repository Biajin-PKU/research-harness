# Phase 1 Architecture Design

本目录包含 Phase 1 (Foundation) 的完整技术架构设计，供 Codex 独立执行开发。

## 设计顺序与依赖关系

```
1.3 Research Primitives  ←─ 最先设计，定义工具词汇表
  │
1.2 ExecutionBackend     ←─ 依赖 1.3，定义执行接口
  │
1.4 Provenance           ←─ 依赖 1.2，记录每次执行
  │
1.1 Core Hardening       ←─ 依赖 1.2/1.3/1.4，整合进现有系统
```

## 文件清单

| 文件 | 内容 | 开发优先级 |
|------|------|-----------|
| [01_research_primitives.md](01_research_primitives.md) | Research Primitives 定义 + 数据类型 | P0 |
| [02_execution_backend.md](02_execution_backend.md) | ExecutionBackend 接口 + ClaudeCodeBackend 实现 | P0 |
| [03_provenance.md](03_provenance.md) | Provenance 系统设计 | P1 |
| [04_core_hardening.md](04_core_hardening.md) | 现有系统整合 + 测试补全 | P1 |
| [06_orchestrator.md](06_orchestrator.md) | Canonical research pipeline orchestrator 规范 | P0 |
| [07_orchestrator_implementation.md](07_orchestrator_implementation.md) | Orchestrator 具体落地方案与开发切片 | P0 |

## Codex 开发指南

1. **按文件编号顺序开发**，每完成一个跑一次全量测试
2. **容器内有所有权限**，可以自由安装依赖、修改文件
3. **现有 91 个测试必须持续通过**，新功能需要新测试
4. **不要修改 paperindex 包的公开 API**，只在 research_harness 包上扩展
5. **参考项目在** `/workspace/claw-code-main`, `/workspace/claude-code-main`, `/workspace/everything-claude-code`，按需读取
