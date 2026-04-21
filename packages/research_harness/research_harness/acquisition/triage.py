"""Triage papers that need manual download: filter by venue tier + LLM necessity."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

CCF_TOP_TIERS = frozenset({"CCF-A*", "CCF-A", "CCF-B"})
CAS_TOP_TIERS = frozenset({"CAS-Q1", "CAS-Q2"})

TIER_KEYWORDS_A = (
    "neurips", "nips", "icml", "iclr", "aaai", "ijcai", "cvpr", "iccv", "eccv",
    "acl", "emnlp", "naacl", "sigir", "kdd", "www", "icde", "vldb", "sigmod",
    "osdi", "sosp", "eurosys", "nsdi", "usenix",
    "nature", "science", "cell", "pnas", "lancet",
)
TIER_KEYWORDS_B = (
    "cikm", "wsdm", "coling", "aistats", "uai", "ecai",
    "infocom", "mobicom", "sigcomm",
    "jmlr", "tpami", "tkde", "tois", "ai journal",
)


def _infer_venue_tier(venue: str) -> str | None:
    v = (venue or "").lower()
    for kw in TIER_KEYWORDS_A:
        if kw in v:
            return "CCF-A"
    for kw in TIER_KEYWORDS_B:
        if kw in v:
            return "CCF-B"
    return None


def triage_manual_papers(
    manual_list: list[dict[str, Any]],
    necessity_map: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Filter manual_list to papers worth human effort (venue OR necessity).

    Args:
        manual_list: papers from AcquisitionReport.manual_list
        necessity_map: {paper_id: "high"|"medium"|"low"} from paper_coverage_check

    Returns:
        Filtered list with added 'triage_reason' field.
    """
    necessity_map = necessity_map or {}
    result: list[dict[str, Any]] = []

    for item in manual_list:
        paper_id = item["paper_id"]
        venue = item.get("venue", "")
        tier = _infer_venue_tier(venue)
        necessity = necessity_map.get(paper_id, "medium")

        is_top_venue = tier in CCF_TOP_TIERS
        is_high_necessity = necessity == "high"

        if is_top_venue or is_high_necessity:
            reasons = []
            if is_top_venue:
                reasons.append(f"venue_tier={tier}")
            if is_high_necessity:
                reasons.append("llm_necessity=high")
            item_out = {**item, "triage_reason": " + ".join(reasons), "venue_tier": tier}
            result.append(item_out)
        else:
            logger.debug(
                "Skipping paper %d (%s) — venue=%s, necessity=%s",
                paper_id, item.get("title", ""), venue, necessity,
            )

    return result
