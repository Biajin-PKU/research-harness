import os
from pathlib import Path

import fitz
import pytest

from paperindex import PaperIndexer

pytestmark = pytest.mark.skipif(
    not (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CURSOR_AGENT_ENABLED")
        or os.getenv("CODEX_ENABLED")
    ),
    reason="Requires an LLM provider (OPENAI_API_KEY / ANTHROPIC_API_KEY / CURSOR_AGENT_ENABLED / CODEX_ENABLED)",
)


def _make_no_toc_pdf(path: Path) -> Path:
    doc = fitz.open()
    pages = [
        (
            "Sample Paper Title",
            "This paper studies budget pacing and proposes a stable control policy.",
        ),
        (
            "1 Method",
            "We optimize spend allocation with a constrained controller and staged updates.",
        ),
        (
            "2 Experiments",
            "We compare against two baselines and improve efficiency by 12 percent.",
        ),
    ]
    for title, body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), title, fontsize=18)
        page.insert_text((72, 120), body, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_layout_fallback_prefers_heading_lines(tmp_path: Path):
    pdf_path = _make_no_toc_pdf(tmp_path / "layout_only.pdf")
    result = PaperIndexer().extract_structure(pdf_path)
    titles = [node.title for node in result.tree]
    assert result.raw["source"] == "llm"
    assert any("Method" in title for title in titles)
    assert any("Experiments" in title for title in titles)
