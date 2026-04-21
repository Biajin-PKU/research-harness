<p align="center">
  <img src="docs/assets/hero.png" alt="Research Harness" width="720"/>
</p>

<h1 align="center">Research Harness</h1>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md"><b>简体中文</b></a>
</p>

<p align="center">
  <b>循证求真，筑基自主科研。</b>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"/></a>
  <img src="https://img.shields.io/badge/tests-987%2B-green.svg" alt="Tests"/>
  <img src="https://img.shields.io/badge/MCP-112_tools-orange.svg" alt="MCP tools"/>
  <img src="https://img.shields.io/badge/primitives-69-purple.svg" alt="Primitives"/>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/status-v0.1.0-yellow.svg" alt="Status"/>
</p>

---

```text
   init  ─▶  build  ─▶  analyze  ─▶  propose  ─▶  experiment  ─▶  write
     │         │          │           │              │            │
     ▼         ▼          ▼           ▼              ▼            ▼
  ┌──gate──┬──gate──┬───gate───┬───gate───┬────gate────┬──gate──┐
  │artifact│ claims │   gaps   │ proposal │   results  │ paper  │
  └────────┴────────┴──────────┴──────────┴────────────┴────────┘
```

每一条箭头都是一道**强类型的证据门禁**。没有对应产物，门不开。
没有 provenance 记录，原语不执行。**没有过注册表校验的数字，不许写进论文。**

---

## 为什么是 Research Harness？

当前 AI 科研赛道主要在做两类产品：

| 形态 | 优点 | 短板 |
|------|------|------|
| 🤖 **全自动流水线**（idea → 论文 N 步生成） | 一键跑完 | 黑箱运行，引用可伪造，没有你能复核的检查点 |
| 📚 **技能包 / Skills 库**（一堆 Markdown 或 TS 提示词） | 可组合、无绑定 | 没有状态，没有溯源，每次都从零开始 |

**Research Harness 两者都不是。** 它是上面这些产品本应跑在其上的**基础设施层** ——
一套让科研可审计、可查询、可在 agent 与人类之间安全交接的工程化框架。

我们起这个名字是认真的。**Harness 不是爬山的人，它是让你掉不下去的那根绳。**

---

## 三大核心支柱

### 🛡️ 一、证据门禁驱动的流程编排
六个阶段，之间都有强类型门禁。一道 gate 不是一段提示词，而是一份**契约**：
它会检查上一阶段交出的产物，拿不出证据就不开门。不是线性流水线，而是**带不变式的状态机**。

### 🗄️ 二、长期沉淀的论文数据库
一个**共享的 SQLite `pool.db`**，跨 session、跨项目、跨协作者持续沉淀：

- 论文记录按 arXiv / DOI / S2 ID 自动去重合并
- 全文 PDF、论文卡片、精读笔记、Claim 抽取全部入库
- 机构信息补全、引用图扩充、覆盖度跟踪
- 可被 `sqlite3`、Pandas、DuckDB 或任意 SQL 工具直接查询

不再是四处散落的 Markdown Wiki，也不再是"堆一大堆文件然后烂掉"。
**一个数据库，承载你整个科研生涯。**

### 🔬 三、每一次调用都有凭证
每一次原语调用都会记录模型、成本、输入 / 输出哈希、产物血缘（`derived_from`、`consumed_by`）。
论文交稿前，`paper_verify_numbers` 会把每一个数字比对到你**实际实验产出的注册表**。
伪造在这里不是"需要避免"，而是**在工程上不可能发生**。

---

## 功能亮点

- 🎯 **69 个原语 → 112 个 MCP 工具** — 检索、抽取、校验、评审、起草、数字核对
- ⚖️ **双轴执行** — `workflow_mode` × `autonomy_mode`，自行拧旋钮平衡风险
- 🔁 **跨模型对抗评审** — 关键决策点由另一个模型 challenge，而非自证
- 🧩 **插件化扩展** — 一个 YAML manifest 就能加原语、加 gate、加阶段、加后端
- 🌐 **客户端无关** — MCP / Python API / CLI 三条路径 100% 覆盖所有原语
- 🎨 **论文级配图生成** — `figure_plan` + `figure_generate` 调用 fal.ai，直接产出可塞进 LaTeX 的架构图
- 🪶 **国内模型友好** — 内置 Kimi / Moonshot，后续将加入 Qwen、DeepSeek、GLM
- 📊 **本地 Web Dashboard** — `http://127.0.0.1:18080` 实时监控
- ✅ **987+ 单元测试** 覆盖三个 package

---

## 三种使用路径

任选其一，底层共享同一个数据库和 provenance。

| 路径 | 适用场景 | 入口 |
|------|----------|------|
| 🤖 **MCP 客户端**（Claude Code、Codex） | Agent 驱动的对话式科研 session | 5 行配置 — [见下 ↓](#mcp-server) |
| 🐍 **Python API** | Notebook、流水线、嵌入既有代码 | `from research_harness import ResearchAPI` |
| ⌨️ **`rh` CLI** | 终端、Shell 脚本、CI | `rh topic init "my-topic"` |

> 不装 MCP 客户端也完全可以用。Python API 与 CLI 各自覆盖 100% 原语，MCP 只是三种传输之一。

---

## 快速开始

```bash
git clone https://github.com/your-org/research-harness.git
cd research-harness
./setup.sh                          # 自动识别 venv / conda
cp .env.example .env                # 填一个 LLM key 即可
rh topic init "my-research-topic"   # 准备就绪
```

**最小必填（三选一）：**

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
KIMI_API_KEY=sk-...          # Kimi / Moonshot — 国内可直连
```

---

## MCP Server

### Claude Code

写入 `.claude/settings.json`（项目级）或 `~/.claude/settings.json`（全局）：

```json
{
  "mcpServers": {
    "research-harness": {
      "command": "/absolute/path/to/research-harness/.venv/bin/python",
      "args": ["-m", "research_harness_mcp"],
      "env": {
        "RESEARCH_HARNESS_DB_PATH": "/absolute/path/to/pool.db"
      }
    }
  }
}
```

### Codex

写入 `~/.codex/config.toml`：

```toml
[mcp_servers.research-harness]
command = "/absolute/path/to/research-harness/.venv/bin/python"
args = ["-m", "research_harness_mcp"]
env = { "RESEARCH_HARNESS_DB_PATH" = "/absolute/path/to/pool.db" }
startup_timeout_sec = 30.0
```

或用命令行：`codex mcp add research-harness -- /abs/path/python -m research_harness_mcp`

配好之后，Claude Code / Codex 直接获得全部 112 个工具，无需其他安装。

---

## 横向对比

|  | 全自动流水线 | 技能包 / Skills 库 | **Research Harness** |
|---|:---:|:---:|:---:|
| 流程编排 | N 步跑到底 | — | **6 阶段 + 类型门禁** |
| 跨 session 状态 | 运行产物 | Markdown 文件 | **SQLite `pool.db`** |
| 全链 Provenance（成本 / 模型 / 哈希） | 部分支持 | — | **每次调用都有** |
| 数字核对 | 注册表（防幻觉） | — | **注册表 + 硬门禁** |
| 扩展方式 | fork 改 | fork 改 | **YAML 插件清单** |
| 客户端支持 | 通常绑一个 | 看具体 agent | **MCP + Python + CLI** |
| 测试覆盖 | — | — | **987+** |

别人是一键跑完的应用。我们是**底下那一层**：**可审计、可扩展、可信任的科研基础设施。**

---

## 仓库结构

```
research-harness/
├── packages/
│   ├── paperindex/              # PDF 理解引擎
│   ├── research_harness/        # 编排 + 原语 + provenance + 插件
│   └── research_harness_mcp/    # 112 个工具的 MCP server（stdio）
├── docs/                        # agent-guide / architecture / plugin-guide / quickstart
├── web_dashboard/               # Flask 监控面板（http://127.0.0.1:18080）
└── .research-harness/pool.db    # 你的长期论文数据库
```

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/quickstart.md](docs/quickstart.md) | 详细安装与配置 |
| [docs/agent-guide.md](docs/agent-guide.md) | Claude Code / Codex 的用法 |
| [docs/architecture.md](docs/architecture.md) | 系统架构与门禁规范 |
| [docs/python-api.md](docs/python-api.md) | 不依赖 MCP 客户端的 Python 用法 |
| [docs/plugin-guide.md](docs/plugin-guide.md) | 自定义原语 / 门禁开发 |

---

## 测试

```bash
python -m pytest packages/ -q --ignore=packages/research_harness_eval
```

## License

[Apache License 2.0](LICENSE) — 所有贡献默认使用同一许可证。

## 贡献

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。Issue / PR 均欢迎。

## 致谢

基于 [MCP](https://modelcontextprotocol.io) 构建，感谢
[Semantic Scholar](https://www.semanticscholar.org)、
[OpenAlex](https://openalex.org)、
[arXiv](https://arxiv.org)、
[Unpaywall](https://unpaywall.org)
提供的开放文献数据底座。
