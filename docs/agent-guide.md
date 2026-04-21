# Research Harness — Agent 使用手册

> 本手册面向所有 VIB-Coding Agent（Claude Code、Codex 等），帮助你在任意研究项目中一致地使用 Research Harness 进行科研。
> 你可以自由决定工作节奏、工具顺序和推进方式，但请遵守**入库规范、流程框架和经验记录**三个统一要求。

---

## ⚠️ 论文管理强制规范（每次 session 必读）

> 详细规范见：`~/code/research-harness/docs/PAPER_MANAGEMENT.md`

**三个不变量（任何 session、任何工具都必须保证）：**

1. **唯一数据库**：`~/.research-harness/pool.db`，禁止直接 SQL 写入，只通过 `paper_ingest` 或 CLI
2. **唯一 PDF 目录**：`~/.research-harness/downloads/`，路径必须是绝对路径
3. **必须指定 topic_id**：`paper_ingest(source=..., topic_id=<N>)`，裸入库不允许

**Session 开始时必做：**
```bash
rh topic overview <topic-name>      # 确认当前状态
rh paper queue --topic <topic-name> # 查看待处理论文
```

---

## 1. 系统概览

Research Harness 是一个 agent-first 的科研工作流平台，核心能力通过 MCP Server 暴露给 Claude Code。

```
你 (VIB-Coding Agent)
 │
 ├── MCP Tools (research-harness)     ← 核心研究原语，直接调用
 ├── Skills (.claude/skills/)     ← 领域工作流模板
 ├── Agents (.claude/agents/)     ← 专业角色 agent
 └── CLI (rhub)                   ← 数据管理和编排
       └── SQLite DB              ← 统一存储 + 溯源
```

**设计原则：** 你有完全的自由度决定何时、以何种顺序使用这些工具。系统只统一三件事：
1. 论文和产出**入库方式**统一（通过 MCP/CLI）
2. 科研**流程框架**统一（12 阶段参考流程）
3. **经验记录**方式统一（反馈循环回系统）

---

## 2. 核心工具清单

### 2.1 MCP Research Primitives（最常用）

| 工具 | 类型 | 用途 |
|------|------|------|
| `paper_search` | 检索 | 多源搜索论文（arXiv, Semantic Scholar, PASA 等） |
| `paper_ingest` | 检索 | 入库论文（arxiv_id / DOI / PDF 路径） |
| `paper_summarize` | 理解 | 生成论文摘要（可指定 focus） |
| `paper_list` | 查询 | 列出已入库论文 |
| `claim_extract` | 提取 | 从论文中提取研究声明 |
| `evidence_link` | 提取 | 将声明关联到证据 |
| `gap_detect` | 分析 | 检测研究空白 |
| `baseline_identify` | 分析 | 识别 baseline 方法 |
| `section_draft` | 生成 | 基于证据起草论文章节 |
| `consistency_check` | 验证 | 检查章节间一致性 |

### 2.2 编排工具（Orchestrator）

| 工具 | 用途 |
|------|------|
| `orchestrator_status` | 查看项目当前阶段和状态 |
| `orchestrator_advance` | 推进到下一阶段（自动检查 gate） |
| `orchestrator_gate_check` | 检查当前阶段的通过条件 |
| `orchestrator_record_artifact` | 记录阶段产出 |
| `adversarial_run` | 运行对抗审查轮次 |
| `adversarial_resolve` | 解决对抗审查结果 |
| `review_add_issue` | 添加审查问题 |
| `review_respond` | 回复审查意见 |
| `integrity_check` | 运行完整性验证 |
| `finalize_project` | 生成最终提交包 |

### 2.3 数据管理 CLI

```bash
rh topic init "topic-name"              # 初始化研究方向
rh paper ingest --arxiv-id 2401.12345   # 入库论文
rh paper queue --topic "topic-name"     # 查看待处理论文
rh task generate --topic "topic-name"   # 自动生成研究任务
rh topic overview "topic-name"          # 查看研究概览
```

### 2.4 Skills（工作流模板）

| Skill | 用途 | 调用方式 |
|-------|------|----------|
| `/literature-search` | 7 源综合文献检索 | 最全面的搜索流程 |
| `/literature-mapping` | 系统性文献地图构建 | 搜索 + 入库一体化 |
| `/citation-trace` | 引用链追踪 | 从种子论文扩展 |
| `/claim-extraction` | 声明提取 | 批量提取论文核心观点 |
| `/gap-analysis` | 研究空白分析 | 找到可做的方向 |
| `/evidence-gating` | 证据门控检查 | 判断是否可推进 |
| `/section-drafting` | 章节起草 | 基于证据写作 |
| `/paper-verify` | 论文验证 | 跨数据库验证论文存在性 |
| `/provenance-review` | 溯源审查 | 回顾执行历史和成本 |

### 2.5 Agents（专业角色）

| Agent | 角色 | 调用方式 |
|-------|------|----------|
| `literature-mapper` | 系统性文献搜索 | `Agent(subagent_type="literature-mapper")` |
| `proposer` | 提出研究方案 | 对抗优化中的提案方 |
| `challenger` | 挑战方案弱点 | 对抗优化中的质疑方 |
| `adversarial-resolver` | 裁决对抗结果 | 编排提案-质疑辩证 |
| `synthesizer` | 跨论文综合分析 | 证据结构化和草稿准备 |

---

## 3. 参考流程（5 阶段）

以下是推荐的科研流程，**你不需要严格按顺序执行**，但整体方向应从上到下推进。人类研究员随时可以干预、跳阶或回退。支持 loopback（analyze→build, propose→build）。

```
 ① Init      环境感知 → 引导交互 → query 生成 → 种子论文 → 参数确认
      ↓
 ② Build     多源检索 → 引用链扩充 → 去重 → 三信号过滤 → LLM 打分 → PDF 采集 → 结构化提取
      ↑ ↓      (analyze/propose 可 loopback 回 build 补充文献)
 ③ Analyze   覆盖度检查 → 方法族分类 → claim 提取 → claim 图谱 → gap 检测 → 方向排序
      ↓
 ④ Propose   提案草稿 → 方法层扩充(跨域) → 对抗优化 → 实验设计
      ↓
 ⑤ Write     竞品学习 → section 撰写 → 引用密度检查 → review 循环 → BibTeX 导出 → 组装
```

### 典型使用模式

**模式 A：完整科研流程**
适用于从零开始的新研究项目。按 5 阶段推进，每个 gate 都过。

**模式 B：局部使用**
适用于已有进展的项目。直接从当前阶段开始，按需回退补充。

**模式 C：纯文献支持**
只用 ①②③，为其他开发工作提供文献基础。不需要完整走流程。

---

## 4. 统一规范（必须遵守）

### 4.1 论文入库规范

**所有论文必须通过 MCP 或 CLI 入库**，不要散落在项目目录中。

```python
# 通过 MCP（推荐，自动记录溯源）
mcp__research-harness__paper_ingest(source="arxiv:2401.12345", topic_id=1, relevance="high")

# 通过 CLI
rh paper ingest --arxiv-id 2401.12345 --topic "my-topic" --relevance high

# 本地 PDF
mcp__research-harness__paper_ingest(source="/path/to/paper.pdf", topic_id=1)
```

入库后论文自动获得：
- 唯一 paper_id
- 溯源记录（谁、何时、从哪个源入库）
- 与 topic 的关联
- 可被后续所有工具引用

### 4.2 产出记录规范

每个阶段的关键产出应通过 `orchestrator_record_artifact` 记录：

```python
mcp__research-harness__orchestrator_record_artifact(
    project_id=1,
    topic_id=1,
    stage="literature_mapping",
    artifact_type="literature_map",
    title="Cross-Budget Literature Map v1",
    payload={"paper_clusters": [...], "baseline_papers": [...]}
)
```

### 4.3 经验记录规范

在科研过程中发现的任何可复用经验，请记录到以下位置：

| 经验类型 | 记录位置 | 示例 |
|----------|----------|------|
| 工具使用心得 | 项目 `session_handoff.md` | "PASA 搜索对新兴领域效果好但慢" |
| 流程改进建议 | `docs/feedback/` 目录下新建 md | "evidence_structuring 阶段应要求至少标记矛盾观点" |
| 缺失工具/Skill | `docs/feedback/tool-gaps.md` | "需要一个批量 PDF 下载工具" |
| MCP 工具 bug | `docs/feedback/bugs.md` | "paper_search venue_filter 不支持简写" |
| 搜索策略 | 入库到 provenance 系统 | 自动记录，无需手动 |

**格式要求：**
```markdown
## [日期] [经验标题]

**场景**: 在做什么时发现的
**问题/发现**: 具体内容
**建议改进**: 如何让系统更好
**优先级**: P0/P1/P2
```

---

## 5. 快速开始

### 场景：为新研究方向建立文献库

```
1. 初始化 topic
   rh topic init "my-research-topic" --venue "CONF 2026"

2. 搜索论文（任选方式）
   - 直接用 MCP: paper_search(query="my research query", year_from=2022)
   - 用 Skill: /literature-search （最全面）
   - 用 Agent: literature-mapper（自动多轮迭代）

3. 入库高相关论文
   paper_ingest(source="arxiv:2401.12345", topic_id=1, relevance="high")

4. 生成论文卡片
   paperindex_card(pdf_path="/path/to/paper.pdf")

5. 提取核心声明
   claim_extract(paper_ids=[1,2,3], topic_id=1, focus="key methodology")

6. 检测研究空白
   gap_detect(topic_id=1, focus="open problems in the area")

7. 查看概览
   rh topic overview "my-research-topic"
```

### 场景：对研究方向做对抗审查

```
1. 提出方案
   orchestrator_record_artifact(
       project_id=1, topic_id=1,
       stage="research_direction",
       artifact_type="direction_proposal",
       payload={...}
   )

2. 运行对抗审查
   adversarial_run(
       project_id=1, artifact_id=<proposal_id>,
       proposal_snapshot={...},
       objections=[...]
   )

3. 查看结果
   adversarial_status(project_id=1)

4. 解决并推进
   adversarial_resolve(project_id=1, round_artifact_id=<id>, scores={...})
```

> **统一协议**：所有对抗环节（`adversarial_optimization`、`study_design`、`novelty_check`）
> 均使用 `/adversarial-loop` skill 执行。该协议的核心规则：
> - Claude 将提案写入文件（`.research-harness/adversarial/{topic}/{stage}/round_N_proposal.md`）
> - 通过 `codex adversarial-review --wait --scope working-tree` 触发 Codex 审核
> - Claude **只读取 objection 行**（`grep "CRITICAL\|MAJOR"`），不将全文载入上下文
> - 最多 3 轮，`VERDICT: APPROVED` 即收敛
> - 收敛报告记录为 DB artifact（`adversarial_resolution` 类型）

---

## 6. 与研究项目的关系

Research Harness 支撑任意研究项目。创建 topic 后，论文库统一在 Research Harness 的 SQLite 数据库中，项目工作区可灵活配置在任意目录。

```bash
# 创建 topic 后查看概览
rh topic list
rh topic overview <topic-name>
```

---

## 7. 自由度与约束的边界

### 你可以自由做的事
- 以任意顺序调用任何工具
- 跳过不需要的阶段
- 在任何阶段回退
- 选择使用 Skill、Agent 还是直接调用 MCP
- 决定搜索深度和广度
- 选择哪些论文值得深入阅读

### 你必须做的事
- **论文必须入库**：发现的有价值论文通过 `paper_ingest` 入库
- **产出必须记录**：关键产出通过 `orchestrator_record_artifact` 记录
- **经验必须反馈**：发现的工具问题、流程改进建议写入 `docs/feedback/`
- **溯源自动化**：使用 MCP 工具时溯源自动记录，无需额外操作

### 人类研究员的角色
- 提供研究方向和 idea
- 在关键节点审批（topic_framing、research_direction、finalize）
- 随时可以干预、重定向或叫停
- 提供实验数据和领域判断
- 最终对论文质量负责

---

## 8. 反馈循环：让系统越来越好

这个系统的核心理念是**在科研过程中不断优化科研工具本身**。

```
科研工作 → 发现工具/流程不足 → 记录到 docs/feedback/
                                    ↓
                              人类审阅反馈
                                    ↓
                         优化 MCP/Skill/Agent/Hook
                                    ↓
                              下次科研工作更顺畅
```

每次你遇到以下情况，请主动记录：
- 想用某个工具但不存在 → 记录到 `tool-gaps.md`
- 某个工具不好用或有 bug → 记录到 `bugs.md`
- 某个流程可以简化 → 记录到 `process-improvements.md`
- 发现一个好的搜索策略 → 直接体现在 provenance 中

这些反馈将帮助研究员定期回顾和改进 Research Harness。

---

## 9. 附录：环境配置

```bash
# 必需环境变量
export RESEARCH_HARNESS_DB_PATH=".research-harness/pool.db"  # 或不设，使用默认

# LLM Provider 配置（多 provider 三档路由）
# 启用 CLI provider（推荐，利用 Cursor/Codex 订阅）
export CURSOR_AGENT_ENABLED=1   # Cursor Agent CLI (~9k overhead/call)
export CODEX_ENABLED=1           # Codex CLI (~33k overhead/call)

# 三档路由默认值（可通过 env 覆盖）
# LLM_ROUTE_LIGHT=cursor_agent:composer-2-fast   # summarize, classify
# LLM_ROUTE_MEDIUM=cursor_agent:gpt-5.4-medium   # claim_extract, gap_detect
# LLM_ROUTE_HEAVY=codex:gpt-5.4                  # consistency_check, adversarial

# 也支持 API provider（作为备选）
# export ANTHROPIC_API_KEY="..."
# export OPENAI_API_KEY="..."

# 安装
conda activate research-harness
pip install -e packages/research_harness[dev]
pip install -e packages/paperindex
```

MCP Server 在 Claude Code 中自动启动，无需手动管理。

## 10. 附录：调用方式说明

### MCP 调用 vs Python 直接调用

**推荐方式：通过 MCP 工具调用**（所有 research primitives 和 orchestrator 工具）：
```
mcp__research-harness__orchestrator_record_artifact(project_id=1, ...)
mcp__research-harness__claim_extract(paper_ids=[1,2], topic_id=1)
```

**Python 直接调用 — 推荐 `ResearchAPI`**（薄封装，与 MCP 工具语义对齐，自动解析 DB 路径）：
```python
from research_harness import ResearchAPI  # re-exported from research_harness.api

api = ResearchAPI()  # auto-resolves DB from RESEARCH_HARNESS_DB_PATH / workspace root
api.record_artifact(project_id=1, topic_id=1, stage="build",
                    artifact_type="literature_map", payload={...})
status = api.orchestrator_status(project_id=1)
```

**低层直接使用 `OrchestratorService`**（需要自行管理 `Database`）：
```python
from research_harness.orchestrator import OrchestratorService
from research_harness.storage.db import Database

db = Database("/path/to/.research-harness/pool.db")
db.migrate()
svc = OrchestratorService(db)
svc.record_artifact(project_id=1, topic_id=1, stage="build",
                    artifact_type="literature_map", payload={...})
```

> **注意**：`research_harness.mcp_primitives` 不存在；改用 `research_harness.api.ResearchAPI`
> 或 `research_harness.orchestrator.OrchestratorService`。

### DB Schema 参考（避免直接 SQL 操作出错）

如果必须直接操作 DB，注意实际的表名和字段名：

| 表名 | 关键字段 |
|------|----------|
| `project_artifacts` | id, project_id, topic_id, stage, artifact_type, title, **payload_json**, version, status |
| `papers` | id, title, year, venue, doi, arxiv_id, s2_id, url, pdf_path, status |
| `paper_topics` | paper_id, topic_id, relevance |
| `paper_annotations` | paper_id, section, content |
| `topic_paper_notes` | paper_id, topic_id, note_type, content |
| `orchestrator_runs` | id, project_id, topic_id, mode, current_stage, stage_status |
| `review_issues` | id, project_id, review_type, severity, category, summary, status |

> **payload 字段**：在 DB 中是 `payload_json`（TEXT），不是 `payload`。
> MCP 工具接受 `payload`（dict），内部自动序列化为 `payload_json`。
