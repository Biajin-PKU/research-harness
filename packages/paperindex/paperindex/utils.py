from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

from .types import SectionNode


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def flatten_nodes(tree: Iterable[SectionNode]) -> list[SectionNode]:
    nodes: list[SectionNode] = []
    for node in tree:
        nodes.append(node)
        nodes.extend(flatten_nodes(node.children))
    return nodes


def assign_node_ids(tree: list[SectionNode]) -> None:
    for index, node in enumerate(flatten_nodes(tree)):
        node.node_id = f"{index:04d}"


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def summarize_text(text: str, max_sentences: int = 2, max_chars: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    summary = " ".join(part.strip() for part in parts[:max_sentences] if part.strip())
    if not summary:
        summary = cleaned
    return summary[:max_chars].strip()
