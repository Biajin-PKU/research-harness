from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import fitz

from ..llm.client import LLMClient, resolve_llm_config
from ..types import SectionNode
from ..utils import assign_node_ids, first_nonempty_line


def extract_structure_tree(pdf_path: str | Path, llm_config: dict[str, Any] | None = None) -> tuple[list[SectionNode], dict]:
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)
    try:
        page_count = doc.page_count
        pages_text = [page.get_text("text") or "" for page in doc]
        toc = doc.get_toc(simple=True)
        if toc:
            tree = _build_tree_from_toc(toc, page_count)
            source = "toc"
        else:
            tree = _build_tree_with_llm(pdf_path, pages_text, page_count, llm_config)
            source = "llm"
        assign_node_ids(tree)
        title = first_nonempty_line(pages_text[0]) if pages_text else pdf_path.stem
        raw = {
            "source": source,
            "page_count": page_count,
            "title": title or pdf_path.stem,
            "pages_text": pages_text,
            "toc": toc,
        }
        return tree, raw
    finally:
        doc.close()



def _build_tree_from_toc(toc: list[list], page_count: int) -> list[SectionNode]:
    roots: list[SectionNode] = []
    stack: list[tuple[int, SectionNode]] = []
    for level, title, start_page in toc:
        node = SectionNode(
            title=str(title).strip(),
            start_page=max(1, int(start_page or 1)),
            end_page=max(1, int(start_page or 1)),
        )
        while stack and stack[-1][0] >= int(level):
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((int(level), node))
    _fill_page_ranges(roots, page_count)
    return roots



def _build_tree_with_llm(
    pdf_path: Path,
    pages_text: list[str],
    page_count: int,
    llm_config: dict[str, Any] | None,
) -> list[SectionNode]:
    config = resolve_llm_config(llm_config)
    # CLI providers (cursor_agent, codex) authenticate out-of-band; no api_key in env.
    _cli_llm_providers = frozenset({"cursor_agent", "codex"})
    if config.provider not in _cli_llm_providers and (not config.api_key or not config.model):
        raise RuntimeError(
            "PDF has no embedded table of contents; LLM-backed section structure extraction requires a configured LLM provider "
            "(API key for OpenAI/Anthropic/Kimi, or set CURSOR_AGENT_ENABLED=1 / CODEX_ENABLED=1 for CLI providers)"
        )

    page_blocks = []
    for page_no, text in enumerate(pages_text, start=1):
        page_blocks.append(f"[Page {page_no}]\n{_page_preview(text)}")

    prompt = f"""You are extracting the section structure of a paper PDF that does not contain an embedded table of contents.
Use ONLY the provided page text snippets. Infer the major section headings and their start pages.
Return ONLY JSON in this shape:
{{"sections": [{{"title": "Introduction", "start_page": 1}}, {{"title": "Method", "start_page": 3}}]}}
Rules:
- Include only real section headings that are supported by the text.
- Keep the list ordered by start_page.
- Use 1-based page numbers between 1 and {page_count}.
- Do not invent subsections unless the heading is clearly visible in the text.
- If the first page is abstract/title material, it is acceptable to include "Abstract" as a section.

File: {pdf_path.name}

Page snippets:
{chr(10).join(page_blocks)}
"""
    raw = LLMClient(config).chat(prompt, temperature=0.0)
    payload = _parse_json_object(raw)
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        raise RuntimeError("LLM did not return a valid section structure")

    nodes: list[SectionNode] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        start_page = _coerce_page(item.get("start_page"), page_count)
        if not title or start_page is None:
            continue
        nodes.append(SectionNode(title=title, start_page=start_page, end_page=start_page))

    if not nodes:
        raise RuntimeError("LLM section structure response did not contain usable sections")

    nodes.sort(key=lambda node: (node.start_page, node.title.lower()))
    deduped: list[SectionNode] = []
    seen: set[tuple[str, int]] = set()
    for node in nodes:
        key = (node.title.lower(), node.start_page)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(node)

    _fill_page_ranges(deduped, page_count)
    return deduped



def _page_preview(text: str, max_lines: int = 16, max_chars: int = 2200) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    preview = "\n".join(lines[:max_lines]).strip()
    if len(preview) > max_chars:
        return preview[:max_chars].rsplit(" ", 1)[0].strip() + "..."
    return preview



def _parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```json\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    inline = re.search(r"\{.*\}", candidate, re.DOTALL)
    if inline:
        raw_json = inline.group(0)
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        # Try json_repair as last resort for LLM-generated malformed JSON
        try:
            import json_repair  # type: ignore[import]
            repaired = json_repair.repair_json(raw_json)
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    raise RuntimeError("LLM response was not valid JSON for section structure extraction")



def _coerce_page(value: Any, page_count: int) -> int | None:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return min(max(page, 1), max(page_count, 1))



def _fill_page_ranges(nodes: list[SectionNode], parent_end: int) -> None:
    for index, node in enumerate(nodes):
        sibling_end = nodes[index + 1].start_page - 1 if index + 1 < len(nodes) else parent_end
        sibling_end = max(node.start_page, sibling_end)
        if node.children:
            _fill_page_ranges(node.children, sibling_end)
            node.end_page = max(sibling_end, node.children[-1].end_page)
        else:
            node.end_page = sibling_end
