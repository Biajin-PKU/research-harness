# Process Improvements

> 流程改进建议。Agent 或人类在科研过程中发现的可以简化、优化的工作流程。

---

## [2026-04-08] research-init 不应收集 research question，而应收集 research direction [DRAFT]

**问题**：`research-init` 在项目初期要求用户提供 research question，但此时上下文不足（无文献综述、无 gap 分析），导致写入 CLAUDE.md 的 research question 要么是伪精确，要么是强迫用户过早承诺。新 session 进来直接调用 skill 时，系统拿到的是一个不准确的"研究问题"。

**根本原因**：research question 不是一次性生成的，而是随项目阶段演化的：
- Day 0：研究方向（vague direction）
- 文献综述后：gap-driven question（精确，基于 gap analysis）
- 实验设计后：contribution claim（可写进摘要）

**改进方案**：
1. `research-init` 只收集 **research direction**，明确标注为 `[DRAFT]`
2. CLAUDE.md 写入字段名改为 `Research Direction [DRAFT]`，带时间戳
3. 后续 skill（`/gap-analysis`）完成后，负责更新该字段并去掉 DRAFT 标注
4. skills 读取上下文时，读 CLAUDE.md 的 Research Direction 即可，无需额外查 DB

**影响的 skill**：`research-init`（已更新），`/gap-analysis`（待添加"更新 CLAUDE.md direction"步骤）

---

## [2026-04-08] research-init 的 Step 6 (record artifact) 依赖 MCP runtime，但 Skill 执行环境不保证 MCP 可用

**问题**：research-init Step 6 要求调用 `orchestrator_record_artifact`，但 Skill 是在 Claude Code 主会话中展开执行的纯文本指令，不能直接写 `mcp__research-harness__orchestrator_record_artifact(...)`——需要 Agent 自行判断是通过 MCP 调用还是操作 DB。这导致执行路径不确定，容易出错（如本次先尝试 Python import 失败，再尝试直接操作 DB 时表名/列名不对）。

**建议改进**：
1. Skill 模板中的 Step 6 应明确指导 Agent 使用 `rhub` CLI 而非 MCP 或直接 DB，因为 CLI 是最可靠的本地调用方式
2. 或者提供 `rhub artifact record` CLI 命令（如果尚未实现）
3. Skill 模板中的代码示例应使用实际可执行的调用方式，避免伪代码

**优先级**: P1

---
