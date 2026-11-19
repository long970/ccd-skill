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
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

BUNDLE_SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "ccd-photo-enhancer" / "scripts"
if str(BUNDLE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(BUNDLE_SCRIPTS))

import apply_ccd  # noqa: E402  (path set above on purpose)
import ccd_ablate  # noqa: E402  (same directory)

TITLE = "管线自检，非 CCD 基线"
NOTE = (
    "这些数字描述本仓库像素管线在同一批图库照片上的行为；样本不是已验证的 CCD 直出原图，"
    "没有与真实机型对照，也没有盲测。任何结论都不能当作“CCD 基线”。"
)

REFERENCE_TITLE = "CCD 参考区间（网页样张，daylight 子集）"
REFERENCE_NOTE = (
    "这些数字量的是真实 CCD 相机的直出 JPEG 本身，不经过本仓库的像素管线。"
    "样本来自公开的相机评测样张，只覆盖 daylight 两族；indoor-flash 只有 1 张、night-flash 为 0，"
    "所以它是“分区间的第一步”，不是四族完整基线，也没有与手机同期对照或盲测。"
)

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


def measure(rgb: np.ndarray, flat_mask: np.ndarray | None = None, lab: np.ndarray | None = None) -> dict[str, float | None]:
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
    if reference:
        measured = measure(before, mask, lab_before)
        return {
            "file": path.name,
            "sha256": digest,
            "size": [width, height],
            "family": family,
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
    measured_before = measure(before, mask, lab_before)
    measured_after = measure(after, mask)
    return {
        "file": path.name,
        "sha256": digest,
        "size": [width, height],
        "family": family or preset_name,
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
    """Group by family and describe each metric as an interval, never a score."""
    families: dict[str, Any] = {}
    for record in records:
        if record.get("status") != "ok":
            continue
        family = record["family"]
        bucket = families.setdefault(family, {"n": 0, "after": {}, "delta": {}})
        bucket["n"] += 1
        for phase in ("after", "delta"):
            source = record[phase]
            for key, value in source.items():
                if value is None:
                    continue
                bucket[phase].setdefault(key, []).append(float(value))

    result: dict[str, Any] = {}
    for family, bucket in sorted(families.items()):
        result[family] = {
            "n": bucket["n"],
            "insufficient_n": bucket["n"] < 4,
            "after": {key: _interval(values) for key, values in sorted(bucket["after"].items())},
            "delta": {key: _interval(values) for key, values in sorted(bucket["delta"].items())},
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
        )
        record["id"] = case["id"]
        record["status"] = "ok"
        records.append(record)

    measured = [record for record in records if record["status"] == "ok"]
    violations = [] if reference else _guardrail_violations(measured)

    return {
        "title": REFERENCE_TITLE if reference else TITLE,
        "baseline": False,
        "reference": reference,
        "note": REFERENCE_NOTE if reference else NOTE,
        "generated_by": "tests/ccd_profile.py",
        "script_version": apply_ccd.SCRIPT_VERSION,
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
            "note": (
                "真实 CCD 直出样张，版权归原站与摄影师；原图不入库、不转载，只保留文件名与 SHA-256。"
                if reference
                else "源图来自图库（Pexels License），不随仓库分发；只保留文件名与 SHA-256。"
            ),
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
        "families": aggregate(records),
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
        after = data["after"]
        delta = data.get("delta") or {}
        marker = " (n<4, 不足以看区间)" if data["insufficient_n"] else ""
        tail = (
            f" L50={_stat(after, 'L_p50')}"
            f" L5={_stat(after, 'L_p5')}"
            f" L95={_stat(after, 'L_p95')}"
            f" nw_max={_stat(after, 'near_white', 'max')}"
            f" nb_max={_stat(after, 'near_black', 'max')}"
            f" corner={_stat(after, 'corner_L')}"
            f" centre={_stat(after, 'centre_L')}"
            f" noise={_stat(after, 'flat_noise')}"
        )
        if not reference:
            tail += f" corner_drop={_stat(delta, 'corner_drop_ratio')} centre={_stat(delta, 'centre_delta_ratio')}"
        print(f"  {family}: n={data['n']}{marker}{tail}", file=sys.stderr)
    if reference:
        coverage = report.get("coverage") or {}
        for family, plan in coverage.items():
            print(f"  coverage {family}: {plan}", file=sys.stderr)
        print("  这是 CCD 自身的区间，不是本仓库管线的输出，也不是四族完整基线。", file=sys.stderr)
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
    if args.reference and args.manifest:
        coverage = json.loads(Path(args.manifest).read_text(encoding="utf-8")).get("coverage")

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
