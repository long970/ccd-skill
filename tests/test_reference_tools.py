"""Tests for the P1 tooling: pipeline fingerprint and reference-set validator.

These tests assert the *instrument*, not the look. They check that the profile
never invents a composite score, that the grain probe compares one region across
both phases, that guardrails only punish what the step made worse, and that the
validator refuses a manifest that would let an unverified photo be counted as a
CCD reference.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import ccd_profile  # noqa: E402
import ccd_ablate  # noqa: E402
import apply_ccd  # noqa: E402
import verify_reference_set  # noqa: E402

FAMILIES = verify_reference_set.FAMILIES


def _entry(**overrides) -> dict:
    entry = {
        "id": "indoor-flash-01",
        "family": "indoor-flash",
        "scene": "close-up portrait",
        "role": "calibration",
        "camera_make": None,
        "camera_model": None,
        "iso": None,
        "flash": None,
        "source": None,
        "license": None,
        "source_sha256": None,
        "local_path": None,
    }
    entry.update(overrides)
    return entry


def _manifest(status: str, entries: list[dict]) -> dict:
    return {
        "schema_version": "1",
        "status": status,
        "families": list(FAMILIES),
        "entries": entries,
    }


class ReferenceToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workdir = Path(tempfile.mkdtemp(prefix="ccd-tools-"))
        print(f"[ccd-tools] scratch directory: {cls.workdir}", file=sys.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.workdir, ignore_errors=True)
        super().tearDownClass()

    # ---- fingerprint -------------------------------------------------

    def test_srgb_to_lab_endpoints(self) -> None:
        white = np.full((2, 2, 3), 255, dtype=np.uint8)
        black = np.zeros((2, 2, 3), dtype=np.uint8)
        neutral = np.full((2, 2, 3), 128, dtype=np.uint8)
        self.assertAlmostEqual(float(ccd_profile.srgb_to_lab(white)[..., 0].mean()), 100.0, places=2)
        self.assertAlmostEqual(float(ccd_profile.srgb_to_lab(black)[..., 0].mean()), 0.0, places=2)
        lab = ccd_profile.srgb_to_lab(neutral)
        self.assertLess(abs(float(lab[..., 1].mean())), 0.5)
        self.assertLess(abs(float(lab[..., 2].mean())), 0.5)

    def test_measure_emits_no_composite_score(self) -> None:
        rgb = np.linspace(0, 255, 64 * 64 * 3, dtype=np.float32).reshape(64, 64, 3).astype(np.uint8)
        metrics = ccd_profile.measure(rgb)
        for key in ("L_p5", "L_p50", "L_p95", "near_white", "clipped_channel", "near_black", "corner_L", "centre_L"):
            self.assertIn(key, metrics)
        for forbidden in ("score", "composite", "total", "grade", "overall"):
            self.assertNotIn(forbidden, metrics)

    def test_grain_probe_reuses_one_mask(self) -> None:
        rng = np.random.default_rng(0)
        base = np.full((160, 160, 3), 96, dtype=np.uint8)
        noisy_half = np.clip(96 + rng.integers(-8, 9, size=(160, 80, 3)), 0, 255).astype(np.uint8)
        base[:, 80:, :] = noisy_half
        lab = ccd_profile.srgb_to_lab(base)
        mask = ccd_profile._flat_mask(lab[..., 0])
        self.assertIsNotNone(mask)
        assert mask is not None
        # The smooth half is the probe; the textured half must be excluded.
        self.assertLessEqual(float(mask.mean()), 0.6)
        self.assertGreater(float(mask.mean()), 0.2)
        self.assertGreater(float(mask[:, :70].mean()), 0.95)
        self.assertLess(float(mask[:, 90:].mean()), 0.05)

        before = ccd_profile.measure(base, mask, lab)
        after_rgb = np.clip(base.astype(np.int16) + rng.integers(-6, 7, size=base.shape), 0, 255).astype(np.uint8)
        after = ccd_profile.measure(after_rgb, mask)
        self.assertIsNotNone(before["flat_noise"])
        self.assertIsNotNone(after["flat_noise"])
        self.assertGreater(after["flat_noise"], before["flat_noise"] + 1.0)

    def test_delta_reports_ratios(self) -> None:
        before = {"corner_L": 100.0, "centre_L": 50.0, "L_p50": 60.0}
        after = {"corner_L": 75.0, "centre_L": 55.0, "L_p50": 58.0}
        delta = ccd_profile._delta(before, after)
        self.assertAlmostEqual(delta["corner_drop_ratio"], 0.25)
        self.assertAlmostEqual(delta["centre_delta_ratio"], 0.1)
        self.assertAlmostEqual(delta["L_p50"], -2.0)
        empty = ccd_profile._delta({"corner_L": 0.0, "centre_L": 0.0}, {"corner_L": 0.0, "centre_L": 0.0})
        self.assertIsNone(empty["corner_drop_ratio"])
        self.assertIsNone(empty["centre_delta_ratio"])

    def test_guardrails_only_punish_increases(self) -> None:
        already_blown = {
            "id": "studio",
            "before": {"near_white": 0.22, "clipped_channel": 0.12},
            "after": {"near_white": 0.19, "clipped_channel": 0.01},
            "delta": {"corner_drop_ratio": 0.01},
        }
        self.assertEqual(ccd_profile._guardrail_violations([already_blown]), [])

        made_worse = {
            "id": "worse",
            "before": {"near_white": 0.0, "clipped_channel": 0.0},
            "after": {"near_white": 0.05, "clipped_channel": 0.02},
            "delta": {"corner_drop_ratio": 0.5},
        }
        checks = {item["check"] for item in ccd_profile._guardrail_violations([made_worse])}
        self.assertEqual(
            checks,
            {"near_white_increase_max", "clipped_channel_increase_max", "corner_drop_ratio_max"},
        )

    def test_profile_image_measures_without_writing(self) -> None:
        path = self.workdir / "probe.png"
        array = np.full((96, 128, 3), 120, dtype=np.uint8)
        array[:32, :, :] = 200
        Image.fromarray(array).save(path)
        before_bytes = path.read_bytes()

        record = ccd_profile.profile_image(path, "daylight-aged", 60, 3)
        self.assertEqual(record["sha256"], hashlib.sha256(before_bytes).hexdigest())
        self.assertEqual(record["size"], [128, 96])
        self.assertEqual(record["preset"], "daylight-aged")
        self.assertEqual(record["strength"], 60)
        self.assertEqual(record["before"]["flat_noise"] is None, record["after"]["flat_noise"] is None)
        self.assertEqual(path.read_bytes(), before_bytes, "profiling must not touch the source file")

    def test_build_report_marks_missing_sources(self) -> None:
        path = self.workdir / "present.png"
        Image.fromarray(np.full((32, 32, 3), 128, dtype=np.uint8)).save(path)
        cases = [
            {"id": "ok", "path": path, "preset": "daylight-clean", "strength": 50},
            {"id": "gone", "path": self.workdir / "missing.png", "preset": "daylight-clean", "strength": 50},
        ]
        report = ccd_profile.build_report(cases, 1, "test", "folder")
        self.assertEqual(report["sources"]["count"], 2)
        self.assertEqual(report["sources"]["measured"], 1)
        self.assertFalse(report["baseline"])
        self.assertEqual(report["title"], ccd_profile.TITLE)
        self.assertIn("非 CCD 基线", report["title"])
        statuses = {image["id"]: image["status"] for image in report["images"]}
        self.assertEqual(statuses, {"ok": "ok", "gone": "missing_source"})

    def test_aggregate_flags_small_families_and_keeps_intervals(self) -> None:
        def record(family: str, value: float) -> dict:
            return {
                "status": "ok",
                "family": family,
                "after": {"L_p50": value},
                "delta": {"corner_drop_ratio": 0.1},
            }

        two = ccd_profile.aggregate([record("indoor-flash", 50.0), record("indoor-flash", 52.0)])
        self.assertTrue(two["indoor-flash"]["insufficient_n"])
        self.assertEqual(two["indoor-flash"]["after"]["L_p50"]["n"], 2)

        four = ccd_profile.aggregate([record("night-flash", 10.0 + i) for i in range(4)])
        self.assertFalse(four["night-flash"]["insufficient_n"])
        interval = four["night-flash"]["after"]["L_p50"]
        self.assertEqual(set(interval), {"n", "min", "p25", "median", "p75", "max"})

    # ---- validator ---------------------------------------------------

    def test_template_manifest_passes_but_is_unverified(self) -> None:
        manifest = json.loads((ROOT / "reference_set" / "manifest.template.json").read_text(encoding="utf-8"))
        report = verify_reference_set.validate(manifest, ROOT)
        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["manifest_status"], "template")
        self.assertEqual(report["counts"]["entries"], 16)
        self.assertEqual(report["counts"]["unverified"], 16)
        for family in FAMILIES:
            self.assertEqual(report["per_family"][family]["calibration"], 3)
            self.assertEqual(report["per_family"][family]["holdout"], 1)

    def test_duplicate_id_and_bad_family_fail(self) -> None:
        entries = [_entry(), _entry(), _entry(family="sepia")]
        report = verify_reference_set.validate(_manifest("template", entries), ROOT)
        self.assertEqual(report["result"], "fail")
        reasons = " ".join(item["reason"] for item in report["errors"])
        self.assertIn("duplicate id", reasons)
        self.assertIn("family must be one of", reasons)

    def test_hash_mismatch_fails_and_missing_path_fails_when_filled(self) -> None:
        image_path = self.workdir / "shot.jpg"
        Image.new("RGB", (24, 24), (120, 120, 120)).save(image_path, "JPEG")

        wrong = _entry(local_path=str(image_path), source_sha256="0" * 64)
        report = verify_reference_set.validate(_manifest("template", [wrong]), ROOT)
        self.assertEqual(report["result"], "fail")
        self.assertIn("sha256 mismatch", " ".join(item["reason"] for item in report["errors"]))

        missing = _entry(local_path=str(self.workdir / "absent.jpg"), source_sha256="0" * 64)
        template_report = verify_reference_set.validate(_manifest("template", [missing]), ROOT)
        self.assertEqual(template_report["result"], "pass")
        missing["id"] = "indoor-flash-02"
        filled_report = verify_reference_set.validate(_manifest("filled", [missing]), ROOT)
        self.assertEqual(filled_report["result"], "fail")
        self.assertIn("not found", " ".join(item["reason"] for item in filled_report["errors"]))

    def test_exif_provenance_separates_verified_from_unverified(self) -> None:
        bare = self.workdir / "bare.jpg"
        Image.new("RGB", (16, 16), (90, 90, 90)).save(bare, "JPEG")

        entry = _entry(
            local_path=str(bare),
            source_sha256=hashlib.sha256(bare.read_bytes()).hexdigest(),
        )
        report = verify_reference_set.validate(_manifest("template", [entry]), ROOT)
        item = report["entries"][0]
        self.assertEqual(item["status"], "unverified")
        self.assertIn("exif camera_model missing", item["reasons"])

        tagged = self.workdir / "tagged.jpg"
        exif = Image.Exif()
        exif[271] = "Canon"
        exif[272] = "PowerShot A80"
        exif[34855] = 100
        exif[37385] = 1
        Image.new("RGB", (16, 16), (90, 90, 90)).save(tagged, "JPEG", exif=exif)

        facts = verify_reference_set._exif_facts(tagged)
        self.assertEqual(facts["camera_make"], "Canon")
        self.assertEqual(facts["camera_model"], "PowerShot A80")
        self.assertIsNotNone(facts["iso"])
        self.assertIsNotNone(facts["flash"])

        entry = _entry(
            id="indoor-flash-03",
            local_path=str(tagged),
            source_sha256=hashlib.sha256(tagged.read_bytes()).hexdigest(),
            camera_make="Canon",
            camera_model="PowerShot A80",
            iso=100,
            flash=1,
            source="local camera, 2004",
            license="own work",
        )
        report = verify_reference_set.validate(_manifest("template", [entry]), ROOT)
        self.assertEqual(report["entries"][0]["status"], "verified")
        self.assertEqual(report["entries"][0]["file_state"], "present")

    def test_filled_manifest_requires_four_per_family(self) -> None:
        report = verify_reference_set.validate(_manifest("filled", [_entry()]), ROOT)
        self.assertEqual(report["result"], "fail")
        reasons = " ".join(item["reason"] for item in report["errors"])
        self.assertIn("at least 4 entries", reasons)
        self.assertIn("at least 1 holdout", reasons)

    def test_cli_exit_codes(self) -> None:
        self.assertEqual(verify_reference_set.main([str(ROOT / "reference_set" / "manifest.template.json")]), 0)

        broken = self.workdir / "broken.json"
        broken.write_text(json.dumps(_manifest("template", [_entry(family="sepia")])), encoding="utf-8")
        self.assertEqual(verify_reference_set.main([str(broken), "--root", str(ROOT)]), 1)


class ReferenceModeTests(unittest.TestCase):
    """--reference measures the camera's own pixels and must not pose as the pipeline."""

    def test_reference_skips_recipe_and_reports_no_delta(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ccd-ref-") as tmp:
            path = Path(tmp) / "src.png"
            Image.new("RGB", (48, 32), (118, 120, 122)).save(path)
            record = ccd_profile.profile_image(
                path, None, 50, 7, reference=True, family="daylight-clean"
            )
        self.assertTrue(record["reference"])
        self.assertEqual(record["delta"], {})
        self.assertIsNone(record["recipe"])
        self.assertIsNone(record["strength"])
        self.assertEqual(record["family"], "daylight-clean")
        self.assertEqual(record["before"], record["after"])

    def test_reference_report_drops_guardrails_and_carries_coverage(self) -> None:
        coverage = {
            "daylight-clean": {"calibration": 1, "holdout": 0, "status": "pilot"},
            "night-flash": {"calibration": 0, "holdout": 0, "status": "missing"},
        }
        with tempfile.TemporaryDirectory(prefix="ccd-ref-") as tmp:
            path = Path(tmp) / "src.png"
            Image.new("RGB", (48, 32), (118, 120, 122)).save(path)
            report = ccd_profile.build_report(
                [{"id": "r1", "path": path, "preset": None, "family": "daylight-clean", "strength": 50}],
                7,
                "m:test",
                "manifest",
                reference=True,
                coverage=coverage,
            )
        self.assertEqual(report["title"], ccd_profile.REFERENCE_TITLE)
        self.assertTrue(report["reference"])
        self.assertIsNone(report["guardrails"])
        self.assertIsNone(report["ablation"])
        self.assertEqual(report["coverage"], coverage)
        self.assertIn("daylight-clean", report["families"])
        absent = report["families"]["night-flash"]
        self.assertEqual(absent["n"], 0)
        self.assertTrue(absent["absent"])
        self.assertTrue(absent["insufficient_n"])
        self.assertIn("不是四族完整基线", report["note"])


class PartialManifestTests(unittest.TestCase):
    """A partial set may be small, but it must never hide which families are missing."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.workdir = Path(tempfile.mkdtemp(prefix="ccd-partial-"))
        tagged = cls.workdir / "tagged.jpg"
        exif = Image.Exif()
        exif[271] = "NIKON"
        exif[272] = "COOLPIX 990"
        exif[34855] = 100
        exif[37385] = 0  # flash did not fire: still real provenance
        Image.new("RGB", (16, 16), (90, 90, 90)).save(tagged, "JPEG", exif=exif)
        cls.entry = _entry(
            local_path=str(tagged),
            source_sha256=hashlib.sha256(tagged.read_bytes()).hexdigest(),
            camera_make="NIKON",
            camera_model="COOLPIX 990",
            iso=100,
            flash=0,
            source="review sample",
            license="analysis only",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.workdir, ignore_errors=True)
        super().tearDownClass()

    def _coverage(self) -> dict:
        return {
            "daylight-clean": {"calibration": 0, "holdout": 0, "status": "missing"},
            "daylight-aged": {"calibration": 0, "holdout": 0, "status": "missing"},
            "indoor-flash": {"calibration": 1, "holdout": 0, "status": "insufficient"},
            "night-flash": {"calibration": 0, "holdout": 0, "status": "missing"},
        }

    def test_flash_zero_counts_as_present(self) -> None:
        manifest = _manifest("partial", [self.entry]) | {"coverage": self._coverage()}
        report = verify_reference_set.validate(manifest, ROOT)
        self.assertEqual(report["entries"][0]["status"], "verified", report["entries"][0]["reasons"])
        self.assertTrue(report["partial"])
        self.assertEqual(report["result"], "pass", report["errors"])

    def test_partial_requires_coverage(self) -> None:
        report = verify_reference_set.validate(_manifest("partial", [self.entry]), ROOT)
        reasons = " ".join(item["reason"] for item in report["errors"])
        self.assertIn("must declare per-family coverage", reasons)

    def test_partial_coverage_must_match_entries(self) -> None:
        coverage = self._coverage()
        coverage["indoor-flash"]["calibration"] = 4
        manifest = _manifest("partial", [self.entry]) | {"coverage": coverage}
        report = verify_reference_set.validate(manifest, ROOT)
        reasons = " ".join(item["reason"] for item in report["errors"])
        self.assertIn("does not match entries", reasons)


class ShippedDaylightPilotTests(unittest.TestCase):
    """The committed Tier C pilot must stay coherent with whatever originals are present."""

    MANIFEST = ROOT / "reference_set" / "manifest.daylight.json"
    ORIGINALS = ROOT / "reference_set" / "originals"

    @unittest.skipUnless(ORIGINALS.is_dir(), "reference originals are local-only and gitignored")
    def test_shipped_daylight_manifest_validates(self) -> None:
        report = verify_reference_set.validate(
            json.loads(self.MANIFEST.read_text(encoding="utf-8")), self.MANIFEST.parent
        )
        self.assertTrue(report["partial"])
        self.assertEqual(report["result"], "pass", report["errors"])
        self.assertEqual(report["counts"]["entries"], 15)
        self.assertEqual(report["counts"]["unverified"], 0)

    def test_shipped_daylight_manifest_declares_its_gaps(self) -> None:
        manifest = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        coverage = manifest["coverage"]
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual(coverage["night-flash"]["status"], "missing")
        self.assertEqual(coverage["indoor-flash"]["status"], "insufficient")
        self.assertEqual(coverage["daylight-clean"]["status"], "pilot")


class AblationTests(unittest.TestCase):
    """Ablation must switch off exactly one stage and never pose as production."""

    def test_ablate_zeroes_exactly_one_stage(self) -> None:
        base = apply_ccd.PRESETS["daylight-aged"]
        ablated, changes = ccd_ablate.ablate(base, "grain")

        self.assertEqual(changes, {"grain_sigma": 0.0})
        self.assertEqual(ablated.grain_sigma, 0.0)
        self.assertEqual(ablated.name, base.name)
        for field in ("contrast_delta", "vignette_amount", "halation", "black_point", "flash_falloff"):
            self.assertEqual(getattr(ablated, field), getattr(base, field), field)

    def test_ablate_rejects_unknown_and_already_off_stages(self) -> None:
        with self.assertRaises(ValueError):
            ccd_ablate.ablate(apply_ccd.PRESETS["night-flash"], "sepia")

        # daylight-clean has flash_falloff == 0.0, so there is nothing to switch off.
        with self.assertRaises(ValueError):
            ccd_ablate.ablate(apply_ccd.PRESETS["daylight-clean"], "flash-falloff")

    def test_ablate_attributes_corner_drop(self) -> None:
        field = np.full((160, 200, 3), 110, dtype=np.uint8)
        base = apply_ccd.PRESETS["indoor-flash"]

        def corner_drop(preset: apply_ccd.Preset) -> float:
            after = apply_ccd._apply_pixel_recipe(field, preset, 100, 7, None, None, None)
            corner, _centre = ccd_profile._corner_and_centre(ccd_profile.srgb_to_lab(after)[..., 0])
            before, _ = ccd_profile._corner_and_centre(ccd_profile.srgb_to_lab(field)[..., 0])
            return (before - corner) / before

        ablated, _changes = ccd_ablate.ablate(base, "vignette")
        self.assertLess(corner_drop(ablated), corner_drop(base))
        self.assertGreater(corner_drop(ablated), -0.02)

    def test_build_report_records_ablation_and_source_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "flat.png"
            Image.fromarray(np.full((48, 64, 3), 120, dtype=np.uint8)).save(path)
            cases = [{"id": "case-1", "path": str(path), "preset": "night-flash", "strength": 50}]

            plain = ccd_profile.build_report(cases, 7, "synthetic", "fixture")
            ablated = ccd_profile.build_report(cases, 7, "synthetic", "fixture", ablation_stage="grain")

        self.assertIsNone(plain["ablation"])
        self.assertEqual(ablated["ablation"]["stage"], "grain")
        self.assertEqual(ablated["ablation"]["per_image"]["case-1"]["status"], "ablated")
        self.assertIn("消融", ablated["ablation"]["note"])


if __name__ == "__main__":
    unittest.main()
