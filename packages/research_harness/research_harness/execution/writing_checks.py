"""Deterministic writing quality checks — no LLM required.

Checks: AI boilerplate phrases, weasel words, word count, section targets,
anti-hedging, anti-repetition. Used by section_review primitive alongside
LLM-based 10-dim scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# -- Word count targets per section (borrowed from ARC) -----------------------

SECTION_WORD_TARGETS: dict[str, tuple[int, int]] = {
    "title": (5, 14),
    "abstract": (180, 260),
    "introduction": (1200, 1800),
    "related_work": (1500, 2800),
    "related work": (1500, 2800),
    "method": (2000, 3500),
    "methodology": (2000, 3500),
    "experiments": (2500, 4500),
    "experiment": (2500, 4500),
    "results": (1000, 2000),
    "discussion": (600, 1200),
    "conclusion": (250, 500),
    "conclusions": (250, 500),
    "limitations": (200, 500),
    "appendix": (500, 5000),
}

# Minimum citation count per section type (top-venue norms)
SECTION_CITATION_QUOTA: dict[str, int] = {
    "introduction": 15,
    "related_work": 30,
    "related work": 30,
    "method": 5,
    "methodology": 5,
    "experiments": 8,
    "experiment": 8,
    "discussion": 3,
    "abstract": 0,
    "conclusion": 2,
    "conclusions": 2,
}

# -- AI boilerplate phrases (75 phrases) -------------------------------------

AI_BOILERPLATE_PHRASES: frozenset[str] = frozenset({
    "in this paper, we propose",
    "in this work, we present",
    "the proposed method",
    "the proposed approach",
    "the proposed framework",
    "the proposed model",
    "the proposed system",
    "our proposed method",
    "we propose a novel",
    "a novel approach",
    "a novel method",
    "a novel framework",
    "state-of-the-art results",
    "state-of-the-art performance",
    "achieves state-of-the-art",
    "outperforms state-of-the-art",
    "surpasses state-of-the-art",
    "cutting-edge",
    "groundbreaking",
    "paradigm shift",
    "it is worth noting that",
    "it should be noted that",
    "it is important to note",
    "it is noteworthy that",
    "it is interesting to note",
    "as shown in table",
    "as illustrated in figure",
    "as depicted in figure",
    "as demonstrated in",
    "extensive experiments show",
    "extensive experiments demonstrate",
    "comprehensive experiments",
    "rigorous evaluation",
    "thorough evaluation",
    "in summary",
    "to summarize",
    "to conclude",
    "in conclusion",
    "leveraging the power of",
    "harnessing the power of",
    "tapping into the potential",
    "unlocking the potential",
    "paving the way",
    "delves into",
    "delve into",
    "shed light on",
    "sheds light on",
    "in the realm of",
    "in the landscape of",
    "the landscape of",
    "in the context of",
    "from the perspective of",
    "a comprehensive overview",
    "a comprehensive survey",
    "a comprehensive study",
    "plays a crucial role",
    "plays a pivotal role",
    "plays an important role",
    "is of paramount importance",
    "is of utmost importance",
    "has gained significant attention",
    "has attracted considerable attention",
    "has received increasing attention",
    "remains an open challenge",
    "remains an open problem",
    "poses significant challenges",
    "aims to address",
    "aims to bridge the gap",
    "bridge the gap between",
    "fill the gap",
    "close the gap",
    "to this end",
    "to address this issue",
    "to tackle this problem",
    "to overcome this limitation",
    "moreover",
    "furthermore",
    "additionally",
    "notably",
    "importantly",
    "significantly",
})

# -- Weasel words / hedging phrases ------------------------------------------

WEASEL_WORDS: frozenset[str] = frozenset({
    "somewhat",
    "relatively",
    "arguably",
    "fairly",
    "quite",
    "rather",
    "slightly",
    "marginally",
    "moderately",
    "approximately",
    "roughly",
    "essentially",
    "basically",
    "virtually",
    "practically",
    "seemingly",
    "apparently",
    "presumably",
    "conceivably",
    "perhaps",
    "possibly",
    "likely",
    "might",
    "may suggest",
    "could potentially",
    "tends to",
    "appear to",
    "seems to",
    "it appears that",
    "it seems that",
    "to some extent",
    "in some cases",
    "in certain scenarios",
    "under certain conditions",
    "to a certain degree",
})

# -- Review dimensions (imported from authoritative source) -------------------

from ..primitives.types import SECTION_REVIEW_DIMENSIONS as REVIEW_DIMENSIONS  # noqa: E402


@dataclass
class CheckResult:
    """Result of a single deterministic check."""

    check_name: str
    passed: bool = True
    details: str = ""
    items_found: list[str] = field(default_factory=list)


def check_word_count(
    content: str,
    section: str,
    target_words: int = 0,
) -> CheckResult:
    """Check if word count is within target range."""
    words = len(content.split())
    section_lower = section.lower().strip()

    if target_words > 0:
        lo, hi = int(target_words * 0.8), int(target_words * 1.2)
    elif section_lower in SECTION_WORD_TARGETS:
        lo, hi = SECTION_WORD_TARGETS[section_lower]
    else:
        return CheckResult(
            check_name="word_count",
            passed=True,
            details=f"Word count: {words} (no target for '{section}')",
        )

    passed = lo <= words <= hi
    return CheckResult(
        check_name="word_count",
        passed=passed,
        details=f"Word count: {words}, target: {lo}-{hi}",
    )


def check_ai_boilerplate(content: str) -> CheckResult:
    """Detect AI-generated boilerplate phrases."""
    lower = content.lower()
    found: list[str] = []

    for phrase in AI_BOILERPLATE_PHRASES:
        if phrase in lower:
            found.append(phrase)

    return CheckResult(
        check_name="ai_boilerplate",
        passed=len(found) <= 3,  # allow up to 3 common phrases
        details=f"Found {len(found)} AI boilerplate phrases",
        items_found=sorted(found),
    )


def check_weasel_words(content: str) -> CheckResult:
    """Detect hedging and weasel words."""
    lower = content.lower()
    found: list[str] = []

    for word in WEASEL_WORDS:
        # Match as whole word/phrase
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, lower):
            found.append(word)

    word_count = len(content.split())
    density = len(found) / max(word_count, 1) * 100

    return CheckResult(
        check_name="weasel_words",
        passed=density < 2.0,  # less than 2% weasel density
        details=f"Found {len(found)} weasel words ({density:.1f}% density)",
        items_found=sorted(found),
    )


def check_repetition(content: str, threshold: int = 3) -> CheckResult:
    """Detect sentence-level repetition (trigram overlap)."""
    sentences = re.split(r"[.!?]+", content)
    sentences = [s.strip().lower() for s in sentences if len(s.strip()) > 20]

    if len(sentences) < 2:
        return CheckResult(check_name="repetition", passed=True, details="Too few sentences to check")

    # Extract trigrams from each sentence
    all_trigrams: dict[str, int] = {}
    for sent in sentences:
        words = sent.split()
        for i in range(len(words) - 2):
            trigram = " ".join(words[i : i + 3])
            all_trigrams[trigram] = all_trigrams.get(trigram, 0) + 1

    repeated = [t for t, c in all_trigrams.items() if c >= threshold]

    return CheckResult(
        check_name="repetition",
        passed=len(repeated) <= 2,
        details=f"Found {len(repeated)} repeated trigrams (threshold={threshold})",
        items_found=repeated[:10],
    )


def check_section_structure(content: str, section: str) -> CheckResult:
    """Check basic section structure requirements."""
    issues: list[str] = []

    # Check for empty content
    if not content.strip():
        return CheckResult(
            check_name="section_structure",
            passed=False,
            details="Section is empty",
        )

    # Check for citation presence in key sections
    section_lower = section.lower()
    needs_citations = section_lower in {"introduction", "related work", "related_work", "method", "methodology"}
    has_citations = bool(re.search(r"\\cite\{|\\citep\{|\\citet\{|\[[\d,\s]+\]", content))

    if needs_citations and not has_citations:
        issues.append(f"Section '{section}' typically needs citations but none found")

    return CheckResult(
        check_name="section_structure",
        passed=len(issues) == 0,
        details="; ".join(issues) if issues else "Structure OK",
        items_found=issues,
    )


def check_citation_quota(content: str, section: str) -> CheckResult:
    """Check that the section cites at least the venue-norm number of papers."""
    section_lower = section.lower().strip()
    quota = SECTION_CITATION_QUOTA.get(section_lower, 0)
    if quota == 0:
        return CheckResult(
            check_name="citation_quota",
            passed=True,
            details=f"No citation quota for '{section}'",
        )

    # Count distinct citation markers: [N] or [N,M] or \cite{...}
    numeric_markers = set()
    for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", content):
        for n in m.group(1).split(","):
            numeric_markers.add(n.strip())

    latex_keys = set()
    for m in re.finditer(r"\\cite[pt]?\*?\{([^}]+)\}", content):
        for k in m.group(1).split(","):
            latex_keys.add(k.strip())

    distinct_citations = len(numeric_markers) + len(latex_keys)
    passed = distinct_citations >= quota

    return CheckResult(
        check_name="citation_quota",
        passed=passed,
        details=(
            f"Section '{section}' cites {distinct_citations} distinct papers "
            f"(quota {quota}, {'OK' if passed else 'BELOW QUOTA'})"
        ),
        items_found=[] if passed else [f"need {quota - distinct_citations} more unique citations"],
    )


def check_overclaiming(content: str) -> CheckResult:
    """Detect overclaiming patterns — unhedged 'first', excessive 'novel'."""
    lower = content.lower()
    issues: list[str] = []

    # "the first" without "to our knowledge" / "to the best of our knowledge"
    first_matches = list(re.finditer(r"\bthe first\b", lower))
    hedged_phrases = ["to our knowledge", "to the best of our knowledge", "among the first"]
    for m in first_matches:
        # Check if hedged within 100 chars before
        context_before = lower[max(0, m.start() - 100):m.start()]
        if not any(h in context_before for h in hedged_phrases):
            issues.append(f"Unhedged 'the first' at position {m.start()}")

    # Count "novel" usage
    novel_count = len(re.findall(r"\bnovel\b", lower))
    if novel_count > 2:
        issues.append(f"'novel' used {novel_count} times (recommend ≤2)")

    return CheckResult(
        check_name="overclaiming",
        passed=len(issues) == 0,
        details=f"Found {len(issues)} overclaiming issues" if issues else "No overclaiming detected",
        items_found=issues,
    )


def check_post_table_analysis(content: str, section: str) -> CheckResult:
    """Check that result tables in experiments sections are followed by analysis."""
    section_lower = section.lower()
    if section_lower not in {"experiments", "experiment", "results"}:
        return CheckResult(
            check_name="post_table_analysis",
            passed=True,
            details=f"Not an experiment section ('{section}')",
        )

    # Find table environments
    table_ends = [m.end() for m in re.finditer(
        r"\\end\{table\}|\\end\{tabular\}", content
    )]
    if not table_ends:
        return CheckResult(
            check_name="post_table_analysis",
            passed=True,
            details="No tables found in section",
        )

    issues: list[str] = []
    for i, end_pos in enumerate(table_ends):
        # Check what follows the table
        after_table = content[end_pos:end_pos + 300].strip()
        # If the next significant content is another table or subsection heading, flag it
        if re.match(r"^\\(subsection|section|begin\{table)", after_table):
            issues.append(f"Table {i+1}: no analysis text before next section/table")
        elif len(after_table.split()) < 30:
            issues.append(f"Table {i+1}: fewer than 30 words of analysis after table")

    return CheckResult(
        check_name="post_table_analysis",
        passed=len(issues) == 0,
        details=f"{len(issues)} tables lack post-table analysis" if issues else "All tables have analysis",
        items_found=issues,
    )


def check_theory_overload(content: str, section: str) -> CheckResult:
    """Detect excessive formal math proofs that indicate theory-heavy writing.

    This paper targets algorithm/model innovation, not theory-driven contribution.
    Multi-step formal proofs have high LLM error probability and should be avoided.
    At most ONE simple proposition is acceptable.
    """
    proof_env_patterns = [
        r"\\begin\{proof\}",
        r"\\begin\{theorem\}",
        r"\\begin\{lemma\}",
        r"\\begin\{corollary\}",
        r"\\begin\{proposition\}",
    ]
    keyword_patterns = [
        r"\\textbf\{Theorem\s+\d",
        r"\\textbf\{Lemma\s+\d",
        r"\\textbf\{Proof\}",
        r"\\textit\{Proof\}",
        r"\bQ\.E\.D\b",
        r"\\qed\b",
        r"\\blacksquare",
        r"\\square",
    ]

    issues: list[str] = []
    proof_count = 0
    theorem_count = 0

    for pat in proof_env_patterns:
        matches = re.findall(pat, content)
        if "proof" in pat:
            proof_count += len(matches)
        else:
            theorem_count += len(matches)

    for pat in keyword_patterns:
        matches = re.findall(pat, content, re.IGNORECASE)
        if "proof" in pat.lower():
            proof_count += len(matches)
        else:
            theorem_count += len(matches)

    if proof_count > 0:
        issues.append(
            f"Found {proof_count} formal proof block(s) — LLM-generated proofs have high error risk. "
            "Replace with informal justification, remarks, or remove."
        )
    if theorem_count > 1:
        issues.append(
            f"Found {theorem_count} theorem/lemma/corollary environments — "
            "at most 1 simple proposition is acceptable for algorithm papers."
        )

    return CheckResult(
        check_name="theory_overload",
        passed=len(issues) == 0,
        details=(
            f"Theory overload: {proof_count} proofs, {theorem_count} theorems"
            if issues
            else "No theory overload detected"
        ),
        items_found=issues,
    )


def run_all_checks(
    content: str,
    section: str,
    target_words: int = 0,
) -> list[CheckResult]:
    """Run all deterministic writing checks on a section."""
    return [
        check_word_count(content, section, target_words),
        check_ai_boilerplate(content),
        check_weasel_words(content),
        check_repetition(content),
        check_section_structure(content, section),
        check_overclaiming(content),
        check_post_table_analysis(content, section),
        check_citation_quota(content, section),
        check_theory_overload(content, section),
    ]
