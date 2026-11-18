from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "ccd-photo-enhancer" / "scripts" / "apply_ccd.py"


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _prepare_source(source: Path, target: Path, max_long_edge: int) -> None:
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        if max(image.size) > max_long_edge:
            scale = max_long_edge / max(image.size)
            size = tuple(max(1, round(value * scale)) for value in image.size)
            image = image.resize(size, Image.Resampling.LANCZOS)
        image.save(target, quality=95, subsampling=0)


def _luma(rgb: np.ndarray) -> np.ndarray:
    values = rgb.astype(np.float32)
    return values[..., 0] * 0.2126 + values[..., 1] * 0.7152 + values[..., 2] * 0.0722


def _metrics(before: np.ndarray, after: np.ndarray) -> dict[str, float]:
    before_luma = _luma(before)
    after_luma = _luma(after)
    height, width = before_luma.shape
    y0, y1 = int(height * 0.4), int(height * 0.6)
    x0, x1 = int(width * 0.4), int(width * 0.6)
    edge = max(1, min(height, width) // 10)
    corners_before = np.concatenate(
        (
            before_luma[:edge, :edge].ravel(),
            before_luma[:edge, -edge:].ravel(),
            before_luma[-edge:, :edge].ravel(),
            before_luma[-edge:, -edge:].ravel(),
        )
    )
    corners_after = np.concatenate(
        (
            after_luma[:edge, :edge].ravel(),
            after_luma[:edge, -edge:].ravel(),
            after_luma[-edge:, :edge].ravel(),
            after_luma[-edge:, -edge:].ravel(),
        )
    )
    return {
        "mean_abs_delta_255": float(np.mean(np.abs(after.astype(np.int16) - before.astype(np.int16)))),
        "mean_luma_before": float(before_luma.mean()),
        "mean_luma_after": float(after_luma.mean()),
        "centre_luma_before": float(before_luma[y0:y1, x0:x1].mean()),
        "centre_luma_after": float(after_luma[y0:y1, x0:x1].mean()),
        "corner_luma_before": float(corners_before.mean()),
        "corner_luma_after": float(corners_after.mean()),
    }


def _comparison(before_path: Path, after_path: Path, target: Path, label: str) -> None:
    with Image.open(before_path) as left_raw, Image.open(after_path) as right_raw:
        left = ImageOps.contain(left_raw.convert("RGB"), (480, 480))
        right = ImageOps.contain(right_raw.convert("RGB"), (480, 480))
    canvas = Image.new("RGB", (1000, 540), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    draw.text((12, 10), "BEFORE", fill="black", font=font)
    draw.text((512, 10), label, fill="black", font=font)
    canvas.paste(left, (10 + (480 - left.width) // 2, 45 + (480 - left.height) // 2))
    canvas.paste(right, (510 + (480 - right.width) // 2, 45 + (480 - right.height) // 2))
    canvas.save(target, quality=92, subsampling=0)


def _overview(entries: list[dict], target: Path) -> None:
    columns = 3
    cell_width, cell_height = 500, 350
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (232, 232, 232))
    font = ImageFont.load_default(size=17)
    for index, entry in enumerate(entries):
        with Image.open(ROOT / entry["comparison"]) as raw:
            image = ImageOps.contain(raw.convert("RGB"), (480, 300))
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet.paste(image, (x + (cell_width - image.width) // 2, y + 35))
        label = f"{entry['id']} | {entry['preset']} | {entry['strength']}"
        ImageDraw.Draw(sheet).text((x + 10, y + 10), label, fill="black", font=font)
    sheet.save(target, quality=91, subsampling=0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the shipped CLI on licensed real-photo fixtures.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "tests" / "real-photo-manifest.json")
    parser.add_argument("--workspace", type=Path, default=ROOT / "_samples-work" / "real-eval")
    parser.add_argument("--report", type=Path, default=ROOT / "docs" / "samples" / "real-evaluation.json")
    parser.add_argument("--overview", type=Path, default=ROOT / "docs" / "samples" / "real-evaluation-overview.jpg")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    working_dir = args.workspace / "working"
    output_dir = args.workspace / "outputs"
    comparison_dir = args.workspace / "comparisons"
    for directory in (working_dir, output_dir, comparison_dir):
        directory.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.overview.parent.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    for case in manifest["cases"]:
        source = ROOT / case["source"]
        working = working_dir / f"{case['id']}.jpg"
        _prepare_source(source, working, manifest["max_long_edge"])
        for strength in case["strengths"]:
            output = output_dir / f"{case['id']}-{case['preset']}-s{strength}.jpg"
            command = [
                sys.executable,
                str(CLI),
                str(working),
                "--preset",
                case["preset"],
                "--strength",
                str(strength),
                "--seed",
                str(manifest["seed"]),
                "--out",
                str(output),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            if completed.returncode != 0:
                raise RuntimeError(f"{case['id']} failed: {completed.stderr.strip()}")
            cli_report = json.loads(completed.stdout)
            actual_output = Path(cli_report["output_path"])
            comparison = comparison_dir / f"{case['id']}-s{strength}.jpg"
            label = f"AFTER {case['preset']} strength {strength}"
            _comparison(working, actual_output, comparison, label)
            with Image.open(working) as before_image, Image.open(actual_output) as after_image:
                before = np.asarray(before_image.convert("RGB"), dtype=np.uint8)
                after = np.asarray(after_image.convert("RGB"), dtype=np.uint8)
            entries.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "source_page": case["page"],
                    "photographer": case["photographer"],
                    "source_sha256": _sha256(source),
                    "working_image": _relative(working),
                    "output_image": _relative(actual_output),
                    "comparison": _relative(comparison),
                    "preset": case["preset"],
                    "strength": strength,
                    "seed": manifest["seed"],
                    "size": cli_report["size"],
                    "script_version": cli_report["script_version"],
                    "pillow_version": cli_report["pillow_version"],
                    "numpy_version": cli_report["numpy_version"],
                    "clipping": cli_report["clipping"],
                    "metrics": _metrics(before, after),
                }
            )
            print(f"processed {case['id']} strength {strength}")

    deltas = [entry["metrics"]["mean_abs_delta_255"] for entry in entries]
    report = {
        "schema_version": 1,
        "license": manifest["license"],
        "photo_count": len(manifest["cases"]),
        "run_count": len(entries),
        "max_long_edge": manifest["max_long_edge"],
        "summary": {
            "mean_abs_delta_255": float(np.mean(deltas)),
            "min_abs_delta_255": float(np.min(deltas)),
            "max_abs_delta_255": float(np.max(deltas)),
            "max_near_white_ratio_after": max(
                entry["clipping"]["after"]["near_white_ratio"] for entry in entries
            ),
            "max_near_black_ratio_after": max(
                entry["clipping"]["after"]["near_black_luma_ratio"] for entry in entries
            ),
        },
        "limitations": [
            "Pixel metrics do not prove CCD authenticity or aesthetic quality.",
            "No automatic face or skin detection is used; portrait review remains visual.",
            "Sources are resized to the evaluation long edge before running the unchanged CLI.",
        ],
        "entries": entries,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _overview(entries, args.overview)
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"report: {args.report}")
    print(f"overview: {args.overview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
