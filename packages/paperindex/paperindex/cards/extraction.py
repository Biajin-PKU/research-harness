from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from llm_router.client import (
    LLMClient,
    ResolvedLLMConfig,
    resolve_llm_config,
    resolve_route,
)
from ..types import SectionNode, SectionResult, StructureResult
from .schema import PaperCard


CARD_EXTRACTION_SECTIONS = (
    "summary",
    "methodology",
    "experiments",
    "equations",
    "limitations",
    "reproduction_notes",
)

_MAX_SECTION_CHARS = 4000
_MAX_PAGE_CHARS = 2500


def _extract_tables_from_pdf(
    pdf_path: str, page_numbers: list[int] | None = None
) -> str:
    """Extract tables from PDF using pdfplumber for better structured data.

    Falls back to empty string if pdfplumber not available or no tables found.
    """
    try:
        import pdfplumber
    except ImportError:
        return ""

    tables_text = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_to_check = page_numbers if page_numbers else range(len(pdf.pages))

            for page_idx in pages_to_check:
                if page_idx >= len(pdf.pages):
                    continue
                page = pdf.pages[page_idx]
                tables = page.extract_tables()

                for table_idx, table in enumerate(tables):
                    if not table:
                        continue
                    # Convert table to CSV format
                    csv_lines = []
                    for row in table:
                        # Clean cell content
                        cleaned_cells = []
                        for cell in row:
                            if cell is None:
                                cleaned_cells.append("")
                            else:
                                # Remove newlines and extra spaces
                                cell_str = str(cell).replace("\n", " ").strip()
                                cleaned_cells.append(cell_str)
                        csv_lines.append(", ".join(cleaned_cells))

                    if csv_lines:
                        tables_text.append(
                            f"<!-- Table {table_idx + 1} on Page {page_idx + 1} -->\n"
                            + "\n".join(csv_lines)
                        )
    except Exception:
        # Silently fail if table extraction doesn't work
        pass

    return "\n\n".join(tables_text)


def _resolve_required_llm_config(
    llm_config: dict[str, Any] | None = None,
) -> ResolvedLLMConfig:
    config = resolve_llm_config(llm_config)
    # CLI providers (cursor_agent, codex) don't need api_key
    cli_providers = {"cursor_agent", "codex"}
    if config.provider not in cli_providers and (
        not config.api_key or not config.model
    ):
        raise RuntimeError("paper card extraction requires a configured LLM provider")
    return config


def _parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if not candidate:
        raise RuntimeError("LLM returned empty response for paper card extraction")

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```json\s*(\{.*\})\s*```", candidate, re.DOTALL)
    if fenced:
        parsed = json.loads(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    inline = re.search(r"\{.*\}", candidate, re.DOTALL)
    if inline:
        parsed = json.loads(inline.group(0))
        if isinstance(parsed, dict):
            return parsed

    raise RuntimeError("LLM response was not valid JSON for paper card extraction")


def _flatten_tree(nodes: list[SectionNode], depth: int = 1) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.append(f"{depth}. {node.title} [pages {node.start_page}-{node.end_page}]")
        if node.children:
            lines.extend(_flatten_tree(node.children, depth + 1))
    return lines


def _clip(text: str, limit: int) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rsplit(" ", 1)[0].strip() + "..."


def _section_payload(sections: list[SectionResult], pdf_path: str | None = None) -> str:
    blocks = []
    for section in sections:
        if not section.content.strip():
            continue
        content = section.content

        # For experiments section, try to extract structured tables
        if section.section == "experiments" and pdf_path:
            # Get page numbers for experiments section (estimate from content position)
            # This is approximate - ideally we'd track page numbers per section
            tables_text = _extract_tables_from_pdf(pdf_path)
            if tables_text:
                # Prepend structured tables to the content
                content = (
                    "[STRUCTURED TABLES FROM PDF]\n"
                    + tables_text
                    + "\n\n[RAW TEXT]\n"
                    + content
                )

        if section.section == "experiments" and len(content) > _MAX_SECTION_CHARS:
            # Smart truncation: keep beginning + any table/result sections
            head_len = 1500
            tail = content[head_len:]
            # Find table/result sections
            table_keywords = [
                "Table 1",
                "Table 2",
                "Result",
                "Rev",
                "Conv",
                "CPC",
                "improvement",
                "%",
            ]
            found_sections = []
            for kw in table_keywords:
                idx = tail.find(kw)
                if idx != -1:
                    # Extract context around keyword
                    start = max(0, idx - 200)
                    end = min(len(tail), idx + 800)
                    found_sections.append(tail[start:end])
            if found_sections:
                content = content[:head_len] + "\n...\n" + "\n".join(found_sections[:2])
            else:
                content = _clip(content, _MAX_SECTION_CHARS)
        else:
            content = _clip(content, _MAX_SECTION_CHARS)
        blocks.append(f"[{section.section}]\n{content}")
    return "\n\n".join(blocks)


CARD_PROMPT_TEMPLATE = """You are extracting a structured academic paper card from a PDF.

Requirements:
- Use ONLY the provided PDF-derived content.
- Return ONLY one JSON object. No markdown, no explanation.
- Populate fields only when supported by the text. Use null for unknown scalars and [] for unknown lists.
- Do not invent citations, authors, venue, metrics, or results.
- `method_family` must be one of [\"learning_based\", \"optimization_based\", \"probabilistic\", \"game_theoretic\", \"heuristic\"] or null.
- `reproducibility_score` must be one of [\"high\", \"medium\", \"low\", \"unknown\"] or null.
- `evidence` must be a list of objects with: `section`, `confidence`, `snippet`.
- `structured_results` must be a list of objects with: `metric`, `value`, `baseline`, `delta`.
- `mathematical_formulation` must be either null or an object with: `objective`, `constraints`, `key_equations`.

CRITICAL METADATA EXTRACTION RULES - FOLLOW STRICTLY:
1. `title`: Extract the EXACT title from the first page. Do NOT normalize or rewrite. Copy it verbatim.
2. `venue`: Look for conference/journal name in the first page header/footer. Examples: "KDD '24", "ICML 2023", "NeurIPS", "arXiv:XXXX.XXXXX", "WWW 2024". Extract the FULL venue name including year if present.
3. `year`: Look for publication year in the first page (often in copyright, footer, or venue line). Use 4-digit format like "2024". If venue includes year (e.g., "KDD '24"), extract year separately as "2024".
4. `source_url`: Look for DOI (e.g., "https://doi.org/10.1145/...") or arXiv URL (e.g., "https://arxiv.org/abs/XXXX.XXXXX") on the first page. If found, include the full URL.
5. `authors`: Extract author names from the first page, typically below the title. Include full names as they appear.

CRITICAL STRUCTURED_RESULTS EXTRACTION RULES:
- `structured_results` must contain EVERY quantitative result with explicit numeric values from the experiments/results sections.
- Scan the provided section text for tables, figures, and sentences containing metrics like: accuracy, precision, recall, F1, CTR, ROI, revenue, conversion rate, latency, throughput, AUC, RMSE, etc.
- For EACH quantitative finding, emit one structured_results entry with these fields:
  - `metric`: the metric name (e.g., "CTR", "ROI", "Accuracy", "Revenue")
  - `value`: the numerical result with unit/% if present (e.g., "8.7%", "1.45", "+12.4%")
  - `baseline`: the comparison baseline method if mentioned (e.g., "DQN", "rule-based", "previous approach")
  - `delta`: the improvement/difference if stated (e.g., "+8.7%", "-5.2ms")
- Examples of text patterns to convert:
  - "CTR improved by 8.7% over rule-based" → {{"metric": "CTR", "value": "+8.7%", "baseline": "rule-based", "delta": "+8.7%"}}
  - "achieved 1.45 ROI compared to 1.19 for DQN" → {{"metric": "ROI", "value": "1.45", "baseline": "DQN", "delta": null}}
  - "latency reduced to 23ms from 45ms" → {{"metric": "latency", "value": "23ms", "baseline": "45ms", "delta": "-22ms"}}
- Do NOT leave structured_results empty if the paper contains ANY experimental results with numbers. Extract at least 1-5 entries for papers with experiments.

Return this schema exactly:
{{
  "title": string|null,
  "authors": string[],
  "venue": string|null,
  "year": string|null,
  "source_url": string|null,
  "artifact_links": string[],
  "domain_tags": string[],
  "technical_tags": string[],
  "motivation": string|null,
  "problem_definition": string|null,
  "application_scenarios": string[],
  "core_idea": string|null,
  "method_summary": string|null,
  "method_pipeline": string[],
  "method_family": string|null,
  "method_tags": string[],
  "algorithmic_view": string|null,
  "mathematical_formulation": object|null,
  "contributions": string[],
  "related_work_positioning": string|null,
  "key_references": string[],
  "assumptions": string[],
  "limitations": string[],
  "future_directions": string|null,
  "tasks": string[],
  "datasets": string[],
  "metrics": string[],
  "baselines": string[],
  "key_results": string[],
  "structured_results": object[],
  "ablation_focus": string[],
  "efficiency_signals": string[],
  "code_url": string|null,
  "reproduction_notes": string|null,
  "reproducibility_score": string|null,
  "evidence": object[]
}}

MANDATORY: Search the experiments/results sections below for ANY tables or sentences containing numeric results (percentages, absolute values, metric comparisons). You MUST extract at least 1-3 quantitative results into structured_results if ANY experimental data exists. DO NOT leave structured_results empty if the paper contains tables, figures, or sentences with numerical comparisons.

ARTIFACT_LINKS FILTERING: Only include links that are directly related to the paper itself:
- GitHub repositories with paper code
- Official project websites
- Dataset repositories
- DOI links
- arXiv pages
- Publisher pages
DO NOT include: product homepages, dashboard links, marketing sites, unrelated blog posts.

Paper title candidate: {title}
PDF section structure:
{structure_lines}

First page text (EXTRACT METADATA FROM HERE - venue, year, source_url, authors, exact title):
{first_page_text}

Selected extracted section text:
{section_payload}
"""


def build_paper_card(
    structure: StructureResult,
    sections: list[SectionResult],
    llm_config: dict[str, Any] | None = None,
    pdf_path: str | None = None,
) -> PaperCard:
    # Paper card extraction: medium tier (override via LLM_ROUTE_MEDIUM env).
    prov, model = resolve_route("medium")
    config = resolve_llm_config(
        {"provider": prov, "model": model, **(llm_config or {})}
    )
    client = LLMClient(config)

    structure_lines = (
        "\n".join(_flatten_tree(structure.tree)) or "(no extracted structure)"
    )
    first_page_text = _clip(
        str((structure.raw.get("pages_text") or [""])[0]), _MAX_PAGE_CHARS
    )
    section_payload_text = (
        _section_payload(sections, pdf_path) or "(no extracted sections)"
    )
    prompt = CARD_PROMPT_TEMPLATE.format(
        title=str(structure.raw.get("title") or structure.doc_name),
        structure_lines=structure_lines,
        first_page_text=first_page_text,
        section_payload=section_payload_text,
    )
    raw = client.chat(prompt, temperature=0.0)
    payload = _parse_json_object(raw)

    payload.setdefault(
        "paper_id", hashlib.sha1(structure.pdf_hash.encode("utf-8")).hexdigest()[:16]
    )
    payload.setdefault("title", structure.raw.get("title") or structure.doc_name)
    payload["pdf_path"] = structure.doc_name

    return PaperCard.from_dict(payload)


def extract_paper_card(pdf_path: str, llm_config: dict | None = None) -> PaperCard:
    from ..indexer import PaperIndexer

    indexer = PaperIndexer(llm_config=llm_config)
    structure = indexer.extract_structure(pdf_path)
    sections = [
        indexer.extract_section(structure, name) for name in CARD_EXTRACTION_SECTIONS
    ]
    return indexer.build_card(structure, sections, pdf_path=pdf_path)
