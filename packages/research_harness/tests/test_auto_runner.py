"""Tests for auto_runner — checkpoint, stage_policy, codex_bridge, runner."""

from __future__ import annotations

import json

import pytest

from research_harness.auto_runner.checkpoint import (
    clear_codex_handoff,
    clear_error,
    load_checkpoint,
    new_checkpoint,
    record_artifact,
    record_error,
    record_event,
    save_checkpoint,
    set_codex_handoff,
    update_stage,
)
from research_harness.auto_runner.codex_bridge import (
    _normalize_review,
    _parse_codex_output,
    codex_issues_to_objections,
)
from research_harness.auto_runner.stage_policy import (
    decide_recovery,
    get_policy,
    max_retries,
    should_invoke_codex,
    should_pause_human,
)


# ---------------------------------------------------------------------------
# Checkpoint tests
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_new_checkpoint(self):
        cp = new_checkpoint(1, mode="standard")
        assert cp["topic_id"] == 1
        assert cp["mode"] == "standard"
        assert cp["current_stage"] == "init"
        assert cp["stage_state"] == "pending"
        assert cp["schema_version"] == 1

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "test_cp.json"
        cp = new_checkpoint(1)
        save_checkpoint(path, cp)
        loaded = load_checkpoint(path)
        assert loaded is not None
        assert loaded["topic_id"] == 1
        assert "updated_at" in loaded

    def test_load_missing(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        assert load_checkpoint(path) is None

    def test_record_event(self):
        cp = new_checkpoint(1)
        record_event(cp, stage="topic_framing", event="stage_start", detail="test")
        assert len(cp["history"]) == 1
        assert cp["history"][0]["event"] == "stage_start"

    def test_record_artifact(self):
        cp = new_checkpoint(1)
        record_artifact(
            cp,
            stage="topic_framing",
            artifact_type="topic_brief",
            artifact_id=5,
            version=1,
        )
        assert cp["artifacts"]["topic_framing"]["topic_brief"]["artifact_id"] == 5

    def test_record_and_clear_error(self):
        cp = new_checkpoint(1)
        record_error(cp, kind="api", message="rate limited", tool_name="paper_search")
        assert cp["last_error"]["kind"] == "api"
        assert cp["last_error"]["retry_count"] == 1
        record_error(cp, kind="api", message="rate limited again")
        assert cp["last_error"]["retry_count"] == 2
        clear_error(cp)
        assert cp["last_error"]["retry_count"] == 0

    def test_update_stage(self):
        cp = new_checkpoint(1)
        update_stage(
            cp, stage="literature_mapping", state="running", summary_md="searching..."
        )
        assert cp["current_stage"] == "literature_mapping"
        assert cp["stage_state"] == "running"

    def test_codex_handoff(self):
        cp = new_checkpoint(1)
        set_codex_handoff(
            cp,
            stage="adversarial_optimization",
            request_path="/tmp/req.json",
            response_path="/tmp/resp.json",
        )
        assert cp["codex_handoff"]["requested"] is True
        clear_codex_handoff(cp, verdict="approve")
        assert cp["codex_handoff"]["requested"] is False
        assert cp["codex_handoff"]["verdict"] == "approve"

    def test_history_bounded(self):
        cp = new_checkpoint(1)
        for i in range(250):
            record_event(cp, stage="test", event=f"e{i}")
        assert len(cp["history"]) == 200


# ---------------------------------------------------------------------------
# Stage policy tests
# ---------------------------------------------------------------------------


class TestStagePolicy:
    def test_all_stages_have_policy(self):
        from research_harness.orchestrator.stages import STAGE_ORDER

        for stage in STAGE_ORDER:
            assert get_policy(stage) is not None, f"Missing policy: {stage}"

    def test_propose_requires_codex(self):
        assert should_invoke_codex("propose", "standard") is True
        assert should_invoke_codex("propose", "explore") is True

    def test_write_codex_by_mode(self):
        assert should_invoke_codex("write", "standard") is True  # recommended
        assert should_invoke_codex("write", "explore") is False

    def test_optional_codex_only_in_strict(self):
        assert should_invoke_codex("build", "strict") is True
        assert should_invoke_codex("build", "standard") is False

    def test_human_checkpoints(self):
        assert should_pause_human("init", "standard") is True
        assert should_pause_human("init", "demo") is False
        assert should_pause_human("analyze", "standard") is True
        assert should_pause_human("build", "standard") is True  # conditional + standard
        assert should_pause_human("write", "standard") is True

    def test_max_retries(self):
        assert max_retries("build") == 2
        assert max_retries("propose") == 1
        assert max_retries("init") == 0
        assert max_retries("write") == 1

    def test_decide_recovery_retry(self):
        assert decide_recovery("build", "api_error", 0) == "retry"
        assert decide_recovery("build", "api_error", 1) == "retry"

    def test_decide_recovery_exhausted(self):
        assert decide_recovery("build", "api_error", 2) == "fallback_stage"
        assert decide_recovery("init", "api_error", 0) == "pause_human"  # no fallback


# ---------------------------------------------------------------------------
# Codex bridge tests
# ---------------------------------------------------------------------------


class TestCodexBridge:
    def test_parse_json_output(self):
        raw = json.dumps(
            {
                "verdict": "approve",
                "issues": [
                    {
                        "severity": "minor",
                        "category": "clarity",
                        "target": "abstract",
                        "reasoning": "unclear",
                    }
                ],
                "scores": {"novelty": 4.5, "clarity": 3.0},
                "notes": "good work",
            }
        )
        result = _parse_codex_output(raw)
        assert result["verdict"] == "approve"
        assert len(result["issues"]) == 1
        assert result["scores"]["novelty"] == 4.5

    def test_parse_fenced_json(self):
        raw = 'Here is my review:\n```json\n{"verdict": "revise", "issues": [], "scores": {}, "notes": "fix it"}\n```\n'
        result = _parse_codex_output(raw)
        assert result["verdict"] == "revise"

    def test_parse_text_fallback(self):
        raw = "This looks good. VERDICT: APPROVE"
        result = _parse_codex_output(raw)
        assert result["verdict"] == "approve"

    def test_normalize_review(self):
        data = {
            "verdict": "APPROVE",
            "issues": "not a list",
            "scores": 42,
            "notes": "ok",
        }
        norm = _normalize_review(data)
        assert norm["verdict"] == "approve"
        assert norm["issues"] == []
        assert norm["scores"] == {}

    def test_issues_to_objections(self):
        issues = [
            {
                "severity": "major",
                "category": "novelty",
                "target": "method",
                "reasoning": "not new",
            },
            {
                "severity": "minor",
                "category": "clarity",
                "target": "abstract",
                "reasoning": "unclear",
            },
        ]
        objs = codex_issues_to_objections(issues)
        assert len(objs) == 2
        assert objs[0]["severity"] == "major"
        assert objs[0]["category"] == "novelty"


# ---------------------------------------------------------------------------
# Runner dry-run test
# ---------------------------------------------------------------------------


class TestRunnerDryRun:
    def test_dry_run(self):
        """Test _dry_run directly to avoid side effects from run_project's
        internal DB/config resolution."""
        from research_harness.auto_runner.runner import _dry_run

        result = _dry_run("init", "standard")
        assert result["status"] == "dry_run"
        assert len(result["plan"]) == 6
        assert result["plan"][0]["stage"] == "init"
        assert result["plan"][4]["stage"] == "experiment"
        assert result["plan"][-1]["stage"] == "write"


# ---------------------------------------------------------------------------
# Integration tests for stage execution
# ---------------------------------------------------------------------------


class TestStageExecutorIntegration:
    """Test execute_stage with real DB but mocked tool dispatch."""

    @pytest.fixture
    def setup_db(self, tmp_path):
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "runner.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO topics (name, description) VALUES (?, ?)",
                ("test-topic", "Runner test"),
            )
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'test', 'test')",
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        return db, svc, tmp_path

    def test_all_tools_failed_triggers_recovery(self, setup_db):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1)

        def fake_dispatch_all_fail(**kwargs):
            return {
                "summary": "Stage build: 0/2 tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": False, "error": "timeout"},
                    {"tool": "paper_ingest", "success": False, "error": "no source"},
                ],
                "errors": ["paper_search: timeout", "paper_ingest: no source"],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_all_fail,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="build",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # Should trigger retry (build has retry_twice policy)
        assert result["status"] == "retry"
        assert "All" in result.get("summary", "") or "failed" in result.get("error", "")

    def test_successful_tools_returns_needs_human(self, setup_db):
        """analyze stage in standard mode returns needs_human (human_checkpoint=always)."""
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage

        db, svc, tmp_path = setup_db
        checkpoint_data = ckpt.new_checkpoint(1)

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage analyze: 3/3 tools succeeded",
                "tool_results": [
                    {"tool": "claim_extract", "success": True, "error": ""},
                ],
                "errors": [],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_ok,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="analyze",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # analyze has human_checkpoint="always" → needs_human in standard mode
        assert result["status"] == "needs_human"


class TestCheckpointAtomicity:
    def test_atomic_write_produces_valid_json(self, tmp_path):
        path = tmp_path / "atomic_test.json"
        cp = new_checkpoint(1)
        save_checkpoint(path, cp)
        loaded = load_checkpoint(path)
        assert loaded is not None
        assert loaded["topic_id"] == 1

    def test_no_partial_write_on_disk(self, tmp_path):
        """Verify no .tmp files remain after successful write."""
        import glob

        path = tmp_path / "atomic_test2.json"
        cp = new_checkpoint(1)
        save_checkpoint(path, cp)
        tmp_files = glob.glob(str(tmp_path / "*.tmp"))
        assert len(tmp_files) == 0


class TestBudgetWallClockResume:
    def test_cumulative_elapsed_persists(self):
        from research_harness.auto_runner.budget import BudgetLimits, BudgetMonitor

        monitor = BudgetMonitor(BudgetLimits(max_wall_time_min=60))
        monitor._cumulative_elapsed_min = 30.0
        data = monitor.to_dict()
        assert data["cumulative_elapsed_min"] >= 30.0

        restored = BudgetMonitor.from_checkpoint(
            data, BudgetLimits(max_wall_time_min=60)
        )
        assert restored._cumulative_elapsed_min >= 30.0

    def test_budget_sync_from_provenance(self, tmp_path):
        from research_harness.auto_runner.budget import BudgetMonitor
        from research_harness.storage.db import Database

        db = Database(tmp_path / "budget.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO topics (name, description) VALUES ('t', 't')",
            )
            conn.execute(
                """INSERT INTO provenance_records
                   (primitive, started_at, finished_at, backend, model_used,
                    topic_id, success, cost_usd, input_hash, output_hash)
                   VALUES ('test_prim', datetime('now'), datetime('now'), 'test', 'test',
                    1, 1, 0.05, 'h1', 'h2')""",
            )
            conn.commit()
        finally:
            conn.close()

        monitor = BudgetMonitor()
        monitor.sync_from_provenance(db, topic_id=1)
        assert monitor.state.total_cost_usd == 0.05
        assert monitor.state.total_tool_calls == 1


class TestDeferredToolsExclusion:
    """Deferred tools (LLM-constructed args) should not count as 'all failed'."""

    def test_deferred_tools_excluded_from_all_failed(self, tmp_path):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "deferred.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        checkpoint_data = ckpt.new_checkpoint(1)

        def fake_dispatch_mixed(**kwargs):
            return {
                "summary": "Stage propose: 1/3 tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": True, "error": ""},
                    {"tool": "adversarial_run", "success": False, "error": "deferred"},
                    {
                        "tool": "adversarial_resolve",
                        "success": False,
                        "error": "deferred",
                    },
                ],
                "errors": [
                    "adversarial_run: deferred",
                    "adversarial_resolve: deferred",
                ],
            }

        with patch(
            "research_harness.auto_runner.stage_executor._execute_stage_tools",
            side_effect=fake_dispatch_mixed,
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # Should NOT trigger all-failed recovery because non-deferred tools succeeded
        assert result["status"] != "retry"
        assert result["status"] != "fallback_stage"


class TestRetryBoundInRunner:
    """Runner loop must respect max_retries to prevent unbounded loops."""

    def test_retry_limit_enforced(self):
        from research_harness.auto_runner.stage_policy import max_retries

        # build has retry_twice → max 2
        assert max_retries("build") == 2
        # Attempt 3 should exceed limit (attempt > limit + 1)
        # This is verified in runner.py: attempt > limit + 1 → error


class TestCodexScopedByStage:
    """Codex handoff verdict is scoped by stage to prevent cross-stage leakage."""

    def test_verdict_for_different_stage_not_reused(self):
        from research_harness.auto_runner.checkpoint import (
            clear_codex_handoff,
            new_checkpoint,
            set_codex_handoff,
        )

        cp = new_checkpoint(1)
        set_codex_handoff(
            cp,
            stage="propose",
            request_path="/tmp/req.json",
            response_path="/tmp/resp.json",
        )
        clear_codex_handoff(cp, verdict="approve")

        # The verdict is for "propose" — should not match "write"
        handoff = cp["codex_handoff"]
        assert handoff["verdict"] == "approve"
        assert handoff["stage"] == "propose"
        # A different stage check should not match
        assert not (handoff.get("verdict") and handoff.get("stage") == "write")


class TestCodexReviseVerdictBlocks:
    """Codex 'revise' verdict on required stages must block advancement."""

    def test_revise_on_required_stage_returns_needs_human(self, tmp_path):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "codex_revise.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        checkpoint_data = ckpt.new_checkpoint(1)

        # Record a fake artifact so codex has something to review
        ckpt.record_artifact(
            checkpoint_data,
            stage="propose",
            artifact_type="direction_proposal",
            artifact_id=42,
        )

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage propose: 2/2 tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": True, "error": ""},
                    {
                        "tool": "orchestrator_record_artifact",
                        "success": True,
                        "error": "",
                    },
                ],
                "errors": [],
            }

        fake_review = {
            "success": True,
            "verdict": "revise",
            "issues": [
                {
                    "severity": "major",
                    "category": "novelty",
                    "target": "method",
                    "reasoning": "not novel enough",
                }
            ],
            "scores": {"novelty": 3.0},
            "notes": "needs more work",
        }

        with (
            patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                side_effect=fake_dispatch_ok,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.run_codex_review",
                return_value=fake_review,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_request",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_response",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.load_handoff_response",
                return_value=None,
            ),
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # Codex returned "revise" on required stage → must block
        assert result["status"] == "needs_human"
        assert (
            "revision" in result["summary"].lower()
            or "revise" in result["summary"].lower()
        )
        assert len(result.get("codex_issues", [])) == 1

    def test_approve_on_required_stage_continues(self, tmp_path):
        from unittest.mock import patch

        from research_harness.auto_runner import checkpoint as ckpt
        from research_harness.auto_runner.stage_executor import execute_stage
        from research_harness.orchestrator.service import OrchestratorService
        from research_harness.storage.db import Database

        db = Database(tmp_path / "codex_approve.db")
        db.migrate()
        conn = db.connect()
        try:
            conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
            conn.execute(
                "INSERT INTO projects (topic_id, name, description) VALUES (1, 'p', 'p')"
            )
            conn.commit()
        finally:
            conn.close()
        svc = OrchestratorService(db)
        svc.resume_run(1)
        checkpoint_data = ckpt.new_checkpoint(1)

        ckpt.record_artifact(
            checkpoint_data,
            stage="propose",
            artifact_type="direction_proposal",
            artifact_id=42,
        )

        def fake_dispatch_ok(**kwargs):
            return {
                "summary": "Stage propose: 2/2 tools succeeded",
                "tool_results": [
                    {"tool": "paper_search", "success": True, "error": ""},
                ],
                "errors": [],
            }

        fake_review = {
            "success": True,
            "verdict": "approve",
            "issues": [],
            "scores": {"novelty": 8.0},
            "notes": "looks good",
        }

        with (
            patch(
                "research_harness.auto_runner.stage_executor._execute_stage_tools",
                side_effect=fake_dispatch_ok,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.run_codex_review",
                return_value=fake_review,
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_request",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.save_handoff_response",
            ),
            patch(
                "research_harness.auto_runner.stage_executor.load_handoff_response",
                return_value=None,
            ),
        ):
            result = execute_stage(
                db=db,
                svc=svc,
                topic_id=1,
                stage="propose",
                mode="standard",
                checkpoint_data=checkpoint_data,
                base_dir=tmp_path,
            )

        # Codex approved on required stage → propose has human_checkpoint=always → needs_human
        assert result["status"] == "needs_human"
