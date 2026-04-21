"""Deep reading primitive implementations — non-LLM operations.

get_deep_reading: reads stored deep reading note from paper_annotations.
enrich_affiliations: extracts affiliations from PDF email domains.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .registry import (
    ENRICH_AFFILIATIONS_SPEC,
    GET_DEEP_READING_SPEC,
    register_primitive,
)
from .types import (
    AffiliationOutput,
    CrossPaperLink,
    DeepReadingNote,
    GetDeepReadingOutput,
    IndustrialFeasibility,
)

logger = logging.getLogger(__name__)

# Known email domain -> institution mapping
_DOMAIN_MAP: dict[str, str] = {
    # US universities
    "mit.edu": "MIT",
    "stanford.edu": "Stanford University",
    "berkeley.edu": "UC Berkeley",
    "cmu.edu": "Carnegie Mellon University",
    "harvard.edu": "Harvard University",
    "princeton.edu": "Princeton University",
    "columbia.edu": "Columbia University",
    "yale.edu": "Yale University",
    "cornell.edu": "Cornell University",
    "uchicago.edu": "University of Chicago",
    "umich.edu": "University of Michigan",
    "gatech.edu": "Georgia Institute of Technology",
    "illinois.edu": "UIUC",
    "ucla.edu": "UCLA",
    "washington.edu": "University of Washington",
    "nyu.edu": "New York University",
    "upenn.edu": "University of Pennsylvania",
    "utexas.edu": "UT Austin",
    "wisc.edu": "University of Wisconsin",
    "usc.edu": "University of Southern California",
    "purdue.edu": "Purdue University",
    # UK/EU universities
    "ox.ac.uk": "University of Oxford",
    "cam.ac.uk": "University of Cambridge",
    "imperial.ac.uk": "Imperial College London",
    "ucl.ac.uk": "University College London",
    "ethz.ch": "ETH Zurich",
    "epfl.ch": "EPFL",
    "mpi-inf.mpg.de": "Max Planck Institute",
    "inria.fr": "INRIA",
    # China universities
    "tsinghua.edu.cn": "Tsinghua University",
    "pku.edu.cn": "Peking University",
    "zju.edu.cn": "Zhejiang University",
    "sjtu.edu.cn": "Shanghai Jiao Tong University",
    "ustc.edu.cn": "USTC",
    "nju.edu.cn": "Nanjing University",
    "fudan.edu.cn": "Fudan University",
    "hit.edu.cn": "Harbin Institute of Technology",
    "ruc.edu.cn": "Renmin University of China",
    "buaa.edu.cn": "Beihang University",
    "bit.edu.cn": "Beijing Institute of Technology",
    "xjtu.edu.cn": "Xi'an Jiaotong University",
    "hust.edu.cn": "Huazhong University of Science and Technology",
    "sdu.edu.cn": "Shandong University",
    "nankai.edu.cn": "Nankai University",
    # Other Asia
    "u-tokyo.ac.jp": "University of Tokyo",
    "kaist.ac.kr": "KAIST",
    "snu.ac.kr": "Seoul National University",
    "nus.edu.sg": "National University of Singapore",
    "ntu.edu.sg": "Nanyang Technological University",
    # Tech companies
    "google.com": "Google",
    "deepmind.com": "Google DeepMind",
    "meta.com": "Meta",
    "fb.com": "Meta",
    "microsoft.com": "Microsoft",
    "openai.com": "OpenAI",
    "amazon.com": "Amazon",
    "amazon.science": "Amazon",
    "nvidia.com": "NVIDIA",
    "apple.com": "Apple",
    "anthropic.com": "Anthropic",
    "alibaba-inc.com": "Alibaba",
    "bytedance.com": "ByteDance",
    "tencent.com": "Tencent",
    "baidu.com": "Baidu",
    "jd.com": "JD.com",
    "meituan.com": "Meituan",
    "kuaishou.com": "Kuaishou",
    "huawei.com": "Huawei",
    "samsung.com": "Samsung",
    "salesforce.com": "Salesforce",
    "adobe.com": "Adobe",
    "ibm.com": "IBM",
    "intel.com": "Intel",
}


def _domain_to_institution(domain: str) -> str:
    """Map email domain to institution, with fallback heuristic."""
    domain = domain.lower().strip()
    if domain in _DOMAIN_MAP:
        return _DOMAIN_MAP[domain]
    # Try matching suffix (e.g., cs.stanford.edu -> stanford.edu)
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in _DOMAIN_MAP:
            return _DOMAIN_MAP[suffix]
    # Heuristic: use second-level domain as institution name
    if len(parts) >= 2:
        name = parts[-2]
        if name not in ("com", "org", "edu", "ac", "co", "net"):
            return name.replace("-", " ").title()
    return domain


def _parse_deep_reading_note(data: dict[str, Any]) -> DeepReadingNote:
    """Parse a dict into DeepReadingNote, tolerant of missing/malformed fields."""
    feas_raw = data.get("industrial_feasibility", {})
    if not isinstance(feas_raw, dict):
        feas_raw = {}
    feasibility = IndustrialFeasibility(
        viability=str(feas_raw.get("viability", "")).strip(),
        latency_constraints=str(feas_raw.get("latency_constraints", "")).strip(),
        data_requirements=str(feas_raw.get("data_requirements", "")).strip(),
        engineering_challenges=[
            str(c) for c in (feas_raw.get("engineering_challenges") or []) if c
        ],
        deployment_prerequisites=[
            str(p) for p in (feas_raw.get("deployment_prerequisites") or []) if p
        ],
    )

    links: list[CrossPaperLink] = []
    for item in data.get("cross_paper_links") or []:
        if isinstance(item, dict):
            links.append(
                CrossPaperLink(
                    target_paper_id=int(item.get("target_paper_id", 0)),
                    relation_type=str(item.get("relation_type", "")),
                    evidence=str(item.get("evidence", "")),
                )
            )

    return DeepReadingNote(
        algorithm_walkthrough=str(data.get("algorithm_walkthrough", "")),
        limitation_analysis=str(data.get("limitation_analysis", "")),
        reproducibility_assessment=str(data.get("reproducibility_assessment", "")),
        critical_assessment=str(data.get("critical_assessment", "")),
        industrial_feasibility=feasibility,
        research_implications=[
            str(r) for r in (data.get("research_implications") or []) if r
        ],
        cross_paper_links=links,
    )


@register_primitive(GET_DEEP_READING_SPEC)
def get_deep_reading(
    *,
    db: Any,
    paper_id: int,
    **_: Any,
) -> GetDeepReadingOutput:
    """Retrieve stored deep reading note from paper_annotations."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT content FROM paper_annotations "
            "WHERE paper_id = ? AND section = 'deep_reading'",
            (paper_id,),
        ).fetchone()
        if row is None or not (row["content"] or "").strip():
            return GetDeepReadingOutput(paper_id=paper_id, note=None, found=False)

        data = json.loads(row["content"])
        note = _parse_deep_reading_note(data)
        return GetDeepReadingOutput(paper_id=paper_id, note=note, found=True)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Failed to parse deep reading for paper %d: %s", paper_id, exc)
        return GetDeepReadingOutput(paper_id=paper_id, note=None, found=False)
    finally:
        conn.close()


@register_primitive(ENRICH_AFFILIATIONS_SPEC)
def enrich_affiliations(
    *,
    db: Any,
    paper_id: int,
    **_: Any,
) -> AffiliationOutput:
    """Extract affiliations from PDF first-page email domains."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            return AffiliationOutput(paper_id=paper_id, source="error")

        existing_raw = row["affiliations"] if "affiliations" in row.keys() else "[]"
        existing: list[str] = json.loads(existing_raw) if existing_raw else []

        first_page_text = _get_first_page_text(conn, paper_id, row)
        if not first_page_text:
            return AffiliationOutput(
                paper_id=paper_id,
                affiliations=existing,
                new_affiliations=[],
                source="no_text",
            )

        # Extract emails and map domains to institutions
        emails = re.findall(r"[\w.+-]+@[\w.-]+\.\w+", first_page_text)
        seen: set[str] = {a.lower() for a in existing}
        new_affiliations: list[str] = []
        for email in emails:
            domain = email.split("@", 1)[1]
            institution = _domain_to_institution(domain)
            if institution.lower() not in seen:
                seen.add(institution.lower())
                new_affiliations.append(institution)

        # Side effect: update papers.affiliations
        if new_affiliations:
            merged = existing + new_affiliations
            conn.execute(
                "UPDATE papers SET affiliations = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), paper_id),
            )
            conn.commit()

        return AffiliationOutput(
            paper_id=paper_id,
            affiliations=existing + new_affiliations,
            new_affiliations=new_affiliations,
            source="pdf_email_domain",
        )
    finally:
        conn.close()


def _get_first_page_text(conn: Any, paper_id: int, paper_row: Any) -> str:
    """Try to get first-page text from paperindex structure artifact or PDF."""
    # Try cached structure artifact first
    artifact = conn.execute(
        "SELECT path FROM paper_artifacts "
        "WHERE paper_id = ? AND artifact_type = 'paperindex_structure'",
        (paper_id,),
    ).fetchone()

    if artifact and artifact["path"]:
        structure_path = Path(artifact["path"])
        if structure_path.exists():
            try:
                structure_data = json.loads(structure_path.read_text())
                pages = structure_data.get("raw", {}).get("pages_text", [])
                if pages:
                    return str(pages[0])
            except Exception:
                pass

    # Fallback: extract from PDF directly
    pdf_path = paper_row["pdf_path"] if "pdf_path" in paper_row.keys() else None
    if pdf_path and Path(pdf_path).exists():
        try:
            from paperindex.indexing.page_index import extract_structure_tree

            structure = extract_structure_tree(pdf_path)
            pages = structure.raw.get("pages_text", [])
            if pages:
                return str(pages[0])
        except Exception:
            pass

    return ""
