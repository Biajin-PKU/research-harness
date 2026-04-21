# Paper Retrieval Pipeline — 最优检索与采集路径

## 工具全景（按稳定性排序）

| 工具 | 发现 | 元数据 | 引用链 | PDF/全文 | 稳定性 | 独有价值 |
|------|------|--------|--------|----------|--------|----------|
| **Semantic Scholar MCP** | search, bulk_search, snippets | 完整（DOI/arXiv/S2/venue/abstract/citations） | citations + references + recommendations | get_paper_fulltext (OA PDF→MD) | **高** (有 key) | 引用图谱、推荐引擎、全文转换 |
| **OpenAlex** (via paper_search) | 内嵌在 paper_search | 最丰富（affiliations, concepts, OA status） | — | pdf_url, landing_page_url | **高** (有 key) | 2.5 亿篇覆盖，OA PDF 发现 |
| **refcheck MCP** | search_references | verify_reference | — | — | **高** | 跨库验证（Crossref+S2+arXiv），防幻觉引用 |
| **mcp-dblp MCP** | search, fuzzy_title_search | author_publications, venue_info | — | — | **高** | 会议/期刊精确匹配，权威 BibTeX |
| **Unpaywall** | — | — | — | 按 DOI 查 OA PDF | **高** (免费 API) | 5 万+ OA 源，合法获取付费墙论文 PDF |
| **arXiv MCP** | search_papers | get_abstract | citation_graph | download_paper (HTML/PDF→text) | **中** (有限流) | 预印本保证免费全文 |
| **arXiv-LaTeX MCP** | — | — | — | get_paper_prompt (LaTeX 原文) | **高** | 数学公式精确提取 |
| **research-harness paper_search** | 聚合 6 个 provider | venue tier 排名 | — | — | **中** (依赖子 provider) | 统一搜索+自动入库 |
| **PASA** (via paper_search) | 预印本语义搜索 | 基础（arXiv ID, 作者, 摘要） | — | arXiv PDF（自动拼接） | **中** (10-15s/查询) | 高召回预印本发现，补充已发表论文的最新版本 |
| **paper-search MCP** | Google Scholar, arxiv, pubmed, biorxiv | 基础 | — | download_arxiv/pubmed/biorxiv | **低** (GS 反爬) | Google Scholar（不稳定） |
| **Exa MCP** | web_search_exa (神经搜索) | — | — | web_fetch_exa | **高** | 语义搜索，能发现非索引论文 |
| **PASA** (via paper_search) | 预印本搜索 | 基础 | — | — | **低** (API 不稳) | 高召回 fallback |

---

## 五阶段流水线

### Stage 1: 种子发现 — 撒大网

**目标**：给定主题，拿到初始论文列表（30-100 篇）

```
优先级顺序（并行执行，结果合并去重）：

1. Semantic Scholar search_papers        ← 学术搜索最精准，有 citation count
2. research-harness paper_search         ← 聚合 local + arxiv + openalex + s2 + openreview + pasa
3. mcp-dblp search                       ← 补充顶会/顶刊论文
4. PASA (已内置在 paper_search)           ← 预印本高召回，补充最新未发表工作
5. Exa web_search_exa                    ← 语义搜索，发现长尾/非索引论文
```

**去重键**：DOI > arXiv ID > S2 ID > 标题+年份 归一化

### Stage 2: 引用链扩展 — 从种子向外辐射

**目标**：从 Stage 1 的高相关种子论文，沿引用链扩展（通常 3x-5x 放大）

```
对每篇高相关种子论文：

1. S2 get_paper_references               ← 向后：它引用了谁（基础工作）
2. S2 get_paper_citations                ← 向前：谁引用了它（后续工作）
3. S2 get_recommendations_batch          ← 横向：内容相似但无引用关系的论文

对 survey 论文特别处理：
4. S2 get_paper_references(survey_id, limit=500)  ← 一次拉出整个领域的论文列表

补充预印本（Stage 1 可能遗漏的最新工作）：
5. PASA search(种子论文关键词)            ← 10-15s/查询，返回带 arXiv ID 的预印本
```

**过滤**：按 citation count、venue tier、年份范围 筛选，避免爆炸

### Stage 3: 元数据补全 — 填满每个字段

**目标**：确保每篇论文有 title, authors, year, venue, DOI, arXiv ID, abstract

```
对元数据不完整的论文：

1. S2 get_paper(paper_id)                ← 最全面的单论文元数据
2. refcheck verify_reference             ← 跨 Crossref/S2/arXiv 验证真实性
3. mcp-dblp fuzzy_title_search           ← 补 venue、确认发表信息
4. refcheck get_bibtex                   ← 拿到标准 BibTeX
```

### Stage 4: PDF 采集级联 — 优先级下降链

**目标**：拿到全文 PDF，按可靠性从高到低尝试

```
对每篇缺 PDF 的论文，按顺序尝试（命中即停）：

① 有 arXiv ID？
   → arXiv MCP download_paper            ← 成功率 ~98%，最稳定

② 有 S2 openAccessPdf？
   → S2 get_paper_fulltext               ← 自动下载 + 转 Markdown

③ 有 DOI？
   → Unpaywall API 查 OA 副本            ← 覆盖 50,000+ 源
   → 如有 url_for_pdf，直接下载

④ OpenAlex 有 pdf_url？
   → 直接下载（已在 paper_search 结果中）

⑤ 以上都失败？
   → paper-search download_arxiv/pubmed   ← 特定源下载
   → Google Scholar 搜 landing page       ← 不稳定，作为最后手段
   → 标记为 unable_to_acquire + 人工介入提示
```

### Stage 5: 全文阅读 — 选最佳格式

**目标**：将 PDF 转为可处理的文本

```
按论文来源选择最佳阅读方式：

① arXiv 论文（有 LaTeX 源）
   → arxiv-latex get_paper_prompt         ← 最精确，保留数学公式

② 有 OA PDF
   → S2 get_paper_fulltext               ← PDF→Markdown，支持分页/搜索

③ arXiv 论文（HTML 版本）
   → arXiv MCP read_paper                ← HTML 解析，比 PDF 干净

④ 其他
   → 本地 paperindex 处理                ← Kimi-backed card extraction
```

---

## 稳定性保障策略

### 限流与重试
- Semantic Scholar: 1 req/s（有 key 后放宽到 ~10 req/s）
- arXiv: 3 s/req 建议间隔，burst 会触发 429
- OpenAlex: polite pool（配了 email 后无限制）
- Unpaywall: 100K req/day（免费）
- DBLP: 无明确限制，建议 1 req/s

### 不稳定源的处理
- **PASA**: 已修复 str/dict 和 coerce_authors bug，纳入常规流程。10-15s/查询，catch 异常不影响主流程
- **Google Scholar**: 不作为主路径，仅在 Stage 4 最后一步使用（IP 易被封）
- **OpenReview**: 需要 access token，未配置时跳过

### 去重与合并
- 全流程使用统一指纹：`DOI > arXiv ID > S2 ID > title+year`
- 多源命中时，按 METADATA_FIELD_PRIORITY 合并最丰富的字段

---

## 快速参考：按场景选工具

| 我要... | 用什么 |
|---------|--------|
| 搜一个主题的论文 | S2 search_papers + research-harness paper_search |
| 从一篇论文扩展相关工作 | S2 get_references + get_citations + get_recommendations |
| 从一篇 survey 批量拉论文列表 | S2 get_paper_references(survey_id, limit=500) |
| 验证一个引用是否真实 | refcheck verify_reference |
| 拿标准 BibTeX | refcheck get_bibtex 或 mcp-dblp add_bibtex_entry |
| 查一个作者的所有论文 | mcp-dblp get_author_publications 或 S2 get_author_papers |
| 找一篇论文的 PDF | 按 Stage 4 级联：arXiv → S2 fulltext → Unpaywall → OpenAlex |
| 读论文全文（含公式） | arxiv-latex get_paper_prompt |
| 读论文全文（通用） | S2 get_paper_fulltext 或 arXiv read_paper |
| 搜非学术源的论文/报告 | Exa web_search_exa |
