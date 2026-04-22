"""Venue tier data — CCF rankings and CAS (Chinese Academy of Sciences) journal quartiles.

Provides lookup and scoring for ~150 top CS venues to support tier-based
filtering and ranking in paper_search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class CCFTier(str, Enum):
    A_STAR = "A*"
    A = "A"
    B = "B"
    C = "C"
    NONE = ""


class CASQuartile(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    NONE = ""


_CCF_SCORES = {
    CCFTier.A_STAR: 100,
    CCFTier.A: 90,
    CCFTier.B: 70,
    CCFTier.C: 40,
    CCFTier.NONE: 0,
}
_CAS_SCORES = {
    CASQuartile.Q1: 85,
    CASQuartile.Q2: 65,
    CASQuartile.Q3: 40,
    CASQuartile.Q4: 20,
    CASQuartile.NONE: 0,
}


@dataclass(frozen=True)
class VenueTier:
    ccf: CCFTier = CCFTier.NONE
    cas: CASQuartile = CASQuartile.NONE
    score: int = 0

    @staticmethod
    def create(
        ccf: CCFTier = CCFTier.NONE, cas: CASQuartile = CASQuartile.NONE
    ) -> VenueTier:
        score = max(_CCF_SCORES.get(ccf, 0), _CAS_SCORES.get(cas, 0))
        return VenueTier(ccf=ccf, cas=cas, score=score)

    @property
    def label(self) -> str:
        parts = []
        if self.ccf != CCFTier.NONE:
            parts.append(f"CCF-{self.ccf.value}")
        if self.cas != CASQuartile.NONE:
            parts.append(f"CAS-{self.cas.value}")
        return "/".join(parts) if parts else ""


_EMPTY_TIER = VenueTier()

# ---------------------------------------------------------------------------
# Tier threshold mapping for filter parameters
# ---------------------------------------------------------------------------

_TIER_THRESHOLDS: dict[str, int] = {
    "ccf_a_star": 100,
    "ccf_a": 90,
    "ccf_b": 70,
    "ccf_c": 40,
    "cas_q1": 85,
    "cas_q2": 65,
    "cas_q3": 40,
    "cas_q4": 20,
}

# ---------------------------------------------------------------------------
# Venue registry — abbreviation and full name mappings
# ---------------------------------------------------------------------------


def _t(ccf: str = "", cas: str = "") -> VenueTier:
    """Shorthand for building VenueTier entries."""
    c = {"A*": CCFTier.A_STAR, "A": CCFTier.A, "B": CCFTier.B, "C": CCFTier.C}.get(
        ccf, CCFTier.NONE
    )
    q = {
        "Q1": CASQuartile.Q1,
        "Q2": CASQuartile.Q2,
        "Q3": CASQuartile.Q3,
        "Q4": CASQuartile.Q4,
    }.get(cas, CASQuartile.NONE)
    return VenueTier.create(c, q)


# Each entry: (list_of_names, VenueTier)
# Names are lowercase; lookup normalizes input to lowercase.
_VENUE_ENTRIES: list[tuple[list[str], VenueTier]] = [
    # === CCF-A* (ML/AI flagships, score=100) ===
    (
        ["neurips", "nips", "advances in neural information processing systems"],
        _t("A*"),
    ),
    (["icml", "international conference on machine learning"], _t("A*")),
    (["iclr", "international conference on learning representations"], _t("A*")),
    # === CCF-A Conferences (score=90) ===
    # AI
    (["aaai", "association for the advancement of artificial intelligence"], _t("A")),
    (["ijcai", "international joint conference on artificial intelligence"], _t("A")),
    # CV
    (
        [
            "cvpr",
            "ieee/cvf conference on computer vision and pattern recognition",
            "ieee conference on computer vision and pattern recognition",
        ],
        _t("A"),
    ),
    (
        [
            "iccv",
            "ieee/cvf international conference on computer vision",
            "international conference on computer vision",
        ],
        _t("A"),
    ),
    # NLP
    (
        [
            "acl",
            "annual meeting of the association for computational linguistics",
            "association for computational linguistics",
        ],
        _t("A"),
    ),
    # Data
    (
        ["sigmod", "acm sigmod", "international conference on management of data"],
        _t("A"),
    ),
    (
        ["vldb", "pvldb", "proceedings of the vldb endowment", "very large data bases"],
        _t("A"),
    ),
    (["icde", "ieee international conference on data engineering"], _t("A")),
    (
        [
            "sigir",
            "acm sigir",
            "international acm sigir conference on research and development in information retrieval",
        ],
        _t("A"),
    ),
    (["kdd", "acm sigkdd", "knowledge discovery and data mining"], _t("A")),
    # Web
    (
        [
            "www",
            "the web conference",
            "world wide web conference",
            "international world wide web conference",
        ],
        _t("A"),
    ),
    # Networks
    (["sigcomm", "acm sigcomm"], _t("A")),
    (
        [
            "mobicom",
            "acm mobicom",
            "international conference on mobile computing and networking",
        ],
        _t("A"),
    ),
    (["infocom", "ieee infocom"], _t("A")),
    # Security
    (
        ["ccs", "acm ccs", "acm conference on computer and communications security"],
        _t("A"),
    ),
    (["ieee s&p", "ieee sp", "ieee symposium on security and privacy"], _t("A")),
    (["usenix security", "usenix security symposium"], _t("A")),
    (["ndss", "network and distributed system security symposium"], _t("A")),
    # Systems
    (
        ["osdi", "usenix symposium on operating systems design and implementation"],
        _t("A"),
    ),
    (["sosp", "acm symposium on operating systems principles"], _t("A")),
    # Architecture
    (["isca", "international symposium on computer architecture"], _t("A")),
    (["micro", "ieee/acm international symposium on microarchitecture"], _t("A")),
    (
        [
            "hpca",
            "ieee international symposium on high-performance computer architecture",
        ],
        _t("A"),
    ),
    # PL
    (
        [
            "pldi",
            "acm sigplan conference on programming language design and implementation",
        ],
        _t("A"),
    ),
    (["popl", "acm sigplan symposium on principles of programming languages"], _t("A")),
    # SE
    (["icse", "international conference on software engineering"], _t("A")),
    (
        [
            "fse",
            "acm sigsoft symposium on the foundation of software engineering",
            "foundations of software engineering",
        ],
        _t("A"),
    ),
    (
        ["ase", "ieee/acm international conference on automated software engineering"],
        _t("A"),
    ),
    # HCI
    (
        ["chi", "acm chi", "acm conference on human factors in computing systems"],
        _t("A"),
    ),
    (
        [
            "ubicomp",
            "acm international joint conference on pervasive and ubiquitous computing",
        ],
        _t("A"),
    ),
    # Graphics
    (["siggraph", "acm siggraph"], _t("A")),
    # Multimedia
    (["acm mm", "acm multimedia"], _t("A")),
    # Robotics (treated as A for relevance)
    (["rss", "robotics: science and systems"], _t("A")),
    # === CCF-B Conferences (score=70) ===
    # CV
    (["eccv", "european conference on computer vision"], _t("B")),
    (
        ["wacv", "ieee/cvf winter conference on applications of computer vision"],
        _t("B"),
    ),
    (["bmvc", "british machine vision conference"], _t("B")),
    # NLP
    (
        ["emnlp", "conference on empirical methods in natural language processing"],
        _t("B"),
    ),
    (
        [
            "naacl",
            "north american chapter of the association for computational linguistics",
        ],
        _t("B"),
    ),
    (["coling", "international conference on computational linguistics"], _t("B")),
    (
        ["eacl", "european chapter of the association for computational linguistics"],
        _t("B"),
    ),
    # Data/IR
    (
        [
            "cikm",
            "acm international conference on information and knowledge management",
        ],
        _t("B"),
    ),
    (["wsdm", "acm international conference on web search and data mining"], _t("B")),
    (["icdm", "ieee international conference on data mining"], _t("B")),
    (["ecir", "european conference on information retrieval"], _t("B")),
    (["dasfaa", "database systems for advanced applications"], _t("B")),
    # AI/ML
    (
        [
            "aamas",
            "international conference on autonomous agents and multiagent systems",
        ],
        _t("B"),
    ),
    (["uai", "conference on uncertainty in artificial intelligence"], _t("B")),
    (
        [
            "aistats",
            "international conference on artificial intelligence and statistics",
        ],
        _t("B"),
    ),
    (["colt", "conference on learning theory"], _t("B")),
    (["ecai", "european conference on artificial intelligence"], _t("B")),
    (
        ["pakdd", "pacific-asia conference on knowledge discovery and data mining"],
        _t("B"),
    ),
    # Systems
    (
        [
            "asplos",
            "international conference on architectural support for programming languages and operating systems",
        ],
        _t("B"),
    ),
    (["eurosys", "european conference on computer systems"], _t("B")),
    (["middleware", "acm/ifip international middleware conference"], _t("B")),
    (
        [
            "sc",
            "supercomputing",
            "international conference for high performance computing",
        ],
        _t("B"),
    ),
    (
        [
            "ppopp",
            "acm sigplan symposium on principles and practice of parallel programming",
        ],
        _t("B"),
    ),
    # Networks
    (["imc", "acm internet measurement conference"], _t("B")),
    (
        [
            "conext",
            "acm international conference on emerging networking experiments and technologies",
        ],
        _t("B"),
    ),
    # Security
    (
        [
            "raid",
            "international symposium on research in attacks, intrusions and defenses",
        ],
        _t("B"),
    ),
    (["acsac", "annual computer security applications conference"], _t("B")),
    # SE
    (["issta", "international symposium on software testing and analysis"], _t("B")),
    (
        [
            "saner",
            "ieee international conference on software analysis, evolution and reengineering",
        ],
        _t("B"),
    ),
    (
        [
            "icsme",
            "ieee international conference on software maintenance and evolution",
        ],
        _t("B"),
    ),
    (["msr", "mining software repositories"], _t("B")),
    # Robotics
    (["icra", "ieee international conference on robotics and automation"], _t("B")),
    (
        ["iros", "ieee/rsj international conference on intelligent robots and systems"],
        _t("B"),
    ),
    (["corl", "conference on robot learning"], _t("B")),
    # Graphics
    (
        [
            "eurographics",
            "eg",
            "annual conference of the european association for computer graphics",
        ],
        _t("B"),
    ),
    # HCI
    (["uist", "acm symposium on user interface software and technology"], _t("B")),
    (
        [
            "cscw",
            "acm conference on computer-supported cooperative work and social computing",
        ],
        _t("B"),
    ),
    # Multimedia
    (["icme", "ieee international conference on multimedia and expo"], _t("B")),
    (["mmm", "international conference on multimedia modeling"], _t("B")),
    # === CCF-C Conferences (score=40) ===
    (["accv", "asian conference on computer vision"], _t("C")),
    (["ijcnn", "international joint conference on neural networks"], _t("C")),
    (["gecco", "genetic and evolutionary computation conference"], _t("C")),
    (
        ["pricai", "pacific rim international conference on artificial intelligence"],
        _t("C"),
    ),
    (["iconip", "international conference on neural information processing"], _t("C")),
    (
        [
            "ksem",
            "international conference on knowledge science, engineering and management",
        ],
        _t("C"),
    ),
    # === Journals — CCF + CAS combined ===
    # CCF-A Journals
    (
        ["tpami", "ieee transactions on pattern analysis and machine intelligence"],
        _t("A", "Q1"),
    ),
    (["ijcv", "international journal of computer vision"], _t("A", "Q1")),
    (["tit", "ieee transactions on information theory"], _t("A", "Q1")),
    (["jmlr", "journal of machine learning research"], _t("A", "Q1")),
    (["ai", "artificial intelligence"], _t("A", "Q1")),
    (["tkde", "ieee transactions on knowledge and data engineering"], _t("A", "Q1")),
    (["tois", "acm transactions on information systems"], _t("A", "Q2")),
    (["jsac", "ieee journal on selected areas in communications"], _t("A", "Q1")),
    (["ton", "ieee/acm transactions on networking"], _t("A", "Q1")),
    (["tse", "ieee transactions on software engineering"], _t("A", "Q1")),
    (
        ["tosem", "acm transactions on software engineering and methodology"],
        _t("A", "Q1"),
    ),
    (["tochi", "acm transactions on computer-human interaction"], _t("A", "Q1")),
    (["tog", "acm transactions on graphics"], _t("A", "Q1")),
    (
        ["tifs", "ieee transactions on information forensics and security"],
        _t("A", "Q1"),
    ),
    (["tdsc", "ieee transactions on dependable and secure computing"], _t("A", "Q1")),
    (["tc", "ieee transactions on computers"], _t("A", "Q2")),
    (
        [
            "tcad",
            "ieee transactions on computer-aided design of integrated circuits and systems",
        ],
        _t("A", "Q2"),
    ),
    (["tpds", "ieee transactions on parallel and distributed systems"], _t("A", "Q1")),
    (["vldbj", "vldb journal", "the vldb journal"], _t("A", "Q1")),
    (["jacm", "journal of the acm"], _t("A", "Q2")),
    # CCF-B Journals
    (["pr", "pattern recognition"], _t("B", "Q1")),
    (["nn", "neural networks"], _t("B", "Q1")),
    (["kbs", "knowledge-based systems"], _t("B", "Q1")),
    (
        [
            "ipm",
            "information processing and management",
            "information processing & management",
        ],
        _t("B", "Q1"),
    ),
    (["eswa", "expert systems with applications"], _t("B", "Q1")),
    (["ins", "information sciences"], _t("B", "Q1")),
    (["neucom", "neurocomputing"], _t("B", "Q2")),
    (["apin", "applied intelligence"], _t("B", "Q2")),
    (["tip", "ieee transactions on image processing"], _t("B", "Q1")),
    (
        ["tnnls", "ieee transactions on neural networks and learning systems"],
        _t("B", "Q1"),
    ),
    (["tcyb", "ieee transactions on cybernetics"], _t("B", "Q1")),
    (["tmm", "ieee transactions on multimedia"], _t("B", "Q1")),
    (
        [
            "taslp",
            "ieee/acm transactions on audio, speech and language processing",
            "ieee/acm transactions on audio speech and language processing",
        ],
        _t("B", "Q1"),
    ),
    (
        ["tacl", "transactions of the association for computational linguistics"],
        _t("B", "Q1"),
    ),
    (["cl", "computational linguistics"], _t("B", "Q1")),
    (
        ["tvcg", "ieee transactions on visualization and computer graphics"],
        _t("B", "Q1"),
    ),
    (["jair", "journal of artificial intelligence research"], _t("B", "Q2")),
    (["ml", "machine learning"], _t("B", "Q2")),
    (
        ["dke", "data & knowledge engineering", "data and knowledge engineering"],
        _t("B", "Q3"),
    ),
    (["ijar", "international journal of approximate reasoning"], _t("B", "Q2")),
    (["aij", "artificial intelligence journal"], _t("B", "Q1")),
    (["robotics and autonomous systems"], _t("B", "Q2")),
    (["tra", "ieee transactions on robotics"], _t("B", "Q1")),
    # CCF-C Journals (or non-CCF but CAS-Q1/Q2)
    (["prl", "pattern recognition letters"], _t("C", "Q2")),
    (["nca", "neural computing and applications"], _t("C", "Q2")),
    (["isci", "information sciences"], _t("C", "Q1")),
    (["access", "ieee access"], _t("", "Q2")),
    # High-impact non-CCF venues (CAS only)
    (["nature", "nature"], _t("", "Q1")),
    (["science"], _t("", "Q1")),
    (["nature machine intelligence"], _t("", "Q1")),
    (["nature communications"], _t("", "Q1")),
    (["pnas", "proceedings of the national academy of sciences"], _t("", "Q1")),
    # arXiv (preprint, no tier)
    (["arxiv", "arxiv.org"], _t()),
]

# Build the lookup dict
_VENUE_REGISTRY: dict[str, VenueTier] = {}
for _names, _tier in _VENUE_ENTRIES:
    for _name in _names:
        _VENUE_REGISTRY[_name.lower()] = _tier

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_YEAR_SUFFIX_RE = re.compile(r"\s*['\"]*\d{4}['\"]*\s*$")
_PREFIX_RE = re.compile(
    r"^(proceedings\s+of\s+(the\s+)?|proc\.\s*|in\s+)",
    re.IGNORECASE,
)
_ORDINAL_RE = re.compile(r"\b\d+(st|nd|rd|th)\b", re.IGNORECASE)


def normalize_venue_name(venue: str) -> str:
    """Normalize venue string for lookup."""
    result = venue.strip()
    result = _YEAR_SUFFIX_RE.sub("", result)
    result = _PREFIX_RE.sub("", result)
    result = _ORDINAL_RE.sub("", result)
    result = result.strip().lower()
    result = re.sub(r"\s+", " ", result)
    return result


def get_venue_tier(venue: str) -> VenueTier:
    """Look up venue tier. Returns empty tier (score=0) for unknown venues."""
    if not venue:
        return _EMPTY_TIER
    normalized = normalize_venue_name(venue)
    tier = _VENUE_REGISTRY.get(normalized)
    if tier is not None:
        return tier
    # Try substring matching against registry keys
    for key, tier in _VENUE_REGISTRY.items():
        if key in normalized or normalized in key:
            return tier
    return _EMPTY_TIER


def meets_tier_threshold(venue: str, min_tier: str) -> bool:
    """Check if venue meets the minimum tier threshold.

    min_tier: one of ccf_a_star, ccf_a, ccf_b, ccf_c, cas_q1, cas_q2, cas_q3, cas_q4
    """
    if not min_tier:
        return True
    threshold = _TIER_THRESHOLDS.get(min_tier.lower(), 0)
    if threshold == 0:
        return True
    tier = get_venue_tier(venue)
    return tier.score >= threshold


def venue_tier_score(venue: str) -> int:
    """Return numeric score 0-100 for ranking."""
    return get_venue_tier(venue).score


def venue_tier_label(venue: str) -> str:
    """Return human-readable tier label, e.g. 'CCF-A/CAS-Q1'."""
    return get_venue_tier(venue).label
