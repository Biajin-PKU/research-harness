from __future__ import annotations

import re

from ..types import SectionNode
from ..utils import flatten_nodes, summarize_text


def normalize_section_title(title: str) -> str:
    text = re.sub(r"\*+", "", str(title or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\s*(?:appendix|chapter|section)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*[A-Za-z]?(?:\d+(?:\.\d+)*)[:.\-\s]+", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def titles_match(left: str, right: str) -> bool:
    left_norm = normalize_section_title(left)
    right_norm = normalize_section_title(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    shorter, longer = sorted((left_norm, right_norm), key=len)
    return len(shorter) >= 6 and shorter in longer


def attach_section_text(
    tree: list[SectionNode], pages_text: list[str]
) -> list[SectionNode]:
    for node in flatten_nodes(tree):
        start = max(1, node.start_page)
        end = max(start, node.end_page)
        chunk = "\n".join(
            pages_text[index - 1]
            for index in range(start, min(end, len(pages_text)) + 1)
            if 0 < index <= len(pages_text)
        )
        node.section_text = _trim_page_span_text(chunk, node.title)
        node.summary = _build_node_summary(node.title, node.section_text)
    return tree


def _trim_page_span_text(text: str, title: str) -> str:
    normalized_title = normalize_section_title(title)
    if not normalized_title:
        return text.strip()
    lines = [line for line in text.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        normalized_line = normalize_section_title(line)
        if titles_match(title, line) or (
            normalized_title and normalized_title in normalized_line
        ):
            return "\n".join(lines[idx:]).strip()
    return text.strip()


def _build_node_summary(title: str, text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    filtered: list[str] = []
    for line in lines:
        if titles_match(title, line):
            continue
        filtered.append(line)
    return summarize_text(" ".join(filtered) or text)
