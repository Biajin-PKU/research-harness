from __future__ import annotations

from ..types import SectionNode


def structure_to_markdown_outline(tree: list[SectionNode]) -> str:
    lines: list[str] = []

    def visit(nodes: list[SectionNode], depth: int) -> None:
        for node in nodes:
            indent = "  " * max(depth - 1, 0)
            lines.append(f"{indent}- {node.title} ({node.start_page}-{node.end_page})")
            visit(node.children, depth + 1)

    visit(tree, 1)
    return "\n".join(lines)
