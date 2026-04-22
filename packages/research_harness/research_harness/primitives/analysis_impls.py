"""Phase 2 local (non-LLM) analysis primitives: reading_prioritize, experiment_design_checklist, dataset_index, author_coverage."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from typing import Any

from ..storage.db import Database
from .registry import (
    DATASET_INDEX_SPEC,
    AUTHOR_COVERAGE_SPEC,
    EXPERIMENT_DESIGN_CHECKLIST_SPEC,
    METRICS_AGGREGATE_SPEC,
    READING_PRIORITIZE_SPEC,
    TOPIC_EXPORT_SPEC,
    VISUALIZE_TOPIC_SPEC,
    register_primitive,
)
from .types import (
    AggregatedMetric,
    AuthorCoverageOutput,
    AuthorEntry,
    ChecklistItem,
    DatasetIndexOutput,
    DatasetEntry,
    ExperimentDesignChecklistOutput,
    MetricsAggregateOutput,
    PrioritizedPaper,
    ReadingPrioritizeOutput,
    TopicExportOutput,
    VisualizationOutput,
)

# ---------------------------------------------------------------------------
# reading_prioritize: rank unread papers by composite score
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {"gap": 0.4, "citation": 0.3, "recency": 0.3}
_CURRENT_YEAR = datetime.now().year
_RECENCY_HALFLIFE = 3  # years — score halves every 3 years


def _recency_decay(year: int | None) -> float:
    """Exponential decay: 1.0 for current year, ~0.5 for 3 years ago."""
    if not year:
        return 0.1  # unknown year gets low score
    age = max(0, _CURRENT_YEAR - year)
    return math.exp(-0.693 * age / _RECENCY_HALFLIFE)  # ln(2) ≈ 0.693


def _citation_score(count: int | None) -> float:
    """Log-scaled citation score, normalized to [0, 1] range for typical values."""
    if not count or count < 0:
        return 0.0
    # ln(count+1) / ln(1001) normalizes: 0 citations → 0, 1000 citations → 1.0
    return min(1.0, math.log(count + 1) / math.log(1001))


@register_primitive(READING_PRIORITIZE_SPEC)
def reading_prioritize(
    *,
    db: Database,
    topic_id: int,
    focus: str = "",
    limit: int = 20,
    weights: dict[str, float] | None = None,
    **_: Any,
) -> ReadingPrioritizeOutput:
    """Rank papers by composite score: gap relevance + citation + recency."""
    w = {**_DEFAULT_WEIGHTS, **(weights or {})}
    # Normalize weights to sum to 1
    total_w = sum(w.values()) or 1.0
    w = {k: v / total_w for k, v in w.items()}

    conn = db.connect()
    try:
        # Get all non-dismissed papers in topic
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.year, p.citation_count, p.status,
                   pt.relevance, p.compiled_summary
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM topic_paper_notes tpn
                  WHERE tpn.paper_id = p.id AND tpn.topic_id = pt.topic_id
                    AND tpn.note_type = 'user_dismissed'
              )
            """,
            (topic_id,),
        ).fetchall()

        # Gap relevance: papers with high relevance and unread status get boosted
        def _gap_relevance(row: Any) -> float:
            rel_map = {"high": 1.0, "medium": 0.6, "low": 0.3}
            base = rel_map.get(row["relevance"] or "medium", 0.6)
            # Unread papers (meta_only, no compiled summary) get a boost
            if row["status"] in ("meta_only", None) and not row["compiled_summary"]:
                base *= 1.2
            return min(1.0, base)

        scored: list[PrioritizedPaper] = []
        for row in rows:
            gap = _gap_relevance(row)
            cit = _citation_score(row["citation_count"])
            rec = _recency_decay(row["year"])
            total = w["gap"] * gap + w["citation"] * cit + w["recency"] * rec

            scored.append(
                PrioritizedPaper(
                    paper_id=int(row["id"]),
                    title=row["title"] or f"Paper #{row['id']}",
                    score=round(total, 4),
                    gap_relevance=round(gap, 4),
                    citation_score=round(cit, 4),
                    recency_score=round(rec, 4),
                )
            )

        scored.sort(key=lambda p: p.score, reverse=True)
        return ReadingPrioritizeOutput(
            ranked=scored[:limit],
            total_papers=len(scored),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# experiment_design_checklist: template-based, no LLM
# ---------------------------------------------------------------------------

_CHECKLIST_TEMPLATE: list[dict[str, str]] = [
    # Baselines
    {
        "category": "baselines",
        "item": "Include at least one well-known baseline from the literature",
    },
    {"category": "baselines", "item": "Include the current state-of-the-art method"},
    {
        "category": "baselines",
        "item": "Include a simple baseline (e.g., random, heuristic)",
    },
    # Metrics
    {
        "category": "metrics",
        "item": "Define primary evaluation metric with clear justification",
    },
    {"category": "metrics", "item": "Include secondary metrics for robustness"},
    {
        "category": "metrics",
        "item": "Report confidence intervals or statistical significance",
    },
    # Datasets
    {"category": "datasets", "item": "Use at least one standard benchmark dataset"},
    {
        "category": "datasets",
        "item": "Include dataset statistics (size, splits, class distribution)",
    },
    {"category": "datasets", "item": "Describe data preprocessing steps"},
    # Ablations
    {
        "category": "ablations",
        "item": "Ablate each key component of the proposed method",
    },
    {"category": "ablations", "item": "Test sensitivity to key hyperparameters"},
    {
        "category": "ablations",
        "item": "Analyze computational cost vs. performance tradeoff",
    },
    # Reproducibility
    {"category": "reproducibility", "item": "Report all hyperparameters used"},
    {"category": "reproducibility", "item": "Specify hardware and training time"},
    {
        "category": "reproducibility",
        "item": "Plan to release code and/or trained models",
    },
    # Analysis
    {"category": "analysis", "item": "Include qualitative examples / case studies"},
    {"category": "analysis", "item": "Analyze failure cases"},
    {
        "category": "analysis",
        "item": "Compare with related methods on shared evaluation settings",
    },
]


@register_primitive(EXPERIMENT_DESIGN_CHECKLIST_SPEC)
def experiment_design_checklist(
    *,
    db: Database,
    topic_id: int,
    method_name: str = "",
    **_: Any,
) -> ExperimentDesignChecklistOutput:
    """Generate a template-based experiment design checklist.

    Uses compiled summaries to pre-fill known baselines, metrics, and datasets.
    """
    conn = db.connect()
    try:
        # Gather known methods/metrics/datasets from compiled summaries
        rows = conn.execute(
            """
            SELECT p.compiled_summary FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ? AND p.compiled_summary IS NOT NULL AND p.compiled_summary != ''
            """,
            (topic_id,),
        ).fetchall()

        known_methods: set[str] = set()
        known_datasets: set[str] = set()
        known_metrics: set[str] = set()
        for row in rows:
            try:
                compiled = json.loads(row["compiled_summary"])
            except (json.JSONDecodeError, TypeError):
                continue
            for m in compiled.get("methods", []):
                if isinstance(m, str) and m:
                    known_methods.add(m)
            for met in compiled.get("metrics", []):
                if isinstance(met, dict):
                    ds = met.get("dataset", "")
                    metric = met.get("metric", "")
                    if ds:
                        known_datasets.add(ds)
                    if metric:
                        known_metrics.add(metric)
    finally:
        conn.close()

    # Build checklist with auto-filled notes
    items: list[ChecklistItem] = []
    for tpl in _CHECKLIST_TEMPLATE:
        notes = ""
        cat = tpl["category"]
        if cat == "baselines" and known_methods:
            notes = f"Known methods in topic: {', '.join(list(known_methods)[:5])}"
        elif cat == "datasets" and known_datasets:
            notes = f"Known datasets: {', '.join(list(known_datasets)[:5])}"
        elif cat == "metrics" and known_metrics:
            notes = f"Known metrics: {', '.join(list(known_metrics)[:5])}"

        items.append(
            ChecklistItem(
                category=cat,
                item=tpl["item"],
                status="pending",
                notes=notes,
            )
        )

    # Completeness = fraction of items with notes (rough proxy for topic coverage)
    filled = sum(1 for i in items if i.notes) / max(len(items), 1)

    return ExperimentDesignChecklistOutput(
        checklist=items,
        completeness_score=round(filled, 2),
    )


# ---------------------------------------------------------------------------
# dataset_index: extract dataset usage from compiled summaries
# ---------------------------------------------------------------------------


@register_primitive(DATASET_INDEX_SPEC)
def dataset_index(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> DatasetIndexOutput:
    """Build a dataset index from compiled summaries — which datasets are used by which papers."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.compiled_summary FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ? AND p.compiled_summary IS NOT NULL AND p.compiled_summary != ''
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    ds_papers: dict[str, set[int]] = defaultdict(set)
    ds_metrics: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        pid = int(row["id"])
        try:
            compiled = json.loads(row["compiled_summary"])
        except (json.JSONDecodeError, TypeError):
            continue
        for met in compiled.get("metrics", []):
            if isinstance(met, dict):
                ds = met.get("dataset", "")
                metric = met.get("metric", "")
                if ds:
                    ds_papers[ds].add(pid)
                    if metric:
                        ds_metrics[ds].add(metric)

    entries = []
    for ds in sorted(ds_papers.keys()):
        entries.append(
            DatasetEntry(
                dataset=ds,
                paper_ids=sorted(ds_papers[ds]),
                metrics=sorted(ds_metrics.get(ds, set())),
                count=len(ds_papers[ds]),
            )
        )

    entries.sort(key=lambda e: e.count, reverse=True)
    return DatasetIndexOutput(datasets=entries, total_papers=len(rows))


# ---------------------------------------------------------------------------
# author_coverage: check which authors are represented in the paper pool
# ---------------------------------------------------------------------------


@register_primitive(AUTHOR_COVERAGE_SPEC)
def author_coverage(
    *,
    db: Database,
    topic_id: int,
    author_name: str = "",
    **_: Any,
) -> AuthorCoverageOutput:
    """List authors and their paper counts in the topic pool."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.authors FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
              AND p.authors IS NOT NULL AND p.authors != ''
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    author_papers: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        pid = int(row["id"])
        authors_raw = row["authors"] or ""
        # Authors stored as comma-separated string
        for a in authors_raw.split(","):
            name = a.strip()
            if name:
                author_papers[name].append(pid)

    # Filter by author_name if provided
    if author_name:
        needle = author_name.lower()
        author_papers = {k: v for k, v in author_papers.items() if needle in k.lower()}

    entries = [
        AuthorEntry(name=name, paper_ids=pids, paper_count=len(pids))
        for name, pids in author_papers.items()
    ]
    entries.sort(key=lambda e: e.paper_count, reverse=True)

    return AuthorCoverageOutput(
        authors=entries[:50],
        total_papers=len(rows),
    )


# ---------------------------------------------------------------------------
# metrics_aggregate: combine extracted tables + compiled summaries into a unified metrics table
# ---------------------------------------------------------------------------


@register_primitive(METRICS_AGGREGATE_SPEC)
def metrics_aggregate(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> MetricsAggregateOutput:
    """Aggregate metrics from extracted tables and compiled summaries with provenance."""
    conn = db.connect()
    try:
        # Source 1: extracted_tables (high confidence)
        table_rows = conn.execute(
            """
            SELECT et.paper_id, et.table_number, et.headers, et.rows, et.caption
            FROM extracted_tables et
            JOIN paper_topics pt ON pt.paper_id = et.paper_id
            WHERE pt.topic_id = ?
            """,
            (topic_id,),
        ).fetchall()

        # Source 2: compiled_summary metrics (lower confidence)
        summary_rows = conn.execute(
            """
            SELECT p.id as paper_id, p.compiled_summary
            FROM papers p
            JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ? AND p.compiled_summary IS NOT NULL AND p.compiled_summary != ''
            """,
            (topic_id,),
        ).fetchall()

        metrics: list[AggregatedMetric] = []
        methods_set: set[str] = set()
        datasets_set: set[str] = set()

        # Process extracted tables
        for trow in table_rows:
            try:
                headers = json.loads(trow["headers"])
                rows = json.loads(trow["rows"])
            except (json.JSONDecodeError, TypeError):
                continue

            pid = int(trow["paper_id"])
            table_num = trow["table_number"]

            # Heuristic: first column is usually the method, remaining are metrics on datasets
            if len(headers) < 2 or not rows:
                continue

            for row_idx, row in enumerate(rows):
                if not row or len(row) < 2:
                    continue
                method = str(row[0]).strip()
                if not method:
                    continue
                methods_set.add(method)

                for col_idx in range(1, min(len(row), len(headers))):
                    value = str(row[col_idx]).strip()
                    if not value or value == "-":
                        continue

                    metric_name = str(headers[col_idx]).strip()
                    # Try to parse dataset from caption or metric name
                    caption = trow["caption"] or ""
                    dataset = ""
                    for part in caption.split():
                        if len(part) > 3 and part[0].isupper():
                            dataset = part
                            break

                    if dataset:
                        datasets_set.add(dataset)

                    conn.execute(
                        """
                        INSERT INTO aggregated_metrics
                        (topic_id, paper_id, method, dataset, metric, value, source_type, source_ref, confidence)
                        VALUES (?, ?, ?, ?, ?, ?, 'table', ?, 0.8)
                        """,
                        (
                            topic_id,
                            pid,
                            method,
                            dataset,
                            metric_name,
                            value,
                            f"Table {table_num}, row {row_idx + 1}",
                        ),
                    )
                    mid_row = conn.execute(
                        "SELECT last_insert_rowid() as id"
                    ).fetchone()
                    metrics.append(
                        AggregatedMetric(
                            metric_id=mid_row["id"] if mid_row else 0,
                            paper_id=pid,
                            method=method,
                            dataset=dataset,
                            metric=metric_name,
                            value=value,
                            source_type="table",
                            source_ref=f"Table {table_num}, row {row_idx + 1}",
                            confidence=0.8,
                        )
                    )

        # Process compiled summaries
        for srow in summary_rows:
            pid = int(srow["paper_id"])
            try:
                compiled = json.loads(srow["compiled_summary"])
            except (json.JSONDecodeError, TypeError):
                continue

            for met in compiled.get("metrics", []):
                if not isinstance(met, dict):
                    continue
                ds = met.get("dataset", "")
                metric = met.get("metric", "")
                value = str(met.get("value", ""))
                _baseline = met.get("baseline", "")

                if not metric or not value:
                    continue

                method = ""
                for m in compiled.get("methods", []):
                    if isinstance(m, str):
                        method = m
                        break

                if method:
                    methods_set.add(method)
                if ds:
                    datasets_set.add(ds)

                conn.execute(
                    """
                    INSERT INTO aggregated_metrics
                    (topic_id, paper_id, method, dataset, metric, value, source_type, source_ref, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, 'text', 'compiled_summary', 0.5)
                    """,
                    (topic_id, pid, method, ds, metric, value),
                )
                mid_row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
                metrics.append(
                    AggregatedMetric(
                        metric_id=mid_row["id"] if mid_row else 0,
                        paper_id=pid,
                        method=method,
                        dataset=ds,
                        metric=metric,
                        value=value,
                        source_type="text",
                        source_ref="compiled_summary",
                        confidence=0.5,
                    )
                )

        conn.commit()
        papers_processed = len(set(m.paper_id for m in metrics))
    finally:
        conn.close()

    return MetricsAggregateOutput(
        metrics=metrics,
        methods=sorted(methods_set),
        datasets=sorted(datasets_set),
        papers_processed=papers_processed,
    )


# ---------------------------------------------------------------------------
# Phase 4: topic_export — structured markdown report
# ---------------------------------------------------------------------------


@register_primitive(TOPIC_EXPORT_SPEC)
def topic_export(
    *,
    db: Database,
    topic_id: int,
    **_: Any,
) -> TopicExportOutput:
    """Export a topic overview as a structured markdown report."""
    conn = db.connect()
    try:
        topic_row = conn.execute(
            "SELECT name, description FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        if not topic_row:
            return TopicExportOutput(markdown="Topic not found.")

        topic_name = topic_row["name"]
        description = topic_row["description"] or ""

        # Paper stats
        papers = conn.execute(
            """
            SELECT p.id, p.title, p.year, p.venue, p.citation_count, p.status, pt.relevance
            FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            ORDER BY COALESCE(p.citation_count, 0) DESC
            """,
            (topic_id,),
        ).fetchall()

        # Method taxonomy
        tax_nodes = conn.execute(
            "SELECT name, description, aliases FROM taxonomy_nodes WHERE topic_id = ? ORDER BY name",
            (topic_id,),
        ).fetchall()

        # Normalized claims count
        claims_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM normalized_claims WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()["cnt"]

        # Contradictions
        contradictions = conn.execute(
            """
            SELECT c.conflict_reason, ca.claim_text as claim_a, cb.claim_text as claim_b
            FROM contradictions c
            JOIN normalized_claims ca ON ca.id = c.claim_a_id
            JOIN normalized_claims cb ON cb.id = c.claim_b_id
            WHERE c.topic_id = ? AND c.status = 'candidate'
            ORDER BY c.confidence DESC LIMIT 10
            """,
            (topic_id,),
        ).fetchall()

        # Gaps (from project_artifacts)
        gaps = conn.execute(
            """
            SELECT payload_json FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'gaps' AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchall()

        # Venue distribution
        venues = conn.execute(
            """
            SELECT COALESCE(p.venue, '(unknown)') as venue, COUNT(*) as cnt
            FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ?
            GROUP BY venue ORDER BY cnt DESC LIMIT 10
            """,
            (topic_id,),
        ).fetchall()

    finally:
        conn.close()

    # Build markdown
    sections: list[str] = []
    md_parts: list[str] = []

    # Header
    md_parts.append(f"# Topic Report: {topic_name}\n")
    if description:
        md_parts.append(f"{description}\n")

    # Statistics
    sections.append("statistics")
    md_parts.append("## Statistics\n")
    md_parts.append(f"- **Total papers:** {len(papers)}")
    md_parts.append(f"- **Normalized claims:** {claims_count}")
    md_parts.append(f"- **Contradictions detected:** {len(contradictions)}")
    md_parts.append(f"- **Methods in taxonomy:** {len(tax_nodes)}")
    if venues:
        md_parts.append("\n### Venue Distribution\n")
        for v in venues:
            md_parts.append(f"- {v['venue']}: {v['cnt']}")

    # Top papers
    sections.append("top_papers")
    md_parts.append("\n## Top Papers (by citations)\n")
    for p in papers[:15]:
        cite = p["citation_count"] or 0
        year = p["year"] or "?"
        venue = p["venue"] or ""
        md_parts.append(
            f"- [{p['id']}] {p['title']} ({year}) {venue} — {cite} citations [{p['relevance']}]"
        )

    # Method taxonomy
    if tax_nodes:
        sections.append("method_taxonomy")
        md_parts.append("\n## Method Taxonomy\n")
        for n in tax_nodes:
            aliases_raw = n["aliases"] or "[]"
            try:
                aliases = json.loads(aliases_raw)
            except (json.JSONDecodeError, TypeError):
                aliases = []
            alias_str = f" (aka: {', '.join(aliases)})" if aliases else ""
            md_parts.append(f"- **{n['name']}**{alias_str}: {n['description']}")

    # Contradictions
    if contradictions:
        sections.append("contradictions")
        md_parts.append("\n## Detected Contradictions\n")
        for c in contradictions:
            md_parts.append(f"- **Claim A:** {c['claim_a']}")
            md_parts.append(f"  **Claim B:** {c['claim_b']}")
            md_parts.append(f"  **Reason:** {c['conflict_reason']}\n")

    # Gaps
    if gaps:
        sections.append("gaps")
        md_parts.append("\n## Research Gaps\n")
        try:
            gap_data = json.loads(gaps[0]["payload_json"])
            for g in gap_data.get("gaps", [])[:10]:
                if isinstance(g, dict):
                    md_parts.append(
                        f"- [{g.get('severity', '?')}] {g.get('description', '')}"
                    )
        except (json.JSONDecodeError, TypeError):
            pass

    # Timeline
    sections.append("timeline")
    years: dict[int, int] = defaultdict(int)
    for p in papers:
        if p["year"]:
            years[p["year"]] += 1
    if years:
        md_parts.append("\n## Publication Timeline\n")
        for y in sorted(years.keys()):
            bar = "█" * min(years[y], 40)
            md_parts.append(f"- {y}: {bar} ({years[y]})")

    markdown = "\n".join(md_parts)
    return TopicExportOutput(
        markdown=markdown,
        topic_name=topic_name,
        paper_count=len(papers),
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Phase 4: visualize_topic — Mermaid diagram generation
# ---------------------------------------------------------------------------


@register_primitive(VISUALIZE_TOPIC_SPEC)
def visualize_topic(
    *,
    db: Database,
    topic_id: int,
    viz_type: str = "paper_graph",
    **_: Any,
) -> VisualizationOutput:
    """Generate Mermaid visualizations for a topic."""
    if viz_type == "paper_graph":
        return _viz_paper_graph(db, topic_id)
    elif viz_type == "taxonomy_tree":
        return _viz_taxonomy_tree(db, topic_id)
    elif viz_type == "timeline":
        return _viz_timeline(db, topic_id)
    else:
        return VisualizationOutput(
            mermaid_code="", viz_type=viz_type, title="Unknown viz type"
        )


def _viz_paper_graph(db: Database, topic_id: int) -> VisualizationOutput:
    """Generate a paper relationship graph from normalized claims."""
    conn = db.connect()
    try:
        # Get papers with claims
        papers = conn.execute(
            """
            SELECT DISTINCT p.id, p.title, p.year
            FROM papers p
            JOIN normalized_claims nc ON nc.paper_id = p.id
            WHERE nc.topic_id = ?
            """,
            (topic_id,),
        ).fetchall()

        # Get contradictions as edges
        contras = conn.execute(
            """
            SELECT ca.paper_id as paper_a, cb.paper_id as paper_b, c.conflict_reason
            FROM contradictions c
            JOIN normalized_claims ca ON ca.id = c.claim_a_id
            JOIN normalized_claims cb ON cb.id = c.claim_b_id
            WHERE c.topic_id = ?
            """,
            (topic_id,),
        ).fetchall()

        # Get shared methods as edges
        shared = conn.execute(
            """
            SELECT nc1.paper_id as p1, nc2.paper_id as p2, nc1.method
            FROM normalized_claims nc1
            JOIN normalized_claims nc2 ON nc1.method = nc2.method AND nc1.paper_id < nc2.paper_id
            WHERE nc1.topic_id = ? AND nc1.method != ''
            GROUP BY nc1.paper_id, nc2.paper_id
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    lines = ["graph LR"]
    for p in papers:
        label = (p["title"] or f"P{p['id']}")[:30]
        lines.append(f'    P{p["id"]}["{label}"]')

    for e in shared[:30]:
        lines.append(f"    P{e['p1']} -->|{e['method'][:15]}| P{e['p2']}")

    for c in contras[:10]:
        lines.append(f"    P{c['paper_a']} -.-x|conflict| P{c['paper_b']}")

    return VisualizationOutput(
        mermaid_code="\n".join(lines),
        viz_type="paper_graph",
        title="Paper Relationship Graph",
        node_count=len(papers),
    )


def _viz_taxonomy_tree(db: Database, topic_id: int) -> VisualizationOutput:
    """Generate a method taxonomy tree diagram."""
    conn = db.connect()
    try:
        nodes = conn.execute(
            "SELECT id, name, parent_id FROM taxonomy_nodes WHERE topic_id = ? ORDER BY id",
            (topic_id,),
        ).fetchall()
        # Count assignments per node
        counts = {}
        for n in nodes:
            cnt = conn.execute(
                "SELECT COUNT(*) as cnt FROM taxonomy_assignments WHERE node_id = ?",
                (n["id"],),
            ).fetchone()
            counts[n["id"]] = cnt["cnt"] if cnt else 0
    finally:
        conn.close()

    lines = ["graph TD"]
    lines.append('    ROOT["Methods"]')

    for n in nodes:
        nid = n["id"]
        label = f"{n['name']} ({counts.get(nid, 0)})"
        lines.append(f'    N{nid}["{label}"]')

        parent = n["parent_id"]
        if parent:
            lines.append(f"    N{parent} --> N{nid}")
        else:
            lines.append(f"    ROOT --> N{nid}")

    return VisualizationOutput(
        mermaid_code="\n".join(lines),
        viz_type="taxonomy_tree",
        title="Method Taxonomy",
        node_count=len(nodes),
    )


def _viz_timeline(db: Database, topic_id: int) -> VisualizationOutput:
    """Generate a publication timeline diagram."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.year, COUNT(*) as cnt,
                   GROUP_CONCAT(SUBSTR(p.title, 1, 25), ' | ') as titles
            FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
            WHERE pt.topic_id = ? AND p.year IS NOT NULL
            GROUP BY p.year ORDER BY p.year
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    lines = ["gantt", "    title Publication Timeline", "    dateFormat YYYY"]
    for r in rows:
        year = r["year"]
        cnt = r["cnt"]
        lines.append(f"    {year} ({cnt} papers) : {year}, 1y")

    return VisualizationOutput(
        mermaid_code="\n".join(lines),
        viz_type="timeline",
        title="Publication Timeline",
        node_count=len(rows),
    )
