from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "skills" / "ccd-photo-enhancer"
sys.path.insert(0, str(BUNDLE / "scripts"))
import apply_ccd  # noqa: E402


def _neutral_preset(**overrides) -> apply_ccd.Preset:
    values = dict(
        name="test-neutral",
        environment="daylight",
        flash_axis="none",
        degradation="clean",
        exposure_ev=0.0,
        contrast_delta=0.0,
        saturation_delta=0.0,
        shadow_gain=(1.0, 1.0, 1.0),
        highlight_gain=(1.0, 1.0, 1.0),
        shadow_lift=0.0,
        highlight_compression=0.0,
        highlight_boost=0.0,
        grain_sigma=0.0,
        vignette_amount=0.0,
        sharpness_amount=0.0,
        halation=0.0,
        black_point=0.0,
        flash_falloff=0.0,
    )
    values.update(overrides)
    return apply_ccd.Preset(**values)


class ApplyCcdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        configured = os.environ.get("CCD_TEST_TMP")
        candidates: list[tuple[Path, str, bool]] = []
        if configured:
            candidates.append((Path(configured).expanduser().resolve(), "CCD_TEST_TMP", False))
        candidates.append((ROOT / "tests" / ".test-work", "bundle-local", True))
        for env_name in ("LOCALAPPDATA", "TEMP", "TMP"):
            value = os.environ.get(env_name)
            if value:
                candidates.append((Path(value).expanduser().resolve() / "ccd-photo-enhancer-tests", env_name, False))

        errors: list[str] = []
        for base, source, remove_base in candidates:
            probe = base / f".probe-{os.getpid()}-{uuid.uuid4().hex}"
            base_existed = base.exists()
            try:
                os.makedirs(base, exist_ok=True)
                os.makedirs(probe)
                os.rmdir(probe)
                cls.test_base = base
                cls.test_base_source = source
                cls.remove_test_base = remove_base or (not base_existed and source != "CCD_TEST_TMP")
                print(f"[ccd-tests] scratch directory: {base} ({source})", file=sys.stderr)
                return
            except OSError as exc:
                errors.append(f"{base}: {exc}")
                try:
                    if probe.exists():
                        shutil.rmtree(probe)
                except OSError:
                    pass
        raise RuntimeError("No writable CCD test directory; tried: " + "; ".join(errors))

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "remove_test_base", False):
            try:
                os.rmdir(cls.test_base)
            except OSError:
                pass
        super().tearDownClass()

    def setUp(self) -> None:
        self.root = self.test_base / f"run-{os.getpid()}-{uuid.uuid4().hex}"
        os.makedirs(self.root)
        self.addCleanup(shutil.rmtree, self.root)

    def args(self, input_path: Path, *extra: str):
        return apply_ccd._parse_args([str(input_path), *extra])

    def test_orientation_is_normalized_and_exif_is_not_copied(self) -> None:
        path = self.root / "oriented.jpg"
        image = Image.new("RGB", (3, 2), (120, 80, 40))
        exif = Image.Exif()
        exif[274] = 6  # rotate 90 degrees clockwise for display
        exif[36867] = "2020:01:02 03:04:05"
        image.save(path, quality=95, exif=exif)

        report = apply_ccd.run(self.args(path, "--preset", "daylight-clean", "--seed", "4"))
        self.assertEqual(report["size"], {"width": 2, "height": 3})
        self.assertEqual(report["aspect_ratio"], "2:3")
        self.assertFalse(report["exif_metadata_copied"])
        self.assertNotEqual(Path(report["output_path"]).resolve(), path.resolve())
        with Image.open(report["output_path"]) as result:
            self.assertEqual(result.size, (2, 3))
            self.assertEqual(len(result.getexif()), 0)

    def test_orientation_3_5_8_keep_displayed_dimensions(self) -> None:
        expected_sizes = {3: (4, 3), 5: (3, 4), 8: (3, 4)}
        for orientation, expected_size in expected_sizes.items():
            path = self.root / f"orientation-{orientation}.jpg"
            exif = Image.Exif()
            exif[274] = orientation
            Image.new("RGB", (4, 3), (80, 100, 120)).save(path, exif=exif)
            report = apply_ccd.run(self.args(path, "--preset", "daylight-clean"))
            self.assertEqual((report["size"]["width"], report["size"]["height"]), expected_size)
            with Image.open(report["output_path"]) as result:
                self.assertEqual(result.size, expected_size)

    def test_alpha_is_preserved_and_default_output_is_png(self) -> None:
        path = self.root / "transparent.png"
        pixels = np.zeros((5, 7, 4), dtype=np.uint8)
        pixels[..., :3] = (40, 130, 210)
        pixels[..., 3] = np.arange(7, dtype=np.uint8)[None, :] * 30
        Image.fromarray(pixels).save(path)

        report = apply_ccd.run(self.args(path, "--preset", "daylight-aged", "--seed", "2"))
        self.assertTrue(report["alpha_preserved"])
        self.assertEqual(Path(report["output_path"]).suffix.lower(), ".png")
        with Image.open(report["output_path"]) as result:
            out = np.asarray(result.convert("RGBA"))
        np.testing.assert_array_equal(out[..., 3], pixels[..., 3])

    def test_palette_transparency_and_alpha_to_jpeg_rejection(self) -> None:
        path = self.root / "palette.png"
        palette = Image.new("P", (4, 3))
        colors = [255, 0, 0, 0, 255, 0] + [0] * (768 - 6)
        palette.putpalette(colors)
        palette.putdata([0, 1, 0, 1] * 3)
        palette.info["transparency"] = 1
        palette.save(path)
        report = apply_ccd.run(self.args(path, "--preset", "daylight-clean"))
        with Image.open(report["output_path"]) as result:
            self.assertEqual(result.mode, "RGBA")
            self.assertEqual(result.getchannel("A").getextrema(), (0, 255))
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "透明通道"):
            apply_ccd.run(self.args(path, "--out", str(self.root / "flatten.jpg")))

    def test_explicit_output_directory_and_quality_validation(self) -> None:
        source = self.root / "source.png"
        Image.new("RGB", (4, 3), (30, 80, 120)).save(source)
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "输出目录不存在"):
            apply_ccd.run(self.args(source, "--out", str(self.root / "missing" / "out.jpg")))
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "quality"):
            apply_ccd.run(self.args(source, "--quality", "69"))
        report = apply_ccd.run(self.args(source, "--out", str(self.root / "quality.jpg"), "--quality", "88"))
        self.assertEqual(report["quality"], 88)
        webp = apply_ccd.run(self.args(source, "--out", str(self.root / "webp.webp"), "--quality", "90"))
        self.assertEqual(webp["format"], "webp")
        self.assertEqual(webp["quality"], 90)
        with Image.open(webp["output_path"]) as result:
            self.assertEqual(result.size, (4, 3))

    def test_same_parameters_and_seed_are_pixel_deterministic(self) -> None:
        path = self.root / "source.png"
        y, x = np.mgrid[0:20, 0:30]
        pixels = np.stack((x * 5, y * 7, (x + y) * 3), axis=-1).clip(0, 255).astype(np.uint8)
        Image.fromarray(pixels).save(path)
        first = apply_ccd.run(self.args(path, "--preset", "night-flash", "--strength", "75", "--seed", "31"))
        second = apply_ccd.run(self.args(path, "--preset", "night-flash", "--strength", "75", "--seed", "31"))
        with Image.open(first["output_path"]) as a, Image.open(second["output_path"]) as b:
            np.testing.assert_array_equal(np.asarray(a), np.asarray(b))
        self.assertNotEqual(first["output_path"], second["output_path"])

    def test_seed_change_changes_grain(self) -> None:
        path = self.root / "seed-source.png"
        Image.new("RGB", (64, 48), (130, 100, 80)).save(path)
        first = apply_ccd.run(self.args(path, "--preset", "night-flash", "--strength", "70", "--seed", "1"))
        second = apply_ccd.run(self.args(path, "--preset", "night-flash", "--strength", "70", "--seed", "2"))
        with Image.open(first["output_path"]) as a, Image.open(second["output_path"]) as b:
            self.assertFalse(np.array_equal(np.asarray(a), np.asarray(b)))

    def test_existing_output_is_never_overwritten(self) -> None:
        source = self.root / "source.png"
        Image.new("RGB", (4, 3), (50, 60, 70)).save(source)
        requested = self.root / "chosen.png"
        sentinel = b"do-not-overwrite"
        requested.write_bytes(sentinel)
        report = apply_ccd.run(self.args(source, "--out", str(requested), "--seed", "0"))
        self.assertEqual(requested.read_bytes(), sentinel)
        self.assertEqual(Path(report["output_path"]).name, "chosen-2.png")
        self.assertTrue(Path(report["output_path"]).exists())

    def test_input_as_output_is_rejected(self) -> None:
        source = self.root / "source.png"
        Image.new("RGB", (4, 3), (80, 90, 100)).save(source)
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "与输入文件相同"):
            apply_ccd.run(self.args(source, "--out", str(source)))
        self.assertTrue(source.exists())

    def test_invalid_input_and_heic_are_actionable(self) -> None:
        fake_heic = self.root / "photo.heic"
        fake_heic.write_bytes(b"not an image")
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "没有 HEIC/HEIF"):
            apply_ccd.run(self.args(fake_heic))

        broken = self.root / "broken.jpg"
        broken.write_bytes(b"broken")
        with self.assertRaises(apply_ccd.ProcessingError):
            apply_ccd.run(self.args(broken))

    def test_16bit_grayscale_is_explicitly_quantized(self) -> None:
        path = self.root / "gray16.png"
        values = np.linspace(0, 65535, 12, dtype=np.uint16).reshape((3, 4))
        Image.fromarray(values).save(path)
        report = apply_ccd.run(self.args(path, "--preset", "daylight-clean"))
        self.assertTrue(any("16-bit" in warning for warning in report["warnings"]))
        with Image.open(report["output_path"]) as result:
            self.assertEqual(result.size, (4, 3))
            self.assertEqual(result.mode, "RGB")

    def test_bad_icc_is_rejected_instead_of_guessed(self) -> None:
        path = self.root / "bad-profile.png"
        Image.new("RGB", (3, 2), (50, 100, 150)).save(path, icc_profile=b"not-a-valid-icc-profile")
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "ICC"):
            apply_ccd.run(self.args(path))

    def test_high_entropy_jpeg_encoding_succeeds(self) -> None:
        rng = np.random.default_rng(987654321)
        for width, height in ((600, 400), (1200, 800)):
            source = self.root / f"noise-{width}x{height}.jpg"
            output = self.root / f"noise-out-{width}x{height}.jpg"
            pixels = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
            Image.fromarray(pixels).save(source, quality=95)
            report = apply_ccd.run(self.args(source, "--out", str(output), "--quality", "94"))
            self.assertEqual(report["status"], "processed")
            self.assertEqual(report["quality"], 94)
            self.assertFalse(report["jpeg_optimize"])
            with Image.open(output) as result:
                result.load()
                self.assertEqual(result.size, (width, height))

    def test_cmyk_without_profile_reports_conversion_warning(self) -> None:
        path = self.root / "cmyk.jpg"
        Image.new("CMYK", (5, 4), (15, 30, 80, 5)).save(path, quality=90)
        report = apply_ccd.run(self.args(path))
        self.assertTrue(any("CMYK" in warning for warning in report["warnings"]))
        self.assertEqual(report["size"], {"width": 5, "height": 4})

    def test_animated_webp_and_float_tiff_are_rejected(self) -> None:
        animated = self.root / "motion.webp"
        frames = [Image.new("RGB", (4, 3), color) for color in ((20, 40, 60), (80, 100, 120))]
        frames[0].save(animated, format="WEBP", save_all=True, append_images=frames[1:], duration=100, loop=0)
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "多帧/动画"):
            apply_ccd.run(self.args(animated))

        floating = self.root / "floating.tiff"
        Image.fromarray(np.zeros((3, 4), dtype=np.float32)).save(floating)
        with self.assertRaises(apply_ccd.ProcessingError):
            apply_ccd.run(self.args(floating))

    def test_pixel_limit_is_enforced(self) -> None:
        path = self.root / "small.png"
        self.assertEqual(self.args(path).max_pixels, 60_000_000)
        Image.new("RGB", (4, 3), (10, 20, 30)).save(path)
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "超出本次限制.*提高到最多"):
            apply_ccd.run(self.args(path, "--max-pixels", "10"))
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "只能向下调"):
            apply_ccd.run(self.args(path, "--max-pixels", "60000001"))

    def test_presets_modify_pixels_and_are_distinguishable(self) -> None:
        path = self.root / "color-ramp.png"
        y, x = np.mgrid[0:48, 0:64]
        pixels = np.stack((x * 4, y * 5, (x * 2 + y * 2)), axis=-1).clip(0, 255).astype(np.uint8)
        Image.fromarray(pixels).save(path)
        daylight = apply_ccd.run(self.args(path, "--preset", "daylight-clean", "--strength", "70"))
        night = apply_ccd.run(self.args(path, "--preset", "night-flash", "--strength", "70"))
        with Image.open(daylight["output_path"]) as a, Image.open(night["output_path"]) as b:
            daylight_pixels = np.asarray(a.convert("RGB"), dtype=np.int16)
            night_pixels = np.asarray(b.convert("RGB"), dtype=np.int16)
        self.assertGreater(float(np.mean(np.abs(daylight_pixels - pixels.astype(np.int16)))), 0.5)
        self.assertGreater(float(np.mean(np.abs(daylight_pixels - night_pixels))), 1.0)

    def test_script_semver_matches_bundle_version(self) -> None:
        self.assertEqual(apply_ccd.SCRIPT_VERSION, (BUNDLE / "VERSION").read_text(encoding="ascii").strip())

    def test_preview_reports_metrics_without_writing_and_rejects_out(self) -> None:
        source = self.root / "preview.png"
        Image.new("RGB", (32, 24), (180, 120, 80)).save(source)
        before = set(self.root.iterdir())
        report = apply_ccd.run(self.args(source, "--preset", "daylight-aged", "--preview"))
        self.assertEqual(report["status"], "preview")
        self.assertTrue(report["preview_only"])
        self.assertFalse(report["image_written"])
        self.assertIsNone(report["output_path"])
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertIn("before file encoding", report["metrics_source"])
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "移除 --out"):
            apply_ccd.run(self.args(source, "--preview", "--out", str(self.root / "unused.png")))

    def test_strength_zero_is_pixel_neutral_for_png(self) -> None:
        source = self.root / "neutral.png"
        pixels = np.arange(24 * 20 * 3, dtype=np.uint8).reshape((20, 24, 3))
        Image.fromarray(pixels).save(source)
        report = apply_ccd.run(self.args(source, "--preset", "daylight-aged", "--strength", "0"))
        with Image.open(report["output_path"]) as result:
            np.testing.assert_array_equal(np.asarray(result.convert("RGB")), pixels)
        self.assertEqual(report["format"], "png")
        self.assertIsNone(report["quality"])

    def test_halation_is_warm_and_localized(self) -> None:
        source = np.zeros((96, 96, 3), dtype=np.uint8)
        source[32:48, 32:48] = 255
        result = apply_ccd._apply_pixel_recipe(
            source, _neutral_preset(halation=0.20), 100, 0, None, None, None
        )
        near_highlight = result[40, 28].astype(np.int16) - source[40, 28].astype(np.int16)
        self.assertGreater(int(near_highlight[0]), 0)
        self.assertGreaterEqual(int(near_highlight[0]), int(near_highlight[1]))
        self.assertGreater(int(near_highlight[1]), int(near_highlight[2]))
        np.testing.assert_array_equal(result[0, 0], source[0, 0])

    def test_halation_is_continuous_across_tile_boundaries(self) -> None:
        # The glow map is built once for the whole frame. A mid-tone band straddling the 256-row
        # tile boundary must not jump where tile 0 ends and tile 1 begins. The glow is isolated by
        # subtracting a render with halation disabled so the band edges cannot mask a real seam.
        height, width = 600, 32
        source = np.zeros((height, width, 3), dtype=np.uint8)
        source[236:276, :] = 215
        with_glow = apply_ccd._apply_pixel_recipe(
            source, _neutral_preset(halation=0.30), 100, 0, None, None, None
        ).astype(np.int16)
        without_glow = apply_ccd._apply_pixel_recipe(
            source, _neutral_preset(halation=0.0), 100, 0, None, None, None
        ).astype(np.int16)
        glow = (with_glow - without_glow)[:, 16, 0]
        boundary = apply_ccd.TILE_ROWS - 1  # step from the last row of tile 0 into tile 1
        self.assertGreater(int(glow[boundary]), 0, msg="glow must reach the tile boundary")
        self.assertLessEqual(
            abs(int(glow[boundary + 1]) - int(glow[boundary])),
            1,
            msg=f"tile seam at row {boundary}: {int(glow[boundary])} -> {int(glow[boundary + 1])}",
        )
        window = np.abs(np.diff(glow))[boundary - 10: boundary + 11]
        self.assertLessEqual(int(window.max()), 2, msg=f"glow not smooth near boundary: {int(window.max())}")

    def test_black_point_toe_deepens_midtones_without_crushing_whites(self) -> None:
        source = np.repeat(np.arange(256, dtype=np.uint8).reshape(16, 16, 1), 3, axis=2)
        result = apply_ccd._apply_pixel_recipe(
            source, _neutral_preset(black_point=0.10), 100, 0, None, None, None
        )
        self.assertEqual(int(result[0, 0, 0]), 0)
        self.assertLess(int(result[4, 0, 0]), int(source[4, 0, 0]))
        self.assertEqual(int(result[-1, -1, 0]), 255)
        self.assertTrue(np.all(np.diff(result[..., 0].reshape(-1).astype(np.int16)) >= 0))

    def test_flash_falloff_brightens_without_new_channel_clipping(self) -> None:
        source = np.zeros((32, 32, 3), dtype=np.uint8)
        source[:] = (240, 40, 40)
        result = apply_ccd._apply_pixel_recipe(
            source, _neutral_preset(flash_falloff=0.16), 100, 0, None, None, None
        )
        centre = result[16, 16]
        self.assertGreater(int(centre[0]), 240)
        self.assertLess(int(centre[0]), 255)
        self.assertGreater(int(centre[1]), 40)
        self.assertLess(int(result[0, 0, 0]), int(centre[0]))

    def test_vignette_at_full_strength_is_measurable(self) -> None:
        source = self.root / "flat.png"
        Image.new("RGB", (256, 256), (128, 128, 128)).save(source)
        report = apply_ccd.run(self.args(
            source, "--preset", "daylight-aged", "--strength", "100",
            "--grain-strength", "0", "--color-strength", "0", "--sharpness-strength", "0",
        ))
        with Image.open(report["output_path"]) as image:
            arr = np.asarray(image, dtype=np.float32)
        center = float(arr[120:136, 120:136].mean())
        corners = float(np.concatenate((arr[:8, :8].reshape(-1, 3), arr[-8:, -8:].reshape(-1, 3))).mean())
        vignette_drop = 1.0 - corners / center
        self.assertGreaterEqual(vignette_drop, 0.08)
        self.assertLessEqual(vignette_drop, 0.30)

    def test_vignette_remains_visible_on_dark_flash_backgrounds(self) -> None:
        source = self.root / "dark-background.png"
        Image.new("RGB", (128, 128), (18, 18, 18)).save(source)
        for preset in ("indoor-flash", "night-flash"):
            for strength in (50, 100):
                report = apply_ccd.run(self.args(
                    source, "--preset", preset, "--strength", str(strength),
                    "--grain-strength", "0", "--color-strength", "0", "--sharpness-strength", "0",
                ))
                with Image.open(report["output_path"]) as image:
                    arr = np.asarray(image, dtype=np.float32)
                center = float(arr[60:68, 60:68].mean())
                corners = float(np.concatenate((arr[:8, :8].reshape(-1, 3), arr[-8:, -8:].reshape(-1, 3))).mean())
                drop = 1.0 - corners / center
                self.assertGreaterEqual(drop, 0.05, msg=f"{preset}/{strength}: {drop:.3%}")
                self.assertLessEqual(drop, 0.45, msg=f"{preset}/{strength}: {drop:.3%}")

    def test_direct_flash_highlights_use_bounded_soft_shoulder(self) -> None:
        source = self.root / "highlight-ramp.png"
        # 205 is a bright but not near-white tone; direct flash may still blow a white shirt,
        # but it must not turn an ordinary bright midtone into a flat white block.
        pixels = np.full((100, 100, 3), 205, dtype=np.uint8)
        pixels[:10, :10] = 253  # a small genuine specular patch
        Image.fromarray(pixels).save(source)
        for strength in (50, 100):
            report = apply_ccd.run(self.args(
                source, "--preset", "indoor-flash", "--strength", str(strength),
                "--grain-strength", "0", "--color-strength", "0", "--vignette-strength", "0", "--sharpness-strength", "0",
            ))
            clipping = report["clipping"]
            self.assertGreater(clipping["after"]["near_white_ratio"], clipping["before"]["near_white_ratio"])
            self.assertLessEqual(clipping["after"]["near_white_ratio"], 0.05)
            self.assertLessEqual(clipping["after"]["clipped_channel_ratio"], 0.05)
            with Image.open(report["output_path"]) as image:
                out = np.asarray(image.convert("RGB"))
            self.assertLess(float(out[50, 50].mean()), 254.0, msg="mid-bright gray must not all clip to white")

    def test_flash_highlight_shoulder_is_monotonic_without_a_flat_shelf(self) -> None:
        source = self.root / "highlight-gradient.png"
        levels = np.arange(150, 256, dtype=np.uint8)
        pixels = np.broadcast_to(levels[None, :, None], (32, len(levels), 3)).copy()
        Image.fromarray(pixels).save(source)
        for strength, max_shelf in (("50", 6), ("100", 10)):
            report = apply_ccd.run(self.args(
                source, "--preset", "indoor-flash", "--strength", strength,
                "--grain-strength", "0", "--color-strength", "0", "--vignette-strength", "0", "--sharpness-strength", "0",
            ))
            with Image.open(report["output_path"]) as image:
                row = np.asarray(image.convert("RGB"), dtype=np.uint8)[16, :, 0]
            self.assertTrue(np.all(np.diff(row.astype(np.int16)) >= 0), msg=f"s{strength} not monotonic")
            self.assertGreaterEqual(len(np.unique(row)), 60, msg=f"s{strength} lost too many output codes")
            longest = run = 1
            for index in range(1, len(row)):
                run = run + 1 if row[index] == row[index - 1] else 1
                longest = max(longest, run)
            self.assertLessEqual(longest, max_shelf, msg=f"s{strength} flat shelf of {longest} levels")
            self.assertLessEqual(int(row.max()), 255)

    def test_indoor_flash_does_not_overwarm_a_mid_skin_patch(self) -> None:
        source = self.root / "skin-patch.png"
        source_pixel = np.asarray([[[205, 160, 140]]], dtype=np.uint8)
        Image.fromarray(np.broadcast_to(source_pixel, (16, 16, 3)).copy()).save(source)
        report = apply_ccd.run(self.args(
            source, "--preset", "indoor-flash", "--strength", "50",
            "--grain-strength", "0", "--vignette-strength", "0", "--sharpness-strength", "0",
        ))
        with Image.open(report["output_path"]) as image:
            result = np.asarray(image.convert("RGB"), dtype=np.int16)
        delta = result[8, 8] - source_pixel[0, 0].astype(np.int16)
        self.assertLessEqual(int(delta[0]), 18, msg=f"red shift too large: {delta.tolist()}")
        self.assertLessEqual(int(delta[0] - delta[1]), 10, msg=f"warm-channel skew too large: {delta.tolist()}")

    def test_preset_pairwise_separation_without_grain(self) -> None:
        source = self.root / "calibration-ramp.png"
        y, x = np.mgrid[0:128, 0:128]
        pixels = np.empty((128, 128, 3), dtype=np.uint8)
        mid = np.stack((30 + x, 20 + y, 40 + (x + y) // 2), axis=-1).clip(0, 255).astype(np.uint8)
        pixels[:] = mid
        # Include dark, midtone, and near-white zones so flash/highlight distinctions are exercised.
        pixels[:, :24] = (18, 24, 32)
        highlight = np.linspace(180, 253, 40, dtype=np.uint8)[None, :, None]
        pixels[:, 88:] = np.repeat(np.repeat(highlight, 128, axis=0), 3, axis=2)
        Image.fromarray(pixels).save(source)
        # At the default strength 50 the presets remain restrained (about 2.2–2.3/255 on the
        # current fixtures); the documented distinct-character claim is asserted at strength 80.
        minimum_pair = self._closest_pair(source, "80")
        self.assertGreaterEqual(minimum_pair[2], 3.4, msg=f"Closest presets: {minimum_pair}")

    def _closest_pair(self, source: Path, strength: str) -> tuple[str, str, float]:
        outputs = {}
        for preset in apply_ccd.PRESETS:
            report = apply_ccd.run(self.args(
                source, "--preset", preset, "--strength", strength, "--seed", "13", "--grain-strength", "0"
            ))
            with Image.open(report["output_path"]) as image:
                outputs[preset] = np.asarray(image.convert("RGB"), dtype=np.int16)
        names = list(outputs)
        distances = []
        for i, left in enumerate(names):
            for right in names[i + 1:]:
                distance = float(np.mean(np.abs(outputs[left] - outputs[right])))
                distances.append((left, right, distance))
        closest = min(distances, key=lambda item: item[2])
        self.assertGreaterEqual(closest[2], 0.0, msg=str(distances))
        return closest

    def test_preset_separation_on_a_photo_like_scene(self) -> None:
        # A second fixture with a smooth sky, ground, subject blob and specular highlight, so the
        # separation claim is not only true for the hard-edged calibration chart.
        height, width = 96, 144
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        sky = np.stack(
            (0.42 + 0.25 * (yy / height), 0.55 + 0.22 * (yy / height), 0.72 + 0.15 * (yy / height)),
            axis=-1,
        )
        ground = (yy > height * 0.62)[..., None]
        image = sky * (1 - ground) + np.asarray([0.28, 0.24, 0.20], dtype=np.float32) * ground
        cy, cx = height * 0.55, width * 0.5
        radius = np.sqrt((yy - cy) ** 2 + ((xx - cx) * 1.1) ** 2)
        subject = (radius < height * 0.22)[..., None]
        image = image * (1 - subject) + np.asarray([0.62, 0.45, 0.36], dtype=np.float32) * subject
        specular = np.exp(
            -(((yy - height * 0.25) ** 2 + (xx - width * 0.72) ** 2) / (2 * (height * 0.05) ** 2))
        )[..., None]
        image = image + specular * 0.55
        image = image + np.random.default_rng(5).normal(0, 0.01, (height, width, 3))
        source = self.root / "photo-like.png"
        Image.fromarray((np.clip(image, 0, 1) * 255).astype(np.uint8)).save(source)
        minimum_pair = self._closest_pair(source, "80")
        self.assertGreaterEqual(minimum_pair[2], 3.4, msg=f"Closest presets: {minimum_pair}")

    def test_json_report_has_layer_and_clipping_metrics(self) -> None:
        source = self.root / "input.png"
        Image.new("RGB", (8, 6), (200, 120, 60)).save(source)
        report = apply_ccd.run(self.args(source, "--preset", "indoor-flash", "--strength", "40"))
        self.assertEqual(report["status"], "processed")
        self.assertEqual(report["capability_layer"], "L2-local-deterministic-pixel-processing")
        self.assertEqual(report["axes"]["flash_tonal_impression"], "direct-tonal")
        self.assertIn("before", report["clipping"])
        self.assertIn("after", report["clipping"])
        json.dumps(report)

    def test_cli_success_reports_output_and_failure_does_not_claim_processing(self) -> None:
        source = self.root / "cli.png"
        Image.new("RGB", (6, 4), (110, 80, 170)).save(source)
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = apply_ccd.main([str(source), "--preset", "daylight-clean", "--seed", "9"])
        self.assertEqual(code, 0)
        success = json.loads(stdout.getvalue())
        self.assertEqual(success["status"], "processed")
        self.assertTrue(Path(success["output_path"]).exists())

        stderr = StringIO()
        with redirect_stderr(stderr):
            code = apply_ccd.main([str(self.root / "missing.png")])
        self.assertNotEqual(code, 0)
        failure = json.loads(stderr.getvalue())
        self.assertEqual(failure["status"], "not_processed")
        self.assertIn("error", failure)
    def test_single_file_default_contract_is_unchanged(self) -> None:
        args = self.args(self.root / "photo.jpg")
        self.assertFalse(args.batch)
        self.assertEqual(args.strength, 50)
        self.assertEqual(args.preset, "daylight-aged")
        self.assertIsNone(args.out)

    def test_batch_processes_directory_without_overwriting_sources_or_outputs(self) -> None:
        sources = self.root / "sources"
        outputs = self.root / "outputs"
        sources.mkdir()
        outputs.mkdir()
        first = sources / "b.jpg"
        second = sources / "a.png"
        Image.new("RGB", (12, 8), (90, 110, 130)).save(first)
        Image.new("RGB", (10, 14), (150, 100, 70)).save(second)
        (sources / "notes.txt").write_text("not a photo", encoding="utf-8")
        original_bytes = {path: path.read_bytes() for path in (first, second)}

        argv = [str(sources), "--batch", "--out", str(outputs), "--preset", "daylight-aged", "--strength", "75", "--seed", "7"]
        report = apply_ccd.run(apply_ccd._parse_args(argv))
        self.assertEqual(report["status"], "processed")
        self.assertEqual(report["processed_files"], 2)
        self.assertEqual(report["failed_files"], 0)
        self.assertEqual(report["ignored_non_photo_files"], 1)
        self.assertFalse(report["recursive"])
        self.assertEqual(report["seed_policy"], "same-explicit-seed-for-each-source-image")
        self.assertEqual(len(report["output_paths"]), 2)
        self.assertTrue(all(Path(path).parent == outputs for path in report["output_paths"]))
        for path, content in original_bytes.items():
            self.assertEqual(path.read_bytes(), content)

        repeated = apply_ccd.run(apply_ccd._parse_args(argv))
        self.assertEqual(repeated["status"], "processed")
        self.assertTrue(set(report["output_paths"]).isdisjoint(repeated["output_paths"]))
        self.assertEqual(len(list(outputs.iterdir())), 4)

    def test_batch_rejects_unsafe_output_and_preview_combinations(self) -> None:
        sources = self.root / "batch-validation"
        outputs = self.root / "batch-output"
        sources.mkdir()
        outputs.mkdir()
        photo = sources / "photo.png"
        Image.new("RGB", (4, 3), (40, 60, 80)).save(photo)

        with self.assertRaisesRegex(apply_ccd.ProcessingError, "必须通过 --out"):
            apply_ccd.run(self.args(sources, "--batch"))
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "不得与输入目录相同"):
            apply_ccd.run(self.args(sources, "--batch", "--out", str(sources)))
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "输出目录不存在"):
            apply_ccd.run(self.args(sources, "--batch", "--out", str(self.root / "missing-output")))
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "暂不支持 --preview"):
            apply_ccd.run(self.args(sources, "--batch", "--out", str(outputs), "--preview"))
        with self.assertRaisesRegex(apply_ccd.ProcessingError, "输入必须是目录"):
            apply_ccd.run(self.args(photo, "--batch", "--out", str(outputs)))

    def test_batch_partial_failure_is_explicit_in_report_and_cli_exit(self) -> None:
        sources = self.root / "partial-sources"
        sources.mkdir()
        Image.new("RGB", (8, 6), (100, 120, 140)).save(sources / "good.png")
        (sources / "phone.heic").write_bytes(b"not a decodable HEIC")
        outputs = self.root / "partial-output"
        outputs.mkdir()

        report = apply_ccd.run(self.args(sources, "--batch", "--out", str(outputs)))
        self.assertEqual(report["status"], "partially_processed")
        self.assertEqual(report["processed_files"], 1)
        self.assertEqual(report["failed_files"], 1)
        failure = next(item for item in report["results"] if item["status"] == "not_processed")
        self.assertIn("HEIC/HEIF", failure["error"])
        self.assertIsNone(failure["output_path"])

        cli_outputs = self.root / "partial-cli-output"
        cli_outputs.mkdir()
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = apply_ccd.main([str(sources), "--batch", "--out", str(cli_outputs)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "partially_processed")
        self.assertEqual(json.loads(stderr.getvalue())["status"], "partially_processed")

    def test_batch_all_failed_uses_stderr_and_nonzero_exit(self) -> None:
        sources = self.root / "failed-sources"
        outputs = self.root / "failed-output"
        sources.mkdir()
        outputs.mkdir()
        (sources / "only.heic").write_bytes(b"not a decodable HEIC")
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = apply_ccd.main([str(sources), "--batch", "--out", str(outputs)])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        failure = json.loads(stderr.getvalue())
        self.assertEqual(failure["status"], "not_processed")
        self.assertEqual(failure["processed_files"], 0)
        self.assertEqual(failure["failed_files"], 1)
        self.assertEqual(list(outputs.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
