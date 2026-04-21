<p align="center">
  <img src="docs/assets/hero.png" alt="Research Harness" width="720"/>
</p>

<h1 align="center">Research Harness</h1>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md"><b>简体中文</b></a>
</p>

<p align="center">
  面向科研文献工作的 Agent Harness —— 持久化状态、类型化原语、阶段门禁推进、可追溯的调用记录。
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-blue.svg" alt="License"/></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/tests-987%2B-green.svg" alt="Tests"/>
  <img src="https://img.shields.io/badge/primitives-69-purple.svg" alt="Primitives"/>
  <img src="https://img.shields.io/badge/MCP-112_tools-orange.svg" alt="MCP tools"/>
</p>

---

## 项目定位

Research Harness 是科研 Agent 在做文献综述、研究提案、实验协调和论文撰写时所依赖的**执行与状态层**。它负责运行「搜集证据 → 采取行动 → 核验结果」的循环，并把每一步都持久化下来，让下一次 session（无论是人还是 Agent）能从上一次停下的位置继续。

具体包含三层：

- **状态层** —— 单一的 SQLite `pool.db`，集中存放论文、Paper Card、精读笔记、Claim、artifact、provenance 记录；
- **原语层** —— 69 个类型化的科研操作（`paper_search`、`claim_extract`、`gap_detect`、`adversarial_review`、`section_draft`、`paper_verify_numbers` 等），一处注册，通过 112 个 MCP 工具、Python API 和 `rh` CLI 三个接口对外暴露；
- **控制层** —— 六个阶段（`init → build → analyze → propose → experiment → write`），每一次推进都要求上一阶段产出了能通过阶段边界门禁的类型化 artifact。

"Harness" 一词沿用 Anthropic Engineering 的定义[^1]：它是把模型变成 Agent 的那套系统 —— 编排工具调用、跨回合保留状态、记录发生的事情。Research Harness 把这套框架落到科研工作上。

[^1]: 参见 Anthropic Engineering 的 *Demystifying evals for AI agents*（2026 年 1 月）与 *Effective harnesses for long-running agents*（2025 年 11 月），二者给出了 Agent Harness 的基础定义。

## 项目动机

系统设计围绕文献密集型科研工作中的三个长期需求展开：

1. **连续性。** 一个论文项目往往跨越数周甚至数月，Agent 积累下来的状态 —— 已入库的论文、抽出的 claim、标记的 gap —— 必须能跨越 session 边界、跨越模型切换、跨越人工交接存活下来。
2. **可审计性。** 最终出现在论文草稿里的每一条论断，都应该能回溯到某个具体的源头：一篇论文、一段抽取的引文、一次实验运行、或一条经过核验的数字。
3. **阶段边界的可复核性。** 从文献综述到研究提案、从提案到实验、从实验到撰稿，这几个关键交接点上，人需要一个清晰的 checkpoint：直接可读的类型化 artifact。

Research Harness 把这三点当成一等公民：状态持久化在数据库里，经过记录通道的原语调用都带 provenance，阶段推进只在所需证据以类型化形式齐备时才开门。

## 面向谁

- **科研人员** —— 在文献密集项目中（PhD、应用实验室、产业研究）希望引入 Agent，同时保留对流程的复核能力。
- **Agent 工程师** —— 基于 MCP 客户端（Claude Code、Codex、自定义 runner）构建领域 Harness，需要一个把状态 / 门禁 / provenance 做完整的参考实现。
- **重视可复现性的团队** —— 需要在 Agent 产出的 artifact 上保证引用完整性和数字到实验的可追溯。

最适合的使用方式是：人工在阶段边界审核 artifact —— 系统的设计精力也都集中在这里。

## 快速上手

需要 Python 3.10+。一把 LLM API key（OpenAI、Anthropic 或 Kimi）即可起步。

```bash
git clone https://github.com/your-org/research-harness.git
cd research-harness
./setup.sh                    # 创建虚拟环境，安装三个 package
cp .env.example .env          # 填入一把 API key
rh topic init "my-topic"      # 注册一个研究主题
```

验证安装：

```bash
python -m pytest packages/ -q --ignore=packages/research_harness_eval
# 987+ passed
```

完整安装说明（含 Conda、GPU、离线环境）见 [`docs/quickstart.md`](docs/quickstart.md)。

## 一次完整的端到端全自动运行

同一条自主流水线，三种入口 —— 按手头的 session 挑一种即可。三种方式都会驱动项目走完六个阶段，都在同一套人工 checkpoint（方向选择、实验设计审批、finalize）停下来，并且都写入同一个 `pool.db`：在一种方式里起步，可以换另一种方式接着往下跑。

示例场景：一个 *diffusion-bidding* 主题、两篇种子论文的项目，自动推进 `init → build → analyze → propose`，在 `experiment` 之前停下供人工审阅方向。

### 1. Vibe coding —— 通过 MCP 由 Claude Code / Codex 驱动

配好 `research-harness` MCP server（见下文 [MCP —— Claude Code](#mcp--claude-code)）后，用自然语言驱动。Agent 会调用 `orchestrator_resume`，参数 `stop_before="experiment"`：

```
你：    在主题 "diffusion-bidding" 下新开一个 "paper-01" 项目。
        种子论文：arXiv 2407.15686 与 2404.10702。
        把流水线跑到 experiment 阶段之前停下，让我审方向。

Agent：[调用 paper_ingest × 2、orchestrator_init、orchestrator_resume
        mode="standard", stop_before="experiment"]
       已完成 init → build → analyze → propose，在 `experiment` 前暂停。
       direction_ranking 里有 3 个候选方向（得分 4.6 / 4.1 / 3.8）；
       gap_detect 标出了 7 个 open gap；adversarial_review 对
       候选 #1 提出了 2 条反驳。要打开看看吗？

你：    给我看候选 #2 的 artifact，然后继续跑到下一个 checkpoint。

Agent：[调用 orchestrator_artifacts 读候选 #2，再
        orchestrator_resume stop_before="finalize"]
       ...
```

这是 Agent 驱动时的标准流程。Agent 每一次工具调用都会跟 artifact 一起写进 `pool.db`，队友之后打开同一个数据库能看到全程轨迹。

### 2. CLI —— `rh auto-runner` 脚本

同一条流程的脚本化版本。不依赖 MCP 客户端，适合 CI、cron、远程 shell。

```bash
# 注册主题并入库种子论文
rh topic init "diffusion-bidding"
rh paper ingest --arxiv-id 2407.15686 --topic diffusion-bidding
rh paper ingest --arxiv-id 2404.10702 --topic diffusion-bidding

# 创建项目并启动自主 Runner
rh project add --topic diffusion-bidding --name paper-01
rh auto-runner start --project-id 1 --mode standard \
  --direction "Hierarchical diffusion planner for cross-channel budget allocation"

# Runner 自动推进 init → build → analyze → propose，然后在人工 checkpoint 停下。
# 查看 Runner 产出的 artifact：
rh auto-runner status     --project-id 1
rh orchestrator artifacts --topic diffusion-bidding --project paper-01 --stage propose

# 继续 —— Runner 会一路推进到下一个人工 checkpoint。
rh auto-runner resume --project-id 1
```

### 3. Python —— 直接调 `run_project`

同一条流程作为函数调用。适合写在 Notebook、更大的训练流水线、或任何已经 import 了 `research_harness` 的脚本里。

```python
from research_harness.auto_runner.runner import run_project, resume_project, get_status
from research_harness.api import ResearchAPI

api = ResearchAPI()                                    # 自动从环境解析 pool.db 路径
topic_id   = api.topic_init("diffusion-bidding")
api.paper_ingest(arxiv_id="2407.15686", topic_id=topic_id)
api.paper_ingest(arxiv_id="2404.10702", topic_id=topic_id)
project_id = api.project_add(topic_id=topic_id, name="paper-01")

result = run_project(
    project_id,
    topic_id=topic_id,
    direction="Hierarchical diffusion planner for cross-channel budget allocation",
    mode="standard",
)
# result = {"status": "paused", "current_stage": "propose", ...}

# 这里是人工审阅点 —— 检查 artifact、编辑、拍板
print(get_status(project_id))

# 继续跑到下一个 checkpoint（或跑到完成）
run_again = resume_project(project_id)
```

---

无论走哪种入口，Runner 都不止是一个加壳的 `for` 循环：

- 每个阶段都会把**类型化 artifact**（gap 表、claim 表、研究提案、草稿章节）写进 `pool.db`，Runner 只有在阶段边界的门禁接受这些 artifact 后才会跨过下一阶段。
- Runner 路由的每一次 LLM 调用都走 `TrackedBackend`，所以 `rh provenance list` 能清楚看到哪条 artifact 由哪个模型、在何种输入下、花了多少成本生成。
- Runner 是可恢复的：中途 kill 掉、换个模型、甚至把数据库拷到另一台机器，`resume` 会从最近一个 checkpoint 继续 —— 不论当初是由哪种入口启动的。

若需要完全手动逐个原语运行的走查版本（不启用 Runner），见 [`docs/quickstart.md`](docs/quickstart.md)。

## 三种接口

三种客户端访问的是同一套原语注册表，读写的是同一份 `pool.db`。按任务选一个顺手的即可。

| 接口 | 适合 | 入口 |
|------|------|------|
| **MCP server** | Claude Code / Codex / 任意 MCP 客户端 | `python -m research_harness_mcp` |
| **Python API** | Notebook、流水线、已有代码库 | `from research_harness import ResearchAPI` |
| **`rh` CLI** | 终端、脚本、CI | `rh --help` |

Provenance 说明：MCP server 和 `rh primitive exec` 走的是 `TrackedBackend`，每次执行都会被记录；Python API 直接调用原语实现，如果需要审计，请自行用 `TrackedBackend` 包一层。详见 [`docs/python-api.md`](docs/python-api.md)。

### MCP —— Claude Code

写入 `.claude/settings.json`（项目级）或 `~/.claude/settings.json`（全局）：

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "/absolute/path/to/research-harness/.venv/bin/python",
      "args": ["-m", "research_harness_mcp"],
      "env": { "RESEARCH_HARNESS_DB_PATH": "/absolute/path/to/pool.db" }
    }
  }
}
```

### MCP —— Codex

写入 `~/.codex/config.toml`：

```toml
[mcp_servers.research-harness]
command = "/absolute/path/to/research-harness/.venv/bin/python"
args = ["-m", "research_harness_mcp"]
env = { "RESEARCH_HARNESS_DB_PATH" = "/absolute/path/to/pool.db" }
startup_timeout_sec = 30.0
```

或用命令行：`codex mcp add research-harness -- /abs/path/python -m research_harness_mcp`。

## Vibe Coding 可用的 Skill

在 Claude Code 或 Codex 里，常态是用自然语言驱动 —— 你描述任务，Agent 自动路由到合适的 Skill，再由 Skill 调度对应的 MCP 工具。仓库里 [`codex-skills/`](codex-skills/) 下随发行版提供了 14 个 Skill，采用 Claude Code 通用的 YAML frontmatter 格式；把目录挂进 skills 路径后，下表里的触发语就能直接生效。

### 对照表

| Skill | 作用 | 自然语言触发示例 |
|-------|------|------------------|
| [`research-harness`](codex-skills/research-harness/SKILL.md) | 路由 Skill —— 意图宽泛时自动转到更具体的子 Skill | "进入科研工作流"、"用 Research Harness 开工" |
| [`research-init`](codex-skills/research-init/SKILL.md) | 初始化主题、搭项目骨架 | "给这个项目接入 Research Harness，主题是 X" |
| [`literature-search`](codex-skills/literature-search/SKILL.md) | 按查询做大范围论文检索 | "帮我搜一下 diffusion bidding 最近的论文" |
| [`literature-mapping`](codex-skills/literature-mapping/SKILL.md) | 聚类论文、识别 baseline、建主题地图 | "给这个主题做一份文献地图" |
| [`citation-trace`](codex-skills/citation-trace/SKILL.md) | 从种子论文沿引用链前/后扩展 | "从这三篇种子论文扩展" |
| [`paper-sync`](codex-skills/paper-sync/SKILL.md) | 体检论文池：元数据、PDF、dismiss | "同步一下我的论文池" |
| [`paper-verify`](codex-skills/paper-verify/SKILL.md) | 校验论文是否真实存在、元数据是否匹配 | "这个 DOI 是真的吗" |
| [`claim-extraction`](codex-skills/claim-extraction/SKILL.md) | 从论文抽取结构化 claim | "把论文 42 的核心 claim 抽出来" |
| [`gap-analysis`](codex-skills/gap-analysis/SKILL.md) | 找研究 gap、缺失的 baseline | "现在的研究 gap 在哪里" |
| [`evidence-gating`](codex-skills/evidence-gating/SKILL.md) | 判断阶段是否可以推进 | "现在能推进到 propose 阶段了吗" |
| [`section-drafting`](codex-skills/section-drafting/SKILL.md) | 基于已挂接的证据起草章节 | "根据抽出的 claim 写 related work" |
| [`provenance-review`](codex-skills/provenance-review/SKILL.md) | 回顾执行历史、已录 artifact、挂接关系 | "审一下这个项目最近的 provenance" |
| [`research-primitives`](codex-skills/research-primitives/SKILL.md) | 参考 —— 所有 MCP 原语一览 | "给我看原语参考表" |
| [`task-taxonomy`](codex-skills/task-taxonomy/SKILL.md) | 参考 —— 模型路由与任务分类指引 | "claim extraction 该用哪一档模型" |

### 示例 —— 自然语言到 Skill 路由

- "开一个关于 hierarchical diffusion bidding 的新项目，先拉 20–30 篇最近的论文" → `research-init` → `literature-search`
- "从这两个 arXiv ID 出发扩展论文池" → `citation-trace`
- "已经入库 80 篇了，研究 gap 在哪儿" → `claim-extraction` → `gap-analysis`
- "基于抽出的 claim 起草 related work 章节" → `section-drafting`
- "现在能不能推进到 experiment 阶段" → `evidence-gating`
- "审一下这个项目上周做过什么" → `provenance-review`

### 在 Claude Code 里启用

```bash
# 方案 A：把仓库里的 skill 软链到用户级 skills 目录
mkdir -p ~/.claude/skills
ln -s "$(pwd)/codex-skills"/* ~/.claude/skills/

# 方案 B：项目级
mkdir -p .claude/skills
cp -r codex-skills/* .claude/skills/
```

Codex 直接从 `codex-skills/` 读取。两种客户端都认同一份 `SKILL.md` 格式 —— 上表里的触发语在任一侧都适用。

## 可信机制

以下三个机制在 [`docs/architecture.md`](docs/architecture.md) 中有更详细的规范说明。

**Provenance（溯源记录）。** 经 `TrackedBackend` 调用的原语（MCP server、`rh primitive exec`）会被记录：模型、档位（tier）、成本、输入 / 输出哈希、以及依赖边（`derived_from`、`consumed_by`）。可以用 `rh provenance list` 或直接写 SQL 查询。Python API 直接调用不会自动记录，有审计需要时请自行包裹 `TrackedBackend`。

**阶段门禁（Stage Gates）。** 一个「阶段」是 `init → build → analyze → propose → experiment → write` 中的一个命名步骤；一个「门禁」是在阶段边界运行的类型化检查。门禁读取当前阶段产出的 artifact，当必要证据缺失时，它不会让流水线推进。门禁是对 artifact 类型的代码化检查。

**Verified Number Registry（已核验数字注册表）。** 进入 `write` 阶段后，草稿中出现的数字可以与一份由**已记录实验指标**构建出的注册表对照。`paper_verify_numbers` 原语负责比对，支持可配置的容差和分节严格度（严格节中的未匹配数字标记为 error，宽松节中标记为 warning）。Always-allowed 值（常用常数、年份、已注册的数据集规模等）会被排除在检查之外。这套机制用来在评审环节捕捉伪造的数字，不替代评审人本身。

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│   MCP server（112 个工具，stdio 传输）                       │
├──────────────────────────────────────────────────────────────┤
│   Orchestrator（编排器）                                     │
│     init → build → analyze → propose → experiment → write    │
│     gates: approval · coverage · adversarial · review ·      │
│            experiment                                        │
├──────────────────────────────────────────────────────────────┤
│   Primitives (69)      Provenance         Observation        │
│   类型化操作           审计轨迹           策略演化            │
├──────────────────────────────────────────────────────────────┤
│   执行后端（LLM 路由、本地、插件）                           │
├──────────────────────────────────────────────────────────────┤
│   SQLite pool.db（论文 · artifact · provenance · tasks）     │
└──────────────────────────────────────────────────────────────┘
```

**双轴执行。** 两个独立的旋钮：

- `workflow_mode` ∈ {`explore`, `standard`, `strict`, `demo`} —— 控制深度、覆盖度和质量阈值。
- `autonomy_mode` ∈ {`supervised`, `autonomous`} —— 控制由谁来解门。方向选择、finalize 这类高风险阶段，即便在 autonomous 模式下也强制要求人工审批。

**跨模型对抗评审（Cross-model adversarial review）。** 在 `propose → experiment` 这类仅靠自洽无法担保结论的 checkpoint 上，提案和草稿会交给一个独立的 challenger 模型评审。challenge / response / resolution 三段都会作为一等公民 artifact 落盘。

## 扩展

新能力通过 `plugin.yaml` 清单发布，不必 fork 主仓。

```yaml
# plugin.yaml
name: my-paper-source
version: 0.1.0
description: Custom paper source integration
author: Your Name
license: Apache-2.0
schema_version: 1
min_harness_version: 0.1.0
extension_points:
  primitives:
    - name: my_search
      category: RETRIEVAL
      module: my_plugin.search
      function: search_impl
      requires_llm: false
```

原语通过 `@register_primitive(spec)` 注册；门禁继承 `GateEvaluator`；后端实现 `ExecutionBackend`。完整的清单 Schema、扩展点列表和发现流程见 [`docs/plugin-guide.md`](docs/plugin-guide.md)。

## 文档

| 文档 | 内容 |
|------|------|
| [`docs/quickstart.md`](docs/quickstart.md) | 安装、API key 配置、第一个主题 |
| [`docs/architecture.md`](docs/architecture.md) | 阶段、门禁、artifact 类型、存储模型 |
| [`docs/agent-guide.md`](docs/agent-guide.md) | Claude Code / Codex 如何驾驭 Harness |
| [`docs/python-api.md`](docs/python-api.md) | 不依赖 MCP 客户端的 Python 用法 |
| [`docs/plugin-guide.md`](docs/plugin-guide.md) | 自定义原语 / 门禁 / 后端开发 |
| [`docs/PAPER_MANAGEMENT.md`](docs/PAPER_MANAGEMENT.md) | 论文存储的规范协议 |

## 项目状态

**0.1.0** —— 首个公开版本。三个 package 合计 987+ 单元测试、69 个原语、112 个 MCP 工具、6 个阶段。版本说明见 [`CHANGELOG.md`](CHANGELOG.md)。

已支持的 LLM Provider：OpenAI、Anthropic、Kimi / Moonshot。Qwen、DeepSeek、GLM 通过 tier 路由接入在近期路线图中。

已知边界：

- Experiment 阶段的算力由用户自备，Research Harness 不负责 provision 训练作业。
- `figure_generate` 调用 fal.ai，需要相应的 API key。
- 数字核验覆盖的是**已记录的实验指标**；来自系统外的数字（例如引用的 baseline）需要登记为 always-allowed 或人工复核。

## 引用

若在学术工作中使用 Research Harness，请引用：

```bibtex
@software{research_harness_2026,
  title        = {Research Harness: an agent harness for scientific literature},
  author       = {Research Harness Contributors},
  year         = {2026},
  version      = {0.1.0},
  url          = {https://github.com/your-org/research-harness},
  license      = {Apache-2.0}
}
```

## License

[Apache License 2.0](LICENSE)。所有贡献默认使用同一许可证。

## 贡献

见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。欢迎 Issue 和 PR；小修复可直接提交，新增原语、门禁、阶段建议先开 Issue 讨论。

## 致谢

基于 [MCP](https://modelcontextprotocol.io) 构建。文献数据来自 [Semantic Scholar](https://www.semanticscholar.org)、[OpenAlex](https://openalex.org)、[arXiv](https://arxiv.org) 和 [Unpaywall](https://unpaywall.org)。

## 相关项目

Agent Harness 空间中的相关工作 —— 各自针对不同的工作流：

- [`anthropics/claude-code`](https://github.com/anthropics/claude-code) —— 终端里的 Agentic 编程 Harness。
- [`SWE-agent/SWE-agent`](https://github.com/SWE-agent/SWE-agent) —— 面向软件基准测试的 Issue 解决 Harness。
- [`All-Hands-AI/OpenHands`](https://github.com/All-Hands-AI/OpenHands) —— 通用开发者 Agent 平台。
- [`langchain-ai/langgraph`](https://github.com/langchain-ai/langgraph) —— 面向 Stateful Agent 的低层编排框架。
