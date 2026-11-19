"""Single-stage ablation for the shipped pixel recipe.

Tuning the recipe is gated on having reference intervals; ablation is the tool that
will be used once those intervals exist. It changes nothing in the bundle: it builds
a copy of a preset with exactly one stage neutralised, so the profiler can attribute a
difference to that stage instead of guessing.

Every preset field listed here is a *magnitude*: 0.0 means "stage off". Fields that
are tuples (colour gains) are deliberately absent, because zeroing a gain is not the
same as disabling the stage.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any

BUNDLE_SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "ccd-photo-enhancer" / "scripts"
if str(BUNDLE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(BUNDLE_SCRIPTS))

import apply_ccd  # noqa: E402  (path set above on purpose)

STAGES: dict[str, tuple[str, ...]] = {
    "s-curve": ("contrast_delta",),
    "black-point": ("black_point",),
    "vignette": ("vignette_amount",),
    "flash-falloff": ("flash_falloff",),
    "halation": ("halation",),
    "grain": ("grain_sigma",),
    "sharpness": ("sharpness_amount",),
}


def ablate(preset: apply_ccd.Preset, stage: str) -> tuple[apply_ccd.Preset, dict[str, float]]:
    """Return a copy of `preset` with one stage zeroed, plus the applied changes."""
    if stage not in STAGES:
        raise ValueError(f"unknown ablation stage {stage!r}; choose from {sorted(STAGES)}")
    fields = STAGES[stage]
    already_off = [field for field in fields if float(getattr(preset, field)) == 0.0]
    if len(already_off) == len(fields):
        raise ValueError(f"stage {stage!r} is already off in preset {preset.name!r}")

    changes = {field: 0.0 for field in fields}
    return dataclasses.replace(preset, **changes), changes


def describe(stage: str, preset_name: str, changes: dict[str, float]) -> dict[str, Any]:
    """Record what was switched off, so an ablated report cannot pass as production."""
    return {
        "stage": stage,
        "preset": preset_name,
        "zeroed_fields": changes,
        "note": "消融测量：该阶段被置零，结果不是生产配方，也不能当作基线。",
    }
