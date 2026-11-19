"""Regressions for the four known visual defects of the current recipe.

Every test here is decorated with ``known_issue`` on purpose: ``unittest.expectedFailure``
by default, a plain test under ``CCD_STRICT=1``. The pixel recipe is
frozen until reference intervals exist (see ``tests/KNOWN_ISSUES.md``), so the suite has
to stay green *while the defect is visible and measured*. When a test starts passing,
unittest reports an unexpected success and the suite turns red: that is the signal to
delete the decorator and the matching row in ``KNOWN_ISSUES.md``.

Measurements in the docstrings are from VERSION 1.5.2 on synthetic fixtures, so they can
be re-derived without any external photo.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "skills" / "ccd-photo-enhancer" / "scripts"))

import apply_ccd  # noqa: E402
import ccd_profile  # noqa: E402

SEED = 7

STRICT = os.environ.get("CCD_STRICT") == "1"


def known_issue(func):
    """Pin a defect: an expected failure by default, a hard failure under CCD_STRICT=1."""
    if STRICT:
        return func
    return unittest.expectedFailure(func)


def _run(strip: np.ndarray, preset: apply_ccd.Preset, strength: int) -> np.ndarray:
    return apply_ccd._apply_pixel_recipe(strip, preset, strength, SEED, None, None, None)


def _tone_only(preset_name: str) -> apply_ccd.Preset:
    """Preset with grain and vignette removed, so only global tone moves the patch."""
    return dataclasses.replace(
        apply_ccd.PRESETS[preset_name],
        grain_sigma=0.0,
        vignette_amount=0.0,
    )


def _longest_equal_run(values: list[int]) -> int:
    best = run = 1
    for previous, current in zip(values, values[1:]):
        run = run + 1 if current == previous else 1
        best = max(best, run)
    return best


class KnownIssueTests(unittest.TestCase):
    """Each failure is documented, attributable and waiting on reference intervals."""

    @known_issue
    def test_ki01_top_end_fuses_adjacent_levels(self) -> None:
        """KI-01: inputs 247..255 all print as 254 (longest run 9, 20/31 levels survive).

        Target: no more than two adjacent input levels may collapse into one output value.
        """
        levels = np.arange(225, 256, dtype=np.uint8)
        strip = np.empty((16, levels.size * 8, 3), dtype=np.uint8)
        for index, level in enumerate(levels):
            strip[:, index * 8 : (index + 1) * 8, :] = level

        after = _run(strip, _tone_only("daylight-clean"), 100)
        printed = [int(after[8, index * 8 + 4, 0]) for index in range(levels.size)]
        run = _longest_equal_run(printed)
        self.assertLessEqual(run, 2, f"{run} adjacent top-end levels print as one value: {printed}")

    @known_issue
    def test_ki02_indoor_flash_dims_the_centre(self) -> None:
        """KI-02: indoor-flash darkens the centre of a mid-grey field by 0.94% L*.

        A direct-flash look should lift the centre; a negative centre delta means the
        global tone stage is outvoting the flash impression.
        Target: centre_delta_ratio >= 0 at full strength.
        """
        field = np.full((240, 320, 3), 110, dtype=np.int16)
        field = np.clip(field + np.random.default_rng(0).integers(-2, 3, size=field.shape), 0, 255).astype(np.uint8)
        preset = dataclasses.replace(apply_ccd.PRESETS["indoor-flash"], grain_sigma=0.0)

        before = ccd_profile.srgb_to_lab(field)[..., 0]
        after = ccd_profile.srgb_to_lab(_run(field, preset, 100))[..., 0]
        _corner_before, centre_before = ccd_profile._corner_and_centre(before)
        _corner_after, centre_after = ccd_profile._corner_and_centre(after)
        centre_delta = (centre_after - centre_before) / centre_before
        self.assertGreaterEqual(centre_delta, 0.0, f"centre moves {centre_delta:+.4f} L*")

    @known_issue
    def test_ki03_restrained_strength_shifts_the_median(self) -> None:
        """KI-03: at strength 50 the median of a mid-grey patch moves -2.06 L* (aged) / -2.25 L* (night).

        Strength 50 is documented as restrained, so a two-L* global shift is more than
        the documentation implies for every preset.
        Target: |delta L*50| <= 1.5 at strength 50 with grain and vignette isolated out.
        """
        neutral = np.full((120, 160, 3), 100, dtype=np.uint8)
        before = ccd_profile.measure(neutral)["L_p50"]
        for preset_name in sorted(apply_ccd.PRESETS):
            after = ccd_profile.measure(_run(neutral, _tone_only(preset_name), 50))["L_p50"]
            self.assertLessEqual(abs(after - before), 1.5, f"{preset_name} moves {after - before:+.2f} L*")

    @known_issue
    def test_ki04_grain_crushes_dark_patches_to_black(self) -> None:
        """KI-04: at strength 50 a flat level-18 patch goes from 0% to 13-20% pure black.

        The crush is grain-driven: with grain off the same patch stays at 0%, so this is
        the noise floor, not the black point.
        Target: near_black increase <= 0.05 at strength 50 on a flat patch that starts clean.
        """
        patch = np.full((160, 200, 3), 18, dtype=np.uint8)
        before = ccd_profile.measure(patch)["near_black"]
        for preset_name in sorted(apply_ccd.PRESETS):
            after = ccd_profile.measure(_run(patch, apply_ccd.PRESETS[preset_name], 50))["near_black"]
            self.assertLessEqual(after - before, 0.05, f"{preset_name} pushes {after - before:+.3f} of the patch to pure black")


if __name__ == "__main__":
    unittest.main()
