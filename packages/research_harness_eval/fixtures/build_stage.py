"""Build stage eval cases — literature coverage and quality."""

from ..models import EvalCase

BUILD_CASES = [
    EvalCase(
        id="build-001",
        stage="build",
        description="Paper search returns results for well-known topic",
        input_data={"query": "auto-bidding advertising optimization", "max_results": 10},
        expected={"min_count": 3, "count_key": "papers"},
        grader_type="deterministic",
        tags=["build", "search", "smoke"],
    ),
    EvalCase(
        id="build-002",
        stage="build",
        description="Coverage check identifies meta_only papers",
        input_data={"topic_id": 1},
        expected={"required_fields": ["items", "total_meta_only", "high_necessity_count"]},
        grader_type="deterministic",
        tags=["build", "coverage"],
    ),
    EvalCase(
        id="build-003",
        stage="build",
        description="Build gate requires minimum 20 papers",
        input_data={"project_id": 1, "stage": "build"},
        expected={"output_type": "str", "contains": ["coverage", "pass"]},
        grader_type="deterministic",
        tags=["build", "gate", "regression"],
    ),
    EvalCase(
        id="build-004",
        stage="build",
        description="Dismissed papers excluded from coverage count",
        input_data={"topic_id": 1, "with_dismissed": True},
        expected={"min_score": 0.0, "score_key": "excluded_count"},
        grader_type="deterministic",
        tags=["build", "gate", "bug-fix", "regression"],
    ),
    EvalCase(
        id="build-005",
        stage="build",
        description="Citation expansion finds forward and backward refs",
        input_data={"seed_paper_ids": [1, 2], "topic_id": 1},
        expected={"min_count": 1, "count_key": "candidates"},
        grader_type="deterministic",
        tags=["build", "expansion"],
    ),
]
