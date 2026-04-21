"""Tests for auto_runner/llm_planner — LLM-driven stage context generation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from research_harness.auto_runner.llm_planner import (
    _call_planner_llm,
    _gather_artifact_payload,
    _gather_topic_meta,
    _get_paper_count,
    _get_top_papers,
    _plan_analyze,
    _plan_build,
    _plan_experiment,
    _plan_propose,
    _plan_write,
    plan_stage,
)
from research_harness.storage.db import Database


def _make_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "planner_test.db")
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, target_venue) "
            "VALUES ('multimodal-ts', 'Multimodal time series forecasting', 'KDD')"
        )
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) "
            "VALUES (1, 'proj1', 'test project')"
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _add_papers(db: Database, topic_id: int, n: int = 5) -> list[int]:
    conn = db.connect()
    ids = []
    try:
        for i in range(n):
            cur = conn.execute(
                "INSERT INTO papers (title, year, venue, citation_count, s2_id, doi, arxiv_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"Paper {i}", 2024, "NeurIPS", 100 - i * 10,
                 f"s2_{topic_id}_{i}", f"10.1234/{topic_id}.{i}", f"2401.{topic_id:02d}{i:03d}"),
            )
            pid = cur.lastrowid
            ids.append(pid)
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
                (pid, topic_id, "high"),
            )
        conn.commit()
    finally:
        conn.close()
    return ids


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


class TestDBHelpers:
    def test_gather_topic_meta(self, tmp_path):
        db = _make_db(tmp_path)
        meta = _gather_topic_meta(db, 1)
        assert meta["name"] == "multimodal-ts"
        assert meta["target_venue"] == "KDD"

    def test_gather_topic_meta_missing(self, tmp_path):
        db = _make_db(tmp_path)
        meta = _gather_topic_meta(db, 999)
        assert meta["name"] == ""

    def test_get_paper_count(self, tmp_path):
        db = _make_db(tmp_path)
        _add_papers(db, 1, n=3)
        assert _get_paper_count(db, 1) == 3
        assert _get_paper_count(db, 999) == 0

    def test_get_top_papers(self, tmp_path):
        db = _make_db(tmp_path)
        _add_papers(db, 1, n=5)
        papers = _get_top_papers(db, 1, limit=3)
        assert len(papers) == 3
        assert papers[0]["citation_count"] >= papers[1]["citation_count"]


# ---------------------------------------------------------------------------
# plan_stage dispatch
# ---------------------------------------------------------------------------


class TestPlanStageDispatch:
    def test_init_returns_topic_meta(self, tmp_path):
        db = _make_db(tmp_path)
        svc = MagicMock()
        result = plan_stage(
            db=db, svc=svc, project_id=1, topic_id=1,
            stage="init", checkpoint_data={},
        )
        assert result["topic_description"]
        assert result["query"]
        assert result["project_id"] == 1

    def test_unknown_stage_returns_empty(self, tmp_path):
        db = _make_db(tmp_path)
        svc = MagicMock()
        result = plan_stage(
            db=db, svc=svc, project_id=1, topic_id=1,
            stage="unknown_stage", checkpoint_data={},
        )
        assert result == {}

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_planner_failure_returns_empty(self, mock_llm, tmp_path):
        mock_llm.side_effect = RuntimeError("LLM unavailable")
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = plan_stage(
            db=db, svc=svc, project_id=1, topic_id=1,
            stage="build", checkpoint_data={},
        )
        assert result == {}

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_plan_stage_sets_project_id(self, mock_llm, tmp_path):
        mock_llm.return_value = {"query": "test query"}
        db = _make_db(tmp_path)
        svc = MagicMock()
        result = plan_stage(
            db=db, svc=svc, project_id=42, topic_id=1,
            stage="build", checkpoint_data={},
        )
        assert result["project_id"] == 42


# ---------------------------------------------------------------------------
# Per-stage planners
# ---------------------------------------------------------------------------


class TestPlanBuild:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_generates_query(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "query": "multimodal time series forecasting",
            "additional_queries": ["temporal fusion", "cross-modal attention"],
            "auto_ingest": True,
            "max_results": 500,
        }
        db = _make_db(tmp_path)
        result = _plan_build(
            db=db, svc=MagicMock(), project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert result["query"] == "multimodal time series forecasting"
        assert result["auto_ingest"] is True
        assert result["max_results"] == 500

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_fallback_on_empty_query(self, mock_llm, tmp_path):
        mock_llm.return_value = {}
        db = _make_db(tmp_path)
        result = _plan_build(
            db=db, svc=MagicMock(), project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert result["query"]  # falls back to topic description
        assert result["auto_ingest"] is True
        assert result["seed_top_n"] == 10


class TestPlanAnalyze:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_selects_papers(self, mock_llm, tmp_path):
        db = _make_db(tmp_path)
        paper_ids = _add_papers(db, 1, n=10)
        mock_llm.return_value = {
            "paper_ids": paper_ids[:5],
            "focus": "cross-modal attention mechanisms",
        }
        result = _plan_analyze(
            db=db, svc=MagicMock(), project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert len(result["paper_ids"]) == 5
        assert result["focus"] == "cross-modal attention mechanisms"

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_fallback_on_empty_paper_ids(self, mock_llm, tmp_path):
        db = _make_db(tmp_path)
        paper_ids = _add_papers(db, 1, n=10)
        mock_llm.return_value = {}
        result = _plan_analyze(
            db=db, svc=MagicMock(), project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert len(result["paper_ids"]) > 0


class TestPlanPropose:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_reads_artifacts(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "artifact_type": "direction_proposal",
            "artifact_title": "ModalGate: Adaptive Gating",
            "artifact_payload": {"direction": "adaptive gating"},
            "focus": "gating mechanisms",
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_propose(
            db=db, svc=svc, project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert result["artifact_type"] == "direction_proposal"
        assert result["artifact_title"] == "ModalGate: Adaptive Gating"


class TestPlanExperiment:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_reads_study_spec(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "study_spec": "Implement ModalGate with 6 experiment groups",
            "primary_metric": "mse",
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_experiment(
            db=db, svc=svc, project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert result["study_spec"] == "Implement ModalGate with 6 experiment groups"
        assert result["primary_metric"] == "mse"


class TestPlanWrite:
    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_generates_sections(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "venue": "KDD",
            "contributions": "We propose ModalGate...",
            "outline": "1. Intro 2. Related 3. Method 4. Experiments 5. Conclusion",
            "sections_to_draft": ["introduction", "related_work", "method",
                                   "experiments", "conclusion"],
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_write(
            db=db, svc=svc, project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert result["venue"] == "KDD"
        assert len(result["sections_to_draft"]) == 5
        assert "introduction" in result["sections_to_draft"]

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_fallback_sections(self, mock_llm, tmp_path):
        mock_llm.return_value = {}
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_write(
            db=db, svc=svc, project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert len(result["sections_to_draft"]) == 5


# ---------------------------------------------------------------------------
# LLM call wrapper
# ---------------------------------------------------------------------------


class TestCallPlannerLLM:
    @patch("research_harness.execution.llm_primitives._client_chat",
           return_value="This is not JSON at all {{")
    @patch("research_harness.execution.llm_primitives._get_client")
    def test_bad_json_returns_empty(self, mock_get_client, mock_chat):
        """When LLM returns non-JSON, _call_planner_llm returns empty dict."""
        from research_harness.auto_runner.llm_planner import _call_planner_llm

        result = _call_planner_llm("test prompt")
        assert result == {}


# ---------------------------------------------------------------------------
# Integration: planner in executor
# ---------------------------------------------------------------------------


class TestPlannerInExecutor:
    def test_planner_enriches_context(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService

        db = _make_db(tmp_path)
        svc = OrchestratorService(db)

        cp = ckpt.new_checkpoint(1, 1)
        cp["current_stage"] = "build"

        planner_output = {"query": "test-from-planner", "auto_ingest": True}

        with _patch("research_harness.auto_runner.llm_planner.plan_stage",
                     return_value=planner_output) as mock_plan, \
             _patch("research_harness.auto_runner.stage_executor._execute_stage_tools",
                    return_value={"summary": "ok", "tool_results": [], "errors": []}) as mock_exec:

            result = execute_stage(
                db=db, svc=svc, project_id=1, topic_id=1,
                stage="build", mode="standard",
                checkpoint_data=cp, base_dir=tmp_path,
            )

            mock_plan.assert_called_once()
            assert cp["stage_context"]["query"] == "test-from-planner"


# ---------------------------------------------------------------------------
# Multi-section loop in tool_dispatch
# ---------------------------------------------------------------------------


class TestMultiSectionLoop:
    def test_section_draft_called_per_section(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db = _make_db(tmp_path)
        svc = MagicMock()

        context = {
            "sections_to_draft": ["introduction", "method", "conclusion"],
            "outline": "test outline",
            "evidence_ids": [],
        }

        with _patch("research_harness.auto_runner.tool_dispatch.dispatch") as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                tool="section_draft", success=True,
                output={"text": "drafted"}, error="",
            )

            result = dispatch_stage_tools(
                db=db, svc=svc,
                project_id=1, topic_id=1,
                stage="write",
                tools=("section_draft",),
                context=context,
            )

            assert mock_dispatch.call_count == 3
            assert len(context.get("_drafted_sections", [])) == 3


# ---------------------------------------------------------------------------
# Contract tests for blocking issue fixes (B1–B5)
# ---------------------------------------------------------------------------


class TestB1ProposeMultiArtifact:
    """B1: propose stage records both direction_proposal and study_spec artifacts."""

    def test_propose_records_study_spec_artifact(self, tmp_path):
        from unittest.mock import call, patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db = _make_db(tmp_path)
        svc = MagicMock()

        context = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test Direction",
            "artifact_payload": {"direction": "test", "research_question": "Why?"},
            "study_spec": "Run experiments on dataset X with metric Y",
            "project_id": 1,
        }

        captured_types: list[str] = []

        def capture_dispatch(tool_name, *, db, svc, project_id, topic_id, stage, context):
            captured_types.append(context.get("artifact_type", ""))
            return MagicMock(
                tool="orchestrator_record_artifact", success=True,
                output={"artifact_type": context.get("artifact_type")}, error="",
            )

        with _patch("research_harness.auto_runner.tool_dispatch.dispatch", side_effect=capture_dispatch):
            result = dispatch_stage_tools(
                db=db, svc=svc,
                project_id=1, topic_id=1,
                stage="propose",
                tools=("orchestrator_record_artifact",),
                context=context,
            )

            assert len(captured_types) == 2
            assert captured_types[0] == "direction_proposal"
            assert captured_types[1] == "study_spec"


class TestB2ExperimentRunContract:
    """B2: experiment_run reads code from files[entry_point], not code field."""

    def test_experiment_run_reads_files_entry_point(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_output_code_generate": {
                "files": {"main.py": "print('hello')", "utils.py": "pass"},
                "entry_point": "main.py",
            },
            "primary_metric": "accuracy",
        }
        params = _build_primitive_params("experiment_run", topic_id=1, context=context)
        assert params["code"] == "print('hello')"
        assert params["primary_metric"] == "accuracy"

    def test_experiment_run_fallback_to_code_field(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_output_code_generate": {"code": "legacy_code()"},
            "primary_metric": "f1",
        }
        params = _build_primitive_params("experiment_run", topic_id=1, context=context)
        assert params["code"] == "legacy_code()"

    def test_verified_registry_build_reads_metrics(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_output_experiment_run": {
                "metrics": {"accuracy": 0.95, "f1": 0.88},
                "primary_metric_name": "accuracy",
            },
        }
        params = _build_primitive_params("verified_registry_build", topic_id=1, context=context)
        assert params["metrics"] == {"accuracy": 0.95, "f1": 0.88}
        assert params["primary_metric_name"] == "accuracy"


class TestB3WriteStageParams:
    """B3: write-stage tools are properly parameterized from prior outputs."""

    def test_section_review_reads_draft(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_drafted_sections": ["introduction", "method"],
            "section": "method",
            "_output_section_draft_method": {"text": "We propose a novel..."},
        }
        params = _build_primitive_params("section_review", topic_id=1, context=context)
        assert params["section"] == "method"
        assert params["content"] == "We propose a novel..."

    def test_section_revise_reads_review(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_drafted_sections": ["introduction"],
            "section": "introduction",
            "_output_section_draft_introduction": {"text": "Draft text"},
            "_output_section_review": {"feedback": "Add more citations"},
        }
        params = _build_primitive_params("section_revise", topic_id=1, context=context)
        assert params["content"] == "Draft text"
        assert params["review_feedback"] == "Add more citations"

    def test_paper_verify_numbers_collects_all_sections(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_drafted_sections": ["method", "experiments"],
            "_output_section_draft_method": {"text": "Method text"},
            "_output_section_draft_experiments": {"text": "Experiments text"},
            "project_id": 1,
        }
        params = _build_primitive_params("paper_verify_numbers", topic_id=1, context=context)
        assert "Method text" in params["text"]
        assert "Experiments text" in params["text"]

    def test_latex_compile_assembles_sections(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_drafted_sections": ["introduction", "conclusion"],
            "_output_section_draft_introduction": {"text": "\\section{Introduction}"},
            "_output_section_draft_conclusion": {"text": "\\section{Conclusion}"},
            "venue": "NeurIPS",
            "contributions": "We propose X",
            "project_id": 1,
        }
        params = _build_primitive_params("latex_compile", topic_id=1, context=context)
        assert "introduction" in params["sections"]
        assert "conclusion" in params["sections"]
        assert params["template"] == "neurips"


class TestB5InvariantCompliance:
    """B5: direction_proposal payload always contains research_question."""

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_research_question_present(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test",
            "artifact_payload": {"direction": "test direction"},
            "focus": "test",
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_propose(
            db=db, svc=svc, project_id=1, topic_id=1,
            checkpoint_data={},
        )
        payload = result["artifact_payload"]
        assert "research_question" in payload
        assert payload["research_question"]  # not empty

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_research_question_preserved_if_provided(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test",
            "artifact_payload": {
                "direction": "gating",
                "research_question": "How does adaptive gating improve forecasting?",
            },
            "focus": "test",
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_propose(
            db=db, svc=svc, project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert result["artifact_payload"]["research_question"] == "How does adaptive gating improve forecasting?"

    @patch("research_harness.auto_runner.llm_planner._call_planner_llm")
    def test_study_spec_present(self, mock_llm, tmp_path):
        mock_llm.return_value = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test",
            "artifact_payload": {"direction": "test"},
        }
        db = _make_db(tmp_path)
        svc = MagicMock()
        svc.get_latest_artifact.return_value = None
        result = _plan_propose(
            db=db, svc=svc, project_id=1, topic_id=1,
            checkpoint_data={},
        )
        assert "study_spec" in result


# ---------------------------------------------------------------------------
# Gate advancement integration tests
# ---------------------------------------------------------------------------


def _setup_integration_db(tmp_path: Path):
    """Create DB with topic, project, and orchestrator run for integration tests."""
    from research_harness.orchestrator.service import OrchestratorService

    db = Database(tmp_path / "gate_test.db")
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, target_venue) "
            "VALUES ('test-topic', 'Integration test topic', 'NeurIPS')"
        )
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) "
            "VALUES (1, 'test-project', 'Integration test project')"
        )
        conn.commit()
    finally:
        conn.close()
    svc = OrchestratorService(db)
    svc.resume_run(1, 1)
    return db, svc


class TestProposeGateAdvancement:
    """Integration: propose stage can pass its gate after auto-artifact recording."""

    def test_propose_gate_passes_with_all_artifacts(self, tmp_path):
        db, svc = _setup_integration_db(tmp_path)

        svc.record_artifact(
            project_id=1, topic_id=1, stage="propose",
            artifact_type="direction_proposal",
            title="Test direction",
            payload={"research_question": "Does X improve Y?"},
        )
        svc.record_artifact(
            project_id=1, topic_id=1, stage="propose",
            artifact_type="adversarial_resolution",
            title="Auto-approved",
            payload={"outcome": "approved"},
        )
        svc.record_artifact(
            project_id=1, topic_id=1, stage="propose",
            artifact_type="study_spec",
            title="Study spec",
            payload={"methodology": "Run 6 experiments on dataset X"},
        )

        from research_harness.orchestrator.transitions import TransitionValidator
        validator = TransitionValidator(db)
        can, reason, _ = validator.can_advance(1, "propose", "experiment")
        assert can, f"Propose gate should pass but failed: {reason}"

    def test_propose_gate_fails_without_adversarial_resolution(self, tmp_path):
        db, svc = _setup_integration_db(tmp_path)

        svc.record_artifact(
            project_id=1, topic_id=1, stage="propose",
            artifact_type="direction_proposal",
            title="Test",
            payload={"research_question": "Q?"},
        )
        svc.record_artifact(
            project_id=1, topic_id=1, stage="propose",
            artifact_type="study_spec",
            title="Spec",
            payload={"methodology": "M"},
        )

        from research_harness.orchestrator.transitions import TransitionValidator
        validator = TransitionValidator(db)
        can, reason, _ = validator.can_advance(1, "propose", "experiment")
        assert not can
        assert "adversarial_resolution" in reason


class TestExperimentGateAdvancement:
    """Integration: experiment stage can pass its gate after auto-artifact recording."""

    def test_experiment_gate_passes_with_all_artifacts(self, tmp_path):
        db, svc = _setup_integration_db(tmp_path)

        svc.record_artifact(
            project_id=1, topic_id=1, stage="experiment",
            artifact_type="experiment_code",
            title="Code",
            payload={"files": ["main.py"], "entry_point": "main.py"},
        )
        svc.record_artifact(
            project_id=1, topic_id=1, stage="experiment",
            artifact_type="experiment_result",
            title="Results",
            payload={"metrics": {"accuracy": 0.95}},
        )
        svc.record_artifact(
            project_id=1, topic_id=1, stage="experiment",
            artifact_type="verified_registry",
            title="Registry",
            payload={"whitelist_size": 5},
        )

        from research_harness.orchestrator.transitions import TransitionValidator
        validator = TransitionValidator(db)
        can, reason, _ = validator.can_advance(1, "experiment", "write")
        assert can, f"Experiment gate should pass but failed: {reason}"

    def test_experiment_gate_fails_without_verified_registry(self, tmp_path):
        db, svc = _setup_integration_db(tmp_path)

        svc.record_artifact(
            project_id=1, topic_id=1, stage="experiment",
            artifact_type="experiment_code",
            title="Code",
            payload={"files": ["main.py"]},
        )
        svc.record_artifact(
            project_id=1, topic_id=1, stage="experiment",
            artifact_type="experiment_result",
            title="Results",
            payload={"metrics": {}},
        )

        from research_harness.orchestrator.transitions import TransitionValidator
        validator = TransitionValidator(db)
        can, reason, _ = validator.can_advance(1, "experiment", "write")
        assert not can
        assert "verified_registry" in reason


class TestWriteGateArtifacts:
    """Integration: write stage records draft_pack via auto-artifact recording."""

    def test_draft_pack_recorded_from_tool_outputs(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db, svc = _setup_integration_db(tmp_path)

        context = {
            "sections_to_draft": ["introduction", "method"],
            "outline": "test",
            "evidence_ids": [],
            "project_id": 1,
        }

        with _patch("research_harness.auto_runner.tool_dispatch.dispatch") as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                tool="section_draft", success=True,
                output={"text": "Section content"}, error="",
            )

            dispatch_stage_tools(
                db=db, svc=svc,
                project_id=1, topic_id=1,
                stage="write",
                tools=("section_draft",),
                context=context,
            )

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM project_artifacts "
                "WHERE project_id = 1 AND artifact_type = 'draft_pack'"
            ).fetchone()
            assert row is not None, "draft_pack artifact should be recorded"
        finally:
            conn.close()


class TestAutoArtifactRecording:
    """Integration: _record_auto_artifacts writes to actual DB."""

    def test_propose_records_adversarial_resolution(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [ToolResult(tool="paper_search", success=True)]
        errors: list[str] = []

        with _patch("research_harness.auto_runner.tool_dispatch._run_automated_adversarial",
                     return_value={"verdict": "approved", "issues": [], "summary": "OK"}):
            recorded = _record_auto_artifacts(
                svc=svc, project_id=1, topic_id=1,
                stage="propose", context={}, results=results, errors=errors,
            )

        assert len(recorded) >= 1
        art_types = [t for t, _ in recorded]
        assert "adversarial_resolution" in art_types
        assert all(aid > 0 for _, aid in recorded)

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM project_artifacts "
                "WHERE project_id = 1 AND artifact_type = 'adversarial_resolution'"
            ).fetchone()
            assert row is not None
            import json as _json
            payload = _json.loads(row["payload_json"])
            assert payload["outcome"] == "approved"
        finally:
            conn.close()

    def test_experiment_records_three_artifacts(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(tool="code_generate", success=True,
                       output={"files": {"main.py": "code"}, "entry_point": "main.py"}),
            ToolResult(tool="experiment_run", success=True,
                       output={"metrics": {"acc": 0.9}}),
            ToolResult(tool="verified_registry_build", success=True,
                       output={"whitelist_size": 3}),
        ]
        context = {
            "_output_code_generate": results[0].output,
            "_output_experiment_run": results[1].output,
            "_output_verified_registry_build": results[2].output,
        }
        errors: list[str] = []

        recorded = _record_auto_artifacts(
            svc=svc, project_id=1, topic_id=1,
            stage="experiment", context=context, results=results, errors=errors,
        )

        assert len(recorded) == 3
        art_types = [t for t, _ in recorded]
        assert "experiment_code" in art_types
        assert "experiment_result" in art_types
        assert "verified_registry" in art_types
        assert all(aid > 0 for _, aid in recorded)

        conn = db.connect()
        try:
            for art_type in ("experiment_code", "experiment_result", "verified_registry"):
                row = conn.execute(
                    "SELECT * FROM project_artifacts WHERE project_id = 1 AND artifact_type = ?",
                    (art_type,),
                ).fetchone()
                assert row is not None, f"Missing artifact: {art_type}"
        finally:
            conn.close()


class TestAutoArtifactCheckpointTracking:
    """Fix 5: auto-artifact IDs flow through to checkpoint_data via stage_executor."""

    def test_auto_artifacts_tracked_in_checkpoint(self, tmp_path):
        from unittest.mock import MagicMock, patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc = _setup_integration_db(tmp_path)
        cp = ckpt.new_checkpoint(1, 1)
        cp["current_stage"] = "propose"

        planner_output = {
            "artifact_type": "direction_proposal",
            "artifact_title": "Test",
            "artifact_payload": {"direction": "test", "research_question": "Q?"},
            "study_spec": "spec",
            "project_id": 1,
        }

        tool_results_return = {
            "summary": "ok",
            "tool_results": [],
            "errors": [],
            "auto_artifacts": [
                ("adversarial_resolution", 42),
                ("direction_proposal", 43),
            ],
        }

        with _patch("research_harness.auto_runner.llm_planner.plan_stage",
                     return_value=planner_output), \
             _patch("research_harness.auto_runner.stage_executor._execute_stage_tools",
                    return_value=tool_results_return):

            result = execute_stage(
                db=db, svc=svc, project_id=1, topic_id=1,
                stage="propose", mode="autonomous",
                checkpoint_data=cp, base_dir=tmp_path,
            )

        arts = cp.get("artifacts", {}).get("propose", {})
        assert "adversarial_resolution" in arts
        assert arts["adversarial_resolution"]["artifact_id"] == 42
        assert "direction_proposal" in arts
        assert arts["direction_proposal"]["artifact_id"] == 43

    def test_dispatch_returns_auto_artifacts_in_summary(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db, svc = _setup_integration_db(tmp_path)

        context = {
            "sections_to_draft": ["introduction"],
            "outline": "test",
            "evidence_ids": [],
            "project_id": 1,
        }

        with _patch("research_harness.auto_runner.tool_dispatch.dispatch") as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                tool="section_draft", success=True,
                output={"text": "Section content"}, error="",
            )

            result = dispatch_stage_tools(
                db=db, svc=svc,
                project_id=1, topic_id=1,
                stage="write",
                tools=("section_draft",),
                context=context,
            )

        assert "auto_artifacts" in result
        art_types = [t for t, _ in result["auto_artifacts"]]
        assert "draft_pack" in art_types


class TestInitGateArtifacts:
    """P0-2: init stage records topic_brief artifact."""

    def test_init_records_topic_brief(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [ToolResult(tool="paper_search", success=True)]
        errors: list[str] = []
        context = {"topic_description": "Multimodal time series forecasting"}

        recorded = _record_auto_artifacts(
            svc=svc, project_id=1, topic_id=1,
            stage="init", context=context, results=results, errors=errors,
        )

        assert len(recorded) >= 1
        art_types = [t for t, _ in recorded]
        assert "topic_brief" in art_types

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM project_artifacts "
                "WHERE project_id = 1 AND artifact_type = 'topic_brief'"
            ).fetchone()
            assert row is not None
        finally:
            conn.close()


class TestBuildGateArtifacts:
    """P0-3: build stage records all 4 gate-required artifacts."""

    def test_build_records_all_artifacts(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(tool="paper_search", success=True,
                       output={"ingested_count": 50, "query_used": "test"}),
            ToolResult(tool="expand_citations", success=True, output={"status": "done"}),
            ToolResult(tool="paper_acquire", success=True, output={"acquired": 30}),
        ]
        context = {
            "_output_paper_search": results[0].output,
            "_output_expand_citations": results[1].output,
            "_output_paper_acquire": results[2].output,
        }
        errors: list[str] = []

        recorded = _record_auto_artifacts(
            svc=svc, project_id=1, topic_id=1,
            stage="build", context=context, results=results, errors=errors,
        )

        art_types = [t for t, _ in recorded]
        assert "literature_map" in art_types
        assert "paper_pool_snapshot" in art_types
        assert "citation_expansion_report" in art_types
        assert "acquisition_report" in art_types


class TestAnalyzeGateArtifacts:
    """P0-4: analyze stage records evidence_pack, claim_candidate_set, direction_proposal."""

    def test_analyze_records_all_artifacts(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(tool="claim_extract", success=True,
                       output={"claims": [{"id": "c1"}], "papers_processed": 20}),
            ToolResult(tool="gap_detect", success=True,
                       output={"gaps": [{"id": "g1"}], "papers_analyzed": 20}),
            ToolResult(tool="baseline_identify", success=True,
                       output={"baselines": []}),
        ]
        context = {
            "_output_claim_extract": results[0].output,
            "_output_gap_detect": results[1].output,
            "_output_baseline_identify": results[2].output,
            "focus": "adaptive gating",
        }
        errors: list[str] = []

        recorded = _record_auto_artifacts(
            svc=svc, project_id=1, topic_id=1,
            stage="analyze", context=context, results=results, errors=errors,
        )

        art_types = [t for t, _ in recorded]
        assert "claim_candidate_set" in art_types
        assert "evidence_pack" in art_types
        assert "direction_proposal" in art_types


class TestWriteGateComplete:
    """P0 extension: write stage records draft_pack + final_bundle + process_summary."""

    def test_write_records_all_three_artifacts(self, tmp_path):
        from unittest.mock import patch as _patch

        from research_harness.auto_runner.tool_dispatch import dispatch_stage_tools

        db, svc = _setup_integration_db(tmp_path)

        context = {
            "sections_to_draft": ["introduction", "method"],
            "outline": "test",
            "evidence_ids": [],
            "project_id": 1,
        }

        with _patch("research_harness.auto_runner.tool_dispatch.dispatch") as mock_dispatch:
            mock_dispatch.return_value = MagicMock(
                tool="section_draft", success=True,
                output={"text": "Section content"}, error="",
            )

            result = dispatch_stage_tools(
                db=db, svc=svc,
                project_id=1, topic_id=1,
                stage="write",
                tools=("section_draft",),
                context=context,
            )

        art_types = [t for t, _ in result["auto_artifacts"]]
        assert "draft_pack" in art_types
        assert "final_bundle" in art_types
        assert "process_summary" in art_types


class TestWriteTerminalCompletion:
    """P0-1: runner recognizes write as terminal stage and returns 'completed'."""

    def test_write_completes_without_advance_error(self, tmp_path):
        """Verify the terminal stage check in runner.py by testing the logic directly."""
        from research_harness.orchestrator.stages import next_stage

        assert next_stage("write") is None, "write should be terminal stage"

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_project

        cp = ckpt.new_checkpoint(1, 1)
        cp["current_stage"] = "write"

        stage_call_count = 0

        def mock_execute_stage(**kwargs):
            nonlocal stage_call_count
            stage_call_count += 1
            return {
                "status": "complete", "stage": "write",
                "summary": "write done", "tool_results": [], "auto_artifacts": [],
            }

        from unittest.mock import MagicMock, patch as _patch

        with _patch("research_harness.auto_runner.runner.execute_stage",
                     side_effect=mock_execute_stage), \
             _patch("research_harness.auto_runner.runner.Database") as mock_db_cls, \
             _patch("research_harness.auto_runner.runner.OrchestratorService") as mock_svc_cls, \
             _patch("research_harness.auto_runner.runner.find_workspace_root",
                    return_value=tmp_path), \
             _patch("research_harness.auto_runner.runner.load_runtime_config") as mock_config:

            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            db, svc = _setup_integration_db(tmp_path)
            mock_db_cls.return_value = db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "write"
            mock_svc.get_run.return_value = run_mock

            result = run_project(
                project_id=1, topic_id=1,
                base_dir=tmp_path, auto_approve=True,
            )

        assert result["status"] == "completed"
        assert stage_call_count == 1
        mock_svc.advance.assert_not_called()


# ---------------------------------------------------------------------------
# Output schema normalization tests (P0-5)
# ---------------------------------------------------------------------------


class TestOutputSchemaNormalization:
    """P0-5: output schema normalization handles real primitive output shapes."""

    def test_extract_section_text_real_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_section_text

        real_output = {"draft": {"content": "We propose...", "section": "intro",
                                  "citations_used": [1, 2], "word_count": 150}}
        assert _extract_section_text(real_output) == "We propose..."

    def test_extract_section_text_legacy_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_section_text

        legacy_output = {"text": "Legacy format"}
        assert _extract_section_text(legacy_output) == "Legacy format"

    def test_extract_review_feedback_real_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_review_feedback

        real_output = {"suggestions": ["Add citations", "Clarify method"],
                       "dimensions": [{"dimension": "clarity", "score": 7.0, "comment": "OK"}]}
        feedback = _extract_review_feedback(real_output)
        assert "Add citations" in feedback

    def test_extract_review_feedback_from_dimensions(self):
        from research_harness.auto_runner.tool_dispatch import _extract_review_feedback

        dim_output = {"suggestions": [],
                      "dimensions": [{"dimension": "rigor", "score": 5.0, "comment": "Weak stats"}]}
        feedback = _extract_review_feedback(dim_output)
        assert "Weak stats" in feedback

    def test_extract_revise_text_real_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_revise_text

        real_output = {"revised_content": "Revised text here", "changes_made": ["Added refs"]}
        assert _extract_revise_text(real_output) == "Revised text here"

    def test_extract_revise_text_legacy_shape(self):
        from research_harness.auto_runner.tool_dispatch import _extract_revise_text

        legacy_output = {"text": "Legacy revised"}
        assert _extract_revise_text(legacy_output) == "Legacy revised"


# ---------------------------------------------------------------------------
# P0-2: experiment_runs row insertion
# ---------------------------------------------------------------------------


class TestExperimentRunsInsertion:
    """P0-2: auto_runner inserts experiment_runs(kept=1) so experiment_gate passes."""

    def test_experiment_inserts_kept_run(self, tmp_path):
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(tool="code_generate", success=True,
                       output={"files": {"main.py": "print('hi')"}, "entry_point": "main.py"}),
            ToolResult(tool="experiment_run", success=True,
                       output={"metrics": {"accuracy": 0.92}, "primary_metric_name": "accuracy",
                               "primary_metric_value": 0.92}),
            ToolResult(tool="verified_registry_build", success=True,
                       output={"whitelist_size": 5}),
        ]
        context = {
            "_output_code_generate": results[0].output,
            "_output_experiment_run": results[1].output,
            "_output_verified_registry_build": results[2].output,
            "primary_metric": "accuracy",
        }
        errors: list[str] = []

        _record_auto_artifacts(
            svc=svc, project_id=1, topic_id=1,
            stage="experiment", context=context, results=results, errors=errors,
        )

        # Verify experiment_runs row exists with kept=1
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM experiment_runs WHERE project_id = 1 AND kept = 1"
            ).fetchone()
            assert row is not None, "experiment_runs row with kept=1 not found"
            assert row["primary_metric_name"] == "accuracy"
            assert row["primary_metric_value"] == 0.92
        finally:
            conn.close()

    def test_experiment_gate_passes_with_inserted_run(self, tmp_path):
        """Full gate check: artifacts + experiment_runs row → pass."""
        from research_harness.auto_runner.tool_dispatch import (
            ToolResult,
            _record_auto_artifacts,
        )
        from research_harness.orchestrator.transitions import GateEvaluator

        db, svc = _setup_integration_db(tmp_path)
        results = [
            ToolResult(tool="code_generate", success=True,
                       output={"files": {"main.py": "x"}, "entry_point": "main.py"}),
            ToolResult(tool="experiment_run", success=True,
                       output={"metrics": {"f1": 0.85}, "primary_metric_name": "f1",
                               "primary_metric_value": 0.85}),
            ToolResult(tool="verified_registry_build", success=True,
                       output={"whitelist_size": 3}),
        ]
        context = {
            "_output_code_generate": results[0].output,
            "_output_experiment_run": results[1].output,
            "_output_verified_registry_build": results[2].output,
            "primary_metric": "f1",
        }
        errors: list[str] = []

        _record_auto_artifacts(
            svc=svc, project_id=1, topic_id=1,
            stage="experiment", context=context, results=results, errors=errors,
        )

        evaluator = GateEvaluator(db)
        decision = evaluator._evaluate_experiment_gate(1, "experiment")
        assert decision == "pass", f"Expected 'pass', got '{decision}'"


# ---------------------------------------------------------------------------
# P0-3: propose reads direction_proposal fallback
# ---------------------------------------------------------------------------


class TestProposeDirectionFallback:
    """P0-3: _plan_propose falls back to direction_proposal when direction_ranking missing."""

    def test_propose_uses_direction_proposal_fallback(self, tmp_path):
        from unittest.mock import MagicMock, patch

        db, svc = _setup_integration_db(tmp_path)

        # Record a direction_proposal in analyze (which auto-artifacts create),
        # but NO direction_ranking.
        svc.record_artifact(
            project_id=1, topic_id=1, stage="analyze",
            artifact_type="direction_proposal",
            title="Direction from gaps",
            payload={"gaps": ["gap1"], "research_question": "How to improve?"},
        )

        from research_harness.auto_runner.llm_planner import _plan_propose

        with patch("research_harness.auto_runner.llm_planner._call_planner_llm") as mock_llm:
            mock_llm.return_value = {
                "artifact_type": "direction_proposal",
                "artifact_title": "Test direction",
                "artifact_payload": {"direction": "novel approach", "research_question": "RQ1"},
                "focus": "test focus",
                "study_spec": "spec from LLM",
            }
            result = _plan_propose(
                db=db, svc=svc, project_id=1, topic_id=1, checkpoint_data={},
            )
        assert result.get("study_spec") == "spec from LLM"
        assert result.get("artifact_type") == "direction_proposal"


# ---------------------------------------------------------------------------
# P0-4: study_spec never empty
# ---------------------------------------------------------------------------


class TestStudySpecNonEmpty:
    """P0-4: study_spec always has substantive content for artifact recording."""

    def test_study_spec_synthesized_when_llm_returns_empty(self, tmp_path):
        from unittest.mock import patch

        db, svc = _setup_integration_db(tmp_path)

        from research_harness.auto_runner.llm_planner import _plan_propose

        with patch("research_harness.auto_runner.llm_planner._call_planner_llm") as mock_llm:
            mock_llm.return_value = {
                "artifact_type": "direction_proposal",
                "artifact_payload": {"direction": "Novel gating mechanism",
                                     "research_question": "How to gate modalities?"},
                "focus": "modality gating",
                # study_spec deliberately missing
            }
            result = _plan_propose(
                db=db, svc=svc, project_id=1, topic_id=1, checkpoint_data={},
            )

        assert result.get("study_spec"), "study_spec must not be empty"
        assert "Novel gating mechanism" in result["study_spec"]


# ---------------------------------------------------------------------------
# R6-3: should_pause_human autonomous mode
# ---------------------------------------------------------------------------


class TestAutonomyAllStages:
    """All 6 stages proceed without pause in autonomous mode."""

    def test_all_stages_no_pause_in_autonomous(self):
        from research_harness.auto_runner.stage_policy import STAGE_POLICIES, should_pause_human

        for stage_name in STAGE_POLICIES:
            result = should_pause_human(stage_name, mode="standard", autonomy="autonomous")
            assert result is False, (
                f"Stage '{stage_name}' pauses in autonomous mode but shouldn't"
            )

    def test_high_risk_stages_pause_in_supervised(self):
        from research_harness.auto_runner.stage_policy import should_pause_human

        # propose and write are human_checkpoint="always"
        assert should_pause_human("propose", mode="standard", autonomy="supervised") is True
        assert should_pause_human("write", mode="standard", autonomy="supervised") is True


# ---------------------------------------------------------------------------
# R6-1: Write terminal gate check
# ---------------------------------------------------------------------------


class TestWriteTerminalGateCheck:
    """Write terminal checks gate before reporting completed."""

    def test_write_pauses_on_blocking_review_issue(self, tmp_path):
        from unittest.mock import MagicMock, patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_project

        # Setup checkpoint at write stage
        ckpt_dir = tmp_path / "checkpoints"
        ckpt_dir.mkdir()
        cp = ckpt.new_checkpoint(1, 1, mode="standard")
        cp["current_stage"] = "write"

        ckpt_path = ckpt.checkpoint_path(tmp_path, 1)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        ckpt.save_checkpoint(ckpt_path, cp)

        def mock_execute_stage(**kwargs):
            return {
                "status": "complete", "stage": "write",
                "summary": "write done", "tool_results": [], "auto_artifacts": [],
            }

        with _patch("research_harness.auto_runner.runner.execute_stage",
                     side_effect=mock_execute_stage), \
             _patch("research_harness.auto_runner.runner.Database") as mock_db_cls, \
             _patch("research_harness.auto_runner.runner.OrchestratorService") as mock_svc_cls, \
             _patch("research_harness.auto_runner.runner.find_workspace_root",
                    return_value=tmp_path), \
             _patch("research_harness.auto_runner.runner.load_runtime_config") as mock_config:

            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            db, svc = _setup_integration_db(tmp_path)
            mock_db_cls.return_value = db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "write"
            mock_svc.get_run.return_value = run_mock
            # Gate returns "needs_review" (blocking review issue)
            mock_svc.check_gate.return_value = "needs_review"

            result = run_project(
                project_id=1, topic_id=1,
                base_dir=tmp_path, auto_approve=False,
            )

        assert result["status"] == "paused"
        assert "needs_review" in result.get("gate_decision", "") or \
               "needs_review" in result.get("summary", "")

    def test_write_completes_when_gate_passes(self, tmp_path):
        from unittest.mock import MagicMock, patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_project

        cp = ckpt.new_checkpoint(1, 1, mode="standard")
        cp["current_stage"] = "write"

        ckpt_path = ckpt.checkpoint_path(tmp_path, 1)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        ckpt.save_checkpoint(ckpt_path, cp)

        def mock_execute_stage(**kwargs):
            return {
                "status": "complete", "stage": "write",
                "summary": "write done", "tool_results": [], "auto_artifacts": [],
            }

        with _patch("research_harness.auto_runner.runner.execute_stage",
                     side_effect=mock_execute_stage), \
             _patch("research_harness.auto_runner.runner.Database") as mock_db_cls, \
             _patch("research_harness.auto_runner.runner.OrchestratorService") as mock_svc_cls, \
             _patch("research_harness.auto_runner.runner.find_workspace_root",
                    return_value=tmp_path), \
             _patch("research_harness.auto_runner.runner.load_runtime_config") as mock_config:

            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            db, svc = _setup_integration_db(tmp_path)
            mock_db_cls.return_value = db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "write"
            mock_svc.get_run.return_value = run_mock
            mock_svc.check_gate.return_value = "pass"

            result = run_project(
                project_id=1, topic_id=1,
                base_dir=tmp_path, auto_approve=True,
            )

        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# R6-4: code_validate receives code parameter
# ---------------------------------------------------------------------------


class TestCodeValidateParams:
    """code_validate gets code from code_generate output."""

    def test_code_validate_reads_code_generate_output(self):
        from research_harness.auto_runner.tool_dispatch import _build_primitive_params

        context = {
            "_output_code_generate": {
                "files": {"main.py": "import torch\nprint('hello')"},
                "entry_point": "main.py",
            },
        }
        params = _build_primitive_params("code_validate", topic_id=1, context=context)
        assert params["code"] == "import torch\nprint('hello')"


# ---------------------------------------------------------------------------
# Codex bridge fallback tests
# ---------------------------------------------------------------------------


class TestCodexBridgeFallback:
    """Codex timeout falls back to joycode."""

    def test_timeout_falls_back_to_joycode(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from research_harness.auto_runner.codex_bridge import run_codex_review

        with patch("research_harness.auto_runner.codex_bridge._find_codex",
                   return_value="/usr/bin/codex"), \
             patch("research_harness.auto_runner.codex_bridge.subprocess.run",
                   side_effect=__import__("subprocess").TimeoutExpired("codex", 300)), \
             patch("research_harness.auto_runner.codex_bridge._adversarial_via_joycode") as mock_joy:
            mock_joy.return_value = {
                "success": True, "verdict": "approve",
                "issues": [], "scores": {}, "notes": "Joycode fallback",
                "raw_output": "", "backend": "joycode",
            }
            result = run_codex_review(
                artifact_path=tmp_path / "test.json",
                stage="propose",
                focus="test",
            )

        assert result["success"] is True
        assert result["backend"] == "joycode"
        mock_joy.assert_called_once()

    def test_no_codex_cli_uses_joycode(self, tmp_path):
        from unittest.mock import patch

        from research_harness.auto_runner.codex_bridge import run_codex_review

        with patch("research_harness.auto_runner.codex_bridge._find_codex",
                   return_value=None), \
             patch("research_harness.auto_runner.codex_bridge._adversarial_via_joycode") as mock_joy:
            mock_joy.return_value = {
                "success": True, "verdict": "approve",
                "issues": [], "scores": {}, "notes": "",
                "raw_output": "", "backend": "joycode",
            }
            result = run_codex_review(
                artifact_path=tmp_path / "test.json",
                stage="propose",
                focus="test",
            )

        assert result["backend"] == "joycode"

    def test_subprocess_error_falls_back_to_joycode(self, tmp_path):
        """Non-timeout subprocess exceptions also fallback to joycode."""
        from unittest.mock import patch

        from research_harness.auto_runner.codex_bridge import run_codex_review

        with patch("research_harness.auto_runner.codex_bridge._find_codex",
                   return_value="/usr/bin/codex"), \
             patch("research_harness.auto_runner.codex_bridge.subprocess.run",
                   side_effect=OSError("Permission denied")), \
             patch("research_harness.auto_runner.codex_bridge._adversarial_via_joycode") as mock_joy:
            mock_joy.return_value = {
                "success": True, "verdict": "approve",
                "issues": [], "scores": {}, "notes": "",
                "raw_output": "", "backend": "joycode",
            }
            result = run_codex_review(
                artifact_path=tmp_path / "test.json",
                stage="propose",
                focus="test",
            )

        assert result["success"] is True
        assert result["backend"] == "joycode"
        mock_joy.assert_called_once()


# ---------------------------------------------------------------------------
# Budget halt test
# ---------------------------------------------------------------------------


class TestBudgetHalt:
    """Budget exhaustion halts the runner."""

    def test_budget_halt_returns_paused(self, tmp_path):
        from unittest.mock import MagicMock, patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_project

        cp = ckpt.new_checkpoint(1, 1, mode="standard")
        cp["current_stage"] = "build"

        ckpt_path = ckpt.checkpoint_path(tmp_path, 1)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        ckpt.save_checkpoint(ckpt_path, cp)

        call_count = 0

        def mock_execute_stage(**kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "status": "complete", "stage": "build",
                "summary": "done", "tool_results": [], "auto_artifacts": [],
            }

        with _patch("research_harness.auto_runner.runner.execute_stage",
                     side_effect=mock_execute_stage), \
             _patch("research_harness.auto_runner.runner.Database") as mock_db_cls, \
             _patch("research_harness.auto_runner.runner.OrchestratorService") as mock_svc_cls, \
             _patch("research_harness.auto_runner.runner.find_workspace_root",
                    return_value=tmp_path), \
             _patch("research_harness.auto_runner.runner.load_runtime_config") as mock_config:

            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            db, svc = _setup_integration_db(tmp_path)
            mock_db_cls.return_value = db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "build"
            mock_svc.get_run.return_value = run_mock

            from research_harness.auto_runner.budget import BudgetCheckResult

            with _patch("research_harness.auto_runner.budget.BudgetMonitor.check",
                        return_value=BudgetCheckResult(action="halt", message="Over budget")):
                result = run_project(
                    project_id=1, topic_id=1,
                    base_dir=tmp_path, auto_approve=True,
                )

        assert result["status"] == "paused"
        assert "Budget" in result.get("summary", "") or "budget" in result.get("summary", "")


# ---------------------------------------------------------------------------
# Loopback path test (T1 — runner.py advance returns loopback)
# ---------------------------------------------------------------------------


class TestLoopbackPath:
    """When orchestrator advance returns loopback, runner rewinds to target stage."""

    def test_loopback_rewinds_to_build(self, tmp_path):
        from unittest.mock import MagicMock, patch as _patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.runner import run_project

        cp = ckpt.new_checkpoint(1, 1, mode="standard")
        cp["current_stage"] = "analyze"

        ckpt_path = ckpt.checkpoint_path(tmp_path, 1)
        ckpt_path.parent.mkdir(parents=True, exist_ok=True)
        ckpt.save_checkpoint(ckpt_path, cp)

        call_stages: list[str] = []

        def mock_execute_stage(**kwargs):
            stage = kwargs["stage"]
            call_stages.append(stage)
            if stage == "build" and call_stages.count("build") > 0:
                return {"status": "needs_human", "stage": stage,
                        "summary": "stopping", "tool_results": [], "auto_artifacts": []}
            return {
                "status": "complete", "stage": stage,
                "summary": "done", "tool_results": [], "auto_artifacts": [],
            }

        advance_calls = [0]

        def mock_advance(*args, **kwargs):
            advance_calls[0] += 1
            if advance_calls[0] == 1:
                return {"success": False, "loopback": True, "to_stage": "build"}
            return {"success": True}

        with _patch("research_harness.auto_runner.runner.execute_stage",
                     side_effect=mock_execute_stage), \
             _patch("research_harness.auto_runner.runner.Database") as mock_db_cls, \
             _patch("research_harness.auto_runner.runner.OrchestratorService") as mock_svc_cls, \
             _patch("research_harness.auto_runner.runner.find_workspace_root",
                    return_value=tmp_path), \
             _patch("research_harness.auto_runner.runner.load_runtime_config") as mock_config:

            mock_config.return_value = MagicMock(db_path=tmp_path / "test.db")
            mock_db = MagicMock()
            mock_db.migrate = MagicMock()
            mock_db_cls.return_value = mock_db

            mock_svc = mock_svc_cls.return_value
            run_mock = MagicMock()
            run_mock.topic_id = 1
            run_mock.current_stage = "analyze"
            mock_svc.get_run.return_value = run_mock
            mock_svc.advance.side_effect = mock_advance
            mock_svc.check_gate.return_value = "pass"

            result = run_project(
                project_id=1, topic_id=1,
                base_dir=tmp_path,
            )

        assert "analyze" in call_stages
        assert "build" in call_stages
        assert result["status"] == "paused"


# ---------------------------------------------------------------------------
# Checkpoint stale .tmp cleanup test (R1)
# ---------------------------------------------------------------------------


class TestCheckpointTempCleanup:
    """Stale .tmp files are cleaned up on load_checkpoint."""

    def test_stale_tmp_removed_on_load(self, tmp_path):
        from research_harness.auto_runner import checkpoint as ckpt

        ckpt_dir = tmp_path / "auto_runner" / "checkpoints"
        ckpt_dir.mkdir(parents=True)

        # Create stale .tmp file
        stale = ckpt_dir / "project_1_checkpoint.tmp"
        stale.write_text("stale data")

        # load_checkpoint on non-existent checkpoint cleans up temps
        result = ckpt.load_checkpoint(ckpt_dir / "project_1.json")

        assert result is None
        assert not stale.exists()
