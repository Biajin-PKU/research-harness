"""Paper number verifier — extract and verify numbers in paper text.

Scans paper text for numeric values, classifies sections as strict
(results, experiments — REJECT unverified) or lenient (intro, related
work — WARN only), and skips always-allowed numbers.

Adapted from AutoResearchClaw (MIT license).
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

from .verified_registry import ALWAYS_ALLOWED, VerifiedRegistry

logger = logging.getLogger(__name__)

# Regex to extract floating-point or integer numbers
_NUMBER_RE = re.compile(
    r"""
    (?<![\\a-zA-Z_])        # not preceded by backslash or letter (skip \cite, variables)
    -?                       # optional negative sign
    (?:
        \d{1,3}(?:,\d{3})+  # numbers with comma separators (1,000,000)
        |
        \d+                  # plain integer part
    )
    (?:\.\d+)?               # optional decimal part
    (?:[eE][+-]?\d+)?        # optional scientific notation
    (?![}\w])                # not followed by } or word char (skip \ref{}, variable names)
    """,
    re.VERBOSE,
)

# Patterns to detect LaTeX contexts we should skip
_SKIP_PATTERNS = [
    re.compile(r"\\(?:cite|ref|label|eqref|cref|Cref|pageref)\{[^}]*\}"),
    re.compile(r"\\(?:begin|end)\{[^}]*\}"),
    re.compile(r"%.*$", re.MULTILINE),  # LaTeX comments
    re.compile(r"\\(?:texttt|url|href)\{[^}]*\}"),
]

# Verbatim-like environments to skip entirely
_VERBATIM_ENVS = re.compile(
    r"\\begin\{(?:verbatim|lstlisting|minted|algorithm|algorithmic)\}.*?"
    r"\\end\{(?:verbatim|lstlisting|minted|algorithm|algorithmic)\}",
    re.DOTALL,
)

# Section classification
STRICT_SECTIONS = frozenset({
    "results", "experiments", "experiment", "experimental results",
    "experimental setup", "evaluation", "main results", "ablation",
    "ablation study", "quantitative results", "comparison",
})

LENIENT_SECTIONS = frozenset({
    "introduction", "intro", "related work", "related works",
    "background", "preliminaries", "motivation", "abstract",
    "conclusion", "conclusions", "discussion", "future work",
    "limitations", "appendix", "acknowledgments", "acknowledgements",
})


@dataclass
class NumberOccurrence:
    """A number found in the paper text."""

    value: float
    raw_text: str
    section: str = ""
    line_number: int = 0
    is_strict_section: bool = False


@dataclass
class VerificationIssue:
    """An issue found during paper number verification."""

    severity: str  # "error" | "warning"
    number: float
    raw_text: str
    section: str
    message: str
    line_number: int = 0


@dataclass
class PaperVerifyResult:
    """Result of verifying numbers in a paper."""

    total_numbers: int = 0
    verified_count: int = 0
    always_allowed_count: int = 0
    unverified_count: int = 0
    issues: list[VerificationIssue] = field(default_factory=list)
    numbers: list[NumberOccurrence] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_numbers == 0:
            return 1.0
        return (self.verified_count + self.always_allowed_count) / self.total_numbers

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


def _strip_skip_patterns(text: str) -> str:
    """Remove LaTeX commands and environments that contain non-data numbers."""
    text = _VERBATIM_ENVS.sub(" ", text)
    for pat in _SKIP_PATTERNS:
        text = pat.sub(" ", text)
    return text


def _parse_number(raw: str) -> float | None:
    """Parse a raw number string, handling comma-separated numbers."""
    cleaned = raw.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _classify_section(section_name: str) -> str:
    """Classify a section as 'strict', 'lenient', or 'unknown'."""
    lower = section_name.lower().strip()
    if lower in STRICT_SECTIONS:
        return "strict"
    if lower in LENIENT_SECTIONS:
        return "lenient"
    # Check partial matches
    for s in STRICT_SECTIONS:
        if s in lower:
            return "strict"
    for s in LENIENT_SECTIONS:
        if s in lower:
            return "lenient"
    return "unknown"


def extract_numbers(
    text: str,
    section: str = "",
) -> list[NumberOccurrence]:
    """Extract numeric values from text, skipping LaTeX commands and verbatim blocks."""
    cleaned = _strip_skip_patterns(text)
    occurrences: list[NumberOccurrence] = []
    section_type = _classify_section(section)

    for match in _NUMBER_RE.finditer(cleaned):
        raw = match.group()
        value = _parse_number(raw)
        if value is None:
            continue

        # Find approximate line number
        line_num = cleaned[:match.start()].count("\n") + 1

        occurrences.append(
            NumberOccurrence(
                value=value,
                raw_text=raw,
                section=section,
                line_number=line_num,
                is_strict_section=(section_type == "strict"),
            )
        )

    return occurrences


def verify_paper_numbers(
    text: str,
    registry: VerifiedRegistry,
    section: str = "",
    tolerance: float = 0.01,
) -> PaperVerifyResult:
    """Verify all numbers in paper text against the verified registry.

    Numbers in strict sections (results, experiments) that are not in the
    registry produce errors. Numbers in lenient sections produce warnings.
    Always-allowed numbers (years, powers of 2, common hyperparams) are skipped.
    """
    numbers = extract_numbers(text, section=section)
    section_type = _classify_section(section)

    result = PaperVerifyResult(
        total_numbers=len(numbers),
        numbers=numbers,
    )

    for occ in numbers:
        v = occ.value

        # Check always-allowed first
        if v in ALWAYS_ALLOWED or _is_always_allowed_like(v):
            result.always_allowed_count += 1
            continue

        # Check verified registry
        if registry.is_verified(v, tolerance):
            result.verified_count += 1
            continue

        # Unverified
        result.unverified_count += 1

        if section_type == "strict" or occ.is_strict_section:
            result.issues.append(
                VerificationIssue(
                    severity="error",
                    number=v,
                    raw_text=occ.raw_text,
                    section=section,
                    message=f"Unverified number {occ.raw_text} in strict section '{section}'",
                    line_number=occ.line_number,
                )
            )
        elif section_type == "lenient":
            result.issues.append(
                VerificationIssue(
                    severity="warning",
                    number=v,
                    raw_text=occ.raw_text,
                    section=section,
                    message=f"Unverified number {occ.raw_text} in '{section}' (lenient — check manually)",
                    line_number=occ.line_number,
                )
            )
        else:
            # Unknown section — default to warning
            result.issues.append(
                VerificationIssue(
                    severity="warning",
                    number=v,
                    raw_text=occ.raw_text,
                    section=section,
                    message=f"Unverified number {occ.raw_text} in section '{section}'",
                    line_number=occ.line_number,
                )
            )

    return result


def _is_always_allowed_like(value: float) -> bool:
    """Check if a value looks like an always-allowed number (integer < 20, etc.)."""
    # Small integers 0-20 are common and not data
    if value == int(value) and 0 <= value <= 20:
        return True
    return False
