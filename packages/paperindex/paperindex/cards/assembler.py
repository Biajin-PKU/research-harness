from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..types import SectionResult, StructureResult
from .schema import EvidenceEntry, PaperCard


_MAX_TEXT_FIELD_CHARS = 1200
_MAX_SNIPPET_CHARS = 300
_METRIC_HINTS = (
    "accuracy",
    "auc",
    "f1",
    "precision",
    "recall",
    "rmse",
    "mae",
    "mse",
    "ndcg",
    "map",
    "ctr",
    "cvr",
    "cpc",
    "cpa",
    "roi",
    "revenue",
    "cost",
    "latency",
    "throughput",
)
_METHOD_KEYWORDS = {
    "learning_based": (
        "learn",
        "training",
        "neural",
        "transformer",
        "reinforcement learning",
        "gradient",
    ),
    "optimization_based": (
        "optimiz",
        "objective",
        "constraint",
        "programming",
        "lagrangian",
        "sinkhorn",
    ),
    "probabilistic": ("probabil", "bayes", "posterior", "likelihood", "stochastic"),
    "game_theoretic": ("auction", "equilibrium", "nash", "game theoretic", "mechanism"),
    "heuristic": ("heuristic", "greedy", "rule-based", "search strategy"),
}
_DOMAIN_TAGS = {
    "advertising": "online advertising",
    "auction": "auction systems",
    "budget": "budget management",
    "marketing": "marketing",
    "recommendation": "recommendation systems",
    "retrieval": "information retrieval",
}
_TECHNICAL_TAGS = (
    "reinforcement learning",
    "optimal transport",
    "sinkhorn",
    "causal",
    "transformer",
    "diffusion",
    "bayesian",
    "game theory",
    "auction design",
    "linear programming",
)


def _content_for(section_map: dict[str, SectionResult], name: str) -> str:
    return section_map.get(name, SectionResult(name, "")).content


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "")).strip(" -\t")


def _clean_text(text: str) -> str:
    lines = [_clean_line(line) for line in str(text or "").splitlines()]
    kept: list[str] = []
    for line in lines:
        if not line:
            continue
        if re.fullmatch(r"[A-Za-z]?\d+(?:\.\d+)*", line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _split_sentences(text: str) -> list[str]:
    normalized = _clean_text(text)
    if not normalized:
        return []
    collapsed = normalized.replace("\n", " ")
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", collapsed)
    return [_clean_line(part) for part in parts if _clean_line(part)]


def _dedupe(items: list[str], *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = re.sub(r"\s+", " ", item).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(item.strip())
        if limit is not None and len(result) >= limit:
            break
    return result


def _truncate(text: str, limit: int = _MAX_TEXT_FIELD_CHARS) -> str:
    clean = _clean_line(text)
    if len(clean) <= limit:
        return clean
    clipped = clean[: limit - 3].rsplit(" ", 1)[0].strip()
    return (clipped or clean[: limit - 3]).strip() + "..."


def _first_sentences(text: str, *, limit: int = 2, min_chars: int = 30) -> str | None:
    sentences = [
        sentence for sentence in _split_sentences(text) if len(sentence) >= min_chars
    ]
    if not sentences:
        return None
    return _truncate(" ".join(sentences[:limit]))


def _best_sentences(
    text: str,
    *,
    limit: int = 3,
    min_chars: int = 30,
    preferred_terms: tuple[str, ...] = (),
) -> list[str]:
    preferred_terms = tuple(term.lower() for term in preferred_terms)
    ranked: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(_split_sentences(text)):
        lowered = sentence.lower()
        if len(sentence) < min_chars:
            continue
        score = 0
        if any(term in lowered for term in preferred_terms):
            score += 3
        if re.search(r"[-+]?\d+(?:\.\d+)?\s*(?:%|x|ms|s|sec|seconds?)", lowered):
            score += 2
        if any(
            token in lowered
            for token in (
                "improv",
                "outperform",
                "better",
                "worse",
                "baseline",
                "result",
            )
        ):
            score += 2
        ranked.append((score, -index, sentence))
    ranked.sort(reverse=True)
    if not ranked:
        return []
    selected = [item[2] for item in ranked[:limit]]
    return _dedupe([_truncate(item) for item in selected], limit=limit)


def _list_from_text(
    text: str,
    *,
    limit: int = 5,
    min_chars: int = 8,
    preferred_terms: tuple[str, ...] = (),
) -> list[str]:
    bullets = []
    for raw_line in _clean_text(text).splitlines():
        line = raw_line.lstrip("*- ").strip()
        if len(line) >= min_chars:
            bullets.append(_truncate(line))
    if bullets:
        preferred = _best_sentences(
            "\n".join(bullets),
            limit=limit,
            min_chars=min_chars,
            preferred_terms=preferred_terms,
        )
        return preferred or _dedupe(bullets, limit=limit)
    return _best_sentences(
        text, limit=limit, min_chars=min_chars, preferred_terms=preferred_terms
    )


def _extract_title(structure: StructureResult) -> str:
    title = str(structure.raw.get("title") or Path(structure.doc_name).stem).strip()
    return title or Path(structure.doc_name).stem


def _infer_method_family(*texts: str) -> str | None:
    joined = " ".join(texts).lower()
    for family, keywords in _METHOD_KEYWORDS.items():
        if any(keyword in joined for keyword in keywords):
            return family
    return None


def _extract_tagged_terms(
    text: str, candidates: tuple[str, ...], *, limit: int = 6
) -> list[str]:
    lowered = text.lower()
    matches = [candidate for candidate in candidates if candidate in lowered]
    return _dedupe(matches, limit=limit)


def _extract_domain_tags(text: str) -> list[str]:
    lowered = text.lower()
    matches = [tag for key, tag in _DOMAIN_TAGS.items() if key in lowered]
    return _dedupe(matches, limit=5)


def _extract_metrics(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for hint in _METRIC_HINTS:
        if hint in lowered:
            found.append(hint.upper() if hint.isalpha() and len(hint) <= 4 else hint)
    return _dedupe(found, limit=6)


def _extract_baselines(text: str) -> list[str]:
    candidates = []
    for sentence in _split_sentences(text):
        lowered = sentence.lower()
        if "baseline" not in lowered and "compare" not in lowered:
            continue
        parts = re.split(r"[,;]|(?:\band\b)", sentence)
        for part in parts:
            cleaned = _clean_line(part)
            if not cleaned or len(cleaned.split()) > 10:
                continue
            candidates.append(cleaned)
    return _dedupe(candidates, limit=5)


def _extract_year(text: str) -> str | None:
    match = re.search(r"\b(?:19|20)\d{2}\b", text)
    return match.group(0) if match else None


def build_card_snapshot(
    structure: StructureResult, sections: list[SectionResult]
) -> PaperCard:
    title = _extract_title(structure)
    section_map = {item.section: item for item in sections}

    summary = _content_for(section_map, "summary")
    methodology = _content_for(section_map, "methodology")
    experiments = _content_for(section_map, "experiments")
    equations = _content_for(section_map, "equations")
    limitations = _content_for(section_map, "limitations")
    reproduction_notes = _content_for(section_map, "reproduction_notes")
    first_page = str((structure.raw.get("pages_text") or [""])[0])
    combined_text = "\n".join(
        [
            title,
            first_page,
            summary,
            methodology,
            experiments,
            equations,
            limitations,
            reproduction_notes,
        ]
    )

    motivation = _best_sentences(
        summary,
        limit=2,
        preferred_terms=(
            "however",
            "motivat",
            "challenge",
            "problem",
            "existing",
            "prior",
        ),
    )
    problem_definition = _best_sentences(
        summary + "\n" + methodology,
        limit=2,
        preferred_terms=("we study", "problem", "formulate", "objective", "constraint"),
    )

    return PaperCard(
        paper_id=hashlib.sha1(structure.pdf_hash.encode("utf-8")).hexdigest()[:16],
        title=title,
        pdf_path=structure.doc_name,
        year=_extract_year(first_page),
        core_idea=_first_sentences(summary, limit=3, min_chars=20),
        motivation=" ".join(motivation) or None,
        problem_definition=" ".join(problem_definition) or None,
        method_summary=_first_sentences(methodology, limit=3, min_chars=20),
        method_pipeline=_list_from_text(
            methodology,
            limit=5,
            preferred_terms=("first", "then", "next", "finally", "step", "algorithm"),
        ),
        method_family=_infer_method_family(methodology, equations, summary),
        method_tags=_extract_tagged_terms(combined_text, _TECHNICAL_TAGS),
        algorithmic_view=_first_sentences(
            equations or methodology, limit=3, min_chars=20
        ),
        contributions=_list_from_text(
            summary + "\n" + methodology,
            limit=4,
            preferred_terms=(
                "we propose",
                "we present",
                "our contribution",
                "first",
                "introduce",
            ),
        ),
        assumptions=_list_from_text(
            summary + "\n" + methodology,
            limit=4,
            preferred_terms=("assum", "suppose", "under", "given"),
        ),
        limitations=_list_from_text(
            limitations or summary,
            limit=5,
            preferred_terms=("limitation", "future work", "failure", "however", "not"),
        ),
        tasks=_extract_tagged_terms(
            combined_text,
            (
                "budget allocation",
                "bidding",
                "forecasting",
                "classification",
                "retrieval",
                "ranking",
            ),
        ),
        datasets=_list_from_text(
            experiments,
            limit=3,
            preferred_terms=("dataset", "data set", "corpus", "benchmark"),
        ),
        metrics=_extract_metrics(experiments),
        baselines=_extract_baselines(experiments),
        key_results=_list_from_text(
            experiments,
            limit=5,
            preferred_terms=("result", "improv", "outperform", "baseline", "ablation"),
        ),
        ablation_focus=_list_from_text(
            experiments,
            limit=3,
            preferred_terms=("ablation", "sensitivity", "coefficient", "parameter"),
        ),
        domain_tags=_extract_domain_tags(combined_text),
        technical_tags=_extract_tagged_terms(combined_text, _TECHNICAL_TAGS),
        reproduction_notes=_first_sentences(
            reproduction_notes or experiments, limit=3, min_chars=20
        ),
        evidence=[
            EvidenceEntry(
                section=item.section,
                confidence=item.confidence,
                snippet=_truncate(item.content, _MAX_SNIPPET_CHARS),
            )
            for item in sections
            if item.content
        ],
    )
