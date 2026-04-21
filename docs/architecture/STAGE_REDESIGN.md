# Research Harness 阶段重新设计

## 现状问题

当前 12 个 stage + 十几个 skill，粒度太细，用户体验差：
- 用户需要记住 `/literature-search`, `/citation-trace`, `/paper-sync`, `/claim-extraction`, `/gap-analysis` 等十几个命令
- 不清楚执行顺序和依赖关系
- 每个 skill 单独调用，无法自动串联

## 新方案：5 阶段

```
Stage 1: Init（定调）
    ↓  [人工确认 query、scope、种子论文]
Stage 2: Build（建库）
    ↓  [人工审查论文池，剔除/补充]
Stage 3: Analyze（分析）
    ↓  [人工选择研究方向 ← 最关键决策点]
Stage 4: Propose（提案）
    ↓  [人工确认提案和实验方案]
Stage 5: Write（写作）
```

---

### Stage 1: Init（定调）

**对应原 stage**: `topic_framing`
**产出**: topic 定义、检索 query 集合、scope 边界、目标会议/期刊、种子论文
**耗时**: 分钟级（人机对话）
**技能**: `/research-init`

#### 执行流程

```
1. 环境感知 — 自动读取当前目录的上下文
   ├── README.md / CLAUDE.md / AGENTS.md          ← 项目说明
   ├── docs/**/*.md                                ← 已有文档
   ├── *.bib                                       ← 已有参考文献
   └── 任何 .pdf / .tex 文件                        ← 可能是种子论文

2. 上下文摘要 — 从读取的内容中提取：
   ├── 研究领域和关键词
   ├── 已有的论文/引用
   ├── 隐含的研究问题
   └── 目标会议/期刊（如有）

3. 引导式交互 — 基于上下文，向用户确认/补充：
   ├── Q1: 研究主题确认（agent 基于文件内容提出初步理解，用户修正）
   ├── Q2: scope 边界（时间范围、领域范围、排除条件）
   ├── Q3: 目标会议/期刊和 deadline
   ├── Q4: 种子论文（用户可以给 DOI/arXiv ID/标题/PDF，也可以跳过）
   └── Q5: 特殊关注点（某个方法、某个团队、某个数据集）

4. 生成检索计划 — 输出：
   ├── topic 定义（存入 DB）
   ├── 检索 query 集合（5-10 个不同角度的 query）
   ├── scope 过滤条件（year_from, venue_filter, tier_filter）
   └── 种子论文列表（如有，直接入库）
```

#### 设计要点

- **先读后问**：agent 不是从空白开始问问题，而是先读懂用户已有的材料，带着理解去确认
- **提供初步理解让用户修正**，比直接问开放式问题效率高得多
- **种子论文是可选的**：用户可以给几篇关键论文帮助聚焦，也可以完全不给让系统从零检索
- **query 集合而非单个 query**：从不同角度（方法、问题、应用、理论）生成多个检索式，确保覆盖面

---

### Stage 2: Build（建库）

**对应原 stage**: `literature_search` + `paper_acquisition`
**产出**: 完整的论文池（元数据 + PDF + 结构化 card），经过相关性过滤
**耗时**: 分钟级（<50 篇）到小时级（100+ 篇）
**技能**: `/research-build`

#### 执行流程

```
1. 多源检索
   ├── S2 search_papers（每个 query）
   ├── research-harness paper_search（聚合 arxiv + openalex + s2 + openreview + pasa）
   ├── mcp-dblp search（顶会/顶刊精确匹配）
   ├── PASA search（预印本补充）
   └── Exa web_search_exa（长尾/非索引论文）

2. 引用链扩展
   ├── S2 get_paper_references（种子论文的参考文献）
   ├── S2 get_paper_citations（种子论文的被引）
   ├── S2 get_recommendations_batch（横向推荐）
   └── Survey 论文特殊处理：get_references(limit=500)

3. 去重合并
   └── 指纹：DOI > arXiv ID > S2 ID > title+year 归一化

4. ★ 相关性过滤（入库前噪声剔除）
   ├── 快速过滤（无 LLM 成本）：
   │   ├── 标题关键词匹配度 < 阈值 → 丢弃
   │   ├── 年份超出 scope → 丢弃
   │   └── venue 在排除列表中 → 丢弃
   ├── 摘要级过滤（轻量 LLM）：
   │   ├── 对标题匹配度中等的论文，读摘要判断相关性
   │   └── 输出：high / medium / low / irrelevant
   └── 只入库 high + medium，low 标记但不处理，irrelevant 丢弃

5. 元数据补全
   ├── S2 get_paper（canonical 元数据）
   ├── refcheck verify_reference（跨库验证）
   └── mcp-dblp fuzzy_title_search（venue + BibTeX）

6. PDF 级联下载
   ├── ① arXiv direct（有 arXiv ID → ~98% 成功）
   ├── ② S2 get_paper_fulltext（OA PDF）
   ├── ③ Unpaywall（按 DOI 查 OA 副本）
   ├── ④ OpenAlex pdf_url
   └── ⑤ 标记 unable_to_acquire + 人工提示

7. 结构化提取
   └── paperindex card extraction（Kimi-backed）

8. 入库
   └── research-harness paper pool（带 relevance 标签）
```

#### 相关性过滤的层次设计

```
                    检索结果（可能 200+ 篇）
                           │
                    ┌──────┴──────┐
                    │ 快速过滤    │  ← 零成本：关键词 + 年份 + venue
                    └──────┬──────┘
                           │ (~100 篇)
                    ┌──────┴──────┐
                    │ 摘要级过滤  │  ← 轻量 LLM：读摘要判相关性
                    └──────┬──────┘
                           │ (~50 篇 high/medium)
                    ┌──────┴──────┐
                    │ 入库 + PDF  │
                    └─────────────┘
```

#### ★ 论文库新鲜度检查（跨 session 机制）

**触发时机**：每次新 session 开始，agent 自动检查

```
检查逻辑：
1. 读取 topic 的 last_search_at 时间戳
2. 计算距今天数 = now - last_search_at

输出：
├── < 7 天：静默，不提醒
├── 7-30 天：提醒 "论文库已 X 天未更新，要补充检索吗？"
└── > 30 天：强提醒 "论文库已过期，建议执行增量检索"

增量检索：
├── date_from = last_search_at（只搜新论文）
├── 复用 Init 阶段的 query 集合
├── 走完整 Build 流程（但 scope 限定在时间窗口内）
└── 更新 last_search_at
```

**实现**：在 topics 表加 `last_search_at` 字段，Build 完成时自动更新。
Session 启动时的检查逻辑放在 `/research-init` 或 session hook 中。

---

### Stage 3: Analyze（分析）

**对应原 stage**: `claim_extraction` + `gap_detection` + `research_direction`
**产出**: claim 图谱、gap 列表、候选研究方向排序
**耗时**: 小时级（LLM 密集）
**技能**: `/research-analyze`

#### 执行流程

```
1. Claim 提取（从 paper card 提取关键论断）
2. Claim 图谱构建（论断之间的支持/矛盾/扩展关系）
3. Gap 检测（文献中的空白、矛盾、未验证假设）
4. 研究方向排序（按 novelty × feasibility × impact 打分）
```

---

### Stage 4: Propose（提案）

**对应原 stage**: `research_proposal` + `adversarial_optimization` + `experiment_design`
**产出**: 经过对抗优化的研究提案 + 实验方案 + 方法层参考论文
**耗时**: 小时级（多轮迭代）
**技能**: `/research-propose`

#### 执行流程

```
1. 研究提案初稿（基于选定方向 + gap）
   └── 明确：我们要用什么方法/模型填什么 gap

2. ★ 方法层论文库扩展（第二轮定向检索）
   │
   │  Stage 2 的论文库是"主题相关"——围绕研究问题本身
   │  这一步是"方法相关"——围绕提案中需要的技术手段
   │
   ├── 从提案中提取方法关键词：
   │   ├── 核心方法/模型（如 "constrained MDP", "Lagrangian relaxation"）
   │   ├── 技术组件（如 "multi-agent RL", "budget pacing algorithm"）
   │   ├── 理论工具（如 "regret bound", "competitive ratio"）
   │   └── 数据/评估相关（如 "auction simulation", "A/B test methodology"）
   │
   ├── 定向检索（复用 Build 的多源检索管道）：
   │   ├── S2 search：方法关键词 + 不限定原主题领域
   │   ├── S2 get_recommendations：以提案最核心的 1-2 篇方法论文为种子
   │   ├── DBLP search：方法名 + 顶会（可能跨领域：ICML/NeurIPS/AAAI）
   │   └── arXiv search：方法名（可能在 cs.LG/stat.ML 而非原主题的 category）
   │
   ├── 相关性过滤（标准不同于 Stage 2）：
   │   ├── 不按"主题相关性"过滤，而是按"方法支撑度"过滤
   │   ├── 问题："这篇论文能帮助我们实现提案中的哪个技术点？"
   │   └── 标签：method_foundation / technique_reference / evaluation_reference / irrelevant
   │
   └── 入库 + PDF + card（走 Stage 2 同样的采集管道）

3. 提案精化（基于新补充的方法论文）
   ├── 验证技术可行性：方法论文中有没有现成的理论/算法可以复用
   ├── 识别技术风险：我们要做的和已有方法的差异在哪里
   └── 补充 related work 定位：在方法层面我们和谁比较

4. 对抗优化（proposer ↔ challenger 多轮迭代）
   ├── challenger 现在可以用方法层论文质疑：
   │   ├── "X 方法已经被 [论文 A] 证明在 Y 场景下失效"
   │   ├── "你的理论 bound 和 [论文 B] 的结果矛盾"
   │   └── "[论文 C] 已经做过类似的方法组合，你的 novelty 在哪"
   └── proposer 必须用论文证据回应，不能空口辩护

5. 实验方案设计
   ├── baseline 选取（从方法层论文中选取）
   ├── 数据集和评估指标（参考方法层论文的实验设置）
   └── 消融实验设计（哪些组件需要验证）
```

#### 两轮论文库扩展的区别

```
Stage 2 Build（第一轮）           Stage 4 Propose（第二轮）
──────────────────────           ──────────────────────
围绕 "研究问题"                   围绕 "解决方法"
query: 主题关键词                 query: 方法/模型/理论名
过滤: 主题相关性                  过滤: 方法支撑度
scope: 同一研究领域               scope: 可跨领域（方法可能来自其他领域）
目的: 了解现状和 gap              目的: 支撑提案的技术可行性
典型: 50-100 篇                  典型: 20-40 篇
```

#### 设计要点

- **方法层检索必须跨领域**：一个 ad auction 的问题可能需要引用 operations research、game theory、online learning 的方法论文，不能局限在原主题领域
- **检索 query 从提案自动提取**：agent 分析提案文本，提取方法术语，自动生成检索式
- **对抗优化的质量取决于方法层论文的充分度**：challenger 只有看过足够多的相关方法论文，才能提出有力的质疑

---

### Stage 5: Write（写作）

**对应原 stage**: `section_drafting` + `paper_assembly` + `submission_preparation`
**产出**: 论文草稿 → 终稿
**耗时**: 天级（多轮修改）
**技能**: `/research-write`

#### 执行流程

```
1. ★ 竞品论文学习（写作前的"读范文"阶段）
   ├── 选取竞品论文：
   │   ├── 目标会议/期刊近 2 年的同主题 best paper / oral
   │   ├── 高引用的方法论相近的论文（citation_count 排序）
   │   └── 用户指定的"想写成这样"的论文
   │
   ├── 结构分析（对每篇竞品论文）：
   │   ├── 整体架构：章节划分、各节篇幅比例
   │   ├── Introduction 的叙事弧线（problem → why hard → our insight → contribution）
   │   ├── Related Work 的组织方式（按主题 vs 按时间 vs 按方法）
   │   ├── Method 的展开逻辑（先 overview 再细节 vs 逐步推导）
   │   ├── Experiments 的对比策略（baseline 选取、ablation 设计、可视化）
   │   └── 写作技巧：transition、claim 的措辞、figure/table 的使用密度
   │
   ├── 模式提取：
   │   ├── 提炼 3-5 个值得学习的写作模式
   │   ├── 识别目标会议的"隐性规范"（页数、格式偏好、审稿关注点）
   │   └── 标注哪些模式适用于我们的论文，哪些不适用
   │
   └── ★ 写作架构对抗讨论：
       ├── proposer：基于竞品分析 + 我们的 contribution，提出论文架构
       ├── challenger：挑战架构的逻辑性、完整性、说服力
       ├── 2-3 轮迭代
       └── 产出：确定的论文架构（章节大纲 + 各节的论证策略 + 篇幅分配）

2. 分节撰写
   ├── 按确定的架构逐节撰写
   ├── 每节写完后对照竞品论文的写作模式检查质量
   └── 重点节（Intro、Method）可以多轮修改

3. 论文组装
   ├── 合并各节
   ├── 统一术语、符号、引用格式
   ├── 补充 figure/table caption
   └── 生成完整 BibTeX

4. 投稿准备
   ├── 格式检查（页数、字体、margin）
   ├── 会议 checklist 逐项对照
   ├── camera-ready 格式调整
   └── supplementary material 整理
```

#### 竞品论文学习的设计要点

- **不是简单模仿**：目标是理解"好论文为什么好"，然后结合自己的 contribution 设计最优呈现方式
- **写作架构的对抗讨论和 Stage 4 提案的对抗讨论同等重要**：提案决定"做什么"，写作架构决定"怎么说"——两者都直接影响审稿结果
- **竞品选取策略**：优先选和我们方法/问题最接近的 accept paper，而非泛泛的好论文
- **结构分析可以半自动化**：用 arxiv-latex 读 LaTeX 源码提取章节结构，LLM 分析叙事逻辑

---

## 人工交互点

| 位置 | 决策内容 | 重要性 |
|------|---------|--------|
| Stage 1 内部 | agent 提出理解，用户确认/修正 | 高（方向错了后面全废） |
| Stage 1 → 2 | 确认检索 query 和 scope | 高 |
| Stage 2 → 3 | 审查论文池，剔除噪声/补充遗漏 | 中（控制分析成本） |
| **Stage 3 → 4** | **选择研究方向** | **最高（核心学术判断）** |
| Stage 4 内部 | 审查方法层扩展检索结果 | 中（确保方法支撑充分） |
| Stage 4 → 5 | 确认提案和实验方案 | 高（避免在错误提案上写作） |
| Stage 5 内部 | 确认写作架构（对抗讨论后） | 高（决定论文呈现方式） |

Stage 内部的 substep 全自动串联，除上述标注的检查点外不需要人工介入。

---

## 跨 Session 机制

### 论文库新鲜度检查

**触发**：每次 session 开始时自动检查
**实现**：topics 表加 `last_search_at` 字段

```
< 7 天   → 静默
7-30 天  → "论文库已 X 天未更新，要补充检索吗？"
> 30 天  → "论文库已过期，建议执行增量检索"
```

增量检索自动限定 `date_from = last_search_at`，只搜新论文，复用 Init 的 query 集合。

### Session 启动自检清单

```
agent 每次启动时自动检查：
1. topic 存在？→ 如不存在，引导 /research-init
2. 论文库新鲜度 → 如过期，提示增量检索
3. 上次 session 停在哪个 stage？→ 提示继续
4. 有未完成的 task？→ 展示待办
```

---

## 实现路径

### 方案：改 orchestrator stage 定义

```python
# orchestrator/stages.py — 新定义
STAGES = {
    "init":    ["topic_framing"],
    "build":   ["literature_search", "relevance_filter", "paper_acquisition"],
    "analyze": ["claim_extraction", "gap_detection", "research_direction"],
    "propose": ["research_proposal", "method_literature_expansion", "adversarial_optimization", "experiment_design"],
    "write":   ["competitive_analysis", "writing_architecture", "section_drafting",
                "paper_assembly", "submission_preparation"],
}
```

### Skill 合并

| 新 Skill | 替代的旧 Skill | 新增能力 |
|----------|---------------|---------|
| `/research-init` | 不变 | + 环境感知（读 README 等）、引导式交互 |
| `/research-build` | `/literature-search` + `/citation-trace` + `/paper-sync` | + 相关性过滤、新鲜度检查 |
| `/research-analyze` | `/claim-extraction` + `/gap-analysis` | 不变 |
| `/research-propose` | （新建） | 不变 |
| `/research-write` | `/section-drafting` | + 竞品学习、写作架构对抗讨论 |

### 数据库变更

```sql
-- topics 表新增字段
ALTER TABLE topics ADD COLUMN last_search_at TEXT DEFAULT NULL;

-- papers 表新增字段（相关性过滤结果）
-- relevance 字段已存在于 paper_topics 表，复用
```

### 向后兼容

- MCP primitive tools（paper_search, claim_extract, gap_detect 等）不变
- 旧 skill 保留为 alias，打印 deprecation warning 并转发到新 skill
- orchestrator 的 provenance 记录粒度仍然是 substep 级别
