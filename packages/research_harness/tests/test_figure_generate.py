"""Tests for figure_generate primitive and fal_image_client."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from research_harness.execution.fal_image_client import (
    build_image_prompt,
    choose_dimensions,
    classify_figure_style,
    figure_id_to_filename,
    generate_image,
    DIMENSION_PRESETS,
)


class TestBuildImagePrompt:
    def test_architecture_prompt(self):
        prompt = build_image_prompt(
            title="ModalGate Architecture",
            purpose="Show the overall system architecture with modal gating mechanism",
            suggested_layout="wide horizontal flow diagram",
            section="method",
        )
        assert "architecture" in prompt.lower()
        assert "ModalGate" in prompt
        assert "white background" in prompt
        assert "labeled" in prompt.lower()

    def test_pipeline_prompt(self):
        prompt = build_image_prompt(
            title="Training Pipeline",
            purpose="Step-by-step data processing flow",
            suggested_layout="left-to-right flow",
            section="method",
        )
        assert "pipeline" in prompt.lower() or "flowchart" in prompt.lower()

    def test_comparison_prompt(self):
        prompt = build_image_prompt(
            title="Model Comparison",
            purpose="Ablation study showing component contributions",
            suggested_layout="grid layout",
            section="experiments",
        )
        assert "comparison" in prompt.lower()

    def test_empty_fields(self):
        prompt = build_image_prompt(title="", purpose="", section="")
        assert "academic" in prompt.lower()
        assert len(prompt) > 50


class TestFigureIdToFilename:
    def test_basic(self):
        assert figure_id_to_filename("fig:arch") == "arch.png"

    def test_no_prefix(self):
        assert figure_id_to_filename("overview") == "overview.png"

    def test_special_chars(self):
        assert figure_id_to_filename("fig:my figure!@#") == "my_figure___.png"

    def test_empty(self):
        assert figure_id_to_filename("") == "figure.png"

    def test_only_prefix(self):
        assert figure_id_to_filename("fig:") == "figure.png"

    def test_underscores_preserved(self):
        assert figure_id_to_filename("fig:arch_overview") == "arch_overview.png"

    def test_hyphens_preserved(self):
        assert figure_id_to_filename("fig:my-figure") == "my-figure.png"


class TestClassifyFigureStyle:
    def test_pipeline(self):
        style = classify_figure_style("data processing flow", "", "Pipeline")
        assert "infographical" in style

    def test_architecture(self):
        style = classify_figure_style("system architecture", "", "Framework")
        assert "digital_illustration" in style

    def test_comparison(self):
        style = classify_figure_style("ablation comparison", "", "Results")
        assert "digital_illustration" in style

    def test_default(self):
        style = classify_figure_style("some random purpose", "", "Figure")
        assert "digital_illustration" in style


class TestChooseDimensions:
    def test_wide_for_architecture(self):
        dims = choose_dimensions("wide horizontal", "architecture overview")
        assert dims == DIMENSION_PRESETS["wide"]

    def test_square_for_grid(self):
        dims = choose_dimensions("grid layout", "matrix comparison")
        assert dims == DIMENSION_PRESETS["square"]

    def test_default(self):
        dims = choose_dimensions("", "some purpose")
        assert dims == DIMENSION_PRESETS["standard"]


class TestGenerateImageMocked:
    def test_success_with_fal_client(self, tmp_path: Path):
        mock_result = {"images": [{"url": "https://example.com/image.png"}]}
        mock_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = mock_result

        mock_resp = MagicMock()
        mock_resp.content = mock_content
        mock_resp.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.get.return_value = mock_resp
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)

        with (
            patch.dict(os.environ, {"FAL_KEY": "test-key"}),
            patch.dict("sys.modules", {"fal_client": mock_fal}),
            patch("httpx.Client", return_value=mock_client_instance),
        ):
            result = generate_image(
                prompt="test diagram",
                output_dir=str(tmp_path),
                filename="test.png",
            )
            assert result.success
            assert result.image_url == "https://example.com/image.png"
            assert result.model_id == "fal-ai/recraft/v3/text-to-image"

    def test_missing_fal_key(self, tmp_path: Path):
        old_key = os.environ.pop("FAL_KEY", None)
        try:
            with pytest.raises(EnvironmentError, match="FAL_KEY"):
                generate_image(
                    prompt="test",
                    output_dir=str(tmp_path),
                    filename="test.png",
                )
        finally:
            if old_key:
                os.environ["FAL_KEY"] = old_key


class TestFigureGeneratePrimitive:
    def test_filters_tables(self, tmp_path: Path):
        from research_harness.execution.llm_primitives import figure_generate
        from research_harness.storage.db import Database

        items = [
            {
                "figure_id": "fig:arch",
                "kind": "figure",
                "title": "Arch",
                "purpose": "overview",
            },
            {"figure_id": "tab:main", "kind": "table", "title": "Main Results"},
        ]

        mock_gen = MagicMock()
        mock_gen.return_value = MagicMock(
            success=True,
            local_path=str(tmp_path / "arch.png"),
            model_id="recraft",
            width=1920,
            height=960,
            error="",
        )

        db = Database(":memory:")
        with patch(
            "research_harness.execution.fal_image_client.generate_image", mock_gen
        ):
            result = figure_generate(
                db=db,
                topic_id=1,
                items=items,
                output_dir=str(tmp_path),
                model="recraft",
            )

        assert result.total_requested == 1
        assert len(result.items) == 1
        assert result.items[0].figure_id == "fig:arch"

    def test_handles_generation_failure(self, tmp_path: Path):
        from research_harness.execution.llm_primitives import figure_generate
        from research_harness.storage.db import Database

        items = [
            {
                "figure_id": "fig:fail",
                "kind": "figure",
                "title": "Failing",
                "purpose": "test",
            },
        ]

        mock_gen = MagicMock(side_effect=RuntimeError("API down"))

        db = Database(":memory:")
        with patch(
            "research_harness.execution.fal_image_client.generate_image", mock_gen
        ):
            result = figure_generate(
                db=db,
                topic_id=1,
                items=items,
                output_dir=str(tmp_path),
                model="recraft",
            )

        assert result.total_requested == 1
        assert result.total_generated == 0
        assert result.total_failed == 1
        assert "API down" in result.items[0].error


@pytest.mark.skipif(
    not os.environ.get("FAL_KEY"),
    reason="FAL_KEY not set — skip real API test",
)
class TestRealGeneration:
    def test_generate_real_image(self, tmp_path: Path):
        result = generate_image(
            prompt=(
                "A clean academic architecture diagram showing an encoder-decoder model. "
                "White background, labeled boxes, connecting arrows. Minimalist style."
            ),
            output_dir=str(tmp_path),
            filename="test_real.png",
        )
        assert result.success, f"Generation failed: {result.error}"
        assert Path(result.local_path).exists()
        assert Path(result.local_path).stat().st_size > 1000
