# 可直接使用的研究工具资源报告

**报告日期**: 2026-04-05  
**调研范围**: MCP Servers, Claude Code Skills, Agents, Hooks

---

## 1. MCP Servers (可直接集成)

### 1.1 🌟 强烈推荐 - Scholar MCP (最全面)

| 属性 | 详情 |
|-----|------|
| **名称** | scholar-mcp |
| **作者** | Liyux3 |
| **GitHub** | https://github.com/Liyux3/scholar-mcp |
| **覆盖范围** | ~97% 的同行评议文献 |
| **数据源** | Semantic Scholar, arXiv, CORE, PubMed, bioRxiv, Google Scholar |

**核心功能**:
- `search_papers` - 搜索 2.14亿+ 论文，支持年份、会议、引用数筛选
- `get_paper` - 获取论文详情、TLDR摘要、BibTeX
- `get_citations` - 获取引用该论文的文献 (up to 1000)
- `get_references` - 获取参考文献 (up to 1000)
- `recommend_papers` - 相似论文推荐
- `search_authors` - 作者搜索 (h-index, 机构)
- `download_paper` - PDF下载 (多源回退)
- `read_paper` - PDF全文提取

**Claude Code 安装**:
```bash
claude mcp add scholar -- uvx scholar-mcp
# 或使用 API key
claude mcp add scholar -e S2_API_KEY=your_key -- uvx scholar-mcp
```

**评估**: ✅ **建议直接替换我们的 search/ingest 原语**

---

### 1.2 📚 Academic MCP (多源支持)

| 属性 | 详情 |
|-----|------|
| **名称** | academic-mcp |
| **作者** | LinXueyuanStdio |
| **GitHub** | https://github.com/LinXueyuanStdio/academic-mcp |
| **数据源** | 19+ 学术数据库 |

**支持平台**:
- 免费: arXiv, PubMed, PMC, bioRxiv, medRxiv, Google Scholar, Semantic Scholar, CORE
- 需 API Key: IEEE, Scopus, Springer, ScienceDirect
- 需机构权限: ACM, Web of Science, JSTOR

**核心工具**:
- `paper_search` - 多平台搜索
- `paper_download` - PDF下载
- `paper_read` - 全文阅读

**Claude Code 安装**:
```bash
pip install academic-mcp
claude mcp add academic -- python -m academic_mcp
```

**评估**: ✅ **数据源更全面，可补充 scholar-mcp**

---

### 1.3 📄 arXiv MCP Server

| 属性 | 详情 |
|-----|------|
| **名称** | arxiv-mcp-server |
| **作者** | blazickjp |
| **GitHub** | https://github.com/blazickjp/arxiv-mcp-server |
| **Stars** | 2.4k |

**评估**: ⚠️ arXiv 专用，功能已被 scholar-mcp 覆盖

---

### 1.4 🔍 其他 Semantic Scholar MCP

- **FujishigeTemma/semantic-scholar-mcp** - 官方风格实现
- **benhaotang/semantic-scholar-mcp** - 社区实现
- **yuzongmin/semantic-scholar-fastmcp** - FastMCP 实现

**评估**: ⚠️ 功能已被 scholar-mcp 覆盖

---

### 1.5 ✓ CiteCheck MCP (参考文献验证)

| 属性 | 详情 |
|-----|------|
| **名称** | citecheck |
| **论文** | arXiv:2603.17339 |
| **功能** | 自动验证和修复参考文献 |

**评估**: ✅ **可用于我们的 citation verification 功能**

---

## 2. Claude Code Skills (可直接使用)

### 2.1 📖 Awesome Claude Code Skills 合集

| 资源 | GitHub | Stars | 描述 |
|-----|--------|-------|------|
| **awesome-claude-code** | hesreallyhim/awesome-claude-code | 36k+ | 最全面的 Curated List |
| **claude-skills** | alirezarezvani/claude-skills | 9k+ | 220+ Skills |
| **awesome-agent-skills** | VoltAgent/awesome-agent-skills | 14k+ | 1000+ Skills |
| **antigravity-awesome-skills** | sickn33/antigravity-awesome-skills | 30k+ | 1340+ Skills |

---

### 2.2 🎓 研究相关 Skills

#### PapersFlow Skills (学术研究工作流)
- **作者**: @papersareflowing
- **功能**: 
  - 文献发现与综合
  - 参考文献管理
  - .bib 文件生成
  - PDF 下载
  - 文献综述生成
  - OpenAlex API 集成
- **状态**: 已提交到 awesome-claude-code #992, #990, #1352
- **评估**: ✅ **可直接使用或参考**

#### Literature Skill
- **来源**: LobeHub Skills Marketplace
- **功能**: 学术文献发现、综合、参考文献管理
- **评估**: ✅ **可用**

#### Scientific Writing Skill
- **来源**: mdskills.ai
- **功能**: 科学写作辅助
- **评估**: ✅ **可用**

---

### 2.3 🛠️ 推荐的 Skill 安装方式

```bash
# 方式1: 直接克隆 skill 仓库到 .claude/skills/
git clone <skill-repo> .claude/skills/<skill-name>

# 方式2: 使用 skill 安装工具
# (部分 skill 仓库提供安装脚本)
```

---

## 3. Agents (可参考/使用)

### 3.1 现有 Agent 资源

| 资源 | 来源 | 描述 |
|-----|------|------|
| **awesome-agent-skills** | VoltAgent | 包含多种 Agent 定义 |
| **claude-code-agents** | 各 skill 仓库 | 研究专用 Agents |

### 3.2 建议的做法

由于 Agents 通常与特定工作流绑定，建议:
1. 参考现有 Agent 的 Prompt 设计
2. 根据我们的 5 个 Agent (proposer, challenger, adversarial-resolver, literature-mapper, synthesizer) 进行适配

---

## 4. Hooks (可参考)

### 4.1 现有 Hook 资源

- **awesome-claude-code** 中收录了多种 Hooks
- **claude-devtools** - 提供 session log 分析
- **agnix** - Claude Code agent 文件 linter

### 4.2 我们的 Hooks (已有)

我们已有的 Hooks 已经比较完整:
- `record-provenance.py` - 来源记录
- `session-summary.py` - 会话总结

---

## 5. 资源对比与建议

### 5.1 MCP Server 对比

| 功能 | scholar-mcp | academic-mcp | 我们自研 | 建议 |
|-----|-------------|--------------|---------|------|
| 论文搜索 | ✅ 2.14亿+ | ✅ 19+数据源 | ✅ 基础 | **用 scholar-mcp** |
| PDF下载 | ✅ 多源回退 | ✅ | ✅ | **用 scholar-mcp** |
| 引用图 | ✅ | ❌ | ❌ | **用 scholar-mcp** |
| 全文提取 | ✅ | ✅ | ✅ paperindex | **结合使用** |
| 作者搜索 | ✅ | ❌ | ❌ | **用 scholar-mcp** |
| 多平台支持 | ❌ | ✅ 19个 | ❌ | **用 academic-mcp 补充** |
| IEEE/Scopus | ❌ | ✅ | ❌ | **用 academic-mcp** |

### 5.2 建议架构 (简化版)

```
Claude Code
  ├── MCP Servers (外部)
  │     ├── scholar-mcp     # 主要论文搜索/下载
  │     └── academic-mcp    # 补充数据源 (IEEE等)
  │
  ├── Skills (混合)
  │     ├── PapersFlow      # 文献综述工作流
  │     └── 我们的 Skills   # 保留 domain-specific skills
  │
  ├── Agents (自研)
  │     └── 我们的 5 个 Agents
  │
  └── Hooks (自研)
        └── provenance + cost tracking
```

---

## 6. 立即行动计划

### 方案 A: 最大复用 (推荐)

1. **集成 scholar-mcp**
   ```bash
   claude mcp add scholar -- uvx scholar-mcp
   ```
   - 替换我们的 `paper_search`, `paper_ingest` 原语
   - 使用其 `download_paper`, `read_paper` 功能

2. **保留 paperindex**
   - 专注于 PDF 理解和卡片生成
   - 不与 MCP 功能重复

3. **评估 PapersFlow Skills**
   - 查看是否可以直接使用
   - 或提取有价值的 workflow

4. **精简 research_harness**
   - 移除与 MCP 重复的 search/ingest
   - 保留: gap_detect, claim_extract, section_draft 等分析原语
   - 保留: provenance tracking

### 方案 B: 保持现状

- 继续使用自研 MCP (research_harness_mcp)
- 优势: 完全控制，定制化
- 劣势: 维护成本，功能不如成熟方案全面

---

## 7. 具体代码修改建议

### 7.1 修改 `.mcp.json`

```json
{
  "mcpServers": {
    "scholar": {
      "command": "uvx",
      "args": ["scholar-mcp"]
    },
    "academic": {
      "command": "python",
      "args": ["-m", "academic_mcp"],
      "env": {
        "ACADEMIC_MCP_ENABLED_SOURCES": "arxiv,pubmed,semantic,core,crossref,google_scholar"
      }
    },
    "research-harness": {
      "command": "python",
      "args": ["-m", "research_harness_mcp"]
    }
  }
}
```

### 7.2 精简后的原语保留清单

保留的 LLM 原语 (research_harness):
- `paper_summarize` - 论文摘要 (基于本地 PDF)
- `claim_extract` - 声明提取
- `gap_detect` - 缺口检测
- `baseline_identify` - 基线识别
- `section_draft` - 章节起草
- `consistency_check` - 一致性检查
- `evidence_link` - 证据链接

移除的原语 (由 MCP 替代):
- `paper_search` → scholar-mcp search_papers
- `paper_ingest` → scholar-mcp get_paper

---

## 8. 参考链接

### MCP Servers
- scholar-mcp: https://github.com/Liyux3/scholar-mcp
- academic-mcp: https://github.com/LinXueyuanStdio/academic-mcp
- arxiv-mcp-server: https://github.com/blazickjp/arxiv-mcp-server
- citecheck: https://arxiv.org/abs/2603.17339

### Skills & Agents
- awesome-claude-code: https://github.com/hesreallyhim/awesome-claude-code
- claude-skills: https://github.com/alirezarezvani/claude-skills
- awesome-agent-skills: https://github.com/VoltAgent/awesome-agent-skills
- antigravity-awesome-skills: https://github.com/sickn33/antigravity-awesome-skills

### PapersFlow
- Website: https://papersflow.ai/
- GitHub Org: https://github.com/papersflow-ai
- Skills: 已提交到 awesome-claude-code #1352

---

## 9. 结论

**核心发现**:
1. ✅ **scholar-mcp** 功能全面，可直接替代我们的 search/ingest
2. ✅ **PapersFlow** 提供完整的学术研究 workflow skills
3. ⚠️ 我们自研的 paperindex 在 PDF 理解方面仍有价值
4. ⚠️ 我们的 analysis 原语 (gap_detect, claim_extract 等) 仍有差异化价值

**建议**:
- **短期**: 集成 scholar-mcp，测试 PapersFlow
- **中期**: 精简自研代码，聚焦差异化功能
- **长期**: 评估是否全面转向成熟方案

**风险**:
- 外部 MCP 依赖可能不稳定
- 功能定制化程度降低
- 需要适配现有 provenance tracking
