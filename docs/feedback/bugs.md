# Bugs

> MCP 工具、Skill、Agent 使用过程中发现的问题。

## 修复状态总览（2026-04-11 审计）

### ✅ 已在当前代码中修复（无需额外操作）
- **anthropic 依赖** (#6): `pyproject.toml` 已声明 `anthropic>=0.40.0`
- **citation_count 未填充** (#9): migration 010 + `enrich_metadata()` 已处理
- **DB 路径不在 orchestrator_status 返回** (#10): 已返回 `db_path` 字段
- **provenance_records.topic_id 为 NULL** (#11): `TrackedBackend` 已正确从 kwargs 提取
- **paper_ingest 元数据不完整** (#12): 已有重试 + 返回 `metadata_incomplete` 标记
- **max_results 默认值** (#13): MCP schema=50, 实现=500, 均合理
- **MCP 服务不可用** (#2): 环境问题, 已在之前修复
- **DB 损坏** (#4): `check_integrity()` + `auto_recover()` 已在 db.py 中实现

### ✅ 本次新修复（commit 1afe8eb）
- **relevance 浮点数→标签** (#16): `_normalize_relevance()` 将 "0.67" 等转为 high/medium/low
- **paper_purge 工具** (#5): 新增 MCP 工具, 可物理删除损坏论文
- **venue_refresh 工具** (#7): 新增 MCP 工具, 批量刷新 arXiv 占位 venue

### ⏳ 待实现（Feature Request）
- S2 rate limit retry/backoff (#8)
- 检索结果全量持久化 (#14)
- 已入库论文 query 精化 (#15)
- Agent 截断策略规范 (#17)
- Python API 层 (#1)
- DB 表名与文档不一致 (#3) — 文档问题

---

## [2026-04-08] orchestrator_record_artifact 无法通过 Python 直接调用

**场景**: 执行 `/research-init` Step 6，需要记录 topic_brief 产出
**问题**: `from research_harness.mcp_primitives import orchestrator_record_artifact` 报 `ModuleNotFoundError: No module named 'research_harness.mcp_primitives'`。实际实现在 `packages/research_harness_mcp/research_harness_mcp/tools.py`，但没有暴露为可独立导入的 Python API。
**影响**: Skill 中无法通过 Python 脚本调用 orchestrator 功能，只能：(1) 直接操作 SQLite，或 (2) 依赖 MCP server 运行时。直接操作 DB 需要知道表名和列名（`project_artifacts` 而非 `artifacts`，`payload_json` 而非 `payload`），容易出错。
**建议改进**: 
1. 提供一个轻量 Python API 层（如 `research_harness.api`），让 Skill 和 CLI 都能直接调用核心函数，无需经过 MCP 协议
2. 或者在 agent-guide.md 中明确说明：orchestrator 工具只能通过 MCP 调用，Skill 中应使用 `mcp__research-harness__orchestrator_record_artifact(...)` 而非直接 Python import
**优先级**: P1

---

## [2026-04-08] 所有 academic MCP 服务在 literature-search 时全部不可用

**场景**: 执行 `/literature-search` Phase 1 并行搜索时，5 个 MCP 工具同时报 `No such tool available`
**根本原因**: 三重问题叠加：
1. `research-harness` conda 环境不存在（`/workspace/research-harness/.conda` 路径硬编码，但本机无此路径）
2. `arxiv_mcp_server`、`refcheck`、`arxiv_latex_mcp`、`semantic-scholar-mcp`、`mcp-dblp` 均未安装在任何环境
3. `auto-bidding/.mcp.json` 使用 `uvx` 运行 semantic-scholar 和 mcp-dblp，但本机无 `uvx`
4. `research-harness` 和 `pasa_search` MCP 只配置在 `~/code/research-harness/.mcp.json`，不在 `auto-bidding` 的父目录链中，Claude Code 加载不到
**修复**: 新建 `research-harness` conda 环境，安装所有包，将 `.mcp.json` 改为使用绝对 python 路径，并将 research-harness MCP 合并到 `auto-bidding/.mcp.json`
**建议**: README 中应有明确的环境初始化步骤，且 `.mcp.json` 应使用绝对路径而非依赖环境变量或 `uvx`
**优先级**: P0（完全阻塞 literature-search 流程）

---

## [2026-04-08] DB 表名和字段名与 agent-guide 文档不一致

**场景**: 尝试直接操作 SQLite 记录 artifact 时
**问题**: agent-guide.md 的示例代码使用 `payload=` 参数，但实际 DB 表 `project_artifacts` 的列名是 `payload_json`。类似地，表名是 `project_artifacts` 而非 `artifacts`。Agent 在不经过 MCP 直接操作 DB 时容易踩坑。
**建议改进**: 如果允许直接 DB 操作，应在 agent-guide 中补充 DB schema 参考；如果不允许，应明确禁止并只暴露 MCP/CLI 接口。
**优先级**: P2

---

## [2026-04-08] baseline_identify / gap_detect 返回 "database disk image is malformed"

**场景**: 执行 `/gap-analysis` Phase 1-2，调用 `mcp__research-harness__baseline_identify(topic_id=1)` 和 `mcp__research-harness__gap_detect(topic_id=1)`
**问题**: 两个工具均返回 `Error: database disk image is malformed`，说明 SQLite DB 文件已损坏
**影响**: gap_detect 和 baseline_identify 完全不可用；需要手动完成 gap analysis，增加人工工作量；artifact 记录功能可能也受影响（但 orchestrator_record_artifact 经测试仍正常写入）
**DB 路径**: `<RESEARCH_HARNESS_ROOT>/.research-harness/pool.db`
**建议修复**:
1. 运行 `sqlite3 pool.db ".recover" | sqlite3 pool_recovered.db` 尝试恢复
2. 如果恢复成功，替换原 DB 文件
3. 建议在 research-harness 启动时增加 DB integrity check（`PRAGMA integrity_check`），损坏时给出明确错误提示
**优先级**: P0（gap_detect/baseline_identify 完全不可用）

---

## [2026-04-09] 单篇论文记录损坏导致整个 topic 的批量操作全部失败

**场景**: 执行 `/claim-extraction`，对 topic_id=2 中的论文批量调用 `claim_extract`
**问题**: paper_id=36（Chaos in Autobidding Auctions）的数据库记录损坏。只要该 paper 出现在 `paper_ids` 列表中，整个批次的 `claim_extract` 就返回 `database disk image is malformed`，其他正常论文一起受牵连失败。
更严重的是：`gap_detect(topic_id=2)` 在**不传任何 paper_ids** 的情况下也失败——说明 gap_detect 内部会遍历 topic 下所有论文，一旦遇到损坏记录就崩溃。即使用 `paper_dismiss` 将 paper 36 标记为忽略后，`gap_detect` 仍然失败，说明 dismiss 并未从遍历路径中排除该记录。
**复现步骤**:
1. `claim_extract(paper_ids=[36], topic_id=2)` → 立即报错
2. `claim_extract(paper_ids=[36, 135], topic_id=2)` → 立即报错（135 正常）
3. `paper_dismiss(paper_id=36, topic_id=2, reason=...)` → 返回成功
4. `gap_detect(topic_id=2)` → 仍然报错
**影响**: 整个 topic 的 `gap_detect`、`baseline_identify`、`paper_coverage_check` 全部不可用；claim_extract 需要手动排除损坏 paper 后逐批调用
**建议修复**:
1. `gap_detect` / `baseline_identify` / `paper_coverage_check` 等遍历操作，应在 SQL 查询层过滤掉 dismissed 论文（`WHERE status != 'dismissed'`）
2. 更根本的修复：在论文入库（`paper_ingest`）时对记录做完整性验证，防止损坏记录写入
3. 提供一个 CLI 命令（如 `rhub paper purge --paper-id 36`）彻底删除损坏记录，而不只是 dismiss
**优先级**: P0（单条损坏记录可导致整个 topic 所有分析工具瘫痪）

---

## [2026-04-09] claim_extract 缺少 anthropic 依赖未在安装时声明

**场景**: 首次调用 `claim_extract(paper_ids=[104,109,...], topic_id=2)`
**问题**: 返回错误 `anthropic package is required for Anthropic-backed LLM calls. Install with: pip install anthropic`。`anthropic` 包未在 research-harness 的依赖列表中声明，导致全新环境下 claim_extract 开箱即失败。
**修复**: 手动执行 `conda run -n research-harness pip install anthropic` 后恢复正常
**建议改进**: 在 `packages/research_harness/pyproject.toml`（或对应的 `setup.py`/`requirements.txt`）中将 `anthropic` 列为必需依赖，而非运行时才提示安装
**优先级**: P1（新环境首次使用必踩）

---

## ⚠️ [2026-04-10] [IMPORTANT] arXiv 预印本入库后 venue 不随正式录用自动更新，导致顶会论文被误判为未发表

**场景**: 检查 topic_id=4 中西湖大学的 ICLR 2026 论文时，发现 DeepScientist 入库时 venue 为 `arXiv.org`，尽管该论文已正式录用并发表于 ICLR 2026。

**问题**: `paper_ingest` 在论文首次以 arXiv 预印本形式入库时，venue 字段被设为 `arXiv.org`。此后即使论文被顶级会议正式录用，系统也不会更新 venue，导致：
1. 按 venue 过滤顶会论文（如 `WHERE venue LIKE "%ICLR%"`）会漏掉这类论文
2. Related Work 中引用该论文时，venue 信息错误（写成 arXiv 而非 ICLR 2026）
3. 无法统计某顶会中与本 topic 相关的论文数量
4. agent 评估论文质量时，venue=arXiv 会低估其学术影响力

**已确认案例**:
- DeepScientist（西湖大学，ICLR 2026）：库中 venue=`arXiv.org` → 已手动修正为 `International Conference on Learning Representations`
- AutoFigure（西湖大学，ICLR 2026，arXiv:2602.03828）：完全未入库 → 已手动补录

**根本原因**: `paper_ingest` 只做一次性元数据抓取，没有后续跟踪机制。arXiv 论文的 venue 字段通常为空或为 `arXiv.org`，而 Semantic Scholar 在论文正式发表后会更新 `venue` 字段，但系统没有定期同步。

**建议修复**:
1. **定期 venue 刷新**：对库中 venue 为 `arXiv.org` 或为空的论文，定期（每次 Build 阶段开始时）调用 S2 API 检查是否已有正式 venue，有则更新
2. **`paper_sync` 工具增加 venue 更新逻辑**：`/paper-sync` skill 目前只做 PDF 补全和健康检查，应增加 venue 同步步骤
3. **入库时标记 venue 置信度**：新增 `venue_confirmed` 布尔字段；arXiv 入库时置为 False，S2 确认正式录用后置为 True；过滤顶会时只信任 `venue_confirmed=True` 的记录
4. **`paper_ingest` 响应增加 venue 警告**：若入库时 venue 为空或 arXiv，在响应中提示"venue 未确认，建议后续通过 paper_sync 更新"

**优先级**: P1（直接影响 Related Work 引用准确性和顶会论文覆盖度评估）

---

## [2026-04-10] Semantic Scholar 因 rate limit 被跳过，导致大量相关论文漏检

**场景**: Build v1 阶段执行多源并行检索（`/literature-search`），Semantic Scholar 因 rate limit 被标记为 `"skipped_due_to_rate_limit"`，整轮检索中完全没有 S2 结果参与。

**直接后果（已确认案例）**:
- EMNLP 2025 main 论文 *SurveyGen: Quality-Aware Scientific Survey Generation with Large Language Models*（Tong Bao et al., University of Alberta）未被检索到，需人工发现后手动补录。S2 是覆盖 ACL Anthology 最完整的数据源，跳过 S2 直接导致 EMNLP/ACL/NAACL 等 NLP 顶会录用论文系统性缺失。

**根本原因**:
1. 并行调用多个 provider 时，S2 请求频率超出免费 API 限制（约 1 req/s）
2. 当前实现遇到 rate limit 后直接 skip，没有 backoff 重试，也没有告警
3. `search_query_registry` 表未记录具体查询词（当前为空），无法事后追溯哪些查询被跳过

**S2 的重要性说明**:
- Semantic Scholar 是本系统最重要的学术检索数据源之一，覆盖 ACL/EMNLP/NeurIPS/ICML/ICLR 等所有主要 AI/NLP 顶会，且支持 venue/year 过滤
- 其他 provider（arXiv、DBLP）无法替代：arXiv 缺少 venue 信息、DBLP 无摘要、无法按相关性排序
- S2 的 citation graph 是 `expand_citations` 的核心数据来源，跳过 S2 检索同时削弱了引用扩散质量

**建议修复**:
1. **降低访问频率，保证可用性**：S2 免费 API 限速 1 req/s，并发调用时必须加 rate limiter（如 `asyncio.Semaphore(1)` + 1s sleep），宁可慢也不能跳过
2. **加 exponential backoff 重试**：遇到 429 时等待 2s/4s/8s 重试，最多 3 次，而非立即 skip
3. **降级而非跳过**：若 S2 rate limit 不可恢复，应降级为串行（其他 provider 先跑，S2 最后跑），并在报告中明确标注"S2 结果不完整"
4. **记录实际查询词**：`search_query_registry` 应在每次 `paper_search` 时写入 `(topic_id, query, source, timestamp)`，以便事后审计和补救

**优先级**: P1（S2 是核心数据源，跳过会导致顶会论文系统性漏检）

---

## [2026-04-10] papers 表缺少 citation_count 字段，无法按引用数筛选高影响力论文

**场景**: 分析阶段需要过滤高质量论文（高引用 / CCF-A/B / 中科院一区），查询 `papers.citation_count` 字段时发现所有记录均为 0 或 NULL。

**问题**: `papers` 表中虽然存在 `citation_count` 列，但 `paper_ingest` 流程未从 Semantic Scholar 或其他来源填充该字段，导致按引用数排序/过滤完全失效。

**影响**:
- 无法自动区分高影响力论文（>100 引用）和低质量预印本
- Related Work 撰写时需要人工查询引用数，增加大量手动工作
- `select_seeds` 选种时无法偏向高引用论文，可能选入低质量种子影响引用扩散质量

**建议修复**:
1. **`paper_ingest` 时同步写入 citation_count**：S2 的 `/paper/{id}` 接口返回 `citationCount` 字段，应在 ingest 时一并写入
2. **提供 `paper_enrich` 批量刷新**：对已入库但 `citation_count=0` 的论文，支持批量从 S2 补全（每次 ingest 时如果 S2 可用则顺便刷新）
3. **定期更新**：citation count 随时间增长，建议每次 Build 阶段开始时对高相关论文做一次批量刷新

**优先级**: P2

---

## [2026-04-10] DB 路径存在两个位置，文档/代码不一致导致 agent 持续读错库

**场景**: Build 阶段和 Analyze 阶段调试时，发现 DB 里的论文数量与预期不符

**问题**: 系统存在两个 pool.db：
- `~/.research-harness/pool.db`（旧路径，CLAUDE.md 和部分文档写的默认路径）
- `~/code/research-harness/.research-harness/pool.db`（实际使用的正确路径）

两个 DB 内容完全不同：旧路径只有 topic_id=1（24 篇），正确路径有 topic_id=4（310 篇）。agent 和人工调试时反复查错库，浪费大量时间。

**影响**: agent 查错库会得到完全错误的数据（论文数、stage、artifact），所有后续决策都基于错误前提

**建议修复**:
1. 统一 DB 路径，废弃 `~/.research-harness/` 或通过软链接指向正确位置
2. MCP server 启动时打印当前使用的 DB 绝对路径，让 agent/用户可以验证
3. `orchestrator_status` 返回值中增加 `db_path` 字段，方便排查
4. CLAUDE.md 模板中的 DB 路径应在 `research-init` 时自动写入实际路径，而非使用硬编码默认值

**优先级**: P1

---

## [2026-04-10] `provenance_records.topic_id` 全部为 NULL，溯源信息不可用

**场景**: 试图通过 `provenance_records` 追溯 topic_id=4 的检索历史（查询词、provider、时间）

**问题**: `SELECT * FROM provenance_records WHERE topic_id=4` 返回 0 条。检查发现所有 provenance 记录的 `topic_id` 列均为 NULL（包括 `paper_search`、`paper_ingest`、`claim_extract` 等操作），尽管这些操作确实指定了 topic_id。

**影响**:
- 无法按 topic 审计检索历史：用了哪些 query、哪些 provider、成功了几条
- `search_query_registry` 表同样为空（0 条），两表共同失效导致检索溯源完全不可用
- 事后无法判断某论文是通过哪次检索进入的，也无法做 gap 检查（"还有哪些查询没跑"）

**建议修复**:
1. `paper_search`、`paper_ingest` 等所有带 `topic_id` 参数的操作，执行时必须将 `topic_id` 写入 `provenance_records`
2. `search_query_registry` 应在每次 `paper_search` 调用时写入 `(topic_id, query, source, last_searched_at)`，作为去重和审计依据
3. 增加 `rh topic audit --topic-id N` CLI 命令，输出该 topic 的完整检索历史

**优先级**: P1

---

## [2026-04-10] Build v1 `max_results` 默认值过低（20），两层 cap 叠加导致论文严重欠采样

**场景**: Build v1 阶段执行多源检索，期望获得 ≥60 篇高相关论文，实际只得到 24 篇

**问题**: `paper_search` 的 `max_results` 默认值为 20，且检索管道对每个 provider 还有一层内部 cap，两层叠加导致每个查询实际只返回约 3–5 篇。多个查询合并后去重，总量仅 24 篇，远低于覆盖性要求。

**影响**:
- 24 篇论文触发 Build gate 的 "too few papers" 警告，但系统没有自动重试或提示调大参数
- `topic_paper_notes` 为空（notes 写入依赖后续流程），而 gate check 读的是 `topic_paper_notes`，导致 gate 报"无论文"，与 `paper_topics`（实际有 24 篇）矛盾，agent 需要手动排查才能发现
- 最终不得不废弃 topic_id=1，用 topic_id=4 重新执行 Build v2（`max_results=50`）

**根本原因**: `max_results` 默认值对"覆盖性文献调研"场景太保守（适合单次 demo，不适合 Build 阶段）

**建议修复**:
1. Build 阶段（`/research-build` skill）调用 `paper_search` 时应显式传 `max_results=50`，不依赖默认值
2. `paper_search` 文档中应注明：Build 阶段推荐 `max_results≥50`，默认值 20 仅适合快速预览
3. Gate check 应同时检查 `paper_topics`（已入库数量）和 `topic_paper_notes`（已标注数量），而非只看后者；两者不一致时给出明确提示

**优先级**: P1

---

## [2026-04-09] paper_ingest 对 arXiv 标识符的元数据补全不稳定

**场景**: 在 `harness-agent-paper-gen` topic 中批量执行 `paper_ingest(source=”arxiv:...”)`
**问题**: 8 篇论文里仅 1 篇自动补全了标题、摘要、作者和 venue；其余 7 篇只写入了 `arxiv_id`，`title/year/venue/abstract` 全为空，形成可引用但不可读的空壳 paper 记录。
**影响**: `paper_list`、literature mapping、claim extraction 前的人工筛选都会变得困难；agent 需要额外调用 arXiv/Semantic Scholar 再手动回写数据库。
**建议修复**:
1. 为 `paper_ingest` 增加 ingest 后完整性检查，若 `title` 仍为空则重试备用元数据源
2. 在响应里显式区分”已入库但元数据缺失”和”已完整入库”
3. 提供一个 `paper_enrich` 或 `paper_refresh_metadata` 原语，避免 agent 直接操作 SQLite 修补
**优先级**: P1

---

## [2026-04-11] papers 表缺少 author_affiliation 字段，无法按机构/公司维度分析论文

**场景**: 分析 auto-bidding topic 中国内外电商大厂的论文产出情况

**问题**: `papers` 表中 `authors` 字段仅存储作者姓名列表（如 `["Chuan Yu", "Jian Xu"]`），不包含机构/公司 affiliation 信息。Semantic Scholar API 在 `/paper/{id}` 和 `/author/{id}` 接口中提供 `affiliations` 字段，但 `paper_ingest` 流程未采集和存储该数据。

**影响**:
- 无法按公司（Alibaba、Google、Meta 等）或机构（清华、Stanford 等）维度统计论文产出
- Related Work 撰写时无法自动标注论文来源机构，影响学术对比的可信度
- 大厂论文识别只能依赖 abstract 关键词匹配（覆盖率低），通过 affiliation 识别才准确
- 无法分析"工业界 vs 学术界"的研究分布差异

**根本原因调查（2026-04-11 实测）**:
已验证 Semantic Scholar (`/paper/{id}?fields=authors.affiliations`)、arXiv Atom API、OpenAlex API 三者，`affiliations`/`institutions` 字段在测试论文上**全部为空**。根本原因是：affiliation 存储在论文 PDF 首页的 author block 中，公开元数据 API 覆盖率极低（仅 ORCID 绑定的作者才有），**无法通过 API 批量补全**。

**可行方案（优先级排序）**:
1. **PDF 解析（最准确）**：下载 PDF 后用 GROBID/ParsCit 提取 author+affiliation block，准确率高，但依赖 `paper_acquire` 已下载 PDF
2. **abstract 关键词匹配（次选，已可用）**：大厂论文 abstract 通常提及 "at Alibaba"、"our advertising platform" 等，用规则或 LLM 识别，覆盖约 50%
3. **已知大厂作者名单维护**：建立并持续更新各大厂研究员姓名列表，与 `authors` 字段交叉匹配
4. **人工标注**：对 core/high 级别高价值论文（约 148 篇），一次性人工标注

**建议修复**:
1. **`papers` 表新增 `affiliations_json` 列**：`[{"author": "Chuan Yu", "affiliations": ["Alibaba"], "source": "pdf|abstract|manual"}]`
2. **`paper_acquire` 后触发 affiliation 提取**：PDF 下载后自动调用 GROBID 解析 author block
3. **`paper_list`/`paper_search` 支持 `--affiliation` 过滤**

**优先级**: P2

---

## [2026-04-11] 大量相关论文因仅有 DOI/会议 ID 而无法入库

**场景**: Build 阶段对 auto-bidding topic 全量检索后，514 篇相关论文中有 149 篇（29%）因缺少 arxiv_id 而被跳过，无法通过当前 `paper_ingest` 流程入库

**问题**: `paper_ingest` 目前主要依赖 `arxiv_id` 作为论文标识符进行元数据补全。对于仅发布在 ACM/IEEE 等封闭出版平台、只有 DOI 或会议内部 ID 的论文，系统无法完成入库，导致：
- KDD、WWW、SIGIR 等顶会的大量已发表论文（非 arXiv 预印本）系统性缺失
- 相关论文覆盖度统计失真（29% 的有效候选被静默丢弃）
- 用户无法区分"该论文不相关"和"该论文无法入库"

**数量估算（auto-bidding topic 为例）**:
- 检索候选：963 篇
- 相关候选（core/high/medium/low）：382 篇
- 其中无 arxiv_id 跳过：149 篇（占 39%）
- 实际入库：233 篇

**建议修复**:
1. **支持 DOI 入库路径**：`paper_ingest(source="doi:10.1145/...")` 应能通过 CrossRef / OpenAlex API 补全元数据（title、abstract、venue、year、authors）
2. **支持 S2 paper ID 入库**：Semantic Scholar 有自己的 paperId，检索时已返回，应直接支持 `source="s2:<paperId>"` 入库
3. **跳过统计写入 acquisition_report**：当前跳过是静默的，`acquisition_report` artifact 应包含"因缺少 arxiv_id 未入库"的论文列表，供人工补录
4. **提供 `paper_import_doi` CLI 命令**：让用户手动补录特定 DOI 论文

**优先级**: P1（顶会已发表论文系统性缺失，影响文献覆盖度可信度）

---

## [2026-04-11] 检索结果未持久化，数据截断后无法复原

**场景**: Build 阶段完成多查询检索后，agent 仅将 top-N 写入文件，剩余候选数据全部丢失

**问题**: `paper_search` 返回的所有候选论文（PaperRef 列表）在入库前没有被持久化到磁盘。当前流程是：检索 → 内存过滤 → 截断 → 入库，中间没有任何 checkpoint。一旦 agent 决策截断或程序异常中断，剩余论文数据永久丢失，只能重新调用 API（消耗 rate limit）。

**直接后果**:
- 本次 auto-bidding topic：检索到 223 篇相关论文，只保存了 45 篇到 `/tmp/auto_bidding_papers.json`，178 篇数据丢失
- 要补全必须重新检索，再次消耗 Semantic Scholar rate limit
- 无法事后审计"哪些论文被过滤掉了、原因是什么"

**建议修复**:
1. **检索结果全量持久化**：`paper_search` 完成后，所有候选结果（含 title/abstract/arxiv_id/score）应立即写入 `search_cache` 表或本地 JSON 文件，入库决策与数据保存解耦
2. **两阶段入库流程**：Phase 1 = 全量检索并持久化候选集；Phase 2 = 从候选集按策略入库。Phase 1 不依赖 API 可重入
3. **`search_query_registry` 表应存储完整候选列表**（或外键引用）：目前该表为空，应在每次检索后写入 `(topic_id, query, source, candidates_json, timestamp)`

**优先级**: P1（数据丢失风险，影响所有 Build 阶段的可复现性）

---

## [2026-04-11] 通过现有入库论文丰富 query 对检索质量有显著提升

**场景**: 重新检索 auto-bidding topic 时，先查看已入库论文的标题/关键词，再补充新 query

**观察**: 已入库论文暴露了初始 query 未覆盖的重要子领域，例如：
- "bid shading"（竞价遮蔽，first-price auction 特有问题）→ 初始 query 完全未涵盖
- "pacing equilibrium"（预算节奏均衡）→ 初始 query 只有 "budget pacing"，未覆盖理论侧
- "oracle imitation learning bidding"、"generative auto-bidding diffusion"、"decision transformer bidding" → 生成式出价是 2024–2025 新兴方向，初始 query 未覆盖
- "KPI-constrained"、"tROAS"、"tCPA" → 工业界常用术语，学术 query 未包含

**建议**:
1. **Build 阶段加入 query 精化步骤**：在执行初始检索后，对已入库论文做关键词提取（title + abstract），用于补充第二轮检索 query
2. **agent-guide 中推荐"滚动检索"策略**：Round 1 用宽泛 query，Round 2 用 Round 1 入库论文的高频关键词补充，最多 2–3 轮
3. **`paper_search` 支持 `expand_from_pool` 参数**：传入 topic_id，自动从已入库论文提取关键词并合并到检索 query

**优先级**: P2（流程改进，可显著提升文献覆盖度）

---

## [2026-04-11] relevance_score 使用连续浮点数，缺乏语义，难以被 agent 和用户理解

**场景**: Build 阶段对检索结果打相关度分，当前为 0.0–1.0 连续值

**问题**: 浮点 relevance_score 对 agent 决策和用户理解均不友好：
- `select_seeds` 期望 "high"/"medium"/"low" 字符串标签，与浮点数不兼容，导致所有论文被判为 "low" 而无法被选为 seed（已在实际运行中复现）
- 用户无法直观理解 0.67 vs 0.80 的区别，难以人工审核
- agent 在截断时倾向于选一个任意阈值（如 0.5），缺乏语义依据

**建议**:
1. **引入 5 档离散标签**（替代或并行于浮点分）：
   - `core`（核心）：直接研究该 topic 的主论文，是必读文献
   - `high`（高相关）：方法或实验与 topic 高度相关
   - `medium`（中相关）：部分内容相关，可作为背景或对比
   - `low`（低相关）：仅在某个子问题上有交集
   - `peripheral`（边缘）：与 topic 相关但不直接，如通用背景论文
2. **`paper_ingest` 的 `relevance` 参数支持离散标签**：当前只接受浮点数，应同时接受字符串标签并内部映射到浮点
3. **`select_seeds` 等工具统一基于标签过滤**：不再依赖浮点阈值，避免不同工具阈值不一致导致的 schema 不兼容问题

**优先级**: P1（已导致 select_seeds 无法选种，citation expansion 功能受损）

---

## [2026-04-11] Agent 自主决策导致大量相关论文漏入库（权限过宽问题）

**场景**: Build 阶段，agent 执行多查询检索后自主决定只入库前 45 篇，导致 223 篇相关论文中有 178 篇被丢弃

**问题**: 当前 Build 阶段对 agent 的入库决策没有明确约束规则。搜索共找到 **341 篇候选论文，过滤后 223 篇相关**，但 agent 自主判断”任务要求至少 30 篇，取前 45 篇即可”，直接截断了剩余 178 篇（其中许多 relevance_score ≥ 0.4，仍属有效相关论文）。

**直接后果**:
- 大量 2022–2025 年的核心 auto-bidding 论文未入库
- 论文池覆盖度不足，后续 gap_detect / claim_extract 分析质量受影响
- 用户事后无法判断”是检索没找到”还是”找到了但 agent 决定不入库”

**根本原因**: 任务描述只给了下限（”至少 30 篇”），agent 将其解读为”达到 30 篇即可停止”，而非”30 篇是最低门槛，相关论文应尽量全量入库”。Build 阶段没有明确的入库策略规则约束 agent 的裁量权。

**建议修复**:
1. **明确入库策略规则**：在 Build 阶段 skill/agent-guide 中写明：relevance_score ≥ 某阈值（如 0.5）的论文**必须全部入库**，不得以”已达到数量目标”为由截断
2. **分级入库而非截断**：高相关（score ≥ 0.7）→ 直接入库；中相关（0.4–0.7）→ 入库并标注 `relevance=medium`；低相关（< 0.4）→ 跳过。不应对高/中相关论文设置数量上限
3. **入库报告应包含”找到但未入库”的统计**：`acquisition_report` artifact 中应明确列出”候选总数 / 相关数 / 实际入库数 / 跳过原因”，让用户可以审计 agent 的裁量决策
4. **”至少 N 篇”应解释为下限而非目标**：stage_policy 或 prompt 中应明确说明数量约束是 floor，不是 target

**优先级**: P1（直接影响文献覆盖度，是系统性漏检风险）

---

---

## [2026-04-20] 1.0 reviewer audit — P0 + P1 fixes landed

Audit found the 1.0 release was actually at RC1 level. Fixed in this session:

### P0 — test + MCP blockers
- **P0-1** `research_harness_eval/conftest.py::pytest_collect_file` returned bare `Path` instead of `Collector|None`, causing pytest INTERNALERROR at repo root. Fixed by removing the dead hook (intended only for data files, not tests).
- **P0-2** `test_primitives.py::test_primitive_registry_has_all_specs` asserted 68 but registry holds 69 (figure_generate added in `90cdcae` without updating the test). Fixed assertion + added `figure_generate` to `GENERATION` category set.
- **P0-3** MCP tool `paper_acquire` registered twice — once as `PAPER_ACQUIRE_SPEC` primitive, once in `_ACQUISITION_TOOLS`. Dispatcher checks primitives first so the acquisition-tools copy was dead code. Removed both the duplicate Tool definition and the matching elif branch.

### P1 — hallucination guard
- **P1-1** `outline_generate` produced fabricated papers (e.g. "SAGE-Fuse" for ModalGate) when contributions were empty after all fallbacks. Fixed by raising `ValueError` with guidance pointing to `project_set_contributions` / `writing_architecture` instead of calling the LLM. Added 2 regression tests in `TestOutlineGenerateContribGuard`.

### P1 — documentation sync
- README: `30+ primitives` → 69, `5-Stage` → 6-Stage, `40+ MCP tools` → 112, test command updated to pass from repo root.

### Verification
- `pytest packages/ --ignore=packages/research_harness_eval -q` → 967 passed, 2 skipped (previously 965 passed / 2 failed)
- `pytest packages/` no longer crashes on collection
- `list_tool_definitions()` → 112 distinct, 0 duplicates
- `PRIMITIVE_REGISTRY` → 69 registered
