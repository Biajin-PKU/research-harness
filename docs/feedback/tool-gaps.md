# Tool Gaps

> Agent 在科研过程中发现的缺失工具、Skill、Hook 或 MCP 功能。
> 格式：日期 + 场景 + 需求 + 优先级。定期审阅后转化为开发任务。

---

<!-- 示例条目 -->
<!-- ## 2026-04-08 批量 PDF 下载工具
**场景**: literature_mapping 阶段找到 30+ 论文，需要逐个下载 PDF
**需求**: 一个 skill 或 MCP 工具，输入 arxiv_id 列表，自动批量下载到 paper_library/
**优先级**: P1
-->

## 2026-04-17 outline_generate 忽视已选 contributions
**场景**: ModalGate v3 论文撰写。Step 2 `writing_architecture` 拿到了我们 direction_proposal 的 4 条 contributions，产出 ModalGate 架构；Step 3 `outline_generate(project_id=4, template='kdd')` 却完全忽略了 contributions 与 writing_architecture 结果，凭 topic 10 的 evidence pack 自动编出一篇名为 "SAGE-Fuse" 的无关论文（不同方法、不同贡献）。
**需求**: `outline_generate` 应接受 `contributions` 和可选 `writing_architecture` 参数，或直接读取 project 的 `direction_proposal` / `writing_architecture` artifact。缺省时应拒绝生成而不是 hallucinate。
**影响**: 本次 pipeline 我直接用 writing_architecture 的 sections 作为 outline，跳过 outline_generate。
**优先级**: P1
