"""fal.ai image generation client for academic figure generation."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RECRAFT_MODEL = "fal-ai/recraft/v3/text-to-image"
FLUX_MODEL = "fal-ai/flux-pro/v1.1"

RECRAFT_STYLES: dict[str, str] = {
    "pipeline": "vector_illustration/infographical",
    "flowchart": "vector_illustration/infographical",
    "architecture": "digital_illustration",
    "system": "digital_illustration",
    "comparison": "digital_illustration",
    "default": "digital_illustration",
}

DIMENSION_PRESETS: dict[str, dict[str, int]] = {
    "wide": {"width": 1920, "height": 960},
    "square": {"width": 1024, "height": 1024},
    "tall": {"width": 960, "height": 1920},
    "standard": {"width": 1440, "height": 960},
}


@dataclass(frozen=True)
class GenerationResult:
    success: bool
    image_url: str = ""
    local_path: str = ""
    error: str = ""
    model_id: str = ""
    width: int = 0
    height: int = 0


def _get_fal_key() -> str:
    key = os.environ.get("FAL_KEY", "")
    if not key:
        raise EnvironmentError(
            "FAL_KEY environment variable not set. "
            "Get your key at https://fal.ai/dashboard/keys"
        )
    return key


def classify_figure_style(purpose: str, suggested_layout: str, title: str) -> str:
    combined = f"{purpose} {suggested_layout} {title}".lower()
    if any(w in combined for w in ("pipeline", "flow", "process", "step", "sequence")):
        return RECRAFT_STYLES["pipeline"]
    if any(w in combined for w in ("architecture", "system", "framework", "overview", "module")):
        return RECRAFT_STYLES["architecture"]
    if any(w in combined for w in ("comparison", "ablation", "matrix", "grid")):
        return RECRAFT_STYLES["comparison"]
    return RECRAFT_STYLES["default"]


def choose_dimensions(suggested_layout: str, purpose: str) -> dict[str, int]:
    combined = f"{suggested_layout} {purpose}".lower()
    if any(w in combined for w in ("wide", "horizontal", "architecture", "pipeline", "overview")):
        return DIMENSION_PRESETS["wide"]
    if any(w in combined for w in ("vertical", "tall", "stack")):
        return DIMENSION_PRESETS["tall"]
    if any(w in combined for w in ("square", "matrix", "grid")):
        return DIMENSION_PRESETS["square"]
    return DIMENSION_PRESETS["standard"]


def figure_id_to_filename(figure_id: str) -> str:
    name = re.sub(r"^fig:", "", figure_id).strip()
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    if not name:
        name = "figure"
    return f"{name}.png"


def build_image_prompt(
    *,
    title: str,
    purpose: str,
    caption: str = "",
    data_source: str = "",
    suggested_layout: str = "",
    section: str = "",
) -> str:
    combined = f"{purpose} {suggested_layout} {title}".lower()
    if "pipeline" in combined or "flow" in combined:
        figure_type = "academic pipeline flowchart"
    elif "comparison" in combined or "ablation" in combined:
        figure_type = "academic comparison diagram"
    elif "overview" in combined or "system" in combined:
        figure_type = "system architecture overview diagram"
    else:
        figure_type = "academic architecture diagram"

    parts = [
        f"A clean, professional {figure_type} for an academic research paper.",
    ]
    if title:
        parts.append(f"Title: {title}.")
    if purpose:
        parts.append(f"The diagram shows: {purpose}.")
    if suggested_layout:
        parts.append(f"Layout: {suggested_layout}.")
    parts.append(
        "Style: clean vector illustration with labeled components, "
        "connecting arrows, white background, professional academic quality. "
        "No photorealistic elements. Clear text labels on each component. "
        "Minimal color palette (blues, grays, accent color for key elements)."
    )
    return " ".join(parts)


def generate_image(
    *,
    prompt: str,
    model: str = "recraft",
    style: str = "digital_illustration",
    dimensions: dict[str, int] | None = None,
    output_dir: str,
    filename: str,
    timeout: float = 60.0,
) -> GenerationResult:
    dims = dimensions or DIMENSION_PRESETS["standard"]
    fal_key = _get_fal_key()

    if model == "flux":
        model_id = FLUX_MODEL
        payload: dict[str, Any] = {
            "prompt": prompt,
            "image_size": dims,
            "output_format": "png",
            "num_images": 1,
            "enhance_prompt": False,
        }
    else:
        model_id = RECRAFT_MODEL
        payload = {
            "prompt": prompt,
            "style": style,
            "image_size": dims,
        }

    try:
        import fal_client
        result = fal_client.subscribe(model_id, arguments=payload)
        image_url: str = result["images"][0]["url"]
    except ImportError:
        logger.info("fal_client not installed, using httpx fallback")
        image_url = _fal_http_generate(model_id, payload, fal_key, timeout)
    except Exception as exc:
        return GenerationResult(success=False, error=f"fal.ai generation failed: {exc}", model_id=model_id)

    try:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        local_path = out_path / filename

        with httpx.Client(timeout=30.0) as client:
            resp = client.get(image_url)
            resp.raise_for_status()
            local_path.write_bytes(resp.content)

        return GenerationResult(
            success=True, image_url=image_url, local_path=str(local_path),
            model_id=model_id, width=dims["width"], height=dims["height"],
        )
    except Exception as exc:
        return GenerationResult(
            success=False, error=f"Image download failed: {exc}",
            image_url=image_url, model_id=model_id,
        )


def _fal_http_generate(
    model_id: str, payload: dict[str, Any], fal_key: str, timeout: float,
) -> str:
    import json

    headers = {"Authorization": f"Key {fal_key}", "Content-Type": "application/json"}
    base_url = f"https://queue.fal.run/{model_id}"

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(base_url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "images" in data:
            return data["images"][0]["url"]

        request_id = data.get("request_id")
        if not request_id:
            raise RuntimeError(f"No request_id in fal response: {data}")

        status_url = f"{base_url}/requests/{request_id}/status"
        result_url = f"{base_url}/requests/{request_id}"

        for _ in range(int(timeout)):
            time.sleep(1.0)
            status_resp = client.get(status_url, headers=headers)
            status_data = status_resp.json()
            if status_data.get("status") == "COMPLETED":
                result_resp = client.get(result_url, headers=headers)
                return result_resp.json()["images"][0]["url"]
            if status_data.get("status") in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"fal.ai job failed: {status_data}")

        raise TimeoutError(f"fal.ai job timed out after {timeout}s")
