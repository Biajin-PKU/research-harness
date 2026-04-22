"""Prompt templates for LLM-backed research primitives."""

from __future__ import annotations

import json


def _truncate(text: str, limit: int) -> str:
    return text[:limit]


def paper_summarize_prompt(paper_title: str, paper_text: str, focus: str = "") -> str:
    focus_line = f"\nFocus area: {focus}" if focus else ""
    return f"""You are a research paper analyst.

Summarize the following paper concisely in 200-300 words.{focus_line}

Paper: {paper_title}

Text:
{_truncate(paper_text, 8000)}

Return JSON only:
{{"summary": "<your summary>", "confidence": <0.0-1.0>}}"""


def claim_extract_prompt(papers_text: str, focus: str = "") -> str:
    focus_line = f"\nFocus on: {focus}" if focus else ""
    return f"""You are a research claim extractor.{focus_line}

Extract distinct research claims from the following papers.
For each claim, provide:
- content
- evidence_type: empirical, theoretical, methodological, or survey-based
- confidence: 0.0-1.0

Papers:
{_truncate(papers_text, 12000)}

Return JSON only:
{{"claims": [{{"content": "<claim text>", "evidence_type": "<type>", "confidence": <float>}}]}}"""


def gap_detect_prompt(literature_summary: str, focus: str = "") -> str:
    focus_line = f"\nFocus on: {focus}" if focus else ""
    return f"""You are a research gap analyst.{focus_line}

Based on the following literature summary, identify research gaps.
Classify each gap as methodological, empirical, theoretical, or application.
Rate severity as low, medium, or high.

Literature:
{_truncate(literature_summary, 10000)}

Return JSON only:
{{"gaps": [{{"description": "<gap>", "gap_type": "<type>", "severity": "<level>"}}]}}"""


def baseline_identify_prompt(literature_summary: str, focus: str = "") -> str:
    focus_line = f"\nFocus on: {focus}" if focus else ""
    return f"""You are a research baseline analyst.{focus_line}

Identify key baseline methods or systems that papers in this area compare against.
For each baseline, note commonly reported metrics and why it is a standard baseline.

Literature:
{_truncate(literature_summary, 10000)}

Return JSON only:
{{"baselines": [{{"name": "<method name>", "metrics": {{"<metric>": "<value or range>"}}, "notes": "<why this is common>"}}]}}"""


def query_refine_prompt(
    *,
    topic_summary: str,
    top_keywords: list[str],
    frequent_authors: list[str],
    venues: list[str],
    known_queries: list[str],
    gaps: list[str],
    max_candidates: int,
) -> str:
    return f"""You are a research retrieval strategist.

Given the current paper-pool summary, derive up to {max_candidates} new search queries
that expand coverage without duplicating already-used searches.

Current topic summary:
{_truncate(topic_summary, 3000)}

Top keywords:
{", ".join(top_keywords) if top_keywords else "(none)"}

Frequent authors:
{", ".join(frequent_authors) if frequent_authors else "(none)"}

Venue distribution:
{", ".join(venues) if venues else "(none)"}

Known queries already used:
{json.dumps(known_queries[:20], ensure_ascii=False)}

Known gaps to target:
{json.dumps(gaps[:10], ensure_ascii=False)}

Return JSON only:
{{
  "candidates": [
    {{
      "query": "<search query>",
      "rationale": "<why this query fills a coverage gap>",
      "coverage_direction": "<which sub-area, method family, or recency gap it targets>",
      "priority": "<high|medium|low>"
    }}
  ]
}}

Requirements:
- Prefer 5-10 word queries that combine topic terms with a gap or method cue.
- Do not repeat or trivially paraphrase existing queries.
- At least half of the candidates should explicitly target uncovered directions or recent work.
- Keep output concise and practical for academic paper search."""


_COMMON_STYLE_BLOCK = """## Writing Quality Requirements

Follow these rules strictly to produce natural, high-quality academic prose:

PROHIBITED phrases and patterns — do NOT use any of these:
- "delve into", "it is important to note", "it is worth noting"
- "in the realm of", "a myriad of", "shed light on"
- "pave the way", "a testament to", "in light of"
- "plays a crucial role", "a growing body of"
- "has attracted growing interest", "has become increasingly important"
- Overuse of em dashes (maximum 2 per page)
- Starting consecutive paragraphs with the same word or structure
- Using "the first" without "to our knowledge" or "among the first"
- Using "novel" more than 2 times total

REQUIRED style:
- Vary paragraph length (3-8 sentences per paragraph, not uniform)
- Vary sentence structure: mix short declarative with longer compound sentences
- Prefer active voice; use passive only when the actor is unknown or irrelevant
- Use precise, discipline-specific vocabulary rather than generic academic filler
- Every factual claim must reference evidence via [N] markers
- Transitions between paragraphs should advance the argument, not just summarize
- Hedge novelty claims with "to our knowledge" or "among the first"
"""


def _citation_block(citation_quota: int, evidence_count: int = 0) -> str:
    if citation_quota <= 0:
        return ""
    bound_line = ""
    if evidence_count > 0:
        bound_line = f"\n- The evidence list contains exactly {evidence_count} papers numbered [1] through [{evidence_count}]. NEVER cite a number outside this range."
    return f"""
## CITATION REQUIREMENT (STRICT)

You MUST cite **at least {citation_quota} DISTINCT papers** from the evidence list below.
- Each citation must be ONE of [1], [2], [3], ... matching the numbered evidence list{bound_line}
- NEVER invent citation numbers that do not appear in the evidence list
- NEVER cite papers by name if they are not in the evidence list — omit the citation rather than guess
- Use citations density consistent with top-venue papers: cite whenever you make a factual claim or reference prior work
- A section with fewer than {citation_quota} distinct citations will be REJECTED for revision
- Before finishing, count the distinct citation numbers you used
"""


def section_draft_prompt(
    section: str,
    outline: str,
    evidence_text: str,
    max_words: int = 2000,
    section_guidance: str = "",
    citation_quota: int = 0,
) -> str:
    """Generic section draft prompt; dispatches to section-specific variants
    via ``build_section_draft_prompt`` based on section name.
    """
    outline_line = f"Outline: {outline}\n" if outline else ""
    guidance_block = f"\n{section_guidance}\n" if section_guidance else ""
    citation_block = _citation_block(citation_quota)
    return f"""You are an academic writer drafting a paper section for a top-venue submission.

Section: {section}
{outline_line}Target words: ~{max_words} (aim for 90-110% of this target)

Evidence and sources (each marked [N] for citation):
{_truncate(evidence_text, 20000)}

Write the section in academic style. Use [N] citation markers matching the numbered evidence above.
{citation_block}{guidance_block}
{_COMMON_STYLE_BLOCK}

Return JSON only:
{{"content": "<section text>", "citations_used": [<evidence indices>], "word_count": <int>}}"""


def intro_draft_prompt(
    outline: str,
    evidence_text: str,
    max_words: int = 1500,
    section_guidance: str = "",
    citation_quota: int = 15,
    evidence_count: int = 0,
) -> str:
    """Introduction-specific prompt enforcing tension building and itemized contributions."""
    outline_line = f"Outline: {outline}\n" if outline else ""
    guidance_block = f"\n{section_guidance}\n" if section_guidance else ""
    citation_block = _citation_block(citation_quota, evidence_count)
    return f"""You are an academic writer drafting the INTRODUCTION section of a top-venue paper.

{outline_line}Target words: ~{max_words} (aim for 90-110% of this target)

Evidence and sources (each marked [N] for citation):
{_truncate(evidence_text, 20000)}

{citation_block}
## INTRODUCTION STRUCTURE (REQUIRED)

Follow this 5-paragraph structure used by top-venue papers:

**Paragraph 1 — Hook + tension**: Start with a concrete fact, surprising observation, or failure
of existing methods (NOT "X has attracted growing interest"). Cite 3-5 supporting references.

**Paragraph 2 — Why existing solutions fall short**: Describe the current landscape of methods
and articulate their specific limitations using concrete evidence. Cite 4-8 competing works.

**Paragraph 3 — Key insight / design idea**: State your core idea and explain *why* it addresses
the gap identified in Paragraph 2. One paragraph. Cite related routing/attention/etc. principles
it builds on.

**Paragraph 4 — Contributions (REQUIRED FORMAT)**: Start with a topic sentence like "We present
<NAME> with <K> contributions:" and then use LaTeX itemize/enumerate:

```
\\begin{{itemize}}
    \\item \\textbf{{<Contribution 1 name>}}: <1-2 sentences stating the INSIGHT not just the artifact, and why it matters>
    \\item \\textbf{{<Contribution 2 name>}}: ...
    \\item \\textbf{{<Contribution 3 name>}}: ...
\\end{{itemize}}
```

**Paragraph 5 — Results preview**: Preview 2-3 empirical findings with concrete numbers
(even placeholders like X\\% are OK). Mention datasets and strongest baseline. Cite baselines.

Every factual or comparative claim in Paragraphs 1-3 and 5 MUST be backed by a [N] citation.
{guidance_block}
{_COMMON_STYLE_BLOCK}

Return JSON only:
{{"content": "<introduction text with LaTeX formatting>", "citations_used": [<evidence indices>], "word_count": <int>}}"""


def related_work_draft_prompt(
    outline: str,
    evidence_text: str,
    max_words: int = 2500,
    section_guidance: str = "",
    citation_quota: int = 30,
    evidence_count: int = 0,
) -> str:
    """Related work prompt enforcing taxonomy organization with per-subsection positioning."""
    outline_line = f"Outline: {outline}\n" if outline else ""
    guidance_block = f"\n{section_guidance}\n" if section_guidance else ""
    citation_block = _citation_block(citation_quota, evidence_count)
    return f"""You are an academic writer drafting the RELATED WORK section of a top-venue paper.

{outline_line}Target words: ~{max_words} (aim for 90-110% of this target)

Evidence and sources (each marked [N] for citation):
{_truncate(evidence_text, 30000)}

{citation_block}
## RELATED WORK STRUCTURE (REQUIRED)

Organize related work as a TAXONOMY with 3-4 \\subsection{{}} groupings. DO NOT use phone-book
enumeration ("X does A. Y does B. Z does C."). Each subsection must:

1. Open with a framing sentence that names the family and its defining principle
2. Group 5-10 papers by their shared approach, summarizing the family's strengths and limits
3. End with a **Positioning paragraph** (labelled `\\textbf{{Positioning:}}`) that explicitly
   contrasts this family with OUR method, naming concrete differences (granularity, assumptions,
   applicability, or empirical regime).

Aim for at least 30 DISTINCT citations across all subsections. Each subsection should cite
≥8 papers.

Example subsection frame:

```
\\subsection{{<Family name>}}
<Opening framing sentence.> Works such as A~\\cite{{a}}, B~\\cite{{b}}, and C~\\cite{{c}} share
<defining principle>. <2-3 sentences explaining the shared approach and naming 3-5 more
representative works [N,N,N].> However, <specific limitation common to this family, with 1-2
concrete examples [N,N]>.

\\textbf{{Positioning:}} <Single sentence explicitly contrasting this family with our method>.
```
{guidance_block}
{_COMMON_STYLE_BLOCK}

Return JSON only:
{{"content": "<related work text with \\\\subsection and \\\\textbf formatting>", "citations_used": [<evidence indices>], "word_count": <int>}}"""


def experiments_draft_prompt(
    outline: str,
    evidence_text: str,
    max_words: int = 3500,
    section_guidance: str = "",
    citation_quota: int = 8,
    evidence_count: int = 0,
) -> str:
    """Experiments prompt enforcing post-table analysis and rich table formatting."""
    outline_line = f"Outline: {outline}\n" if outline else ""
    guidance_block = f"\n{section_guidance}\n" if section_guidance else ""
    citation_block = _citation_block(citation_quota, evidence_count)
    return f"""You are an academic writer drafting the EXPERIMENTS section of a top-venue paper.

{outline_line}Target words: ~{max_words} (aim for 90-110% of this target)

Evidence and sources (each marked [N] for citation):
{_truncate(evidence_text, 20000)}

{citation_block}
## EXPERIMENTS STRUCTURE (REQUIRED)

Provide 6-8 \\subsection{{}} blocks, e.g. Setup, Main Results, Granularity Ablation,
Cross-Domain Transfer, Component Ablation, Efficiency, Robustness, Case Study / Visualization.

### Table Formatting (REQUIRED)

EVERY table must use this style:

```
\\begin{{table}}[t]
\\centering
\\small
\\caption{{<Descriptive caption explaining what is measured, NOT just "Main results"> (MSE $\\downarrow$).
Best in \\textbf{{bold}}, second best \\underline{{underlined}}. $\\pm$ indicates std over 3 seeds.}}
\\label{{tab:<id>}}
\\resizebox{{\\textwidth}}{{!}}{{%
\\begin{{tabular}}{{l|cccc|c}}
\\toprule
\\multirow{{2}}{{*}}{{\\textbf{{Method}}}} & \\multicolumn{{4}}{{c|}}{{<Group 1>}} & \\multirow{{2}}{{*}}{{\\textbf{{Avg}}}} \\\\
& col1 & col2 & col3 & col4 & \\\\
\\midrule
Baseline A & ... & ... & ... & ... & ... \\\\
Baseline B & ... & ... & ... & ... & ... \\\\
\\midrule
\\rowcolor{{gray!15}} \\textbf{{Ours}} & \\textbf{{X.XX}} & ... & ... & ... & \\textbf{{X.XX}} \\\\
\\bottomrule
\\end{{tabular}}%
}}
\\end{{table}}
```

Required table features: \\multirow or \\multicolumn for grouped headers, \\rowcolor{{gray!15}} or
\\cellcolor{{gray!15}} for OUR method's row, \\textbf for best results, \\underline for second-best,
\\resizebox to fit page width, \\label{{tab:...}}, informative \\caption.

### Post-Table Analysis (REQUIRED)

Every table MUST be followed by 2-3 paragraphs (≥100 words) covering:
1. **Win/loss diagnosis**: WHICH domains/settings we win, which we lose, and WHY
2. **Hypothesis linking**: how the result supports (or refines) our key claim
3. **Unexpected findings**: any counter-intuitive results and their explanation

### Figure Placeholders

Include at least 3 `\\begin{{figure}}` blocks: (a) architecture overview, (b) main quantitative
trend plot, (c) qualitative case study / visualization (e.g., gate heatmap). Use
`\\includegraphics[width=...]{{figs/<name>.pdf}}` with informative captions.

### Result Narrative

Always lead with the *claim*, then point to the table as evidence. Do NOT open with
"As shown in Table X". Open with "Our method achieves XX\\% lower MSE than ... (Table~\\ref{{tab:X}})".
{guidance_block}
{_COMMON_STYLE_BLOCK}

Return JSON only:
{{"content": "<experiments text with LaTeX tables, figures, and post-table analysis>", "citations_used": [<evidence indices>], "word_count": <int>}}"""


def method_draft_prompt(
    outline: str,
    evidence_text: str,
    max_words: int = 3000,
    section_guidance: str = "",
    citation_quota: int = 8,
    evidence_count: int = 0,
) -> str:
    """Method-specific prompt enforcing proper LaTeX subsections, equations, and algorithms."""
    outline_line = f"Outline: {outline}\n" if outline else ""
    guidance_block = f"\n{section_guidance}\n" if section_guidance else ""
    citation_block = _citation_block(citation_quota, evidence_count)
    return f"""You are an academic writer drafting the METHOD section of a top-venue paper.

{outline_line}Target words: ~{max_words} (aim for 90-110% of this target)

Evidence and sources (each marked [N] for citation):
{_truncate(evidence_text, 20000)}

{citation_block}
## METHOD SECTION FORMAT REQUIREMENTS (STRICT)

The output MUST be valid LaTeX. Follow these formatting rules exactly:

1. **Subsection structure**: Use \\subsection{{...}} and \\subsubsection{{...}} for all headings.
   Do NOT use plain-text headings like "3.1 Problem Formulation" — use \\subsection{{Problem Formulation}}.
   Do NOT include a top-level \\section{{Method}} — the assembler adds that automatically.

2. **Math environments**: ALL mathematical expressions must be in LaTeX math mode:
   - Inline math: $g_t^{{(m)}}$, $z_t = \\sum_m g_t^{{(m)}} h_t^{{(m)}}$
   - Display equations: Use \\begin{{equation}}...\\end{{equation}} or \\begin{{align}}...\\end{{align}}
   - Never write raw subscripts/superscripts outside math mode

3. **Algorithm blocks**: Use \\begin{{algorithm}} with \\begin{{algorithmic}} for pseudocode:
   ```
   \\begin{{algorithm}}[t]
   \\caption{{Algorithm title}}
   \\label{{alg:name}}
   \\begin{{algorithmic}}[1]
   \\Require Input description
   \\For{{$t = 1$ \\textbf{{to}} $T$}}
       \\State Compute $x_t$
   \\EndFor
   \\end{{algorithmic}}
   \\end{{algorithm}}
   ```

4. **Cross-references**: Use \\cref{{fig:name}}, \\cref{{tab:name}}, \\cref{{alg:name}} for references.
   Do NOT write "Figure 1" or "Figure arch" — always use \\cref.

5. **Notation table**: If defining many symbols, use a small table or inline list with \\textbf for terms.

6. **Design justification**: Each major design choice should have a 1-2 sentence "why" explaining
   the rationale vs. alternatives, citing relevant prior work with [N].

7. **Theory constraint (CRITICAL)**: This paper is algorithm/model innovation, NOT theory-driven.
   - Do NOT generate multi-step proofs, lemmas, or corollaries
   - At MOST one simple proposition (hand-verifiable in ≤1 page) is allowed if it provides design grounding
   - A wrong theorem is 10x worse than no theorem — LLM-generated proofs have high error probability
   - Focus on: intuitive explanations, design rationale, complexity analysis, convergence arguments WITHOUT formal proof
   - If a theoretical guarantee is needed, state it as a "Remark" or "Claim" with informal justification, not a formal proof

## STRUCTURE TEMPLATE

Organize the method section as:
- \\subsection{{Problem Formulation}} — formal setup, notation, objective
- \\subsection{{Architecture Overview}} — high-level pipeline with \\cref to architecture figure
- \\subsection{{<Core Technical Component>}} — the main algorithmic contribution (equations + algorithm block)
- \\subsection{{Training Objective}} — loss function with equation environment
- \\subsection{{Training and Inference}} — practical details, complexity analysis
{guidance_block}
{_COMMON_STYLE_BLOCK}

Return JSON only:
{{"content": "<method text with proper LaTeX subsections, equations, and algorithm blocks>", "citations_used": [<evidence indices>], "word_count": <int>}}"""


def build_section_draft_prompt(
    section: str,
    outline: str,
    evidence_text: str,
    max_words: int = 2000,
    section_guidance: str = "",
    citation_quota: int = 0,
    writing_patterns: str = "",
    evidence_count: int = 0,
) -> str:
    """Dispatch to section-specific prompt if available, else generic."""
    sec = (section or "").strip().lower().replace(" ", "_")
    if sec in {"introduction", "intro"}:
        return intro_draft_prompt(
            outline,
            evidence_text,
            max_words,
            section_guidance,
            citation_quota,
            evidence_count=evidence_count,
        )
    if sec in {"related_work", "related-work", "related"}:
        return related_work_draft_prompt(
            outline,
            evidence_text,
            max_words,
            section_guidance,
            citation_quota,
            evidence_count=evidence_count,
        )
    if sec in {"method", "methodology", "approach", "proposed_method"}:
        return method_draft_prompt(
            outline,
            evidence_text,
            max_words,
            section_guidance,
            citation_quota,
            evidence_count=evidence_count,
        )
    if sec in {"experiments", "experiment", "results", "evaluation"}:
        return experiments_draft_prompt(
            outline,
            evidence_text,
            max_words,
            section_guidance,
            citation_quota,
            evidence_count=evidence_count,
        )
    if writing_patterns:
        return section_draft_with_patterns_prompt(
            section,
            outline,
            evidence_text,
            writing_patterns,
            max_words,
            section_guidance=section_guidance,
        )
    return section_draft_prompt(
        section,
        outline,
        evidence_text,
        max_words,
        section_guidance=section_guidance,
        citation_quota=citation_quota,
    )


def paper_coverage_check_prompt(
    topic_context: str,
    papers_text: str,
    focus: str = "",
    dismissal_history: list[tuple[str, str]] | None = None,
) -> str:
    focus_line = f"\nResearch focus: {focus}" if focus else ""
    if dismissal_history:
        history_lines = "\n".join(
            f'- "{title}": {reason}' for title, reason in dismissal_history
        )
        calibration_block = f"""
User preference signal — papers previously dismissed by the researcher (use these to calibrate your scoring):
{_truncate(history_lines, 1500)}

Apply the same dismissal logic when scoring similar papers below.
"""
    else:
        calibration_block = ""
    return f"""You are a research coverage analyst.{focus_line}

Given the research topic context and the list of papers below (each with available metadata),
assess whether the full text of each paper is necessary for a thorough literature review and gap analysis.

Topic context:
{_truncate(topic_context, 1000)}
{calibration_block}
Papers (id | title | abstract_available | abstract_snippet):
{_truncate(papers_text, 8000)}

For each paper, rate full-text necessity as:
- "high": Paper is directly relevant to the core topic; missing full text creates a significant blind spot for gap analysis.
- "medium": Paper is relevant but abstract may suffice for high-level coverage; full text would improve depth.
- "low": Tangential or peripheral paper; title/abstract is sufficient.

Return JSON only — include every paper_id listed above:
{{"assessments": [{{"paper_id": <int>, "necessity_level": "<high|medium|low>", "reason": "<one sentence>"}}]}}"""


def deep_read_pass1_prompt(paper_title: str, paper_text: str, focus: str = "") -> str:
    focus_line = f"\nFocus area: {focus}" if focus else ""
    return f"""You are a senior research scientist performing a critical deep reading.{focus_line}

Paper: {paper_title}

Full text:
{_truncate(paper_text, 16000)}

Perform a thorough technical analysis:

1. Algorithm walkthrough: explain the core method step-by-step, including key equations, design choices, and how components interact. Use pseudo-code level detail where appropriate.

2. Limitation analysis: what assumptions does the method make? Where might it fail? What scenarios are not addressed? What are the boundary conditions?

3. Reproducibility assessment: are all hyperparameters specified? Is code publicly available? Are datasets accessible? Are training details sufficient to reproduce results? Rate as high/medium/low with justification.

Return JSON only:
{{"algorithm_walkthrough": "<detailed step-by-step walkthrough>", "limitation_analysis": "<thorough limitation analysis>", "reproducibility_assessment": "<assessment with rating>"}}"""


def deep_read_pass2_prompt(
    paper_title: str,
    pass1_json: str,
    card_text: str,
    topic_summary: str,
    focus: str = "",
) -> str:
    focus_line = f"\nFocus area: {focus}" if focus else ""
    return f"""You are a senior research scientist providing critical analysis and cross-paper synthesis.{focus_line}

Paper: {paper_title}

Paper card (objective extraction):
{_truncate(card_text, 3000)}

Deep extraction (Pass 1 analysis):
{_truncate(pass1_json, 4000)}

Topic literature context (other papers in the pool):
{_truncate(topic_summary, 6000)}

Provide:

1. Critical assessment: evaluate method soundness, experiment fairness, novelty relative to prior work, statistical rigor, and potential biases.

2. Industrial feasibility: assess deployment viability.
   - viability: high/medium/low
   - latency_constraints: real-time requirements or latency budget
   - data_requirements: what data is needed, availability
   - engineering_challenges: key technical hurdles for production
   - deployment_prerequisites: infrastructure or system requirements

3. Research implications: what new research directions does this paper enable, block, or suggest? Be specific to our topic.

4. Cross-paper links: how does this paper relate to other papers in the topic context? Use paper IDs from the context. Types: extends, contradicts, applies, improves, competes.

Return JSON only:
{{"critical_assessment": "<assessment>", "industrial_feasibility": {{"viability": "<high|medium|low>", "latency_constraints": "<str>", "data_requirements": "<str>", "engineering_challenges": ["<challenge>"], "deployment_prerequisites": ["<prerequisite>"]}}, "research_implications": ["<implication>"], "cross_paper_links": [{{"target_paper_id": <int>, "relation_type": "<type>", "evidence": "<why>"}}]}}"""


def outline_generate_prompt(
    topic_summary: str,
    claims_summary: str,
    template: str = "neurips",
    contributions: str = "",
) -> str:
    # outline_generate in llm_primitives refuses to invoke this prompt with
    # an empty contributions string; if we ever get here with blank input it
    # is a bug — treat it strictly rather than fabricating a paper topic.
    contrib_block = f"""
==========================================================================
PAPER CONTRIBUTIONS (AUTHORITATIVE — this is the paper YOU are writing)
==========================================================================
{_truncate(contributions, 4000)}
==========================================================================

CRITICAL RULES:
- The title, abstract, and outline MUST describe THE paper defined by the
  contributions above. Do NOT invent a different paper title or topic.
- Literature and claims below are background context for citation and
  positioning only; they are NOT the subject of this paper.
- Every section's key_points must directly support one or more of the
  listed contributions.
- If contributions mention a specific method/system name, use that name
  in the title and throughout the outline verbatim.
"""

    return f"""You are an academic paper architect designing an outline for a {template}-style paper.
{contrib_block}
Background literature (for citation context only):
{_truncate(topic_summary, 8000)}

Related claims (for citation context only):
{_truncate(claims_summary, 3000)}

For each section provide:
- section: identifier (introduction, related_work, method, experiments, results, discussion, conclusion)
- title: display title
- target_words: recommended word count
- key_points: 2-4 bullet points of what should be covered — each must tie back to a stated contribution
- evidence_ids: which claims/evidence to cite (use claim IDs or paper IDs from context)

Also generate a working title and abstract draft (150-200 words). Title and abstract MUST be about the contributions above, not about the background literature.

Return JSON only:
{{"title": "<working title>", "abstract_draft": "<abstract text>", "sections": [{{"section": "<id>", "title": "<display title>", "target_words": <int>, "key_points": ["<point>"], "evidence_ids": ["<id>"]}}]}}"""


def section_review_prompt(section: str, content: str, target_words: int = 0) -> str:
    target_line = f"\nTarget word count: {target_words}" if target_words > 0 else ""
    return f"""You are a rigorous academic paper reviewer scoring a single section.

Section: {section}{target_line}

Text to review:
{_truncate(content, 12000)}

Score each dimension from 0.0 to 1.0, where 1.0 is excellent and 0.0 is unacceptable.
Provide a brief justification comment for each score.

Dimensions:
1. clarity — Is the writing clear and unambiguous?
2. novelty — Does the content present original insights or framing?
3. correctness — Are claims technically accurate and well-supported?
4. significance — Does the section contribute meaningfully to the paper?
5. reproducibility — Are details sufficient for replication?
6. writing_quality — Grammar, style, flow, and academic tone
7. evidence_support — Are claims backed by citations and data?
8. logical_flow — Does the argument progress logically?
9. completeness — Are all expected aspects covered for this section type?
10. conciseness — Is the text free of redundancy and filler?

Also provide 3-5 actionable suggestions for improvement.

CRITICAL CHECK — Theory overload detection:
If the section contains formal theorems, lemmas, corollaries, or multi-step proofs:
- Flag this as a HIGH-PRIORITY issue in suggestions
- Score "correctness" at most 0.5 (LLM-generated proofs have high error probability)
- Recommend replacing with: intuitive arguments, remarks with informal justification, or complexity analysis without formal proof
- Exception: ONE simple proposition (≤0.5 page) with hand-verifiable reasoning is acceptable

Return JSON only:
{{"dimensions": [{{"dimension": "<name>", "score": <0.0-1.0>, "comment": "<justification>"}}], "suggestions": ["<suggestion>"], "overall_score": <0.0-1.0>}}"""


def section_revise_prompt(
    section: str,
    content: str,
    review_feedback: str,
    target_words: int = 0,
) -> str:
    target_line = f"\nTarget word count: {target_words}" if target_words > 0 else ""
    return f"""You are an academic writer revising a paper section based on reviewer feedback.

Section: {section}{target_line}

Current text:
{_truncate(content, 10000)}

Reviewer feedback to address:
{_truncate(review_feedback, 3000)}

Revise the section to address ALL feedback points. Maintain academic style and citation markers [N].

## Writing Quality Requirements

PROHIBITED phrases — do NOT use:
- "delve into", "it is important to note", "it is worth noting"
- "in the realm of", "a myriad of", "shed light on"
- "pave the way", "plays a crucial role", "a growing body of"

REQUIRED style:
- Vary paragraph length (2-8 sentences)
- Mix short declarative with longer compound sentences
- Prefer active voice
- Use precise, discipline-specific vocabulary
- Every claim must reference evidence via [N] markers

Return JSON only:
{{"revised_content": "<full revised section text>", "changes_made": ["<description of each change>"], "word_count": <int>}}"""


def consistency_check_prompt(sections_text: str) -> str:
    return f"""You are a paper consistency reviewer.

Review the following paper sections for:
1. Contradictory claims between sections
2. Undefined terms used before introduction
3. Citation gaps
4. Logical flow issues
5. Notation inconsistencies

Sections:
{_truncate(sections_text, 15000)}

Return JSON only:
{{"issues": [{{"issue_type": "<type>", "severity": "<low|medium|high>", "location": "<section>", "description": "<what is wrong>", "suggestion": "<how to fix>"}}]}}"""


def compiled_summary_prompt(paper_title: str, source_text: str) -> str:
    return f"""You are a research paper analyst producing a structured summary.

Paper: {paper_title}

Source material:
{_truncate(source_text, 10000)}

Extract a structured summary with these fields:
- overview: 2-3 sentence summary of the paper's core contribution
- methods: list of methods/techniques used (short descriptions)
- claims: list of specific claims with evidence and strength (strong/moderate/weak)
- limitations: list of limitations, assumptions, failure modes
- metrics: list of reported results with dataset, metric name, value, and baseline comparison
- relations: list of relationships to other work (extends X, contradicts Y, applies Z)

Return JSON only:
{{"overview": "<str>", "methods": ["<str>"], "claims": [{{"claim": "<str>", "evidence": "<str>", "strength": "<strong|moderate|weak>"}}], "limitations": ["<str>"], "metrics": [{{"dataset": "<str>", "metric": "<str>", "value": "<str>", "baseline": "<str>"}}], "relations": ["<str>"]}}"""


def topic_overview_prompt(papers_context: str, total_count: int) -> str:
    return f"""You are a research field analyst producing a literature overview.

You are seeing a representative sample of papers from a topic containing {total_count} papers total.
The sample includes high-impact foundational papers and recent work, plus papers that may present contrasting findings.

Papers:
{_truncate(papers_context, 16000)}

Write a structured overview covering:
1. Major research themes and methodological families
2. Key findings and emerging consensus
3. Notable disagreements or contradictions
4. Temporal trends (how the field has evolved)
5. Remaining open questions

Return JSON only:
{{"overview": "<comprehensive overview text, 500-800 words>"}}"""


def code_generate_prompt(
    study_spec: str,
    topic_summary: str,
    iteration: int = 0,
    previous_code: str = "",
    previous_metrics: str = "",
    feedback: str = "",
) -> str:
    iteration_block = ""
    if iteration > 0 and previous_code:
        iteration_block = f"""
This is iteration {iteration}. Previous code:
```python
{_truncate(previous_code, 6000)}
```

Previous metrics: {previous_metrics}
Feedback: {feedback}

Improve the code based on the feedback. Fix bugs, improve metrics, address issues.
"""
    return f"""You are an expert ML experiment coder.

Generate a complete, self-contained Python experiment script based on the study specification below.

Study Specification:
{_truncate(study_spec, 6000)}

Research Context:
{_truncate(topic_summary, 4000)}
{iteration_block}
Requirements:
1. Script must be SELF-CONTAINED — all imports at top, no external config files
2. Print metrics as "METRIC <name> <value>" on stdout for automatic parsing
3. Use standard libraries + numpy/scipy/sklearn/torch where appropriate
4. Include a clear main() function as entry point
5. Handle errors gracefully — print meaningful error messages
6. Set random seeds for reproducibility

Return JSON only:
{{"files": {{"main.py": "<complete python code>"}}, "entry_point": "main.py", "description": "<what this experiment does>"}}"""


# ---------------------------------------------------------------------------
# Phase 2: Cross-paper analysis prompts
# ---------------------------------------------------------------------------


def method_taxonomy_prompt(papers_context: str, focus: str = "") -> str:
    """Prompt for building a method taxonomy from paper summaries."""
    focus_line = f"\nResearch focus: {focus}" if focus else ""
    return f"""Analyze the following paper summaries and build a hierarchical method taxonomy.{focus_line}

Papers:
{papers_context}

Build a hierarchical taxonomy of methods/approaches used in these papers. For each method:
- Group similar methods under parent categories
- Detect aliases (same method, different names)
- Estimate how many papers use each method

Return JSON only:
{{"nodes": [
    {{"name": "<method name>", "parent": "<parent category or null>",
      "description": "<1-sentence description>",
      "aliases": ["<alias1>", "<alias2>"],
      "paper_ids": [<paper_id>, ...]}}
  ]
}}"""


def evidence_matrix_prompt(claims_context: str, focus: str = "") -> str:
    """Prompt for normalizing claims into structured dimensions."""
    focus_line = f"\nResearch focus: {focus}" if focus else ""
    return f"""Normalize the following research claims into a structured evidence matrix.{focus_line}

Claims from papers:
{claims_context}

For each claim, extract structured dimensions:
- method: the method/approach name
- dataset: the evaluation dataset
- metric: the evaluation metric
- task: the task being evaluated
- value: the reported value (number or qualitative description)
- direction: "higher_better", "lower_better", or "qualitative"
- confidence: 0.0-1.0 based on evidence strength

Return JSON only:
{{"normalized_claims": [
    {{"paper_id": <int>, "claim_text": "<original claim>",
      "method": "<method>", "dataset": "<dataset>", "metric": "<metric>",
      "task": "<task>", "value": "<value>", "direction": "<direction>",
      "confidence": <float>}}
  ]
}}"""


def contradiction_detect_prompt(claims_context: str) -> str:
    """Prompt for detecting contradictions between normalized claims."""
    return f"""Analyze the following normalized claims and identify potential contradictions — pairs of claims that report conflicting results.

Normalized claims:
{claims_context}

Only flag pairs where:
1. Both claims evaluate on the SAME task AND (same dataset OR same metric)
2. Their results genuinely conflict (e.g., method A > B in one paper but B > A in another)
3. You have reasonable confidence this is a real tension, not just different experimental settings

Return JSON only:
{{"contradictions": [
    {{"claim_a_id": <int>, "claim_b_id": <int>,
      "same_task": <bool>, "same_dataset": <bool>, "same_metric": <bool>,
      "confidence": <float 0-1>,
      "conflict_reason": "<explanation of the contradiction>"}}
  ]
}}"""


# ---------------------------------------------------------------------------
# Phase 2: Prompt extensions
# ---------------------------------------------------------------------------


def deep_read_math_prompt(paper_title: str, paper_text: str, focus: str = "") -> str:
    """Deep read with math explanation mode — simplifies equations, builds symbol table."""
    focus_line = f"\nFocus area: {focus}" if focus else ""
    return f"""You are a math-literate research scientist explaining a paper's technical details.{focus_line}

Paper: {paper_title}

Full text:
{_truncate(paper_text, 16000)}

Provide a math-focused deep reading:

1. Symbol table: list ALL mathematical symbols/notation used in the paper with their meanings, dimensions, and typical value ranges.

2. Key equations explained: for each important equation, provide:
   - The equation in plain text
   - Intuitive explanation of what it computes and WHY
   - How each term contributes to the result
   - What happens at boundary cases (e.g., when a term is 0 or ∞)

3. Hyperparameter analysis: list all hyperparameters with their reported values, sensitivity (if discussed), and practical guidance for tuning.

4. Computational complexity: time and space complexity of the core algorithm, bottleneck operations, and scalability considerations.

Return JSON only:
{{"symbol_table": [{{"symbol": "<str>", "meaning": "<str>", "dimension": "<str>", "range": "<str>"}}],
  "key_equations": [{{"equation": "<str>", "intuition": "<str>", "term_breakdown": "<str>", "boundary_cases": "<str>"}}],
  "hyperparameters": [{{"name": "<str>", "value": "<str>", "sensitivity": "<str>", "tuning_guide": "<str>"}}],
  "complexity": {{"time": "<str>", "space": "<str>", "bottleneck": "<str>", "scalability": "<str>"}}
}}"""


def section_draft_abstract_prompt(
    title: str,
    contributions: str,
    results_summary: str,
    max_words: int = 250,
) -> str:
    """Prompt for drafting a paper abstract."""
    return f"""Write a concise academic abstract for the following paper.

Title: {title}
Maximum words: {max_words}

Key contributions:
{_truncate(contributions, 2000)}

Results summary:
{_truncate(results_summary, 2000)}

The abstract should:
1. State the problem in 1-2 sentences
2. Describe the proposed approach briefly
3. Highlight key results with specific numbers
4. End with the broader impact/implication

Write ONLY the abstract text, no JSON wrapper needed. Use precise, academic language.
Avoid: "delve into", "it is important to note", "a myriad of", "shed light on"."""


def section_draft_contributions_prompt(
    paper_title: str,
    method_summary: str,
    results_summary: str,
) -> str:
    """Prompt for generating a structured contributions list."""
    return f"""Generate a numbered list of contributions for the following paper.

Paper: {paper_title}

Method summary:
{_truncate(method_summary, 3000)}

Results:
{_truncate(results_summary, 3000)}

Write 3-5 bullet-point contributions. Each contribution should:
- Start with a verb (e.g., "We propose...", "We demonstrate...", "We introduce...")
- Be specific about what is novel
- Reference concrete results where applicable

Return JSON only:
{{"contributions": ["<contribution 1>", "<contribution 2>", ...]}}"""


def rebuttal_draft_prompt(
    review_issues: str,
    responses: str,
    paper_context: str = "",
) -> str:
    """Prompt for formatting a rebuttal letter from review issues and responses."""
    context_line = (
        f"\nPaper context:\n{_truncate(paper_context, 3000)}\n" if paper_context else ""
    )
    return f"""Format a professional rebuttal letter from the following reviewer comments and author responses.{context_line}

Reviewer issues:
{_truncate(review_issues, 5000)}

Author responses:
{_truncate(responses, 5000)}

Format the rebuttal as:
1. Thank reviewers
2. For each major issue: quote the concern → provide the response → describe any changes made
3. Summary of changes

Use a professional, grateful tone. Be specific about modifications.
Write the full rebuttal text. No JSON needed."""


# ---------------------------------------------------------------------------
# Phase 3: Quantitative extraction prompts
# ---------------------------------------------------------------------------


def table_extract_prompt(paper_title: str, paper_text: str) -> str:
    """Prompt for extracting structured tables from paper text."""
    return f"""Extract ALL tables from the following paper text. For each table, identify the caption, column headers, and data rows.

Paper: {paper_title}

Text:
{_truncate(paper_text, 16000)}

For each table found:
- table_number: sequential number (1, 2, 3...)
- caption: the table caption/title
- headers: column header names
- rows: each row as an array of cell values (strings)
- source_page: page number if detectable, else null

Return JSON only:
{{"tables": [
    {{"table_number": <int>, "caption": "<str>",
      "headers": ["<col1>", "<col2>", ...],
      "rows": [["<val1>", "<val2>", ...], ...],
      "source_page": <int or null>}}
  ]
}}"""


def figure_interpret_prompt(paper_title: str, paper_text: str) -> str:
    """Prompt for interpreting figures described in the paper text."""
    return f"""Identify and interpret ALL figures referenced in the following paper text. Extract what each figure shows and key data points.

Paper: {paper_title}

Text:
{_truncate(paper_text, 16000)}

For each figure:
- figure_number: the figure number as referenced in text
- caption: the figure caption if available
- interpretation: 2-3 sentence description of what the figure shows
- key_data_points: specific values, trends, or comparisons visible in the figure
- figure_type: bar_chart, line_plot, scatter, diagram, table_figure, architecture, other

Return JSON only:
{{"figures": [
    {{"figure_number": <int>, "caption": "<str>",
      "interpretation": "<str>",
      "key_data_points": ["<data point 1>", ...],
      "figure_type": "<type>"}}
  ]
}}"""


def competitive_learning_prompt(
    venue: str,
    exemplar_papers_text: str,
    your_contributions: str = "",
) -> str:
    """Prompt for extracting writing patterns from exemplar papers."""
    contributions_line = (
        f"\nYour paper's contributions:\n{_truncate(your_contributions, 2000)}\n"
        if your_contributions
        else ""
    )
    return f"""You are a writing strategy analyst for academic papers.

Target venue: {venue}

Below are excerpts (title, abstract, section structure, and key passages) from
{venue}'s recent high-quality papers. Analyze their writing patterns — not their
technical content — to extract actionable guidance for a new paper targeting the
same venue.
{contributions_line}
Exemplar papers:
{_truncate(exemplar_papers_text, 12000)}

## Analysis Dimensions

For each dimension below, identify the dominant pattern across the exemplars:

1. **intro_narrative**: How does the Introduction build its argument?
   (e.g. "problem → why existing solutions fail → our key insight → contribution list")
2. **related_work_org**: How is Related Work organized?
   (e.g. "by method family", "by problem dimension", "chronological with pivot")
3. **method_exposition**: How is the Method section structured?
   (e.g. "overview figure → formal definition → algorithm → analysis",
    "problem setup → key insight → derivation → implementation")
4. **experiment_strategy**: How are experiments presented?
   (e.g. "main table → ablation → case study → scalability",
    "baseline comparison → per-component analysis → visualization")
5. **section_lengths**: Typical word count per section (intro, related, method, experiments, conclusion)
6. **transition_techniques**: How do sections and paragraphs connect?
7. **claim_density**: How frequently are citations used? Which sections are citation-heavy?

## Output Format

Return JSON only:
{{
  "patterns": [
    {{
      "dimension": "<dimension_name>",
      "pattern": "<description of the dominant pattern>",
      "example": "<concrete example sentence or structure from an exemplar>",
      "source_paper": "<title of the exemplar>"
    }}
  ],
  "section_length_norms": {{
    "introduction": <words>,
    "related_work": <words>,
    "method": <words>,
    "experiments": <words>,
    "conclusion": <words>
  }},
  "narrative_guidance": "<2-3 sentence overall writing strategy recommendation for the target venue>"
}}"""


def section_draft_with_patterns_prompt(
    section: str,
    outline: str,
    evidence_text: str,
    writing_patterns: str,
    max_words: int = 2000,
    section_guidance: str = "",
) -> str:
    """Enhanced section_draft prompt with competitive learning patterns injected."""
    outline_line = f"Outline: {outline}\n" if outline else ""
    guidance_block = f"\n{section_guidance}\n" if section_guidance else ""
    return f"""You are an academic writer drafting a paper section.

Section: {section}
{outline_line}Maximum words: {max_words}

Evidence and sources:
{_truncate(evidence_text, 8000)}
{guidance_block}
## Writing Patterns from Top Papers at This Venue

The following patterns were extracted from recent high-quality papers at the
target venue. Adopt these patterns where they fit your content naturally — do NOT
force-fit patterns that don't match your material.

{_truncate(writing_patterns, 3000)}

## Writing Quality Requirements

Follow these rules strictly to produce natural, high-quality academic prose:

PROHIBITED phrases and patterns — do NOT use any of these:
- "delve into", "it is important to note", "it is worth noting"
- "in the realm of", "a myriad of", "shed light on"
- "pave the way", "a testament to", "in light of"
- "plays a crucial role", "a growing body of"
- Overuse of em dashes (maximum 2 per page)
- Starting consecutive paragraphs with the same word or structure

REQUIRED style:
- Vary paragraph length (2-8 sentences per paragraph, not uniform)
- Vary sentence structure: mix short declarative with longer compound sentences
- Prefer active voice; use passive only when the actor is unknown or irrelevant
- Use precise, discipline-specific vocabulary rather than generic academic filler
- Every claim must reference evidence via [N] markers; no unsupported assertions
- Transitions between paragraphs should advance the argument, not just summarize

Return JSON only:
{{"content": "<section text>", "citations_used": [<evidence indices>], "word_count": <int>}}"""


# ---------------------------------------------------------------------------
# Topic framing
# ---------------------------------------------------------------------------


def topic_framing_prompt(context_text: str) -> str:
    return f"""You are a research advisor helping define a new research topic.

Based on the following context extracted from the user's project files
(README, docs, existing papers, notes), produce a structured topic definition.

Context:
{_truncate(context_text, 8000)}

Return JSON only:
{{
  "topic_name": "<2-5 words, lowercase, hyphen-separated>",
  "description": "<one paragraph scope description>",
  "search_queries": ["<query1>", "<query2>", ...],
  "scope_keywords": ["<kw1>", ...],
  "target_venue": "<str or empty>",
  "year_from": <int>,
  "exclusions": ["<out of scope item>", ...],
  "seed_papers": ["<title or id>", ...]
}}"""


def direction_ranking_prompt(
    gaps_text: str,
    claims_text: str,
    topic_context: str,
) -> str:
    return f"""You are a research strategist ranking candidate research directions.

Topic context:
{_truncate(topic_context, 3000)}

Known gaps in the literature:
{_truncate(gaps_text, 4000)}

Key claims from existing papers:
{_truncate(claims_text, 4000)}

For each gap, propose a concrete research direction. Score each on three
dimensions (1-10): Novelty, Feasibility (3-6 months), Impact.
Composite = novelty*0.4 + feasibility*0.3 + impact*0.3. Rank descending. 3-6 directions.

Return JSON only:
{{
  "directions": [
    {{
      "direction": "<title>",
      "description": "<2-3 sentences>",
      "novelty": <float>, "feasibility": <float>, "impact": <float>,
      "composite_score": <float>,
      "supporting_gaps": ["<gap>", ...],
      "risks": ["<risk>", ...]
    }}
  ],
  "recommendation": "<which direction to pursue and why>"
}}"""


def method_layer_expansion_prompt(proposal_text: str, topic_context: str) -> str:
    return f"""You are a research methodology expert. Extract technical methods from
this proposal and generate search queries for method-layer literature — potentially
from DIFFERENT fields than the application domain.

Topic context:
{_truncate(topic_context, 2000)}

Research proposal:
{_truncate(proposal_text, 5000)}

Generate 5-10 search queries for method-layer papers. Categorize each as:
method_foundation / technique_reference / evaluation_reference.

Return JSON only:
{{
  "method_keywords": ["<keyword>", ...],
  "queries": [
    {{"query": "<str>", "category": "<str>", "rationale": "<str>"}}
  ],
  "cross_domain_venues": ["<venue>", ...]
}}"""


def writing_architecture_prompt(
    contributions_text: str,
    writing_patterns: str = "",
    outline_text: str = "",
) -> str:
    extras = ""
    if writing_patterns:
        extras += f"\nWriting patterns from exemplar papers:\n{_truncate(writing_patterns, 3000)}\n"
    if outline_text:
        extras += f"\nExisting outline draft:\n{_truncate(outline_text, 2000)}\n"
    return f"""You are a paper architecture designer. Design the optimal paper
structure for the following contributions.

Research contributions:
{_truncate(contributions_text, 4000)}
{extras}
Design an architecture that maximizes persuasiveness, front-loads the key insight,
and allocates space proportionally to contribution significance.

Return JSON only:
{{
  "paper_title": "<suggested title>",
  "narrative_strategy": "<how the paper tells its story>",
  "sections": [
    {{
      "section": "<section_id>", "title": "<display title>",
      "target_words": <int>,
      "argument_strategy": "<what this section must accomplish>",
      "key_evidence": ["<evidence item>", ...]
    }}
  ],
  "total_words": <int>,
  "strengths": ["<structural strength>", ...]
}}"""


# ---------------------------------------------------------------------------
# Figure planning
# ---------------------------------------------------------------------------


def figure_plan_prompt(
    contributions: str,
    outline_text: str,
    evidence_text: str,
    target_venue: str = "",
) -> str:
    """Plan figures and tables for a paper based on contributions + outline."""
    venue_line = f"\nTarget venue: {target_venue}" if target_venue else ""
    return f"""You are a figure/table planner for a top-venue academic paper.{venue_line}

Paper contributions:
{_truncate(contributions, 3000)}

Paper outline:
{_truncate(outline_text, 3000)}

Literature / evidence context:
{_truncate(evidence_text, 4000)}

## Task

Produce a plan for the figures and tables this paper should contain. Follow top-venue norms:

- 3-5 FIGURES total (at least one architecture overview, at least one qualitative visualization)
- 5-8 TABLES total (main results, ablations, cross-domain, efficiency, robustness)
- Every table must use multirow/multicolumn/cellcolor for visual emphasis
- Every figure must describe concrete visual content, not generic "diagram"

For each item, specify:
- figure_id (LaTeX label, e.g. "fig:arch", "tab:main")
- kind ("figure" or "table")
- title (short, e.g. "ModalGate architecture overview")
- caption (full LaTeX caption text, 1-3 sentences)
- section (which section the figure/table appears in)
- purpose (what the figure/table communicates; one sentence)
- data_source (where the data/source material comes from)
- suggested_layout (concrete layout description, e.g. "3-panel figure: (a) gate heatmap overlay,
  (b) ablation grid, (c) per-domain gain bar chart" or "multirow table with grouped headers,
  cellcolor gray!15 for Ours row, bold for best, underline for second-best")
- placement_hint (where in the section this should appear)

## Output

Return JSON only:
{{"items": [
    {{"figure_id": "<id>", "kind": "figure|table", "title": "<title>",
      "caption": "<caption>", "section": "<section>", "purpose": "<purpose>",
      "data_source": "<source>", "suggested_layout": "<layout>",
      "placement_hint": "<hint>"}}
]}}"""


# ---------------------------------------------------------------------------
# Universal Writing Skill: pattern extraction
# ---------------------------------------------------------------------------


def writing_pattern_extract_prompt(
    paper_title: str,
    paper_text: str,
    paper_venue: str = "",
) -> str:
    """Extract structural writing patterns from a paper — structure, not content."""
    venue_line = f"\nPublished at: {paper_venue}" if paper_venue else ""
    return f"""You are an academic writing analyst. Analyze the STRUCTURE and WRITING CRAFT
of this paper — NOT its technical content. Focus on HOW the paper is written, not WHAT it says.

Paper: {paper_title}{venue_line}

Text (first ~2000 words, covering abstract through early method):
{_truncate(paper_text, 12000)}

For each dimension below, extract a structured observation. Be precise and factual.

## Dimensions

1. **abstract_hook_type**: What type is the FIRST sentence of the abstract?
   Types: statistic (cites a number/fact), contradiction (challenges assumption),
   question (poses a research question), failure_case (shows existing methods fail),
   trend (describes a growing trend), definition (defines a concept)

2. **abstract_structure**: How many sentences in the abstract? What ROLE does each play?
   Roles: hook, background, gap, method_summary, result_highlight, implication

3. **intro_tension_building**: How does the introduction build tension?
   Count paragraphs. What does each paragraph accomplish? How many paragraphs before
   the contribution list? Does it use a concrete failure example or running example?

4. **intro_contribution_style**: How are contributions presented?
   Types: numbered_list (explicit enumeration), inline (woven into narrative),
   insight_driven (each contribution preceded by the insight motivating it)

5. **rw_taxonomy_type**: How is Related Work organized?
   Types: by_method (grouped by approach family), by_problem (grouped by problem),
   by_timeline (chronological), hybrid (combination), table_comparison (includes comparison table)

6. **rw_positioning**: How does each Related Work subsection end? Is there an explicit
   positioning statement ("Unlike X, our method...")?  Quote the positioning sentence if present.

7. **method_motivation_ratio**: Before each major equation/algorithm, how many sentences
   of intuition/motivation are provided? Estimate the ratio of motivation text to formal notation.

8. **method_design_justification**: Does the method section explain WHY design choices
   were made (not just what they are)? Does it mention alternatives considered?

9. **exp_post_table_analysis**: After result tables, how many paragraphs of analysis follow?
   What elements do they cover? (winner_explanation, loser_diagnosis, hypothesis_linking,
   domain_comparison, statistical_significance)

10. **exp_result_narrative**: How are results narrated?
    Types: hypothesis_first (state claim, then cite table), table_first (describe table, then interpret),
    domain_by_domain (one paragraph per domain/dataset), metric_by_metric

11. **conclusion_structure**: What elements appear in the conclusion?
    Elements: summary, key_finding, limitations, future_work, broader_impact, call_to_action

12. **claim_calibration**: How does the paper handle novelty claims?
    Count: uses of "the first", "novel", "to our knowledge", "among the first".
    Is hedging appropriate? Are claims supported by exhaustive literature review?

## Output

Return JSON with exactly 12 entries, one per dimension:
{{"observations": [
    {{"dimension": "<dimension_name>",
      "section": "<abstract|introduction|related_work|method|experiments|conclusion|overall>",
      "observation": "<structured factual observation>",
      "example_text": "<verbatim quote from the paper illustrating this pattern, max 150 words>"}}
]}}"""


# ---------------------------------------------------------------------------
# Algorithm design subsystem prompts
# ---------------------------------------------------------------------------

THEORY_CONSTRAINT_BLOCK = """\
**Theory constraint (CRITICAL)**: This paper targets algorithm/model innovation, NOT theory-driven contribution.
- Do NOT generate multi-step proofs, lemmas, or corollaries.
- At MOST one simple proposition (hand-verifiable in ≤1 page) is allowed for design grounding.
- A wrong theorem is 10x worse than no theorem — LLM-generated proofs have high error probability.
- Focus on: intuitive explanations, design rationale, complexity analysis, convergence arguments WITHOUT formal proof."""


def design_brief_expand_prompt(
    direction: str,
    gap_context: str = "",
    method_taxonomy: str = "",
    constraints: str = "",
) -> tuple[str, str]:
    system = f"""\
You are an expert algorithm designer specializing in top-venue (KDD/NeurIPS/ICML) research.
Your task is to expand a research direction into a formal design brief.

{THEORY_CONSTRAINT_BLOCK}

Output JSON with these fields:
- "problem_definition": Formal problem statement (mathematical notation OK, LaTeX format)
- "constraints": Array of design constraints (computational, data, domain)
- "method_slots": Array of objects, each: {{"name": "<slot>", "role": "<what it does>", "candidates": ["<method1>", "<method2>"], "status": "open|filled|blocked"}}
- "blocking_questions": Array of questions that must be answered before proceeding

Return ONLY valid JSON, no markdown fences."""

    user = f"""\
## Research Direction
{direction}

## Known Gaps in Literature
{gap_context if gap_context else "(none provided)"}

## Method Taxonomy from Paper Pool
{method_taxonomy if method_taxonomy else "(none provided)"}

## Additional Constraints
{constraints if constraints else "(none)"}

Expand this direction into a formal design brief. Identify 3-6 method slots that need to be filled
with concrete algorithmic choices. For each slot, list 2-3 candidate methods from the literature
with their provenance (which paper, which technique)."""

    return system, user


def design_gap_probe_prompt(
    brief: str,
    method_inventory: str = "",
    existing_papers_summary: str = "",
) -> tuple[str, str]:
    system = """\
You are a research gap analyst. Given a design brief and existing paper pool, identify
knowledge gaps that prevent confident algorithm design decisions.

For each gap, specify:
- Which method slot it blocks
- What type of gap (technique_unknown, performance_unclear, scalability_unknown, interaction_unclear)
- Severity (critical = blocks design, moderate = degrades quality, low = nice-to-know)
- A targeted search query to resolve it
- Paper IDs from the pool that might resolve it if deep-read

Output JSON:
{
  "knowledge_gaps": [{"slot": "...", "gap_type": "...", "severity": "...", "search_query": "...", "candidate_paper_ids": [...]}],
  "recommended_actions": ["search for X", "deep-read paper Y", ...],
  "deep_read_targets": [<paper_id>, ...]
}

Return ONLY valid JSON."""

    user = f"""\
## Design Brief
{brief}

## Method Inventory (from method_taxonomy)
{method_inventory if method_inventory else "(not available)"}

## Existing Papers Summary
{existing_papers_summary if existing_papers_summary else "(not available)"}

Identify knowledge gaps that prevent confident method slot decisions."""

    return system, user


def algorithm_candidate_generate_prompt(
    brief: str,
    method_inventory: str = "",
    gap_probe: str = "",
    deep_read_notes: str = "",
) -> tuple[str, str]:
    system = f"""\
You are a senior ML researcher designing novel algorithms for top-venue publication.
Generate 2-3 concrete algorithm candidates, each with provenance-tagged components.

{THEORY_CONSTRAINT_BLOCK}

For each candidate:
1. Give it a descriptive name
2. Describe the architecture end-to-end
3. List components with provenance tags:
   - "borrowed": taken directly from a published method (cite paper_id)
   - "modified": adapted from a published method with specific changes (cite paper_id + describe changes)
   - "novel": new design not found in existing literature
4. State what makes this candidate novel (novelty_statement)
5. Assess feasibility (compute, data requirements, implementation complexity)

The BEST candidate should have at least ONE "novel" component at the architecture level.
A candidate that is entirely "borrowed" components is NOT acceptable.

Output JSON:
{{
  "candidates": [
    {{
      "name": "...",
      "architecture_description": "...",
      "components": [{{"name": "...", "role": "...", "provenance_tag": "borrowed|modified|novel", "source_paper_id": <int|null>, "details": "..."}}],
      "novelty_statement": "...",
      "feasibility_notes": "..."
    }}
  ],
  "method_inventory_used": <count of methods referenced>
}}

Return ONLY valid JSON."""

    user = f"""\
## Design Brief
{brief}

## Method Inventory
{method_inventory if method_inventory else "(not available)"}

## Gap Analysis
{gap_probe if gap_probe else "(no gaps identified)"}

## Deep Reading Notes (relevant papers)
{deep_read_notes if deep_read_notes else "(none)"}

Generate 2-3 concrete algorithm candidates with provenance-tagged components."""

    return system, user


def originality_boundary_check_prompt(
    candidate: str,
    near_papers_summaries: str = "",
) -> tuple[str, str]:
    system = """\
You are a novelty evaluator for top-venue research. Your job is to determine whether
an algorithm candidate is genuinely novel or too similar to existing work.

Verdict options:
- "novel": Significant architectural/methodological innovation not found in prior art
- "incremental": Minor variation on existing work — publishable but weak contribution
- "too_similar": Nearly identical to an existing published method — will be rejected

For each near-match paper, specify:
- Overlap areas (what is shared)
- Differentiation (what is genuinely different)
- Novelty impact (how much the overlap reduces the contribution)

Score novelty from 0 to 1:
- 0.0-0.3: too_similar
- 0.3-0.6: incremental
- 0.6-1.0: novel

If the verdict is NOT "novel", provide specific recommended modifications
to increase novelty (concrete algorithmic changes, not vague suggestions).

Output JSON:
{
  "candidate_name": "...",
  "near_matches": [{"paper_id": <int>, "title": "...", "overlap_areas": [...], "differentiation": [...]}],
  "novelty_verdict": "novel|incremental|too_similar",
  "novelty_score": <float>,
  "recommended_modifications": ["..."]
}

Return ONLY valid JSON."""

    user = f"""\
## Algorithm Candidate
{candidate}

## Near-Match Papers (deep-read summaries)
{near_papers_summaries if near_papers_summaries else "(no near matches found — likely novel)"}

Evaluate the novelty of this candidate against existing published work."""

    return system, user


def algorithm_design_refine_prompt(
    candidate: str,
    originality_result: str = "",
    feedback: str = "",
    constraints: str = "",
) -> tuple[str, str]:
    system = f"""\
You are a senior researcher refining an algorithm design into a publication-ready proposal.
Integrate originality feedback to strengthen the novel contribution while maintaining feasibility.

{THEORY_CONSTRAINT_BLOCK}

Output a complete research proposal document:
{{
  "proposal_title": "...",
  "problem_formulation": "... (formal problem statement with notation)",
  "algorithm_description": "... (end-to-end algorithm with key equations, NO formal proofs)",
  "components": [{{"name": "...", "role": "...", "provenance_tag": "...", "source_paper_id": <int|null>, "details": "..."}}],
  "novelty_statement": "Unlike [prior work], our method [specific differentiator]...",
  "experiment_hooks": ["<what to test>", "...", "..."],
  "provenance_summary": [{{"component": "...", "origin": "novel|modified|borrowed", "source": "..."}}]
}}

Return ONLY valid JSON."""

    user = f"""\
## Current Best Candidate
{candidate}

## Originality Assessment
{originality_result if originality_result else "(not available)"}

## Refinement Feedback
{feedback if feedback else "(no specific feedback)"}

## Design Constraints
{constraints if constraints else "(none)"}

Refine this candidate into a publication-ready research proposal.
Address any novelty weaknesses identified in the originality assessment."""

    return system, user
