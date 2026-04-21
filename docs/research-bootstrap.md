# Research Harness Bootstrap Prompt

> 复制以下内容到你的项目 `CLAUDE.md`（Claude Code）或 `AGENTS.md`（Codex）中。
> 或者在 Claude Code 中直接运行 `/research-init`，会自动完成。

---

## 适用于项目 CLAUDE.md / AGENTS.md 的内容

```markdown
## Research Harness 集成

本项目使用 Research Harness 进行科研流程管理。

### 系统位置
- Research Harness: ~/code/research-harness
- Agent 使用手册: ~/code/research-harness/docs/agent-guide.md
- 数据库: ~/code/research-harness/.research-harness/pool.db

### 必读
开始任何科研工作前，先读取使用手册：
cat ~/code/research-harness/docs/agent-guide.md

### 三条铁律
1. **论文必须入库** — 通过 research-harness MCP 的 paper_ingest 或 `rhub paper ingest` CLI 入库，不要把论文散放在项目目录
2. **产出必须记录** — 关键产出通过 orchestrator_record_artifact 记录到数据库
3. **经验必须反馈** — 工具不足/流程改进/bug 写入 ~/code/research-harness/docs/feedback/

### 可用工具（MCP research-harness）
- paper_search — 多源论文搜索
- paper_ingest — 论文入库（arxiv_id/DOI/PDF）
- paper_summarize — 论文摘要
- claim_extract — 提取研究声明
- gap_detect — 研究空白分析
- baseline_identify — baseline 识别
- section_draft — 章节起草
- consistency_check — 一致性检查
- orchestrator_status/advance/gate_check — 流程编排
- adversarial_run/resolve — 对抗审查

### 可用 Skills（Claude Code / Codex 兼容触发词）
/research-harness, /research-init, /literature-search, /citation-trace, /gap-analysis, /claim-extraction, /section-drafting, /evidence-gating

在 Codex 中，以上 `/xxx` 作为 skill 触发词使用，不是原生 REPL 命令；推荐显式写出完整触发词。

### 可用 Agents
literature-mapper, proposer, challenger, adversarial-resolver, synthesizer

### 自由度
你可以按任意顺序、任意方式使用以上工具。12 阶段流程是参考框架，不是强制要求。人类研究员随时可以干预。
```
