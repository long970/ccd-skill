#!/usr/bin/env python3
"""Deterministic, local CCD-look pixel treatment for existing photographs.

This program does not use a generative model, perform semantic edits, or make
network requests. The result is a style approximation, not a physical camera
sensor simulation. Source EXIF metadata is intentionally not copied.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms, ImageFilter, ImageOps, UnidentifiedImageError, __version__ as PILLOW_VERSION

def _load_bundle_version() -> str:
    try:
        return (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="ascii").strip()
    except OSError:
        return "0+unknown"


SCRIPT_VERSION = _load_bundle_version()
MAX_PIXELS = 60_000_000
TILE_ROWS = 256
SUPPORTED_INPUT_FORMATS = {"JPEG", "PNG", "WEBP"}
OUTPUT_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}


class ProcessingError(Exception):
    """Expected input/processing failure suitable for an actionable message."""


@dataclass(frozen=True)
class Preset:
    name: str
    environment: str
    flash_axis: str
    degradation: str
    exposure_ev: float
    contrast_delta: float
    saturation_delta: float
    shadow_gain: tuple[float, float, float]
    highlight_gain: tuple[float, float, float]
    shadow_lift: float
    highlight_compression: float
    highlight_boost: float
    grain_sigma: float
    vignette_amount: float
    sharpness_amount: float


PRESETS: dict[str, Preset] = {
    "daylight-clean": Preset(
        name="daylight-clean", environment="daylight", flash_axis="none", degradation="clean",
        exposure_ev=0.00, contrast_delta=0.12, saturation_delta=0.14,
        shadow_gain=(1.005, 1.000, 1.012), highlight_gain=(1.020, 1.005, 0.985),
        shadow_lift=0.00, highlight_compression=0.02, highlight_boost=0.00,
        grain_sigma=0.005, vignette_amount=0.12, sharpness_amount=0.22,
    ),
    "daylight-aged": Preset(
        name="daylight-aged", environment="daylight", flash_axis="none", degradation="light-aged",
        exposure_ev=-0.005, contrast_delta=0.12, saturation_delta=0.18,
        shadow_gain=(0.995, 1.000, 1.020), highlight_gain=(1.025, 1.008, 0.975),
        shadow_lift=0.035, highlight_compression=0.18, highlight_boost=0.00,
        grain_sigma=0.030, vignette_amount=0.36, sharpness_amount=0.20,
    ),
    "indoor-flash": Preset(
        name="indoor-flash", environment="indoor", flash_axis="direct-tonal", degradation="clean",
        exposure_ev=0.045, contrast_delta=0.20, saturation_delta=0.06,
        shadow_gain=(0.990, 1.000, 1.022), highlight_gain=(1.018, 1.004, 0.992),
        shadow_lift=0.045, highlight_compression=0.00, highlight_boost=0.30,
        grain_sigma=0.014, vignette_amount=0.70, sharpness_amount=0.34,
    ),
    "night-flash": Preset(
        name="night-flash", environment="night", flash_axis="direct-tonal", degradation="light-aged",
        exposure_ev=-0.020, contrast_delta=0.22, saturation_delta=0.14,
        shadow_gain=(0.820, 1.000, 1.250), highlight_gain=(1.020, 1.005, 0.985),
        shadow_lift=0.070, highlight_compression=0.00, highlight_boost=0.26,
        grain_sigma=0.045, vignette_amount=0.70, sharpness_amount=0.30,
    ),
}


def _profile_bytes() -> bytes | None:
    try:
        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        return None


SRGB_PROFILE_BYTES = _profile_bytes()


def _has_alpha(image: Image.Image) -> bool:
    return "A" in image.getbands() or "transparency" in image.info


def _quantize_16bit_gray(image: Image.Image) -> Image.Image:
    """Convert an explicitly 16-bit integer grayscale raster to 8-bit L."""
    arr = np.asarray(image)
    if arr.dtype.kind not in "ui":
        raise ProcessingError("不支持浮点像素图；请先在本机导出为 8-bit PNG/JPEG。")
    if arr.size and (int(arr.min()) < 0 or int(arr.max()) > 65535):
        raise ProcessingError("整数灰度图超出 0–65535 范围，无法安全量化。")
    wide = arr.astype(np.uint32, copy=False)
    quantized = ((wide + 128) // 257).astype(np.uint8)
    return Image.fromarray(quantized)


def _to_srgb_rgb(image: Image.Image, icc_profile: bytes | None, warnings: list[str]) -> Image.Image:
    """Return an RGB image in sRGB, failing rather than guessing bad ICC data."""
    mode = image.mode
    work = image

    if mode.startswith("I;16") or mode == "I":
        work = _quantize_16bit_gray(work)
        mode = "L"
        warnings.append("输入为 16-bit 整数灰度；为生成 8-bit 风格输出，按固定 0–65535 范围量化。")
    elif mode == "F":
        raise ProcessingError("不支持浮点像素图；请先在本机转换为 8-bit PNG/JPEG。")

    if mode == "P":
        work = work.convert("RGB")
        mode = "RGB"
    elif mode in ("RGBA", "LA", "RGBa", "La"):
        work = work.convert("RGB")
        mode = "RGB"
    elif mode not in ("RGB", "CMYK", "L"):
        work = work.convert("RGB")
        mode = "RGB"

    if icc_profile:
        try:
            source_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
            target_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
            return ImageCms.profileToProfile(work, source_profile, target_profile, outputMode="RGB")
        except Exception as exc:
            raise ProcessingError(f"无法读取或转换输入 ICC 色彩配置：{exc}") from exc

    if mode == "CMYK":
        warnings.append("输入为无 ICC 的 CMYK；使用 Pillow 默认转换到 RGB，颜色可能略有偏差。")
    else:
        warnings.append("输入未嵌入 ICC；按 sRGB 假设处理，原始色彩空间未知。")
    return work.convert("RGB")


def _display_rgb(image: Image.Image, icc_profile: bytes | None, warnings: list[str]) -> tuple[Image.Image, Image.Image | None]:
    alpha = image.convert("RGBA").getchannel("A") if _has_alpha(image) else None
    rgb = _to_srgb_rgb(image, icc_profile, warnings)
    return rgb, alpha


def _effect_fraction(override: int | None, main_strength: int) -> float:
    return (main_strength if override is None else override) / 100.0


def _apply_pixel_recipe(
    source: np.ndarray,
    preset: Preset,
    strength: int,
    seed: int,
    grain_strength: int | None,
    color_strength: int | None,
    vignette_strength: int | None,
) -> np.ndarray:
    if strength == 0 and all(value in (None, 0) for value in (grain_strength, color_strength, vignette_strength)):
        return source.copy()
    height, width, _ = source.shape
    out = np.empty_like(source, dtype=np.uint8)
    main = strength / 100.0
    grain_mix = _effect_fraction(grain_strength, strength)
    color_mix = _effect_fraction(color_strength, strength)
    vignette_mix = _effect_fraction(vignette_strength, strength)
    rng = np.random.default_rng(seed)

    x_coords = (np.arange(width, dtype=np.float32) + 0.5) / max(width, 1)
    xx = (x_coords - 0.5) * 2.0
    shadow_gain = np.asarray(preset.shadow_gain, dtype=np.float32)
    highlight_gain = np.asarray(preset.highlight_gain, dtype=np.float32)
    white_balance_span = np.maximum(np.abs(shadow_gain - 1.0), np.abs(highlight_gain - 1.0))
    if not np.any(white_balance_span):
        color_mix = 0.0

    for y0 in range(0, height, TILE_ROWS):
        y1 = min(height, y0 + TILE_ROWS)
        work = source[y0:y1].astype(np.float32) / 255.0
        source_luma = work[..., 0] * 0.2126 + work[..., 1] * 0.7152 + work[..., 2] * 0.0722
        work *= np.float32(math.pow(2.0, preset.exposure_ev * main))

        # Gentle shadow/highlight-specific channel gains create a small digital color cast.
        luma = work[..., 0] * 0.2126 + work[..., 1] * 0.7152 + work[..., 2] * 0.0722
        shadow_mask = np.square(np.clip(1.0 - luma, 0.0, 1.0))[..., None]
        highlight_mask = np.square(np.clip(luma, 0.0, 1.0))[..., None]
        channel_gain = 1.0 + (shadow_gain - 1.0) * shadow_mask + (highlight_gain - 1.0) * highlight_mask
        work *= 1.0 + (channel_gain - 1.0) * color_mix

        # Endpoint-pinned S-curve: it raises midtone contrast without ever exceeding 1.0 or
        # flattening the top, so highlights keep distinct output codes instead of forming a shelf.
        curve_a = preset.contrast_delta * 1.6 * main
        if curve_a > 0:
            work = np.clip(work, 0.0, 1.0)
            work = work + np.float32(curve_a) * work * (1.0 - work) * (2.0 * work - 1.0)

        # Retain a little shadow detail instead of making global contrast crush blacks.
        luma = work[..., 0] * 0.2126 + work[..., 1] * 0.7152 + work[..., 2] * 0.0722
        shadow_visibility = np.square(np.clip((0.28 - luma) / 0.28, 0.0, 1.0))
        work += (shadow_visibility * np.float32(preset.shadow_lift * main))[..., None]

        saturation = 1.0 + preset.saturation_delta * color_mix
        luma = work[..., 0] * 0.2126 + work[..., 1] * 0.7152 + work[..., 2] * 0.0722
        work = luma[..., None] + (work - luma[..., None]) * np.float32(saturation)

        # Direct flash pushes bright areas toward white. The gain shrinks as values approach
        # 1.0 (work + (1-work)*lift), so there is no saturation wall and no long flat shelf;
        # only genuine near-white source specular is pinned, which is a 2-code clip at most.
        if preset.highlight_boost > 0 and main > 0:
            work = np.clip(work, 0.0, 1.0)
            luma = work[..., 0] * 0.2126 + work[..., 1] * 0.7152 + work[..., 2] * 0.0722
            highlight_mask = np.clip((luma - 0.72) / 0.28, 0.0, 1.0)
            lift = np.float32(preset.highlight_boost * main)
            work = work + (1.0 - work) * (highlight_mask * lift)[..., None]
            genuine_specular = (source_luma >= 0.995)[..., None]
            work = np.where(genuine_specular, 1.0, work)

        # Non-flash aging may compress highlights; direct-flash presets use the soft knee above.
        compression = preset.highlight_compression * main
        if compression > 0:
            start = np.float32(0.78)
            above = np.maximum(work - start, 0.0)
            work = np.where(work > start, start + above * np.float32(1.0 - compression), work)

        if preset.vignette_amount > 0 and vignette_mix > 0:
            y_coords = (np.arange(y0, y1, dtype=np.float32) + 0.5) / max(height, 1)
            yy = (y_coords - 0.5) * 2.0
            # Normalize so the farthest corner is approximately 1; no geometry is changed.
            radius2 = (yy[:, None] ** 2 + xx[None, :] ** 2) * 0.5
            luma = work[..., 0] * 0.2126 + work[..., 1] * 0.7152 + work[..., 2] * 0.0722
            # Protect only near-black pixels; ordinary night backgrounds must still receive a vignette.
            shadow_guard = np.clip(luma / 0.02, 0.0, 1.0)
            # Give night backgrounds a visible edge falloff while leaving true black pixels alone.
            dark_scene_boost = 1.0 + 0.35 * np.clip((0.08 - luma) / 0.08, 0.0, 1.0)
            vignette_drop = np.float32(0.34 * preset.vignette_amount * vignette_mix)
            local_drop = np.minimum(vignette_drop * dark_scene_boost, 0.20)
            factor = 1.0 - local_drop * radius2 * shadow_guard
            work *= np.clip(factor, 0.45, 1.0)[..., None]

        if preset.grain_sigma > 0 and grain_mix > 0:
            rows = y1 - y0
            sigma = preset.grain_sigma * grain_mix
            luminance_noise = rng.standard_normal((rows, width, 1), dtype=np.float32)
            chroma_noise = rng.standard_normal((rows, width, 3), dtype=np.float32)
            work += luminance_noise * np.float32(sigma)
            work += chroma_noise * np.float32(sigma * 0.18)

        out[y0:y1] = np.clip(work * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)

    return out


def _clip_stats(rgb: np.ndarray, alpha: np.ndarray | None = None) -> dict[str, float]:
    height, width = rgb.shape[:2]
    counts = {"visible": 0, "near_white": 0, "clipped_channel": 0, "near_black": 0}
    for y0 in range(0, height, TILE_ROWS):
        y1 = min(height, y0 + TILE_ROWS)
        block = rgb[y0:y1]
        luma = (
            block[..., 0].astype(np.float32) * 0.2126
            + block[..., 1].astype(np.float32) * 0.7152
            + block[..., 2].astype(np.float32) * 0.0722
        ) / 255.0
        visible = np.ones(luma.shape, dtype=bool) if alpha is None else alpha[y0:y1] > 0
        counts["visible"] += int(np.count_nonzero(visible))
        counts["near_white"] += int(np.count_nonzero(np.all(block >= 254, axis=2) & visible))
        counts["clipped_channel"] += int(np.count_nonzero(np.any(block >= 254, axis=2) & visible))
        counts["near_black"] += int(np.count_nonzero((luma <= (2.0 / 255.0)) & visible))
    total = counts["visible"]
    if not total:
        return {"near_white_ratio": 0.0, "clipped_channel_ratio": 0.0, "near_black_luma_ratio": 0.0}
    return {
        "near_white_ratio": counts["near_white"] / total,
        "clipped_channel_ratio": counts["clipped_channel"] / total,
        "near_black_luma_ratio": counts["near_black"] / total,
    }


def _format_from_path(path: Path) -> str:
    fmt = OUTPUT_FORMATS.get(path.suffix.lower())
    if not fmt:
        raise ProcessingError("输出路径扩展名须为 .jpg、.jpeg、.png 或 .webp。")
    return fmt


def _default_output_path(source: Path, preset: str, strength: int, has_alpha: bool, input_format: str) -> Path:
    suffix = ".png" if has_alpha or input_format == "PNG" else ".jpg"
    return source.with_name(f"{source.stem}_ccd-{preset}-{strength}{suffix}")



def _save_new_file(image: Image.Image, requested: Path, fmt: str, quality: int) -> Path:
    icc = SRGB_PROFILE_BYTES
    for index in range(1, 10000):
        candidate = requested if index == 1 else requested.with_name(f"{requested.stem}-{index}{requested.suffix}")
        try:
            with candidate.open("xb") as handle:
                try:
                    save_args: dict[str, Any] = {}
                    if icc:
                        save_args["icc_profile"] = icc
                    if fmt == "JPEG":
                        # Keep libjpeg's optimized Huffman pass off: high-entropy images can
                        # trigger "Suspension not allowed here" in the bundled encoder.
                        save_args.update(quality=quality, optimize=False, progressive=False, subsampling=0)
                    elif fmt == "PNG":
                        save_args.update(compress_level=6)
                    elif fmt == "WEBP":
                        save_args.update(quality=quality, method=4)
                    image.save(handle, format=fmt, **save_args)
                except Exception:
                    handle.close()
                    candidate.unlink(missing_ok=True)
                    raise
            return candidate
        except FileExistsError:
            continue
        except OSError as exc:
            raise ProcessingError(f"无法写出文件 {candidate}：{exc}。可用 --out 指定一个可写的输出目录。") from exc
    raise ProcessingError("无法为输出文件分配不冲突的文件名。")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 Pillow/NumPy 在本地对静态照片应用可复现的 CCD 观感近似；不联网、不覆盖原图。"
    )
    parser.add_argument("input", type=Path, help="输入静态照片：JPEG、PNG 或 WebP")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="daylight-aged")
    parser.add_argument("--strength", type=int, default=50, help="主强度 0–100；默认 50")
    parser.add_argument("--seed", type=int, default=0, help="颗粒随机种子；默认 0，可复现")
    parser.add_argument("--out", type=Path, help="可选输出路径；不得与输入相同，现有文件不会覆盖")
    parser.add_argument("--preview", action="store_true", help="只计算像素效果与指标，不写入图像文件")
    parser.add_argument("--quality", type=int, default=94, help="JPEG/WebP 质量 70–100；默认 94")
    parser.add_argument("--max-pixels", type=int, default=MAX_PIXELS, help=f"本次最大像素数 1–{MAX_PIXELS:,}；默认 {MAX_PIXELS:,}，可向下调以限制内存")
    parser.add_argument("--grain-strength", type=int, default=None, help="颗粒子效果强度 0–100；省略则跟随主强度")
    parser.add_argument("--color-strength", type=int, default=None, help="色彩子效果强度 0–100；省略则跟随主强度")
    parser.add_argument("--vignette-strength", type=int, default=None, help="暗角子效果强度 0–100；省略则跟随主强度")
    parser.add_argument("--sharpness-strength", type=int, default=None, help="锐度子效果强度 0–100；省略则跟随主强度")
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> None:
    if not 0 <= args.strength <= 100:
        raise ProcessingError("--strength 必须是 0–100。")
    if args.seed < 0:
        raise ProcessingError("--seed 必须是非负整数。")
    if not 70 <= args.quality <= 100:
        raise ProcessingError("--quality 必须是 70–100。")
    if not 1 <= args.max_pixels <= MAX_PIXELS:
        raise ProcessingError(f"--max-pixels 必须是 1–{MAX_PIXELS:,}。只能向下调，不能突破安全上限。")
    for key in ("grain_strength", "color_strength", "vignette_strength", "sharpness_strength"):
        value = getattr(args, key)
        if value is not None and not 0 <= value <= 100:
            raise ProcessingError(f"--{key.replace('_', '-')} 必须是 0–100。")


def run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    if args.preview and args.out is not None:
        raise ProcessingError("--preview 不写文件；请移除 --out。")
    try:
        source_path = args.input.expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise ProcessingError(f"输入文件不存在：{args.input}") from exc
    except OSError as exc:
        raise ProcessingError(f"无法访问输入路径 {args.input}：{exc}") from exc
    if not source_path.is_file():
        raise ProcessingError(f"输入不是普通文件：{source_path}")
    explicit_output = args.out.expanduser().resolve(strict=False) if args.out else None
    if explicit_output is not None:
        if os.path.normcase(str(explicit_output)) == os.path.normcase(str(source_path)):
            raise ProcessingError("输出路径与输入文件相同；为保护原图，拒绝原地覆盖。")
        _format_from_path(explicit_output)
        if not explicit_output.parent.exists() or not explicit_output.parent.is_dir():
            raise ProcessingError(f"输出目录不存在或不是目录：{explicit_output.parent}")
    if source_path.suffix.lower() in {".heic", ".heif"}:
        raise ProcessingError("当前没有 HEIC/HEIF 解码器。请在本机导出 JPEG/PNG 后重试；图片不会被上传。")

    warnings: list[str] = []
    try:
        with Image.open(source_path) as raw:
            if raw.format not in SUPPORTED_INPUT_FORMATS:
                raise ProcessingError(f"不支持输入格式 {raw.format!r}；支持静态 JPEG、PNG、WebP。")
            input_format = raw.format
            if getattr(raw, "n_frames", 1) != 1:
                raise ProcessingError("不支持多帧/动画图像；请先在本机导出所需静态帧。")
            raw_w, raw_h = raw.size
            if raw_w <= 0 or raw_h <= 0 or raw_w * raw_h > args.max_pixels:
                if args.max_pixels < MAX_PIXELS:
                    remedy = f"若内存允许，可把 --max-pixels 提高到最多 {MAX_PIXELS:,}；"
                else:
                    remedy = f"已经达到 {MAX_PIXELS:,} 像素安全上限；"
                raise ProcessingError(
                    f"图像尺寸 {raw_w}×{raw_h} 超出本次限制（最多 {args.max_pixels:,} 像素）；"
                    f"{remedy}脚本不会自动缩放。超过安全上限时请选择其他本地处理方案。"
                )
            icc_profile = raw.info.get("icc_profile")
            has_alpha = _has_alpha(raw)
            oriented = ImageOps.exif_transpose(raw)
            oriented.load()
            display_size = oriented.size
            rgb_image, alpha_image = _display_rgb(oriented, icc_profile, warnings)
            rgb_source = np.asarray(rgb_image, dtype=np.uint8)
            alpha_source = np.asarray(alpha_image, dtype=np.uint8) if alpha_image is not None else None
            input_stats = _clip_stats(rgb_source, alpha_source)
            preset = PRESETS[args.preset]
            rgb_out = _apply_pixel_recipe(
                rgb_source,
                preset,
                args.strength,
                args.seed,
                args.grain_strength,
                args.color_strength,
                args.vignette_strength,
            )
            output_rgb_image = Image.fromarray(rgb_out)
            sharp_mix = _effect_fraction(args.sharpness_strength, args.strength)
            sharpness_percent = int(round(100 * preset.sharpness_amount * sharp_mix))
            # Scale radius with the long edge so the sharpening footprint is similar at display size.
            sharpen_radius = max(0.5, max(display_size) / 3000.0)
            if preset.sharpness_amount > 0 and sharpness_percent > 0:
                output_rgb_image = output_rgb_image.filter(
                    ImageFilter.UnsharpMask(radius=sharpen_radius, percent=sharpness_percent, threshold=3)
                )
            if alpha_source is not None:
                output_rgba = output_rgb_image.convert("RGBA")
                output_rgba.putalpha(Image.fromarray(alpha_source))
                output_image = output_rgba
            else:
                output_image = output_rgb_image
    except ProcessingError:
        raise
    except UnidentifiedImageError as exc:
        raise ProcessingError("无法识别输入图像；确认文件未损坏且为 JPEG、PNG 或 WebP。") from exc
    except (OSError, ValueError) as exc:
        raise ProcessingError(f"无法读取或处理输入图像：{exc}") from exc

    requested = explicit_output if explicit_output is not None else _default_output_path(
        source_path, args.preset, args.strength, has_alpha, input_format
    )
    fmt = _format_from_path(requested)
    if alpha_source is not None and fmt == "JPEG":
        raise ProcessingError("输入有透明通道，不能无提示地压平成 JPEG；请使用 .png 或 .webp 输出。")
    output_path: Path | None = None
    if args.preview:
        # Preview measures the transformed in-memory pixels and never creates an image file.
        rgb_check = np.asarray(output_image.convert("RGB"), dtype=np.uint8)
        output_stats = _clip_stats(rgb_check, alpha_source)
    else:
        if not requested.parent.exists() or not requested.parent.is_dir():
            raise ProcessingError(f"输出目录不存在或不是目录：{requested.parent}")
        output_path = _save_new_file(output_image, requested, fmt, args.quality)
        try:
            with Image.open(output_path) as check:
                check.load()
                if check.size != display_size:
                    raise ProcessingError(f"输出尺寸异常：预期 {display_size}，实际 {check.size}。")
                if alpha_source is not None and not _has_alpha(check):
                    raise ProcessingError("输出丢失了输入透明通道。")
                rgb_check = np.asarray(check.convert("RGB"), dtype=np.uint8)
                output_stats = _clip_stats(rgb_check, alpha_source)
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            if isinstance(exc, ProcessingError):
                raise
            raise ProcessingError(f"输出文件校验失败，已清理不完整结果：{exc}") from exc

    if SRGB_PROFILE_BYTES is None:
        warnings.append("无法创建 sRGB ICC profile；输出未嵌入目标 ICC profile。")

    ratio_divisor = math.gcd(display_size[0], display_size[1])
    overrides = {
        "grain": args.grain_strength,
        "color": args.color_strength,
        "vignette": args.vignette_strength,
        "sharpness": args.sharpness_strength,
    }
    return {
        "status": "preview" if args.preview else "processed",
        "capability_layer": "L2-local-pixel-preview" if args.preview else "L2-local-deterministic-pixel-processing",
        "preview_only": bool(args.preview),
        "image_written": not args.preview,
        "script_version": SCRIPT_VERSION,
        "pillow_version": PILLOW_VERSION,
        "numpy_version": np.__version__,
        "input_path": str(source_path),
        "input_format": input_format.lower(),
        "output_path": str(output_path.resolve()) if output_path is not None else None,
        "preset": args.preset,
        "axes": {
            "environment": preset.environment,
            "flash_tonal_impression": preset.flash_axis,
            "degradation": preset.degradation,
        },
        "strength": args.strength,
        "subeffect_mix_overrides": overrides,
        "effective_preset_mix_percent": {
            key: (value if value is not None else args.strength) for key, value in overrides.items()
        },
        "sharpness_filter": {
            "percent": sharpness_percent,
            "radius_px": round(sharpen_radius, 3),
            "radius_normalization": "max(0.5, long_edge / 3000)",
        },
        "seed": args.seed,
        "max_pixels": args.max_pixels,
        "size": {"width": display_size[0], "height": display_size[1]},
        "aspect_ratio": f"{display_size[0] // ratio_divisor}:{display_size[1] // ratio_divisor}",
        "format": fmt.lower(),
        "quality": args.quality if fmt in ("JPEG", "WEBP") else None,
        "jpeg_optimize": False if fmt == "JPEG" else None,
        "alpha_preserved": alpha_source is not None,
        "exif_metadata_copied": False,
        "icc_handling": "converted-or-assumed-srgb; sRGB profile embedded when available",
        "metrics_source": "in-memory pixels before file encoding" if args.preview else "decoded saved output",
        "clipping": {"before": input_stats, "after": output_stats},
        "warnings": warnings,
        "limitations": [
            "风格为数码相机观感近似，不是特定 CCD 传感器的物理仿真。",
            "不进行人脸检测、对象分割、真实闪光阴影重建或语义内容修改。",
            "高光/阴影剪切比例仅为技术提示，不评价审美或身份保真。",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = run(args)
    except ProcessingError as exc:
        print(json.dumps({"status": "not_processed", "capability_layer": "L2-local-deterministic-pixel-processing", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:  # last-resort failure is explicit; never imply success
        print(json.dumps({"status": "not_processed", "capability_layer": "L2-local-deterministic-pixel-processing", "error": f"意外处理错误：{exc}"}, ensure_ascii=False), file=sys.stderr)
        return 3
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
