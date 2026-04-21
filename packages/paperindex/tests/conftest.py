from __future__ import annotations

from pathlib import Path

import fitz
import pytest


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    pages = [
        ("Sample Paper Title", "Abstract\nThis paper studies budget pacing and proposes a stable control policy."),
        ("Method", "Method\nWe optimize spend allocation with a constrained controller and staged updates."),
        ("Experiments", "Experiments\nWe compare against two baselines and improve efficiency by 12 percent."),
    ]
    for title, body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), title, fontsize=18)
        page.insert_text((72, 120), body, fontsize=11)
    doc.set_toc([
        [1, "Abstract", 1],
        [1, "Method", 2],
        [1, "Experiments", 3],
    ])
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def no_toc_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "no_toc.pdf"
    doc = fitz.open()
    pages = [
        (
            "No TOC Paper",
            "No TOC Paper\nAbstract\nThis paper studies budget pacing without embedded bookmarks.",
        ),
        (
            "Introduction",
            "1 Introduction\nWe study budget pacing with a controller and staged updates.",
        ),
        (
            "Method",
            "2 Method\nOur method uses constrained optimization and offline replay.",
        ),
    ]
    for title, body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), title, fontsize=18)
        page.insert_text((72, 120), body, fontsize=11)
    doc.save(path)
    doc.close()
    return path
