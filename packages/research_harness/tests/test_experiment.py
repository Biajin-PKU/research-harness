"""Tests for experiment subpackage — validator, metric parser, sandbox, verified registry."""

from __future__ import annotations

import pytest

from research_harness.experiment.metric_parser import (
    detect_nan_divergence,
    parse_metrics,
)
from research_harness.experiment.sandbox import is_improvement, run_experiment
from research_harness.experiment.validator import (
    auto_fix_unbound_locals,
    validate_code,
    validate_imports,
    validate_security,
    validate_syntax,
)
from research_harness.experiment.verified_registry import (
    ALWAYS_ALLOWED,
    VerifiedRegistry,
    build_registry_from_metrics,
)


# -- Metric Parser -----------------------------------------------------------


class TestMetricParser:
    def test_plain_format(self):
        metrics = parse_metrics("accuracy: 0.95\nloss: 0.23\n")
        assert metrics["accuracy"] == pytest.approx(0.95)
        assert metrics["loss"] == pytest.approx(0.23)

    def test_condition_prefixed(self):
        metrics = parse_metrics(
            "condition=baseline accuracy: 0.85\ncondition=ours accuracy: 0.92\n"
        )
        assert metrics["baseline/accuracy"] == pytest.approx(0.85)
        assert metrics["ours/accuracy"] == pytest.approx(0.92)

    def test_ratio_format(self):
        metrics = parse_metrics("condition=model success_rate: 85/100\n")
        assert metrics["model/success_rate"] == pytest.approx(0.85)

    def test_summary_format(self):
        metrics = parse_metrics("SUMMARY condition=ours metric=f1 mean=0.91 std=0.03\n")
        assert metrics["ours/f1"] == pytest.approx(0.91)
        assert metrics["ours/f1_std"] == pytest.approx(0.03)

    def test_skips_nan(self):
        metrics = parse_metrics("accuracy: nan\nloss: 0.5\n")
        assert "accuracy" not in metrics
        assert metrics["loss"] == pytest.approx(0.5)

    def test_nan_divergence_detection(self):
        assert detect_nan_divergence("loss: nan", "") != ""
        assert detect_nan_divergence("", "math domain error") != ""
        assert detect_nan_divergence("loss: 200.5", "") != ""
        assert detect_nan_divergence("accuracy: 0.95", "") == ""

    def test_inf_detection(self):
        assert detect_nan_divergence("loss: inf", "") != ""
        assert (
            detect_nan_divergence("information about training", "") == ""
        )  # "info" not "inf"


# -- Validator ----------------------------------------------------------------


class TestValidator:
    def test_valid_code(self):
        code = "import numpy as np\nx = np.array([1, 2, 3])\nprint(x.mean())\n"
        result = validate_code(code)
        assert result.ok

    def test_syntax_error(self):
        issues = validate_syntax("def foo(\n")
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].category == "syntax"

    def test_dangerous_call(self):
        issues = validate_security("import os\nos.system('rm -rf /')\n")
        assert any(i.severity == "error" and "os.system" in i.message for i in issues)

    def test_dangerous_builtin(self):
        issues = validate_security("eval('print(1)')\n")
        assert any(i.severity == "error" and "eval" in i.message for i in issues)

    def test_banned_module(self):
        issues = validate_security("import subprocess\n")
        assert any(i.severity == "error" and "subprocess" in i.message for i in issues)

    def test_unknown_import_is_warning(self):
        issues = validate_imports("import some_obscure_package\n")
        assert any(
            i.severity == "warning" and "some_obscure_package" in i.message
            for i in issues
        )

    def test_safe_imports_pass(self):
        code = "import numpy\nimport torch\nimport json\nimport math\n"
        issues = validate_imports(code)
        assert not any(i.severity == "error" for i in issues)

    def test_combined_validation(self):
        bad_code = "import subprocess\nsubprocess.run(['ls'])\n"
        result = validate_code(bad_code)
        assert not result.ok
        assert result.error_count >= 1

    def test_auto_fix_unbound(self):
        code = "if True:\n    x = 1\nprint(x)\n"
        fixed, n = auto_fix_unbound_locals(code)
        assert n >= 1
        assert "x = None" in fixed


# -- Sandbox ------------------------------------------------------------------


class TestSandbox:
    def test_simple_experiment(self):
        code = 'print("accuracy: 0.95")\nprint("loss: 0.23")\n'
        result = run_experiment(code, timeout_sec=10.0)
        assert result.returncode == 0
        assert result.metrics["accuracy"] == pytest.approx(0.95)
        assert result.metrics["loss"] == pytest.approx(0.23)
        assert not result.timed_out

    def test_timeout(self):
        code = "import time\ntime.sleep(100)\n"
        result = run_experiment(code, timeout_sec=1.0)
        assert result.timed_out
        assert result.returncode == -1

    def test_error_code(self):
        code = "raise ValueError('boom')\n"
        result = run_experiment(code, timeout_sec=5.0)
        assert result.returncode != 0
        assert "boom" in result.stderr

    def test_is_improvement(self):
        assert is_improvement(0.95, 0.90, direction="maximize")
        assert not is_improvement(0.85, 0.90, direction="maximize")
        assert is_improvement(0.10, 0.15, direction="minimize")
        assert not is_improvement(0.20, 0.15, direction="minimize")


# -- Verified Registry --------------------------------------------------------


class TestVerifiedRegistry:
    def test_basic_verification(self):
        registry = VerifiedRegistry()
        registry.add_value(0.95, "accuracy")
        assert registry.is_verified(0.95)
        assert registry.is_verified(0.9500001)  # within 1% tolerance
        assert not registry.is_verified(0.80)

    def test_rounding_variants(self):
        registry = VerifiedRegistry()
        registry.add_value(0.9534, "accuracy")
        assert registry.is_verified(0.95)  # rounded to 2dp
        assert registry.is_verified(0.953)  # rounded to 3dp

    def test_percentage_variant(self):
        registry = VerifiedRegistry()
        registry.add_value(0.87, "accuracy")
        assert registry.is_verified(87.0)  # percentage conversion

    def test_inverse_variant(self):
        registry = VerifiedRegistry()
        registry.add_value(73.42, "metric")
        assert registry.is_verified(0.7342)  # inverse conversion

    def test_build_from_metrics(self):
        metrics = {
            "baseline/accuracy": 0.85,
            "ours/accuracy": 0.92,
            "baseline/f1": 0.80,
            "ours/f1": 0.88,
        }
        registry = build_registry_from_metrics(metrics, "accuracy")
        assert registry.primary_metric is not None  # picks first match
        assert "baseline" in registry.condition_names
        assert "ours" in registry.condition_names
        # Both accuracy values are registered
        assert registry.is_verified(0.85)
        assert registry.is_verified(0.92)
        # Pairwise diff
        assert registry.is_verified(0.07)

    def test_always_allowed(self):
        assert 0.0 in ALWAYS_ALLOWED
        assert 100.0 in ALWAYS_ALLOWED
        assert 2024.0 in ALWAYS_ALLOWED
        assert 256.0 in ALWAYS_ALLOWED

    def test_lookup_returns_source(self):
        registry = VerifiedRegistry()
        registry.add_value(42.0, "the_answer")
        assert registry.lookup(42.0) is not None
        assert "the_answer" in registry.lookup(42.0)
        assert registry.lookup(999.0) is None


# -- Experiment Primitives (integration) --------------------------------------


class TestExperimentPrimitives:
    def test_code_validate_primitive(self):
        from research_harness.primitives.experiment_impls import code_validate

        result = code_validate(code="import numpy\nprint(1)\n")
        assert result.ok

    def test_code_validate_rejects_dangerous(self):
        from research_harness.primitives.experiment_impls import code_validate

        result = code_validate(code="import subprocess\nsubprocess.run(['ls'])\n")
        assert not result.ok

    def test_experiment_run_primitive(self):
        from research_harness.primitives.experiment_impls import experiment_run

        result = experiment_run(
            code='print("val_loss: 0.42")\n',
            timeout_sec=5.0,
            primary_metric="val_loss",
        )
        assert result.primary_metric_value == pytest.approx(0.42)
        assert result.returncode == 0

    def test_verified_registry_build_and_check(self, tmp_path):
        from research_harness.primitives.experiment_impls import (
            verified_registry_build,
            verified_registry_check,
        )
        from research_harness.storage.db import Database

        db = Database(tmp_path / "test.db")
        db.migrate()
        conn = db.connect()
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 't')")
        # Stub projects row needed because verified_numbers.project_id FK
        # still references projects(id) and the impl writes topic_id there.
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, 'stub', 'stub')"
        )
        conn.commit()
        conn.close()

        build_result = verified_registry_build(
            db=db,
            topic_id=1,
            metrics={"baseline/acc": 0.85, "ours/acc": 0.92},
            primary_metric_name="acc",
        )
        assert build_result.whitelist_size > 0
        assert build_result.primary_metric is not None  # picks first match

        check_result = verified_registry_check(
            db=db,
            topic_id=1,
            numbers=[0.92, 0.85, 999.99],
        )
        assert 0.92 in check_result.verified
        assert 999.99 in check_result.unverified
        assert check_result.pass_rate < 1.0
