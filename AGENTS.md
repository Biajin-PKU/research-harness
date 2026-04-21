## Research Harness 集成

本项目使用 Research Harness 进行科研流程管理。

### 系统位置

- Research Harness: `~/code/research-harness`
- Agent 使用手册: `~/code/research-harness/docs/agent-guide.md`
- 数据库: `~/code/research-harness/.research-harness/pool.db`

### 必读

开始任何科研工作前，先读取使用手册：

```bash
cat ~/code/research-harness/docs/agent-guide.md
```

### 三条铁律

1. 论文必须入库：通过 research-harness MCP 的 `paper_ingest` 或 `rh paper ingest` CLI 入库，不要把论文散放在项目目录
2. 产出必须记录：关键产出通过 `orchestrator_record_artifact` 记录到数据库
3. 经验必须反馈：工具不足、流程改进、bug 写入 `~/code/research-harness/docs/feedback/`

### ⚠️ MCP 优先，CLI 只做数据管理

**所有 research primitive（gap_detect、claim_extract、baseline_identify、section_draft、consistency_check 等）必须通过 MCP 工具调用，不要用 `rh` / `rh` CLI 执行这些操作。**

原因：CLI 绕过了 provenance 追踪、orchestrator gate 检查和 artifact 版本管理。

| 场景 | 用 MCP 工具 | 禁止 |
|------|------------|------|
| 识别 baseline | `baseline_identify(topic_id=X)` | `rh baseline-identify ...` |
| 提取 claims | `claim_extract(paper_ids=[...])` | `rh claim-extract ...` |
| 起草章节 | `section_draft(section=..., topic_id=X)` | `rh section-draft ...` |
| 检测 gap | `gap_detect(topic_id=X)` | `rh gap-detect ...` |

`rh` / `rh` CLI 只用于：`topic list`、`paper list`、`paper ingest`、`orchestrator status` 等只读/入库操作。

### 可用工具（MCP research-harness）

- `paper_search`：多源论文搜索
- `paper_ingest`：论文入库（arxiv_id / DOI / PDF）
- `paper_summarize`：论文摘要
- `claim_extract`：提取研究声明
- `gap_detect`：研究空白分析
- `baseline_identify`：baseline 识别
- `section_draft`：章节起草
- `consistency_check`：一致性检查
- `orchestrator_resume`：**接管已有项目的首选入口**，自动从现有 artifact 推断当前阶段（不会从头开始）
- `orchestrator_status` / `orchestrator_advance` / `orchestrator_gate_check`：流程编排
- `adversarial_review`：**独立跨模型对抗审查**（Claude 环境自动调 Codex/GPT，Codex 环境自动调 Opus，保证 reviewer 独立性）
- `adversarial_run` / `adversarial_resolve`：手动对抗轮次管理（高级用法）

### Codex 中的 Research Harness Skills

如果已在 `~/.codex/skills/` 安装 Research Harness skills，优先按以下触发词理解：

- `research-harness`
- `research-init`
- `literature-search`
- `literature-mapping`
- `citation-trace`
- `claim-extraction`
- `gap-analysis`
- `evidence-gating`
- `section-drafting`
- `paper-verify`
- `provenance-review`

兼容输入写法：

- 直接写 skill 名称，如 `literature-search`
- 使用 Claude 风格前缀，如 `/literature-search`
- 入口分流，如 `/research-harness 帮我初始化一个新 topic`
- 在中文里明确说“用 literature-search skill”或“执行 /research-init”

注意：Codex 没有 Claude Code 那种原生 `/命令` 注册表。这里的 `/xxx` 是约定式触发词，不是 REPL 内建命令。

### 可用 Agents

- `literature-mapper`
- `proposer`
- `challenger`
- `adversarial-resolver`
- `synthesizer`

### 自由度

你可以按任意顺序、任意方式使用以上工具。12 阶段流程是参考框架，不是强制要求。人类研究员随时可以干预。
