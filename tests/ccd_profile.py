"""Measure tone/colour fingerprints of the local pixel pipeline.

This tool is a pipeline self-check, not a CCD baseline. It reports distributions
and per-family intervals; it never collapses them into one composite score,
because a single number would hide exactly the per-family differences that the
strategy work identified (corner/centre balance, highlight handling, black level).

Usage:
    python tests/ccd_profile.py --manifest tests/real-photo-manifest.json --out docs/samples/pipeline-self-check.json
    python tests/ccd_profile.py --sources some/folder --preset night-flash --strength 75
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SCRIPTS = REPO_ROOT / "skills" / "ccd-photo-enhancer" / "scripts"
if str(BUNDLE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(BUNDLE_SCRIPTS))

import apply_ccd  # noqa: E402
import verify_reference_set  # noqa: E402  (path set above on purpose)
import ccd_ablate  # noqa: E402  (same directory)

TITLE = "管线自检，非 CCD 基线"
NOTE = (
    "这些数字描述本仓库像素管线在同一批图库照片上的行为；样本不是已验证的 CCD 直出原图，"
    "没有与真实机型对照，也没有盲测。任何结论都不能当作“CCD 基线”。"
)

GRAIN_REFERENCE_LONG_EDGE = 1600
REFERENCE_NOTE_TIER_A = (
    "这些数字量的是清单声明为 Tier A 的 CCD 直出原图本身，不经过本仓库的像素管线。"
    "校验只证明清单字段与文件 EXIF 一致，不证明传感器类型、未经修图，也不证明存在同场景对照或盲测。"
)
REFERENCE_NOTE_TIER_B = (
    "这些数字量的是清单声明为 Tier B 的对照样张本身，不经过本仓库的像素管线。"
    "Tier B 只作场景对照，不进入标定区间，也不能当作某机型的直出特征。"
)
REFERENCE_NOTE_TIER_C = (
    "这些数字量的是公开网页样张（Tier C）本身，不经过本仓库的像素管线。"
    "Tier C 不进入标定区间，也不构成 CCD 直出认证；只覆盖 daylight 两族，indoor-flash 只有 1 张、"
    "night-flash 为 0，没有手机同期对照，也没有盲测。"
)
REFERENCE_NOTE_UNVERIFIED = (
    "这些数字来自未经校验的图片，只是源图描述性测量，不经过本仓库的像素管线。"
    "不得据此声称任何 CCD 直出特征；要成为参考区间，输入必须先通过清单校验并声明 Tier A。"
)
def reference_note(tier: str | None, verified: bool) -> str:
    """Describe the source that was actually measured.

    A fixed sentence claimed every ``--reference`` run measured real CCD straight-out
    JPEGs, including runs over an arbitrary folder. The note now follows the tier the
    manifest declares, and unverified input gets no CCD claim at all.
    """
    if not verified:
        return REFERENCE_NOTE_UNVERIFIED
    return {
        "A": REFERENCE_NOTE_TIER_A,
        "B": REFERENCE_NOTE_TIER_B,
        "C": REFERENCE_NOTE_TIER_C,
    }.get(tier or "", REFERENCE_NOTE_UNVERIFIED)


def source_note(reference: bool, tier: str | None, verified: bool) -> str:
    if not reference:
        return "源图来自图库（Pexels License），不随仓库分发；只保留文件名与 SHA-256。"
    if not verified:
        return "来源未经清单校验，只能当作描述性测量；版权归原站与摄影师，原图不入库、不转载。"
    if tier == "A":
        return "源图由清单声明为 Tier A 的 CCD 直出原图；版权归采集者，原图不入库、不转载。"
    return "源图由清单声明为 Tier B/C 样张，不构成 CCD 直出认证；版权归原站与摄影师，原图不入库、不转载。"


def working_tree_dirty() -> bool | None:
    """Whether tracked work outside the evidence directory is uncommitted.

    Evidence files under `docs/samples/` are excluded because writing a report is what
    changes them; including them would make every report claim it was produced from a
    dirty tree. None means git was unavailable, which is not the same as clean.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if path and not path.startswith("docs/samples/"):
            return True
    return False


def profiler_commit() -> str | None:
    """Short hash of the commit that produced the numbers, when this is a git checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def reference_title(source_label: str) -> str:
    """Name the report after the source it actually measured.

    A fixed title claimed every ``--reference`` run was the cameralabs daylight pilot,
    including runs over an unrelated folder. The label is now part of the title, so a
    reader can tell which source produced the numbers.
    """
    return f"源图区间测量：{source_label}"


_M_RGB2XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float32,
)
_WHITE = (0.95047, 1.0, 1.08883)

SCALAR_KEYS = (
    "L_p5",
    "L_p25",
    "L_p50",
    "L_p75",
    "L_p95",
    "near_white",
    "clipped_channel",
    "near_black",
    "mean_a",
    "mean_b",
    "highlight_a",
    "highlight_b",
    "shadow_a",
    "shadow_b",
    "centre_L",
    "corner_L",
    "flat_noise",
    "flat_noise_scaled",
)

# Only increases are judged. An absolute near-white ratio condemns the source, not
# the pipeline: a studio frame that arrives 22% blown is not damaged by a step that
# lowers it to 19%. The guardrail asks "did this step make it worse".
GUARDRAIL_LIMITS = {
    "near_white_increase_max": 0.01,
    "clipped_channel_increase_max": 0.005,
    "corner_drop_ratio_max": 0.45,
}

# Full-resolution Lab conversion is the memory peak of this tool. Reference cards
# shoot at 3–8MP; anything above this ceiling is re-exported smaller instead of
# silently swallowing several GB.
MEASURE_MAX_PIXELS = 24_000_000


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Return CIELAB (D65) for an 8-bit sRGB array, assuming sRGB primaries."""
    scaled = rgb.astype(np.float32) / 255.0
    linear = np.where(scaled <= 0.04045, scaled / 12.92, ((scaled + 0.055) / 1.055) ** 2.4)
    xyz = linear.reshape(-1, 3) @ _M_RGB2XYZ.T
    xyz = xyz.reshape(rgb.shape).astype(np.float32)
    xyz[..., 0] /= _WHITE[0]
    xyz[..., 1] /= _WHITE[1]
    xyz[..., 2] /= _WHITE[2]

    def _f(t: np.ndarray) -> np.ndarray:
        return np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16.0 / 116.0)

    fx, fy, fz = _f(xyz[..., 0]), _f(xyz[..., 1]), _f(xyz[..., 2])
    lightness = 116.0 * fy - 16.0
    a_axis = 500.0 * (fx - fy)
    b_axis = 200.0 * (fy - fz)
    return np.stack([lightness, a_axis, b_axis], axis=-1)


def _box_mean(values: np.ndarray, radius: int) -> np.ndarray:
    """Mean over a square window, edge-padded, computed with summed-area tables."""
    window = 2 * radius + 1
    padded = np.pad(values.astype(np.float64), radius, mode="edge")
    cumulative = np.cumsum(np.cumsum(padded, axis=0), axis=1)
    cumulative = np.pad(cumulative, ((1, 0), (1, 0)))
    total = (
        cumulative[window:, window:]
        - cumulative[:-window, window:]
        - cumulative[window:, :-window]
        + cumulative[:-window, :-window]
    )
    return total / (window * window)


def _corner_and_centre(lightness: np.ndarray) -> tuple[float, float]:
    height, width = lightness.shape
    rows = max(1, int(round(height * 0.2)))
    cols = max(1, int(round(width * 0.2)))
    corner_means = [
        float(lightness[:rows, :cols].mean()),
        float(lightness[:rows, -cols:].mean()),
        float(lightness[-rows:, :cols].mean()),
        float(lightness[-rows:, -cols:].mean()),
    ]
    centre = float(lightness[int(height * 0.3) : int(height * 0.7), int(width * 0.3) : int(width * 0.7)].mean())
    return sum(corner_means) / 4.0, centre


def _flat_mask(lightness: np.ndarray) -> np.ndarray | None:
    """Select the smoothest quartile as a grain probe, or None if nothing qualifies.

    The mask is derived from the *source* and reused for both phases. Deriving it
    per phase silently compares different regions, which is how a grain metric can
    report a change that no viewer would see.
    """
    local = _box_mean(lightness, 2)
    variance = np.maximum(_box_mean(lightness * lightness, 2) - local * local, 0.0)
    limit = min(float(np.percentile(variance, 25)), 4.0)
    mask = variance <= limit
    if int(mask.sum()) < max(64, lightness.size // 100):
        return None
    return mask


def _flat_noise(lightness: np.ndarray, mask: np.ndarray) -> float | None:
    local = _box_mean(lightness, 2)
    residual = lightness - local
    values = residual[mask]
    if values.size < 64:
        return None
    median = float(np.median(values))
    return float(1.4826 * np.median(np.abs(values - median)))


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)


def _scaled_probe(
    rgb: np.ndarray, long_edge: int = GRAIN_REFERENCE_LONG_EDGE
) -> tuple[tuple[int, int], np.ndarray] | None:
    """Fix the display size and the smooth-region mask for a scaled grain reading.

    Native-pixel MAD is not comparable between a 2 MP compact and a 24 MP phone: the
    same physical grain spans a different number of pixels. Resampling to one display
    size makes the number mean "what a viewer sees at the same size". Images already
    smaller than the reference edge return None, because upsampling would invent detail.

    Only the size and the mask come from the source. Each phase resamples its own pixels
    through `_scaled_noise`, so the after reading measures the after image: returning the
    source lightness here once made before and after identical by construction.
    """
    height, width = rgb.shape[:2]
    if max(width, height) <= long_edge:
        return None
    scale = long_edge / float(max(width, height))
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    mask = _flat_mask(srgb_to_lab(_resize_for_scale(rgb, size))[..., 0])
    return None if mask is None else (size, mask)


def _resize_for_scale(rgb: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(Image.fromarray(rgb).resize(size, Image.BOX), dtype=np.uint8)


def _scaled_noise(rgb: np.ndarray, probe: tuple[tuple[int, int], np.ndarray]) -> float | None:
    """Grain of *this* raster at the probe's display size, through the probe's mask."""
    size, mask = probe
    lightness = srgb_to_lab(_resize_for_scale(rgb, size))[..., 0]
    return _flat_noise(lightness, mask)


def measure(
    rgb: np.ndarray,
    flat_mask: np.ndarray | None = None,
    lab: np.ndarray | None = None,
    scaled_probe: tuple[tuple[int, int], np.ndarray] | None = None,
) -> dict[str, float | None]:
    """Summarise one sRGB raster without reducing it to a single score."""
    if lab is None:
        lab = srgb_to_lab(rgb)
    lightness = lab[..., 0]
    a_axis = lab[..., 1]
    b_axis = lab[..., 2]

    p5, p25, p50, p75, p95 = np.percentile(lightness, [5, 25, 50, 75, 95])
    highlight = lightness >= 80.0
    shadow = lightness <= 25.0
    corner, centre = _corner_and_centre(lightness)

    def _mean(values: np.ndarray, mask: np.ndarray) -> float | None:
        return float(values[mask].mean()) if int(mask.sum()) else None

    return {
        "L_p5": round(float(p5), 3),
        "L_p25": round(float(p25), 3),
        "L_p50": round(float(p50), 3),
        "L_p75": round(float(p75), 3),
        "L_p95": round(float(p95), 3),
        "near_white": round(float((lightness >= 97.0).mean()), 5),
        "clipped_channel": round(float((rgb >= 255).mean()), 5),
        "near_black": round(float((lightness <= 2.0).mean()), 5),
        "mean_a": round(float(a_axis.mean()), 3),
        "mean_b": round(float(b_axis.mean()), 3),
        "highlight_a": _round(_mean(a_axis, highlight)),
        "highlight_b": _round(_mean(b_axis, highlight)),
        "shadow_a": _round(_mean(a_axis, shadow)),
        "shadow_b": _round(_mean(b_axis, shadow)),
        "centre_L": round(centre, 3),
        "corner_L": round(corner, 3),
        "flat_noise": _round(_flat_noise(lightness, flat_mask)) if flat_mask is not None else None,
        "flat_noise_scaled": _round(_scaled_noise(rgb, scaled_probe)) if scaled_probe is not None else None,
    }


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key in SCALAR_KEYS:
        prior, current = before.get(key), after.get(key)
        out[key] = None if prior is None or current is None else round(float(current) - float(prior), 4)
    if before["corner_L"]:
        out["corner_drop_ratio"] = round(
            float((before["corner_L"] - after["corner_L"]) / before["corner_L"]), 5
        )
    else:
        out["corner_drop_ratio"] = None
    if before["centre_L"]:
        out["centre_delta_ratio"] = round(
            float((after["centre_L"] - before["centre_L"]) / before["centre_L"]), 5
        )
    else:
        out["centre_delta_ratio"] = None
    return out


def profile_image(
    path: Path,
    preset_name: str,
    strength: int,
    seed: int,
    max_pixels: int = MEASURE_MAX_PIXELS,
    preset: apply_ccd.Preset | None = None,
    family: str | None = None,
    reference: bool = False,
    role: str = "calibration",
) -> dict[str, Any]:
    """Measure one image before and after the production recipe, in memory.

    With ``reference`` the recipe is skipped: the source pixels are measured once and
    reported as both ``before`` and ``after``, so per-family intervals describe the
    camera's own output instead of this repository's pipeline.
    """
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    warnings: list[str] = []
    with Image.open(path) as raw:
        icc_profile = raw.info.get("icc_profile")
        rgb_image, _alpha = apply_ccd._display_rgb(ImageOps.exif_transpose(raw), icc_profile, warnings)
    rgb_image = rgb_image.convert("RGB")
    width, height = rgb_image.size
    if width * height > max_pixels:
        raise SystemExit(
            f"{path.name}: {width}x{height} 超过 --max-pixels {max_pixels}；"
            "指纹测量不需要这么大，请导出较小副本后再测。"
        )

    before = np.asarray(rgb_image, dtype=np.uint8).copy()
    lab_before = srgb_to_lab(before)
    mask = _flat_mask(lab_before[..., 0])
    probe = None if mask is None else round(float(mask.mean()), 4)
    scaled_probe = _scaled_probe(before)
    if reference:
        measured = measure(before, mask, lab_before, scaled_probe)
        return {
            "file": path.name,
            "sha256": digest,
            "size": [width, height],
            "family": family,
            "role": role,
            "preset": None,
            "recipe": None,
            "strength": None,
            "reference": True,
            "flat_probe_fraction": probe,
            "warnings": warnings,
            "before": measured,
            "after": measured,
            "delta": {},
        }

    recipe = preset if preset is not None else apply_ccd.PRESETS[preset_name]
    after = apply_ccd._apply_pixel_recipe(
        before,
        recipe,
        strength,
        seed,
        None,
        None,
        None,
    )
    # The file pipeline unsharp-masks after the recipe. Measuring only the recipe
    # described a pipeline that never ships, and made `--ablate sharpness` a no-op.
    after = apply_ccd.apply_sharpness(after, recipe, strength, None)
    measured_before = measure(before, mask, lab_before, scaled_probe)
    measured_after = measure(after, mask, scaled_probe=scaled_probe)
    return {
        "file": path.name,
        "sha256": digest,
        "size": [width, height],
        "family": family or preset_name,
        "role": role,
        "preset": preset_name,
        "recipe": recipe.name,
        "strength": strength,
        "reference": False,
        "flat_probe_fraction": probe,
        "warnings": warnings,
        "before": measured_before,
        "after": measured_after,
        "delta": _delta(measured_before, measured_after),
    }


def _interval(values: list[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    q = np.percentile(array, [0, 25, 50, 75, 100])
    return {
        "n": int(array.size),
        "min": round(float(q[0]), 4),
        "p25": round(float(q[1]), 4),
        "median": round(float(q[2]), 4),
        "p75": round(float(q[3]), 4),
        "max": round(float(q[4]), 4),
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Group by family, then by role, and describe each metric as an interval.

    Calibration frames are the only ones allowed to justify a tuning decision; holdout
    frames are acceptance evidence. Pooling them lets a change look justified by the
    very frames it was tuned on, so the two are never mixed here.
    """
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    totals: dict[str, int] = {}
    for record in records:
        if record.get("status") != "ok":
            continue
        family = record["family"]
        role = record.get("role") or "calibration"
        bucket = buckets.setdefault((family, role), {"n": 0, "after": {}, "delta": {}})
        bucket["n"] += 1
        totals[family] = totals.get(family, 0) + 1
        for phase in ("after", "delta"):
            source = record[phase]
            for key, value in source.items():
                if value is None:
                    continue
                bucket[phase].setdefault(key, []).append(float(value))

    result: dict[str, Any] = {}
    for family in sorted(totals):
        roles: dict[str, Any] = {}
        for (name, role), bucket in sorted(buckets.items()):
            if name != family:
                continue
            roles[role] = {
                "n": bucket["n"],
                "insufficient_n": bucket["n"] < 4,
                "after": {key: _interval(values) for key, values in sorted(bucket["after"].items())},
                "delta": {key: _interval(values) for key, values in sorted(bucket["delta"].items())},
            }
        result[family] = {
            "n": totals[family],
            "insufficient_n": any(block["insufficient_n"] for block in roles.values()),
            "roles": roles,
        }
    return result


def _load_cases(args: argparse.Namespace) -> tuple[list[dict[str, Any]], str]:
    if args.manifest:
        manifest_path = Path(args.manifest).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("cases")
        if entries is not None:
            root = Path(args.root).resolve() if args.root else manifest_path.parent.parent
        else:
            entries = manifest.get("entries") or []
            root = Path(args.root).resolve() if args.root else manifest_path.parent
        cases = []
        for case in entries:
            relative = case.get("local_path") or case.get("source")
            if not relative:
                continue
            source = Path(relative)
            cases.append(
                {
                    "id": case.get("id") or source.stem,
                    "path": source if source.is_absolute() else root / source,
                    "preset": case.get("preset") or args.preset,
                    "family": case.get("family") or case.get("preset") or args.preset,
                    "role": case.get("role") or "calibration",
                    "strength": args.strength
                    if args.strength is not None
                    else int((case.get("strengths") or [50])[0]),
                }
            )
        return cases, f"manifest:{manifest_path.name}"

    folder = Path(args.sources).resolve()
    if not folder.is_dir():
        raise SystemExit(f"--sources 不是目录：{folder}")
    suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in suffixes)
    return (
        [
            {
                "id": path.stem,
                "path": path,
                "preset": args.preset,
                "family": args.preset,
                "role": "calibration",
                "strength": args.strength if args.strength is not None else 50,
            }
            for path in paths
        ],
        f"folder:{folder.name}",
    )


def _guardrail_violations(measured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report only what this step made worse, never what the source already was."""
    violations = []
    for record in measured:
        before, after = record["before"], record["after"]
        near_white_delta = after["near_white"] - before["near_white"]
        if near_white_delta > GUARDRAIL_LIMITS["near_white_increase_max"]:
            violations.append(
                {
                    "id": record["id"],
                    "check": "near_white_increase_max",
                    "before": before["near_white"],
                    "after": after["near_white"],
                    "delta": round(near_white_delta, 5),
                    "limit": GUARDRAIL_LIMITS["near_white_increase_max"],
                }
            )
        clipped_delta = after["clipped_channel"] - before["clipped_channel"]
        if clipped_delta > GUARDRAIL_LIMITS["clipped_channel_increase_max"]:
            violations.append(
                {
                    "id": record["id"],
                    "check": "clipped_channel_increase_max",
                    "before": before["clipped_channel"],
                    "after": after["clipped_channel"],
                    "delta": round(clipped_delta, 5),
                    "limit": GUARDRAIL_LIMITS["clipped_channel_increase_max"],
                }
            )
        ratio = record["delta"]["corner_drop_ratio"]
        if ratio is not None and ratio > GUARDRAIL_LIMITS["corner_drop_ratio_max"]:
            violations.append(
                {
                    "id": record["id"],
                    "check": "corner_drop_ratio_max",
                    "value": ratio,
                    "limit": GUARDRAIL_LIMITS["corner_drop_ratio_max"],
                }
            )
    return violations


def build_report(
    cases: list[dict[str, Any]],
    seed: int,
    source_label: str,
    origin: str,
    max_pixels: int = MEASURE_MAX_PIXELS,
    ablation_stage: str | None = None,
    reference: bool = False,
    coverage: dict[str, Any] | None = None,
    reference_tier: str | None = None,
    reference_verified: bool = False,
) -> dict[str, Any]:
    ablation_records: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    for case in cases:
        path = Path(case["path"])
        if not path.is_file():
            records.append(
                {
                    "id": case["id"],
                    "file": path.name,
                    "family": case.get("family") or case.get("preset"),
                    "preset": case.get("preset"),
                    "strength": case.get("strength"),
                    "status": "missing_source",
                }
            )
            continue

        recipe: apply_ccd.Preset | None = None
        if ablation_stage and not reference:
            try:
                recipe, changes = ccd_ablate.ablate(apply_ccd.PRESETS[case["preset"]], ablation_stage)
                ablation_records[case["id"]] = {"status": "ablated", "zeroed_fields": changes}
            except ValueError as exc:
                ablation_records[case["id"]] = {"status": "already_off", "reason": str(exc)}

        record = profile_image(
            path,
            case.get("preset"),
            int(case["strength"]),
            seed,
            max_pixels,
            recipe,
            family=case.get("family"),
            reference=reference,
            role=case.get("role") or "calibration",
        )
        record["id"] = case["id"]
        record["status"] = "ok"
        records.append(record)

    measured = [record for record in records if record["status"] == "ok"]
    violations = [] if reference else _guardrail_violations(measured)
    families = aggregate(records)
    # A family the manifest declares but no image covers must still appear, with n=0,
    # so a reader cannot mistake an omission for a family that happened to be fine.
    for name in (coverage or {}):
        families.setdefault(
            name,
            {"n": 0, "insufficient_n": True, "absent": True, "roles": {}},
        )
    families = {name: families[name] for name in sorted(families)}

    return {
        "title": reference_title(source_label) if reference else TITLE,
        "baseline": False,
        "reference": reference,
        "note": reference_note(reference_tier, reference_verified) if reference else NOTE,
        "generated_by": "tests/ccd_profile.py",
        "script_version": apply_ccd.SCRIPT_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profiler_commit": profiler_commit(),
        "working_tree_dirty": working_tree_dirty(),
        "reference_tier": reference_tier,
        "reference_verified": reference_verified,
        "seed": seed,
        "ablation": None
        if not ablation_stage or reference
        else {
            "stage": ablation_stage,
            "per_image": ablation_records,
            "note": "消融测量：该阶段被置零，结果不是生产配方，也不能当作基线。",
        },
        "source_label": source_label,
        "sources": {
            "origin": origin,
            "count": len(records),
            "measured": len(measured),
            "redistributed": False,
            "note": source_note(reference, reference_tier, reference_verified),
        },
        "metric_definitions": {
            "L_p*": "CIELAB L* 的百分位（D65，按 sRGB 解释；已由脚本转成 sRGB）",
            "near_white": "L* ≥ 97 的像素比例",
            "clipped_channel": "8-bit 通道值等于 255 的比例",
            "near_black": "L* ≤ 2 的像素比例",
            "highlight_a/_b": "L* ≥ 80 像素的平均 a*/b*",
            "shadow_a/_b": "L* ≤ 25 像素的平均 a*/b*",
            "corner_drop_ratio": "(处理前四角均值 − 处理后四角均值) / 处理前四角均值",
            "centre_delta_ratio": "(处理后中心均值 − 处理前中心均值) / 处理前中心均值",
            "flat_noise": "在源图最平滑四分位区域上测得的 L* 残差稳健标准差（1.4826×MAD）；前后两相使用同一掩膜",
            "flat_noise_scaled": (
                f"同上，但先把两相按面积平均重采样到长边 {GRAIN_REFERENCE_LONG_EDGE} 像素，"
                "在同一显示尺度上复用源图掩膜比较，用于跨分辨率对照；小于该长边的图不计算"
            ),
            "roles": (
                "calibration/holdout 只允许 Tier A（可参与调参 / 只作验收）；pilot/holdout_preview 是 "
                "Tier B/C 的描述性分区，不进入标定；一律按 family × role 分开聚合"
            ),
            "flat_probe_fraction": "颗粒探针覆盖的像素比例；为 null 表示画面太平滑区域不足，未测颗粒",
        },
        "guardrails": None
        if reference
        else {
            "limits": GUARDRAIL_LIMITS,
            "policy": "只判罚管线新增的近白、通道剪切与四角压暗；绝对过曝/欠曝属于源图，只报告。",
            "violations": violations,
        },
        "coverage": coverage,
        "images": records,
        "families": families,
    }


def _stat(block: dict[str, Any], key: str, field: str = "median") -> str:
    """Read one interval endpoint without assuming the metric was measurable."""
    entry = block.get(key)
    if not entry:
        return "n/a"
    value = entry.get(field)
    return "n/a" if value is None else f"{value:.3f}"


def _print_summary(report: dict[str, Any]) -> None:
    print(f"[ccd_profile] {report['title']}", file=sys.stderr)
    print(f"  sources: {report['sources']['measured']}/{report['sources']['count']}", file=sys.stderr)
    reference = bool(report.get("reference"))
    for family, data in report["families"].items():
        if data.get("absent"):
            print(f"  {family}: absent（清单声明但没有图）", file=sys.stderr)
            continue
        for role, block in data.get("roles", {}).items():
            after = block["after"]
            delta = block.get("delta") or {}
            marker = " (n<4, 不足以看区间)" if block["insufficient_n"] else ""
            tail = (
                f" L50={_stat(after, 'L_p50')}"
                f" L5={_stat(after, 'L_p5')}"
                f" L95={_stat(after, 'L_p95')}"
                f" nw_max={_stat(after, 'near_white', 'max')}"
                f" nb_max={_stat(after, 'near_black', 'max')}"
                f" corner={_stat(after, 'corner_L')}"
                f" centre={_stat(after, 'centre_L')}"
                f" noise={_stat(after, 'flat_noise')}"
                f" noise@{GRAIN_REFERENCE_LONG_EDGE}={_stat(after, 'flat_noise_scaled')}"
            )
            if not reference:
                tail += f" corner_drop={_stat(delta, 'corner_drop_ratio')} centre={_stat(delta, 'centre_delta_ratio')}"
            print(f"  {family}/{role}: n={block['n']}{marker}{tail}", file=sys.stderr)
    if reference:
        coverage = report.get("coverage") or {}
        for family, plan in coverage.items():
            print(f"  coverage {family}: {plan}", file=sys.stderr)
        print("  这是清单声明来源的自身区间，不是本仓库管线的输出，也不是四族完整基线。", file=sys.stderr)
        return
    print(f"  guardrail violations: {len(report['guardrails']['violations'])}", file=sys.stderr)
    print("  不做单一总分；这些区间不是 CCD 基线。", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="测量本地管线的色调/色彩指纹；不写图片，不做单一评分。")
    parser.add_argument("--manifest", type=Path, help="带 cases 的清单（按 case 取预设与强度）")
    parser.add_argument("--sources", type=Path, help="图片目录（配合 --preset）")
    parser.add_argument("--preset", choices=sorted(apply_ccd.PRESETS), default="daylight-aged")
    parser.add_argument("--strength", type=int, default=None, help="覆盖清单里的强度；默认取清单第一档，目录模式默认 50")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--max-pixels",
        type=int,
        default=MEASURE_MAX_PIXELS,
        help=f"测量上限（默认 {MEASURE_MAX_PIXELS}）；超过时请导出较小副本",
    )
    parser.add_argument(
        "--ablate",
        choices=sorted(ccd_ablate.STAGES),
        help="把单个阶段置零后测量（消融），一次只能关闭一个阶段",
    )
    parser.add_argument("--out", type=Path, help="写入 JSON；省略时打印到 stdout")
    parser.add_argument("--root", type=Path, help="清单里相对路径的根；默认按清单类型推断")
    parser.add_argument(
        "--reference",
        action="store_true",
        help="只测源图（不跑配方），用于量真实 CCD 直出本身的区间",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if bool(args.manifest) == bool(args.sources):
        parser.error("必须且只能给 --manifest 或 --sources 之一")
    if args.strength is not None and not 0 <= args.strength <= 100:
        parser.error("--strength 必须位于 0–100")
    if args.reference and args.ablate:
        parser.error("--reference 只测源图，不能与 --ablate 同时使用")

    coverage = None
    reference_tier = None
    reference_verified = False
    if args.reference:
        if not args.manifest:
            parser.error("--reference 需要 --manifest：数字必须和来源声明一起留下")
        manifest_path = Path(args.manifest).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") == "template":
            parser.error("--reference 拒绝模板清单：先填真实证据，或改用普通清单")
        # Numbers must be tied to a manifest that actually validates: field presence is
        # a claim, a passing check of hashes and EXIF is evidence.
        verdict = verify_reference_set.validate(manifest, manifest_path.parent)
        if verdict["result"] != "pass":
            details = "; ".join(
                f"{item.get('scope')}: {item.get('reason')}" for item in verdict["errors"][:5]
            )
            print(f"清单未通过校验，拒绝测量：{details}", file=sys.stderr)
            raise SystemExit(2)
        coverage = manifest.get("coverage")
        entries = [item for item in manifest.get("entries", []) if isinstance(item, dict)]
        tiers = {item.get("evidence_tier") for item in entries}
        reference_tier = tiers.pop() if len(tiers) == 1 else None
        reference_verified = True

    cases, label = _load_cases(args)
    origin = "manifest" if args.manifest else "folder"
    report = build_report(
        cases,
        args.seed,
        label,
        origin,
        args.max_pixels,
        args.ablate,
        reference=args.reference,
        coverage=coverage,
        reference_tier=reference_tier,
        reference_verified=reference_verified,
    )
    if not args.quiet:
        _print_summary(report)

    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
        print(f"[ccd_profile] wrote {args.out}", file=sys.stderr)
    else:
        print(payload)
    return 0 if report["sources"]["measured"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
