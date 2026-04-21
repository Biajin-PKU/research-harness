"""Write stage eval cases — section drafting, review, consistency."""

from ..models import EvalCase

WRITE_CASES = [
    EvalCase(
        id="write-001",
        stage="write",
        description="Section draft produces content with citations",
        input_data={"section": "related_work", "topic_id": 1, "max_words": 500},
        expected={"required_fields": ["draft"], "regex": r"\\\\cite\{|[\[\(]\d+[\]\)]"},
        grader_type="deterministic",
        tags=["write", "draft", "citations"],
    ),
    EvalCase(
        id="write-002",
        stage="write",
        description="Section review scores all 10 dimensions",
        input_data={"section": "method", "content": "Test content for review."},
        expected={"required_fields": ["section", "overall_score", "dimensions", "suggestions"]},
        grader_type="deterministic",
        tags=["write", "review"],
    ),
    EvalCase(
        id="write-003",
        stage="write",
        description="Consistency check detects contradictions",
        input_data={"topic_id": 1, "sections": ["introduction", "method"]},
        expected={"required_fields": ["issues", "sections_checked"]},
        grader_type="deterministic",
        tags=["write", "consistency"],
    ),
    EvalCase(
        id="write-004",
        stage="write",
        description="Outline generates all standard sections",
        input_data={"topic_id": 1, "project_id": 1, "template": "neurips"},
        expected={"min_count": 5, "count_key": "sections"},
        grader_type="deterministic",
        tags=["write", "outline"],
    ),
    EvalCase(
        id="write-005",
        stage="write",
        description="Section revise produces different content than input",
        input_data={"section": "method", "content": "Original text.", "review_feedback": "Add more detail."},
        expected={"required_fields": ["section", "revised_content", "changes_made"]},
        grader_type="deterministic",
        tags=["write", "revision"],
    ),
]
