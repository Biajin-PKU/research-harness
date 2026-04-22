"""Tests for orchestrator service and stage management."""

from __future__ import annotations

import pytest

from research_harness.orchestrator import (
    OrchestratorService,
    STAGE_REGISTRY,
    get_stage_metadata,
    is_valid_transition,
    next_stage,
    stage_index,
)
from research_harness.orchestrator.stages import resolve_stage, LEGACY_STAGE_REGISTRY
from research_harness.storage.db import Database


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.migrate()
    return db


@pytest.fixture
def svc(db):
    return OrchestratorService(db)


@pytest.fixture
def topic_and_project(db):
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("test-topic", "Test topic"),
        )
        topic_id = int(cur.lastrowid)
        cur = conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (?, ?, ?)",
            (topic_id, "test-project", "Test project"),
        )
        project_id = int(cur.lastrowid)
        conn.commit()
        return topic_id, project_id
    finally:
        conn.close()


def _seed_topic_with_papers(db, topic_id: int, count: int = 3) -> list[int]:
    """Ingest ``count`` seed papers and link them to ``topic_id``.

    Returns list of inserted paper ids. Used by tests that need to satisfy
    the init-stage seed-paper-count gate.
    """
    paper_ids: list[int] = []
    conn = db.connect()
    try:
        for i in range(count):
            cur = conn.execute(
                """INSERT INTO papers (arxiv_id, s2_id, doi, title, year)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    f"seed-{topic_id}-{i}",
                    f"s2-{topic_id}-{i}",
                    f"doi-{topic_id}-{i}",
                    f"Seed paper {i}",
                    2024 - (i % 3),
                ),
            )
            paper_id = int(cur.lastrowid)
            paper_ids.append(paper_id)
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
                (paper_id, topic_id, "seed"),
            )
        conn.commit()
    finally:
        conn.close()
    return paper_ids


def _valid_topic_brief_payload() -> dict:
    """Return a minimal topic_brief payload that satisfies init-gate checks."""
    return {
        "scope": "Test research scope",
        "venue_target": "NeurIPS",
        "exclusion_criteria": ["unrelated domain"],
        "goals": ["test"],
    }


class TestStageRegistry:
    def test_all_v2_stages_defined(self):
        expected = ["init", "build", "analyze", "propose", "experiment", "write"]
        assert list(STAGE_REGISTRY.keys()) == expected

    def test_legacy_registry_preserved(self):
        assert "topic_framing" in LEGACY_STAGE_REGISTRY
        assert "finalize" in LEGACY_STAGE_REGISTRY
        assert len(LEGACY_STAGE_REGISTRY) == 13

    def test_init_predecessor_is_none(self):
        meta = get_stage_metadata("init")
        assert meta.predecessor is None

    def test_build_predecessor(self):
        meta = get_stage_metadata("build")
        assert meta.predecessor == "init"

    def test_stage_index(self):
        assert stage_index("init") == 0
        assert stage_index("experiment") == 4
        assert stage_index("write") == 5
        assert stage_index("nonexistent") == -1

    def test_legacy_name_resolves_to_v2_index(self):
        # Legacy names should resolve through to V2 stages
        assert stage_index("topic_framing") == 0  # → init
        assert stage_index("literature_mapping") == 1  # → build
        assert stage_index("evidence_structuring") == 2  # → analyze

    def test_next_stage(self):
        assert next_stage("init") == "build"
        assert next_stage("write") is None
        assert next_stage("nonexistent") is None

    def test_next_stage_from_legacy_name(self):
        assert next_stage("topic_framing") == "build"

    def test_valid_transition_next(self):
        assert is_valid_transition("init", "build") is True

    def test_valid_transition_same(self):
        assert is_valid_transition("init", "init") is True

    def test_valid_transition_fallback(self):
        # State graph: build can self-loop, but cannot go back to init
        assert is_valid_transition("build", "build") is True
        assert is_valid_transition("build", "init") is False

    def test_valid_transition_loopback_analyze_to_build(self):
        assert is_valid_transition("analyze", "build") is True

    def test_valid_transition_loopback_propose_to_build(self):
        assert is_valid_transition("propose", "build") is True

    def test_invalid_transition_skip(self):
        assert is_valid_transition("init", "analyze") is False

    def test_invalid_transition_unknown(self):
        assert is_valid_transition("unknown", "init") is False

    def test_resolve_stage(self):
        assert resolve_stage("init") == "init"
        assert resolve_stage("topic_framing") == "init"
        assert resolve_stage("literature_mapping") == "build"
        assert resolve_stage("evidence_structuring") == "analyze"
        assert resolve_stage("adversarial_optimization") == "propose"
        assert resolve_stage("draft_preparation") == "write"
        assert resolve_stage("finalize") == "write"


class TestOrchestratorInit:
    def test_init_run_creates_run(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        run = svc.init_run(project_id=project_id, topic_id=topic_id, mode="standard")

        assert run.id is not None
        assert run.project_id == project_id
        assert run.topic_id == topic_id
        assert run.mode == "standard"
        assert run.current_stage == "init"
        assert run.stage_status == "in_progress"

    def test_init_run_default_mode(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        run = svc.init_run(project_id=project_id, topic_id=topic_id)
        assert run.mode == "standard"

    def test_get_run_returns_run(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        run = svc.get_run(project_id)
        assert run is not None
        assert run.project_id == project_id

    def test_get_run_none_for_unknown(self, svc):
        run = svc.get_run(99999)
        assert run is None

    def test_init_run_creates_stage_event(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        run = svc.init_run(project_id=project_id, topic_id=topic_id)

        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM orchestrator_stage_events WHERE run_id = ?",
                (run.id,),
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["from_stage"] == ""
            assert rows[0]["to_stage"] == "init"
            assert rows[0]["event_type"] == "init"
        finally:
            conn.close()

    def test_init_run_rolls_back_on_failure(self, db, topic_and_project):
        """Verify that init_run is atomic — a failure during stage event insert
        should roll back the run insert as well."""
        topic_id, project_id = topic_and_project
        svc = OrchestratorService(db)

        # Wrap db.connect to return a connection whose execute() bombs on the
        # stage-event INSERT.  sqlite3.Connection.execute is read-only, so we
        # wrap the whole connection object instead.
        original_connect = db.connect

        class _SabotageConn:
            def __init__(self, real):
                self._real = real
                self._n = 0

            def execute(self, sql, params=()):
                self._n += 1
                if self._n == 2 and "orchestrator_stage_events" in sql:
                    raise RuntimeError("simulated stage event failure")
                return self._real.execute(sql, params)

            def commit(self):
                return self._real.commit()

            def rollback(self):
                return self._real.rollback()

            def close(self):
                return self._real.close()

        db.connect = lambda: _SabotageConn(original_connect())

        with pytest.raises(RuntimeError, match="simulated"):
            svc.init_run(project_id=project_id, topic_id=topic_id)

        # Restore and verify no partial data was committed
        db.connect = original_connect
        conn = db.connect()
        try:
            runs = conn.execute(
                "SELECT * FROM orchestrator_runs WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            assert len(runs) == 0, "Run should have been rolled back"
        finally:
            conn.close()


class TestOrchestratorStatus:
    def test_status_returns_error_for_no_run(self, svc):
        status = svc.get_status(99999)
        assert "error" in status

    def test_status_shows_current_stage(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        status = svc.get_status(project_id)
        assert status["run"]["current_stage"] == "init"

    def test_status_shows_required_artifacts(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        status = svc.get_status(project_id)
        assert "topic_brief" in status["stage"]["required_artifacts"]

    def test_status_shows_missing_artifacts(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        status = svc.get_status(project_id)
        assert "topic_brief" in status["stage"]["missing_artifacts"]


class TestArtifactPersistence:
    def test_record_artifact(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        artifact = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            title="Test Brief",
            payload={"question": "What is X?"},
        )

        assert artifact.id is not None
        assert artifact.project_id == project_id
        assert artifact.stage == "topic_framing"
        assert artifact.artifact_type == "topic_brief"
        assert artifact.version == 1
        assert artifact.payload == {"question": "What is X?"}

    def test_artifact_version_increments(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            payload={"v": 1},
        )
        artifact2 = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            payload={"v": 2},
        )

        assert artifact2.version == 2

    def test_old_artifact_superseded(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        art1 = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            payload={"v": 1},
        )
        art2 = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            payload={"v": 2},
        )

        # art1 should be superseded
        updated = svc._artifact_manager.get(art1.id)
        assert updated.status == "superseded"
        # art2 should be active
        assert art2.status == "active"

    def test_list_artifacts(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            payload={},
        )

        artifacts = svc.list_artifacts(project_id)
        assert len(artifacts) == 1

    def test_get_latest_artifact(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            payload={"v": 1},
        )
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            payload={"v": 2},
        )

        latest = svc.get_latest_artifact(project_id, "topic_framing", "topic_brief")
        assert latest is not None
        assert latest.payload == {"v": 2}

    def test_record_artifact_can_attach_dependencies(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        upstream = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="build",
            artifact_type="literature_map",
            payload={"v": 1},
        )
        downstream = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="analyze",
            artifact_type="gap_analysis",
            payload={"v": 1},
            dependency_artifact_ids=[upstream.id],
        )

        conn = svc._db.connect()
        try:
            row = conn.execute(
                """
                SELECT 1 FROM artifact_dependencies
                WHERE from_artifact_id = ? AND to_artifact_id = ? AND dependency_type = 'consumed_by'
                """,
                (upstream.id, downstream.id),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None

    def test_superseding_artifact_marks_dependents_stale(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        upstream_v1 = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="build",
            artifact_type="literature_map",
            payload={"v": 1},
        )
        downstream = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="analyze",
            artifact_type="gap_analysis",
            payload={"v": 1},
            dependency_artifact_ids=[upstream_v1.id],
        )

        upstream_v2 = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="build",
            artifact_type="literature_map",
            payload={"v": 2},
        )

        assert upstream_v2.version == 2
        stale = svc.list_stale_artifacts(project_id)
        stale_ids = {artifact.id for artifact in stale}
        assert downstream.id in stale_ids
        refreshed = svc._artifact_manager.get(downstream.id)
        assert refreshed is not None
        assert refreshed.stale is True
        assert "superseded by newer literature_map version 2" in (
            refreshed.stale_reason or ""
        )

    def test_mark_and_clear_artifact_stale(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        artifact = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="analyze",
            artifact_type="gap_analysis",
            payload={"v": 1},
        )

        marked = svc.mark_artifact_stale(artifact.id, reason="manual review requested")
        assert marked["success"] is True
        assert artifact.id in marked["stale_ids"]

        cleared = svc.clear_artifact_stale(artifact.id)
        assert cleared["success"] is True
        refreshed = svc._artifact_manager.get(artifact.id)
        assert refreshed is not None
        assert refreshed.stale is False


class TestStageAdvancement:
    def test_advance_requires_artifact(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        result = svc.advance(project_id)
        assert result["success"] is False
        assert "Missing required artifact" in result["error"]

    def test_advance_with_artifact(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _seed_topic_with_papers(db, topic_id, count=3)

        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="init",
            artifact_type="topic_brief",
            payload=_valid_topic_brief_payload(),
        )

        result = svc.advance(project_id)
        assert result["success"] is True
        assert result["from_stage"] == "init"
        assert result["to_stage"] == "build"

        run = svc.get_run(project_id)
        assert run.current_stage == "build"

    def test_advance_cannot_skip_stages(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        # Record artifact for init
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="init",
            artifact_type="topic_brief",
            payload={},
        )

        # Advance to build
        svc.advance(project_id)

        # Try to advance without literature_map artifact
        result = svc.advance(project_id)
        assert result["success"] is False

    def test_advance_from_write_is_none(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        # Manually set stage to write (last stage)
        conn = svc._db.connect()
        try:
            conn.execute(
                "UPDATE orchestrator_runs SET current_stage = 'write' WHERE project_id = ?",
                (project_id,),
            )
            conn.commit()
        finally:
            conn.close()

        result = svc.advance(project_id)
        assert result["success"] is False
        assert "No next stage" in result["error"]

    def test_advance_records_stage_event(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        run = svc.init_run(project_id=project_id, topic_id=topic_id)
        _seed_topic_with_papers(db, topic_id, count=3)

        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="init",
            artifact_type="topic_brief",
            payload=_valid_topic_brief_payload(),
        )

        svc.advance(project_id)

        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM orchestrator_stage_events WHERE run_id = ? AND event_type = 'advance'",
                (run.id,),
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["from_stage"] == "init"
            assert rows[0]["to_stage"] == "build"
        finally:
            conn.close()


class TestGateCheck:
    def test_gate_check_approval_gate_needs_artifact(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        decision = svc.check_gate(project_id, stage="topic_framing")
        assert decision == "needs_approval"

    def test_gate_check_approval_gate_passes_with_artifact(
        self, svc, db, topic_and_project
    ):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _seed_topic_with_papers(db, topic_id, count=3)

        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            payload=_valid_topic_brief_payload(),
        )

        decision = svc.check_gate(project_id, stage="topic_framing")
        assert decision == "pass"

    def test_gate_check_uses_current_stage_by_default(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        # Without artifact, should fail for topic_framing (current stage)
        decision = svc.check_gate(project_id)
        assert decision == "needs_approval"


class TestAdversarialOptimization:
    """Slice 4: Adversarial optimization tests."""

    def test_adversarial_round_creates_artifact(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        # First, create a target artifact
        target = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="direction_proposal",
            title="Test Proposal",
            payload={"direction": "AI safety via RLHF"},
        )

        result = svc.run_adversarial_round(
            project_id=project_id,
            target_artifact_id=target.id,
            proposal_snapshot={"direction": "AI safety via RLHF"},
            objections=[
                {
                    "category": "methodology",
                    "severity": "major",
                    "target": "RLHF approach",
                    "reasoning": "Needs more baseline comparison",
                    "suggested_fix": "Add comparison to constitutional AI",
                }
            ],
            resolver_notes="First round",
        )

        assert result["success"] is True
        assert result["round_number"] == 1
        assert "artifact_id" in result

    def test_adversarial_resolution_blocks_without_approval(
        self, svc, topic_and_project
    ):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        # Create proposal and run round
        target = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="direction_proposal",
            payload={"direction": "Test"},
        )

        round_result = svc.run_adversarial_round(
            project_id=project_id,
            target_artifact_id=target.id,
            proposal_snapshot={"direction": "Test"},
            objections=[
                {
                    "category": "evidence",
                    "severity": "critical",
                    "target": "claim1",
                    "reasoning": "No citation",
                }
            ],
        )

        # Resolve with low scores (should not approve)
        resolve_result = svc.resolve_adversarial_round(
            project_id=project_id,
            round_artifact_id=round_result["artifact_id"],
            scores={"novelty": 2.0, "evidence_coverage": 3.0},
            notes="Needs work",
        )

        assert resolve_result["success"] is True
        assert resolve_result["outcome"] == "revise_and_repeat"
        assert resolve_result["should_repeat"] is True

    def test_adversarial_resolution_approves_with_good_scores(
        self, svc, topic_and_project
    ):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        target = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="direction_proposal",
            payload={"direction": "Test"},
        )

        round_result = svc.run_adversarial_round(
            project_id=project_id,
            target_artifact_id=target.id,
            proposal_snapshot={"direction": "Test"},
            objections=[
                {
                    "category": "minor",
                    "severity": "minor",
                    "target": "typo",
                    "reasoning": "Fix typo",
                    "suggested_fix": "Fix it",
                }
            ],
            proposer_responses=[
                {"target": "typo", "resolved": True, "explanation": "Fixed"}
            ],
        )

        # Resolve with good scores (should approve)
        resolve_result = svc.resolve_adversarial_round(
            project_id=project_id,
            round_artifact_id=round_result["artifact_id"],
            scores={"novelty": 4.5, "evidence_coverage": 4.5, "method_validity": 4.5},
            notes="Good proposal",
        )

        assert resolve_result["success"] is True
        assert resolve_result["outcome"] == "approved"
        assert resolve_result["should_repeat"] is False
        assert resolve_result["mean_score"] >= 4.0

    def test_adversarial_gate_blocks_stage_advance(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        # Move to adversarial_optimization stage (which has adversarial_gate)
        conn = svc._db.connect()
        try:
            conn.execute(
                "UPDATE orchestrator_runs SET current_stage = 'adversarial_optimization' WHERE project_id = ?",
                (project_id,),
            )
            conn.commit()
        finally:
            conn.close()

        # Add required artifact but no adversarial resolution
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="adversarial_optimization",
            artifact_type="adversarial_round",
            payload={"round_number": 1},
        )

        # Gate should fail without adversarial resolution
        decision = svc.check_gate(project_id)
        assert decision == "needs_adversarial"

        # Create adversarial resolution
        target = svc.list_artifacts(
            project_id,
            stage="adversarial_optimization",
            artifact_type="adversarial_round",
        )[0]

        svc.resolve_adversarial_round(
            project_id=project_id,
            round_artifact_id=target.id,
            scores={"novelty": 4.5, "evidence_coverage": 4.5, "method_validity": 4.5},
        )

        # Gate should now pass
        decision = svc.check_gate(project_id)
        assert decision == "pass"

    def test_adversarial_status_reflects_current_state(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        # Initially no resolution
        status = svc.check_adversarial_status(project_id)
        assert status["has_resolution"] is False
        assert status["status"] == "no_resolution_yet"

        # Create resolution
        target = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="direction_proposal",
            payload={},
        )

        round_result = svc.run_adversarial_round(
            project_id=project_id,
            target_artifact_id=target.id,
            proposal_snapshot={},
            objections=[],
        )

        svc.resolve_adversarial_round(
            project_id=project_id,
            round_artifact_id=round_result["artifact_id"],
            scores={"novelty": 4.5},
        )

        status = svc.check_adversarial_status(project_id)
        assert status["has_resolution"] is True
        assert status["outcome"] == "approved"
        assert status["should_repeat"] is False


class TestReviewLoop:
    """Slice 5: Review loop tests."""

    @staticmethod
    def _set_stage(db, project_id: int, stage: str) -> None:
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE orchestrator_runs SET current_stage = ? WHERE project_id = ?",
                (stage, project_id),
            )
            conn.commit()
        finally:
            conn.close()

    def test_create_review_bundle_from_artifacts(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "formal_review")

        # Create report artifacts
        a1 = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="formal_review",
            artifact_type="integrity_review_report",
            payload={"findings": []},
        )
        a2 = svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="formal_review",
            artifact_type="scholarly_review_report",
            payload={"findings": []},
        )

        result = svc.create_review_bundle(
            project_id=project_id,
            integrity_artifact_id=a1.id,
            scholarly_artifact_id=a2.id,
        )

        assert result["success"] is True
        assert "artifact_id" in result
        assert result["cycle_number"] == 1

        # Verify persisted
        bundle = svc.get_latest_artifact(project_id, "formal_review", "review_bundle")
        assert bundle is not None
        assert bundle.payload["cycle_number"] == 1

    def test_add_issues_with_various_severities(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "formal_review")

        r1 = svc.add_review_issue(
            project_id=project_id,
            review_type="scholarly",
            severity="critical",
            category="methodology",
            summary="Missing baseline comparison",
        )
        r2 = svc.add_review_issue(
            project_id=project_id,
            review_type="scholarly",
            severity="low",
            category="writing",
            summary="Minor typo in abstract",
        )

        assert r1["success"] is True
        assert r1["blocking"] is True  # critical auto-blocks
        assert r2["success"] is True
        assert r2["blocking"] is False

    def test_blocking_issues_prevent_gate_passage(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "formal_review")

        # Add required artifacts
        for art_type in (
            "integrity_review_report",
            "scholarly_review_report",
            "review_bundle",
        ):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="formal_review",
                artifact_type=art_type,
                payload={},
            )

        # Add blocking issue
        svc.add_review_issue(
            project_id=project_id,
            review_type="integrity",
            severity="critical",
            category="citation",
            summary="Fabricated reference",
        )

        decision = svc.check_gate(project_id)
        assert decision == "needs_review"

        advance_result = svc.advance(project_id)
        assert advance_result["success"] is False

    def test_responses_link_to_issues(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "formal_review")

        issue_result = svc.add_review_issue(
            project_id=project_id,
            review_type="scholarly",
            severity="medium",
            category="evidence",
            summary="Weak evidence for claim 3",
        )
        issue_id = issue_result["issue_id"]

        resp = svc.respond_to_issue(
            issue_id=issue_id,
            project_id=project_id,
            response_type="change",
            response_text="Added additional citations and analysis",
        )

        assert resp["success"] is True
        assert resp["response_type"] == "change"

        responses = svc._review.list_responses(issue_id)
        assert len(responses) == 1
        assert responses[0].response_text == "Added additional citations and analysis"

    def test_resolve_issues_allows_gate_passage(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "formal_review")

        # Write-stage gate now requires a final_bundle + process_summary in
        # addition to the review report bundle and absence of blocking issues.
        for art_type in (
            "integrity_review_report",
            "scholarly_review_report",
            "review_bundle",
            "final_bundle",
            "process_summary",
        ):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="formal_review",
                artifact_type=art_type,
                payload={},
            )

        # Add and resolve blocking issue
        issue_result = svc.add_review_issue(
            project_id=project_id,
            review_type="integrity",
            severity="high",
            category="statistics",
            summary="P-value calculation error",
        )
        assert svc.check_gate(project_id) == "needs_review"

        svc.resolve_review_issue(issue_result["issue_id"], "resolved")
        assert svc.check_gate(project_id) == "pass"

    def test_review_summary_counts(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "formal_review")

        # Add mixed issues
        svc.add_review_issue(
            project_id=project_id,
            review_type="scholarly",
            severity="critical",
            category="methodology",
            summary="Issue 1",
        )
        svc.add_review_issue(
            project_id=project_id,
            review_type="scholarly",
            severity="critical",
            category="evidence",
            summary="Issue 2",
        )
        svc.add_review_issue(
            project_id=project_id,
            review_type="scholarly",
            severity="medium",
            category="writing",
            summary="Issue 3",
        )

        # Resolve one critical
        issues = svc.list_review_issues(project_id)
        critical_id = next(i["id"] for i in issues if i["summary"] == "Issue 1")
        svc.resolve_review_issue(critical_id, "resolved")

        summary = svc.get_review_status(project_id)
        assert summary["total_issues"] == 3
        assert summary["blocking_open"] == 1  # one critical still open
        assert summary["decision"] == "reject"  # critical open
        assert summary["can_pass_gate"] is False

    def test_max_review_cycles_enforced(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "formal_review")

        # Create 2 bundles (max)
        svc.create_review_bundle(project_id=project_id)
        svc.create_review_bundle(project_id=project_id)

        # Third should fail
        with pytest.raises(ValueError, match="Maximum review cycles"):
            svc._review.create_bundle(project_id, topic_id, "formal_review")

    def test_critical_severity_auto_blocks(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "formal_review")

        result = svc.add_review_issue(
            project_id=project_id,
            review_type="scholarly",
            severity="critical",
            category="scope",
            summary="Out of scope claim",
            blocking=False,  # explicitly False, but should be overridden
        )

        assert result["blocking"] is True

    def test_change_response_sets_issue_in_progress(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "formal_review")

        issue_result = svc.add_review_issue(
            project_id=project_id,
            review_type="scholarly",
            severity="medium",
            category="writing",
            summary="Unclear methodology section",
        )

        svc.respond_to_issue(
            issue_id=issue_result["issue_id"],
            project_id=project_id,
            response_type="change",
            response_text="Rewrote methodology section",
        )

        issues = svc.list_review_issues(project_id)
        issue = next(i for i in issues if i["id"] == issue_result["issue_id"])
        assert issue["status"] == "in_progress"


class TestIntegrityAndFinalize:
    """Slice 6: Integrity verification and finalize tests."""

    @staticmethod
    def _set_stage(db, project_id: int, stage: str) -> None:
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE orchestrator_runs SET current_stage = ? WHERE project_id = ?",
                (stage, project_id),
            )
            conn.commit()
        finally:
            conn.close()

    def test_integrity_check_passes_with_no_findings(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "final_integrity")

        result = svc.run_integrity_check(project_id=project_id)
        assert result["success"] is True
        assert result["passed"] is True
        assert result["critical_count"] == 0
        assert len(result["phases_completed"]) == 5

    def test_integrity_check_fails_with_critical_findings(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "final_integrity")

        findings = [
            {
                "phase": "citation_context",
                "severity": "critical",
                "category": "citation",
                "summary": "Citation misrepresents source finding",
                "details": "Page 5 claim contradicts cited paper",
            },
        ]
        result = svc.run_integrity_check(project_id=project_id, findings=findings)
        assert result["success"] is True
        assert result["passed"] is False
        assert result["critical_count"] == 1

    def test_integrity_findings_create_review_issues(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "final_integrity")

        findings = [
            {
                "phase": "statistical_data",
                "severity": "high",
                "category": "statistics",
                "summary": "P-value not reported for main result",
            },
        ]
        svc.run_integrity_check(project_id=project_id, findings=findings)

        # Should have created a blocking review issue
        issues = svc.list_review_issues(project_id)
        assert len(issues) >= 1
        stat_issue = next((i for i in issues if i["category"] == "statistics"), None)
        assert stat_issue is not None
        assert stat_issue["blocking"] is True

    def test_integrity_gate_blocks_with_critical_issues(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        # Set to write stage (which has review_gate in V2, but we test
        # that critical issues block passage regardless)
        self._set_stage(svc._db, project_id, "write")

        # Add required artifact
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="write",
            artifact_type="final_integrity_report",
            payload={"passed": False},
        )

        # Add critical finding via integrity check
        svc.run_integrity_check(
            project_id=project_id,
            findings=[
                {
                    "phase": "originality",
                    "severity": "critical",
                    "category": "novelty_claim",
                    "summary": "Contribution already published",
                }
            ],
        )

        decision = svc.check_gate(project_id)
        assert decision == "needs_review"

    def test_integrity_gate_passes_when_clean(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        # ``final_integrity`` is a legacy substep of ``write``; the active
        # gate is therefore the review gate which additionally requires the
        # final bundle + process summary artifacts.
        self._set_stage(svc._db, project_id, "final_integrity")

        for art_type, payload in (
            ("final_integrity_report", {"passed": True, "critical_count": 0}),
            ("final_bundle", {}),
            ("process_summary", {}),
        ):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="final_integrity",
                artifact_type=art_type,
                payload=payload,
            )

        decision = svc.check_gate(project_id)
        assert decision == "pass"

    def test_integrity_reference_check_catches_missing_paper(
        self, svc, topic_and_project
    ):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "final_integrity")

        # Create a draft_pack artifact with a nonexistent cited paper
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="draft_preparation",
            artifact_type="draft_pack",
            payload={"cited_paper_ids": [99999]},
        )

        result = svc.run_integrity_check(project_id=project_id)
        assert result["critical_count"] >= 1

    def test_finalize_creates_bundle_and_summary(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(svc._db, project_id, "finalize")

        # Add some artifacts first
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="topic_framing",
            artifact_type="topic_brief",
            payload={"goals": ["test"]},
        )

        result = svc.finalize_project(project_id=project_id)
        assert result["success"] is True
        assert "bundle_artifact_id" in result
        assert "summary_artifact_id" in result
        assert result["artifact_count"] >= 1
        assert result["stages_traversed"] >= 1


class TestCoverageGateThreshold:
    """Sprint 1A: Configurable coverage threshold."""

    def test_default_min_paper_count_is_50(self):
        from research_harness.orchestrator.models import DEFAULT_MIN_PAPER_COUNT

        assert DEFAULT_MIN_PAPER_COUNT == 50

    def test_coverage_gate_blocks_below_threshold(self, svc, topic_and_project, db):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        conn = db.connect()
        try:
            conn.execute(
                "UPDATE orchestrator_runs SET current_stage = 'build' WHERE project_id = ?",
                (project_id,),
            )
            conn.commit()
        finally:
            conn.close()

        for art_type in (
            "literature_map",
            "paper_pool_snapshot",
            "citation_expansion_report",
            "acquisition_report",
        ):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="build",
                artifact_type=art_type,
                payload={},
            )

        conn = db.connect()
        try:
            for i in range(10):
                cur = conn.execute(
                    "INSERT INTO papers (title, year, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?)",
                    (f"Paper {i}", 2024, f"10.test/{i}", f"test.{i}", f"s2-{i}"),
                )
                pid = int(cur.lastrowid)
                conn.execute(
                    "INSERT INTO paper_topics (paper_id, topic_id) VALUES (?, ?)",
                    (pid, topic_id),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO topic_paper_notes (topic_id, paper_id) VALUES (?, ?)",
                    (topic_id, pid),
                )
            conn.commit()
        finally:
            conn.close()

        decision = svc.check_gate(project_id, stage="build")
        assert decision == "needs_coverage"

    def test_soft_prerequisites_use_threshold(self):
        from research_harness.orchestrator.stages import STAGE_REGISTRY
        from research_harness.orchestrator.models import DEFAULT_MIN_PAPER_COUNT

        analyze = STAGE_REGISTRY["analyze"]
        assert any(
            str(DEFAULT_MIN_PAPER_COUNT) in p for p in analyze.soft_prerequisites
        )


class TestGapTriggeredLoopback:
    """Sprint 1B: Gap-triggered analyze→build loopback."""

    @staticmethod
    def _set_stage(db, project_id: int, stage: str) -> None:
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE orchestrator_runs SET current_stage = ? WHERE project_id = ?",
                (stage, project_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _setup_analyze(self, svc, db, topic_id, project_id):
        """Set up project at analyze stage with all required artifacts."""
        svc.init_run(project_id=project_id, topic_id=topic_id)
        self._set_stage(db, project_id, "analyze")

        for art_type in ("evidence_pack", "claim_candidate_set", "direction_proposal"):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="analyze",
                artifact_type=art_type,
                payload={},
            )

    def test_analyze_gate_needs_expansion_with_few_gaps(
        self, svc, topic_and_project, db
    ):
        topic_id, project_id = topic_and_project
        self._setup_analyze(svc, db, topic_id, project_id)

        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="analyze",
            artifact_type="gap_detect",
            payload={"gaps": [{"id": 1, "severity": "high"}]},
        )

        decision = svc.check_gate(project_id, stage="analyze")
        assert decision == "needs_expansion"

    def test_analyze_gate_passes_with_enough_gaps(self, svc, topic_and_project, db):
        topic_id, project_id = topic_and_project
        self._setup_analyze(svc, db, topic_id, project_id)

        gaps = [{"id": i, "severity": "high"} for i in range(5)]
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="analyze",
            artifact_type="gap_detect",
            payload={"gaps": gaps},
        )

        decision = svc.check_gate(project_id, stage="analyze")
        assert decision == "pass"

    def test_advance_triggers_loopback_on_needs_expansion(
        self, svc, topic_and_project, db
    ):
        topic_id, project_id = topic_and_project
        self._setup_analyze(svc, db, topic_id, project_id)

        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="analyze",
            artifact_type="gap_detect",
            payload={"gaps": [{"id": 1}]},
        )

        result = svc.advance(project_id)
        assert result["success"] is True
        assert result.get("loopback") is True
        assert result["from_stage"] == "analyze"
        assert result["to_stage"] == "build"
        assert result["round"] == 1

        run = svc.get_run(project_id)
        assert run.current_stage == "build"

    def test_loopback_limited_to_max_rounds(self, svc, topic_and_project, db):
        topic_id, project_id = topic_and_project
        self._setup_analyze(svc, db, topic_id, project_id)

        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="analyze",
            artifact_type="gap_detect",
            payload={"gaps": [{"id": 1}]},
        )

        conn = db.connect()
        try:
            run = svc.get_run(project_id)
            for i in range(2):
                conn.execute(
                    """
                    INSERT INTO orchestrator_stage_events
                    (run_id, project_id, topic_id, from_stage, to_stage,
                     event_type, status, actor, rationale)
                    VALUES (?, ?, ?, 'analyze', 'build', 'transition', 'in_progress', 'system', ?)
                    """,
                    (run.id, project_id, topic_id, f"loopback round {i + 1}"),
                )
            conn.commit()
        finally:
            conn.close()

        result = svc.advance(project_id)
        assert result["success"] is False
        assert result["gate_decision"] == "needs_expansion"


class TestExpansionBudget:
    """Sprint 1C: Expansion budget on stage policies."""

    def test_analyze_has_paper_search_tools(self):
        from research_harness.auto_runner.stage_policy import STAGE_POLICIES

        tools = STAGE_POLICIES["analyze"].tools
        assert "paper_search" in tools
        assert "paper_ingest" in tools

    def test_analyze_has_expansion_budget(self):
        from research_harness.auto_runner.stage_policy import STAGE_POLICIES

        assert STAGE_POLICIES["analyze"].expansion_paper_budget == 30

    def test_propose_has_expansion_budget(self):
        from research_harness.auto_runner.stage_policy import STAGE_POLICIES

        assert STAGE_POLICIES["propose"].expansion_paper_budget == 10

    def test_build_has_unlimited_budget(self):
        from research_harness.auto_runner.stage_policy import STAGE_POLICIES

        assert STAGE_POLICIES["build"].expansion_paper_budget == 0

    def test_finalize_summary_includes_stage_history(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)

        result = svc.finalize_project(project_id=project_id)
        summary_id = result["summary_artifact_id"]
        summary = svc._artifact_manager.get(summary_id)
        assert summary is not None
        assert "stage_history" in summary.payload
        assert len(summary.payload["stage_history"]) >= 1  # at least the init event


# ---------------------------------------------------------------------------
# Reinforced-gate coverage — added alongside the 2026-04-22 gate hardening
# pass. Each test here corresponds to a specific rule baked into
# transitions.py::GateEvaluator or service.py::_try_auto_loopback.
# ---------------------------------------------------------------------------


def _set_stage(db, project_id: int, stage: str) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE orchestrator_runs SET current_stage = ? WHERE project_id = ?",
            (stage, project_id),
        )
        conn.commit()
    finally:
        conn.close()


class TestInitGateStricter:
    """Init stage gate: scope + exclusion + seed papers are required."""

    def test_empty_topic_brief_blocks_gate(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _seed_topic_with_papers(db, topic_id, count=3)
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="init",
            artifact_type="topic_brief",
            payload={},
        )
        # Missing scope/exclusion → needs_approval (schema violation on
        # scope/venue_target is only medium severity and therefore not
        # blocking, but the init-gate semantic check still blocks).
        assert svc.check_gate(project_id, stage="init") == "needs_approval"

    def test_missing_exclusion_blocks_gate(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _seed_topic_with_papers(db, topic_id, count=3)
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="init",
            artifact_type="topic_brief",
            payload={"scope": "Test scope", "venue_target": "NeurIPS"},
        )
        assert svc.check_gate(project_id, stage="init") == "needs_approval"

    def test_too_few_seed_papers_blocks_gate(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _seed_topic_with_papers(db, topic_id, count=1)  # below MIN_SEED_PAPER_COUNT
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="init",
            artifact_type="topic_brief",
            payload=_valid_topic_brief_payload(),
        )
        assert svc.check_gate(project_id, stage="init") == "needs_approval"

    def test_full_init_setup_passes(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _seed_topic_with_papers(db, topic_id, count=3)
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="init",
            artifact_type="topic_brief",
            payload=_valid_topic_brief_payload(),
        )
        assert svc.check_gate(project_id, stage="init") == "pass"


class TestReviewGateHardened:
    """Write-stage review gate must enforce final_bundle + integrity + citations."""

    def _write_stage(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _set_stage(db, project_id, "write")
        return topic_id, project_id

    def _all_required(self, svc, project_id: int, topic_id: int) -> None:
        for art_type, payload in (
            ("final_bundle", {}),
            ("process_summary", {}),
            ("final_integrity_report", {"passed": True, "critical_count": 0}),
        ):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="write",
                artifact_type=art_type,
                payload=payload,
            )

    def test_missing_final_bundle_blocks(self, svc, db, topic_and_project):
        topic_id, project_id = self._write_stage(svc, db, topic_and_project)
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="write",
            artifact_type="process_summary",
            payload={},
        )
        assert svc.check_gate(project_id) == "needs_review"

    def test_missing_process_summary_blocks(self, svc, db, topic_and_project):
        topic_id, project_id = self._write_stage(svc, db, topic_and_project)
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="write",
            artifact_type="final_bundle",
            payload={},
        )
        assert svc.check_gate(project_id) == "needs_review"

    def test_failing_integrity_report_blocks(self, svc, db, topic_and_project):
        topic_id, project_id = self._write_stage(svc, db, topic_and_project)
        for art_type, payload in (
            ("final_bundle", {}),
            ("process_summary", {}),
            ("final_integrity_report", {"passed": False, "critical_count": 2}),
        ):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="write",
                artifact_type=art_type,
                payload=payload,
            )
        assert svc.check_gate(project_id) == "needs_review"

    def test_hallucinated_citation_blocks(self, svc, db, topic_and_project):
        topic_id, project_id = self._write_stage(svc, db, topic_and_project)
        self._all_required(svc, project_id, topic_id)
        conn = db.connect()
        try:
            conn.execute(
                """INSERT INTO citation_verifications
                   (project_id, title, status) VALUES (?, ?, 'hallucinated')""",
                (project_id, "Fake Paper"),
            )
            conn.commit()
        finally:
            conn.close()
        assert svc.check_gate(project_id) == "needs_review"

    def test_critical_open_issue_blocks(self, svc, db, topic_and_project):
        topic_id, project_id = self._write_stage(svc, db, topic_and_project)
        self._all_required(svc, project_id, topic_id)
        svc.add_review_issue(
            project_id=project_id,
            review_type="integrity",
            severity="critical",
            category="methodology",
            summary="Critical finding",
            blocking=False,  # will still be escalated
        )
        assert svc.check_gate(project_id) == "needs_review"

    def test_passes_with_all_artifacts_and_clean(self, svc, db, topic_and_project):
        topic_id, project_id = self._write_stage(svc, db, topic_and_project)
        self._all_required(svc, project_id, topic_id)
        assert svc.check_gate(project_id) == "pass"


class TestAnalyzeGateEvidenceCoverage:
    """Evidence-trace coverage soft check at the analyze gate."""

    def _analyze_ready(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _set_stage(db, project_id, "analyze")
        # Required artifacts for analyze approval gate.
        for art_type, payload in (
            ("evidence_pack", {"claims": [{"id": "c1"}]}),
            ("claim_candidate_set", {}),
            ("direction_proposal", {"research_question": "Q?"}),
            # Enough gaps so analyze doesn't trigger needs_expansion.
            ("gap_detect", {"gaps": [1, 2, 3, 4, 5]}),
        ):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="analyze",
                artifact_type=art_type,
                payload=payload,
            )
        return topic_id, project_id

    def test_low_evidence_coverage_triggers_needs_expansion(
        self, svc, db, topic_and_project
    ):
        topic_id, project_id = self._analyze_ready(svc, db, topic_and_project)
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="analyze",
            artifact_type="evidence_trace_report",
            payload={"coverage_ratio": 0.4},
        )
        assert svc.check_gate(project_id) == "needs_expansion"

    def test_high_evidence_coverage_passes(self, svc, db, topic_and_project):
        topic_id, project_id = self._analyze_ready(svc, db, topic_and_project)
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="analyze",
            artifact_type="evidence_trace_report",
            payload={"coverage_ratio": 0.9},
        )
        assert svc.check_gate(project_id) == "pass"


class TestExperimentGateMigrationFailure:
    """experiment_gate should surface DB problems as 'fail', not pretend the
    experiment simply wasn't run."""

    def test_missing_experiment_runs_table_reports_fail(
        self, svc, db, topic_and_project
    ):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _set_stage(db, project_id, "experiment")
        for art_type in ("experiment_code", "experiment_result", "verified_registry"):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="experiment",
                artifact_type=art_type,
                payload={"metrics": {}, "whitelist_size": 1},
            )
        conn = db.connect()
        try:
            conn.execute("DROP TABLE IF EXISTS experiment_runs")
            conn.commit()
        finally:
            conn.close()
        assert svc.check_gate(project_id) == "fail"


class TestAutoLoopbackRules:
    """Generic AUTO_LOOPBACK_RULES should fire for multiple (stage, decision)
    pairs, not only analyze→build."""

    def test_rules_cover_expected_transitions(self):
        rules = OrchestratorService.AUTO_LOOPBACK_RULES
        assert ("analyze", "needs_expansion") in rules
        assert ("propose", "needs_coverage") in rules
        assert ("propose", "needs_expansion") in rules
        assert ("experiment", "needs_experiment") in rules
        assert ("write", "needs_review") in rules

    def test_loopback_respects_max_rounds(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        run = svc.init_run(project_id=project_id, topic_id=topic_id)
        # Simulate max rounds of prior analyze→build transitions.
        conn = db.connect()
        try:
            for _ in range(OrchestratorService.MAX_GAP_LOOPBACKS):
                conn.execute(
                    """INSERT INTO orchestrator_stage_events
                       (run_id, project_id, topic_id, from_stage, to_stage,
                        event_type, status, actor, rationale)
                       VALUES (?, ?, ?, 'analyze', 'build', 'transition',
                               'in_progress', 'system', 'prior loop')""",
                    (run.id, project_id, topic_id),
                )
            conn.commit()
        finally:
            conn.close()

        result = svc._try_auto_loopback(
            run, "analyze", "needs_expansion", actor="test"
        )
        assert result is None

    def test_loopback_respects_stop_before(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        run = svc.init_run(project_id=project_id, topic_id=topic_id)
        run = svc.resume_run(
            project_id=project_id, topic_id=topic_id, stop_before="build"
        )
        result = svc._try_auto_loopback(
            run, "analyze", "needs_expansion", actor="test"
        )
        # target_stage is "build" which is also the stop_before guard.
        assert result is None


class TestInferStageRespectsGate:
    """infer_stage_from_artifacts must stop at the first unsatisfied gate."""

    def test_returns_init_when_empty(self, svc, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        assert svc.infer_stage_from_artifacts(project_id) == "init"

    def test_stops_at_incomplete_build_gate(self, svc, db, topic_and_project):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _seed_topic_with_papers(db, topic_id, count=3)
        # Init complete...
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="init",
            artifact_type="topic_brief",
            payload=_valid_topic_brief_payload(),
        )
        # ...but only half of build artifacts recorded (no citation expansion
        # or acquisition report).
        for art_type in ("literature_map", "paper_pool_snapshot"):
            svc.record_artifact(
                project_id=project_id,
                topic_id=topic_id,
                stage="build",
                artifact_type=art_type,
                payload={},
            )
        # Init passed so we should resume at build (missing artifacts).
        assert svc.infer_stage_from_artifacts(project_id) == "build"


class TestInvariantSectionCitations:
    """check_section_citations must now run via check_all."""

    def test_draft_without_citations_surfaces_violation(
        self, svc, db, topic_and_project
    ):
        topic_id, project_id = topic_and_project
        svc.init_run(project_id=project_id, topic_id=topic_id)
        _set_stage(db, project_id, "write")
        # Draft pack has an introduction longer than 200 chars with no \cite
        # / [N] / (Author, Year) pattern at all.
        long_intro = (
            "This paper introduces a fascinating new framework. " * 10
        )
        svc.record_artifact(
            project_id=project_id,
            topic_id=topic_id,
            stage="write",
            artifact_type="draft_pack",
            payload={"sections": {"introduction": long_intro}},
        )
        from research_harness.orchestrator.invariants import InvariantChecker

        checker = InvariantChecker(db)
        violations = checker.check_all(project_id, "write")
        assert any(v.check == "section_citations" for v in violations)
