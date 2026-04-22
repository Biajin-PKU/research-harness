from __future__ import annotations

from pathlib import Path
from typing import Any

from ..indexing.section_text import normalize_section_title
from ..types import SectionResult, StructureResult
from ..utils import flatten_nodes

SECTION_KEYWORDS = {
    "summary": ("abstract", "introduction", "conclusion", "summary"),
    "methodology": ("method", "approach", "framework", "model", "architecture"),
    "experiments": ("experiment", "evaluation", "result", "benchmark", "ablation"),
    "equations": ("equation", "preliminar", "theorem", "proof", "objective"),
    "limitations": ("limitation", "discussion", "conclusion", "failure"),
    "reproduction_notes": (
        "implementation",
        "training",
        "dataset",
        "hyperparameter",
        "setup",
    ),
}


def extract_section_content(
    structure: StructureResult,
    section: str,
    llm_config: dict[str, Any] | None = None,
    pdf_path: str | Path | None = None,
) -> SectionResult:
    del pdf_path
    keywords = SECTION_KEYWORDS[section]
    matches = []
    for node in flatten_nodes(structure.tree):
        normalized = normalize_section_title(node.title)
        if any(keyword in normalized for keyword in keywords):
            matches.append(node)
    if not matches and structure.tree:
        matches = flatten_nodes(structure.tree)[:1]

    # For experiments section, also include next sibling section's content
    # to catch tables/results that may span pages beyond TOC bounds
    extra_text = ""
    if section == "experiments" and matches and structure.raw.get("pages_text"):
        pages_text = structure.raw.get("pages_text", [])
        last_match = matches[-1]
        # Include one more page after the section's end_page if available
        if last_match.end_page < len(pages_text):
            extra_page_idx = (
                last_match.end_page
            )  # end_page is 1-based, so this is next page
            if extra_page_idx < len(pages_text):
                extra_text = "\n\n" + pages_text[extra_page_idx]

    content = "\n\n".join(
        node.section_text.strip() for node in matches if node.section_text.strip()
    )
    content = (content + extra_text).strip()
    if not content:
        content = "\n\n".join(node.title for node in matches)
    confidence = 0.9 if matches else 0.2
    model_used = (llm_config or {}).get("model", "")
    return SectionResult(
        section=section,
        content=content.strip(),
        confidence=confidence,
        extractor_version="rule-based-v0",
        source_pdf_hash=structure.pdf_hash,
        model_used=model_used,
    )
