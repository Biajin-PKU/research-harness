"""Analyze stage eval cases — claim extraction, gap detection, baselines."""

from ..models import EvalCase

ANALYZE_CASES = [
    EvalCase(
        id="analyze-001",
        stage="analyze",
        description="Claim extraction produces structured claims from papers",
        input_data={"paper_ids": [1, 2, 3], "topic_id": 1},
        expected={"min_count": 1, "count_key": "claims", "required_fields": ["claims", "papers_processed"]},
        grader_type="deterministic",
        tags=["analyze", "claims", "smoke"],
    ),
    EvalCase(
        id="analyze-002",
        stage="analyze",
        description="Gap detection identifies research gaps",
        input_data={"topic_id": 1},
        expected={"min_count": 1, "count_key": "gaps", "required_fields": ["gaps", "papers_analyzed"]},
        grader_type="deterministic",
        tags=["analyze", "gaps"],
    ),
    EvalCase(
        id="analyze-003",
        stage="analyze",
        description="Baseline identification finds comparison methods",
        input_data={"topic_id": 1},
        expected={"min_count": 1, "count_key": "baselines"},
        grader_type="deterministic",
        tags=["analyze", "baselines"],
    ),
    EvalCase(
        id="analyze-004",
        stage="analyze",
        description="Claims have required structure (content, evidence_type, confidence)",
        input_data={"paper_ids": [1], "topic_id": 1},
        expected={"required_fields": ["claims"]},
        grader_type="deterministic",
        tags=["analyze", "claims", "schema"],
    ),
]
