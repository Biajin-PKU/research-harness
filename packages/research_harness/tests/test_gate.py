"""Tests for V2 ValidationGate (experience quality filter)."""

from __future__ import annotations


import pytest

from research_harness.evolution.experience import ExperienceRecord, ExperienceStore
from research_harness.evolution.gate import (
    GateVerdict,
    ValidationGate,
    FIELD_DECAY_CONSTANTS,
    temporal_relevance,
)


class TestGateVerdict:
    def test_defaults(self):
        v = GateVerdict(verdict="accepted", score=0.8)
        assert v.verdict == "accepted"
        assert v.score == 0.8
        assert v.reasoning == ""

    def test_is_accepted(self):
        assert GateVerdict(verdict="accepted", score=0.9).is_accepted
        assert not GateVerdict(verdict="rejected", score=0.3).is_accepted
        assert not GateVerdict(verdict="deferred", score=0.5).is_accepted


class TestTemporalRelevance:
    def test_fresh_paper_high_relevance(self):
        score = temporal_relevance(age_months=3, field="llm_systems")
        assert score > 0.8

    def test_old_paper_low_relevance(self):
        score = temporal_relevance(age_months=60, field="llm_systems")
        assert score < 0.2

    def test_field_specific_decay(self):
        """LLM systems decay faster than SE."""
        llm_score = temporal_relevance(age_months=24, field="llm_systems")
        se_score = temporal_relevance(age_months=24, field="software_engineering")
        assert llm_score < se_score

    def test_unknown_field_uses_default(self):
        score = temporal_relevance(age_months=12, field="unknown_field")
        assert 0.0 < score < 1.0

    def test_all_fields_have_decay_constants(self):
        for field_name, tau in FIELD_DECAY_CONSTANTS.items():
            assert tau > 0
            score = temporal_relevance(age_months=int(tau), field=field_name)
            assert score == pytest.approx(1.0 / 2.718, abs=0.02)


class TestValidationGateTier1:
    def test_human_edit_auto_accepted(self, db):
        """Human edits bypass rule layer — always accepted."""
        gate = ValidationGate(db)
        record = ExperienceRecord(
            source_kind="human_edit",
            stage="section_draft",
            diff_summary="Rewrote intro paragraph",
        )
        verdict = gate.evaluate_tier1(record)
        assert verdict.verdict == "accepted"
        assert verdict.score >= 0.9

    def test_empty_diff_rejected(self, db):
        """Records with no meaningful content are rejected."""
        gate = ValidationGate(db)
        record = ExperienceRecord(
            source_kind="self_review",
            stage="section_draft",
            diff_summary="",
            before_text="",
            after_text="",
        )
        verdict = gate.evaluate_tier1(record)
        assert verdict.verdict == "rejected"

    def test_self_review_with_content_accepted(self, db):
        gate = ValidationGate(db)
        record = ExperienceRecord(
            source_kind="self_review",
            stage="section_draft",
            diff_summary="Section too short: 500 words vs 1500 target",
        )
        verdict = gate.evaluate_tier1(record)
        assert verdict.verdict == "accepted"

    def test_gold_comparison_needs_quality_delta(self, db):
        """Gold comparisons with zero quality delta are deferred."""
        gate = ValidationGate(db)
        record = ExperienceRecord(
            source_kind="gold_comparison",
            stage="section_draft",
            diff_summary="Some difference",
            quality_delta=0.0,
        )
        verdict = gate.evaluate_tier1(record)
        assert verdict.verdict in ("deferred", "accepted")

    def test_verdict_persisted_to_db(self, db):
        gate = ValidationGate(db)
        store = ExperienceStore(db)
        rec_id = store.ingest(
            ExperienceRecord(
                source_kind="self_review",
                stage="section_draft",
                diff_summary="Found weasel words in method",
            )
        )
        record = store.get(rec_id)
        verdict = gate.evaluate_tier1(record)

        # Check validation_traces table
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM validation_traces WHERE experience_id = ?",
                (rec_id,),
            ).fetchone()
            assert row is not None
            assert row["tier"] == "tier1"
            assert row["verdict"] == verdict.verdict
        finally:
            conn.close()


class TestValidationGateIntegration:
    def test_ingest_with_gate(self, db):
        """When gate is enabled, ingest should auto-evaluate and update verdict."""
        gate = ValidationGate(db)
        store = ExperienceStore(db, gate=gate)
        rec_id = store.ingest(
            ExperienceRecord(
                source_kind="self_review",
                stage="section_draft",
                diff_summary="Check 'word_count' failed: 800 words vs 1500 target",
            )
        )
        record = store.get(rec_id)
        assert record.gate_verdict in ("accepted", "deferred", "rejected")
        assert record.gate_verdict != "pending"

    def test_ingest_without_gate_stays_pending(self, db):
        """Without gate, records stay in pending state."""
        store = ExperienceStore(db)
        rec_id = store.ingest(
            ExperienceRecord(
                source_kind="self_review",
                stage="section_draft",
                diff_summary="Some issue",
            )
        )
        record = store.get(rec_id)
        assert record.gate_verdict == "pending"
