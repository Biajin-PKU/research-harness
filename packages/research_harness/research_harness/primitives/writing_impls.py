"""Writing pipeline primitive implementations — Sprint 4.

outline_generate (LLM), section_review (LLM + deterministic), section_revise (LLM),
latex_compile (non-LLM).

LLM primitives use stub implementations that return placeholder output.
Real LLM calls are dispatched by execution/llm_primitives.py (same pattern as
code_generate from Sprint 2).
"""

from __future__ import annotations

import logging
from typing import Any

from ..execution.latex_compiler import assemble_latex, compile_latex
from ..execution.writing_checks import REVIEW_DIMENSIONS, run_all_checks
from .registry import (
    LATEX_COMPILE_SPEC,
    OUTLINE_GENERATE_SPEC,
    PAPER_FINALIZE_SPEC,
    SECTION_REVIEW_SPEC,
    SECTION_REVISE_SPEC,
    register_primitive,
)
from .types import (
    DeterministicCheck,
    LatexCompileOutput,
    OutlineGenerateOutput,
    OutlineSectionItem,
    PaperFinalizeOutput,
    ReviewDimension,
    SectionReviewOutput,
    SectionReviseOutput,
)

logger = logging.getLogger(__name__)


@register_primitive(OUTLINE_GENERATE_SPEC)
def outline_generate(
    *,
    topic_id: int,
    project_id: int,
    template: str = "neurips",
    **_: Any,
) -> OutlineGenerateOutput:
    """Generate paper outline. Stub — real LLM call dispatched by harness."""
    # Default outline structure with word targets
    default_sections = [
        OutlineSectionItem(section="introduction", title="Introduction", target_words=900),
        OutlineSectionItem(section="related_work", title="Related Work", target_words=800),
        OutlineSectionItem(section="method", title="Method", target_words=1500),
        OutlineSectionItem(section="experiments", title="Experiments", target_words=1200),
        OutlineSectionItem(section="results", title="Results", target_words=800),
        OutlineSectionItem(section="discussion", title="Discussion", target_words=600),
        OutlineSectionItem(section="conclusion", title="Conclusion", target_words=300),
    ]
    total = sum(s.target_words for s in default_sections)

    return OutlineGenerateOutput(
        title="",
        abstract_draft="",
        sections=default_sections,
        total_target_words=total,
        model_used="stub",
    )


@register_primitive(SECTION_REVIEW_SPEC)
def section_review(
    *,
    section: str,
    content: str,
    target_words: int = 0,
    **_: Any,
) -> SectionReviewOutput:
    """Review a paper section: deterministic checks + LLM scoring stub.

    The deterministic checks (AI boilerplate, weasel words, word count,
    repetition, structure) run immediately. LLM-based 10-dim scoring
    is dispatched by the harness and merged later.
    """
    # Run deterministic checks
    check_results = run_all_checks(content, section, target_words)

    deterministic_checks = [
        DeterministicCheck(
            check_name=c.check_name,
            passed=c.passed,
            details=c.details,
            items_found=c.items_found,
        )
        for c in check_results
    ]

    # Stub LLM dimensions (all 0.0 — real scores filled by harness)
    dimensions = [
        ReviewDimension(dimension=dim, score=0.0, comment="")
        for dim in REVIEW_DIMENSIONS
    ]

    # Determine if revision needed based on deterministic checks
    failed_checks = [c for c in check_results if not c.passed]
    suggestions = [c.details for c in failed_checks]

    return SectionReviewOutput(
        section=section,
        overall_score=0.0,
        dimensions=dimensions,
        deterministic_checks=deterministic_checks,
        suggestions=suggestions,
        needs_revision=len(failed_checks) > 0,
        model_used="deterministic_only",
    )


@register_primitive(SECTION_REVISE_SPEC)
def section_revise(
    *,
    section: str,
    content: str,
    review_feedback: str,
    target_words: int = 0,
    **_: Any,
) -> SectionReviseOutput:
    """Revise a paper section based on review feedback. Stub — real LLM call dispatched."""
    return SectionReviseOutput(
        section=section,
        revised_content=content,  # pass-through in stub mode
        changes_made=["Stub: no LLM revision applied"],
        word_count=len(content.split()),
        model_used="stub",
    )


@register_primitive(LATEX_COMPILE_SPEC)
def latex_compile(
    *,
    project_id: int,
    output_dir: str,
    template: str = "generic",
    sections: dict[str, str] | None = None,
    title: str = "",
    authors: list[str] | None = None,
    abstract: str = "",
    bibliography_entries: list[str] | None = None,
    **_: Any,
) -> LatexCompileOutput:
    """Assemble and compile LaTeX paper."""
    sections = sections or {}
    authors = authors or []

    tex_content, bib_content = assemble_latex(
        title=title,
        authors=authors,
        abstract=abstract,
        sections=sections,
        bibliography_entries=bibliography_entries,
        template=template,
    )

    result = compile_latex(tex_content, bib_content, output_dir)

    return LatexCompileOutput(
        success=result.success,
        pdf_path=result.pdf_path,
        log_summary=result.log_summary,
        warnings=result.warnings,
        errors=result.errors,
        pages=result.pages,
        auto_fixes_applied=result.auto_fixes,
    )


@register_primitive(PAPER_FINALIZE_SPEC)
def paper_finalize(
    *,
    project_id: int,
    output_dir: str,
    title: str = "",
    authors: list[str] | None = None,
    abstract: str = "",
    sections: dict[str, str] | None = None,
    bibliography_entries: list[str] | None = None,
    template: str = "arxiv",
    **_: Any,
) -> PaperFinalizeOutput:
    """One-shot assemble + compile: sections dict → .tex → .pdf.

    Defaults to ``arxiv`` template (single-column, self-contained). Uses pdflatex
    if available, otherwise tectonic. Returns the generated file paths.
    """
    sections = sections or {}
    authors = authors or []

    tex_content, bib_content = assemble_latex(
        title=title,
        authors=authors,
        abstract=abstract,
        sections=sections,
        bibliography_entries=bibliography_entries,
        template=template,
    )

    result = compile_latex(tex_content, bib_content, output_dir)

    from pathlib import Path as _Path
    tex_path = str(_Path(output_dir) / "paper.tex")
    bib_path = str(_Path(output_dir) / "references.bib") if bib_content else ""

    return PaperFinalizeOutput(
        success=result.success,
        tex_path=tex_path,
        bib_path=bib_path,
        pdf_path=result.pdf_path,
        pages=result.pages,
        word_count=sum(len(v.split()) for v in sections.values()),
        sections_assembled=len(sections),
        warnings=result.warnings,
        errors=result.errors,
        auto_fixes_applied=result.auto_fixes,
        template_used=template,
        validation_errors=sum(1 for f in result.validation_findings if f.level == "error"),
        validation_warnings=sum(1 for f in result.validation_findings if f.level == "warning"),
    )
