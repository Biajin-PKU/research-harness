from __future__ import annotations

import os

import pytest

from research_harness.execution.harness import ResearchHarnessBackend


requires_kimi = pytest.mark.skipif(
    not os.environ.get("KIMI_API_KEY"),
    reason="KIMI_API_KEY not set",
)


@requires_kimi
class TestHarnessE2EKimi:
    def test_paper_summarize_real(self, db):
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
                (
                    "Attention Is All You Need",
                    "10.1000/attention-e2e",
                    "1706.03762-e2e",
                    "s2-attention-e2e",
                ),
            )
            paper_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                "INSERT INTO paper_annotations (paper_id, section, content) VALUES (?, ?, ?)",
                (
                    paper_id,
                    "summary",
                    "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose the Transformer, based solely on attention mechanisms and dispensing with recurrence and convolutions entirely.",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        backend = ResearchHarnessBackend(db=db)
        result = backend.execute("paper_summarize", paper_id=paper_id)

        assert result.success, f"Failed: {result.error}"
        assert result.backend == "research_harness"
        assert len(result.output.summary) > 50
        assert result.output.model_used != "none"

    def test_claim_extract_real(self, db):
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO papers (title, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?)",
                (
                    "BERT: Pre-training of Deep Bidirectional Transformers",
                    "10.1000/bert-e2e",
                    "1810.04805-e2e",
                    "s2-bert-e2e",
                ),
            )
            paper_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                "INSERT INTO paper_annotations (paper_id, section, content) VALUES (?, ?, ?)",
                (
                    paper_id,
                    "summary",
                    "We introduce BERT, which obtains new state-of-the-art results on eleven natural language processing tasks, including pushing the GLUE score to 80.5%, MultiNLI accuracy to 86.7%, and SQuAD v1.1 question answering F1 to 93.2%.",
                ),
            )
            conn.execute("INSERT INTO topics (name) VALUES (?)", ("e2e-test",))
            topic_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
                (paper_id, topic_id),
            )
            conn.commit()
        finally:
            conn.close()

        backend = ResearchHarnessBackend(db=db)
        result = backend.execute(
            "claim_extract",
            paper_ids=[paper_id],
            topic_id=topic_id,
        )

        assert result.success, f"Failed: {result.error}"
        assert len(result.output.claims) >= 1
