"""Validate a reference-set manifest before anyone treats its numbers as evidence.

A manifest is only useful if its entries are self-consistent. This checker never
downloads anything: it verifies the declarative fields, the recorded SHA-256 values
against local files, and whether the EXIF still carries the camera model, ISO and
flash state that make an image usable as a reference.

Missing EXIF provenance does not fail the run; it marks the entry `unverified`,
because an unverified entry must never be silently counted as a CCD reference.
Structural problems and hash mismatches do fail, because they mean the manifest
does not describe the files on disk.

Usage:
    python tests/verify_reference_set.py                       # validates the template
    python tests/verify_reference_set.py reference_set/manifest.json --root .
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

FAMILIES = ("indoor-flash", "night-flash", "daylight-aged", "daylight-clean")
ROLES = ("calibration", "holdout")
REQUIRED_ENTRY_KEYS = (
    "id",
    "family",
    "scene",
    "role",
    "camera_make",
    "camera_model",
    "iso",
    "flash",
    "source",
    "license",
    "source_sha256",
    "local_path",
)
MIN_PER_FAMILY = 4
REQUIRED_PER_FAMILY_HOLDOUT = 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _comparable(value: Any) -> Any:
    """Normalise a declared value so it can be compared with an EXIF value.

    Text tags differ only by spacing and case between cameras and manifests; numeric
    tags arrive as int, float or tuple depending on the writer. Comparing the raw
    values reported every real file as a mismatch.
    """
    if isinstance(value, str):
        text = " ".join(value.split())
        try:
            # Manifests store ISO and Flash as JSON strings; EXIF returns numbers.
            return round(float(text), 3)
        except ValueError:
            return text.casefold()
    if isinstance(value, (list, tuple)):
        return tuple(_comparable(item) for item in value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 3)
    return value


def _exif_facts(path: Path) -> dict[str, Any]:
    """Read the provenance tags a real camera writes in IFD0 and the Exif sub-IFD."""
    with Image.open(path) as image:
        exif = image.getexif()
        try:
            sub_ifd = dict(exif.get_ifd(0x8769))
        except (KeyError, ValueError, OSError):
            sub_ifd = {}

    def pick(tag: int) -> Any:
        value = exif.get(tag)
        # 0 is a real value for Flash ("did not fire"), so only None/"" may fall through.
        if value is None or value == "":
            value = sub_ifd.get(tag)
        return value

    return {
        "camera_make": pick(271),
        "camera_model": pick(272),
        "iso": pick(34855),
        "flash": pick(37385),
    }


def validate(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    status = manifest.get("status", "template")
    if status not in ("template", "filled", "partial"):
        errors.append({"scope": "manifest", "reason": f"unknown status {status!r}"})

    families = manifest.get("families")
    if not isinstance(families, list) or sorted(families) != sorted(FAMILIES):
        errors.append({"scope": "manifest", "reason": f"families must be exactly {list(FAMILIES)}"})

    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append({"scope": "manifest", "reason": "entries must be a non-empty list"})
        entries = []

    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append({"scope": f"entries[{index}]", "reason": "not an object"})
            continue
        missing = [key for key in REQUIRED_ENTRY_KEYS if key not in entry]
        entry_errors = [f"missing field {key}" for key in missing]
        entry_id = entry.get("id")
        label = entry_id or f"entries[{index}]"

        if not isinstance(entry_id, str) or not entry_id.strip():
            entry_errors.append("id must be a non-empty string")
        elif entry_id in seen_ids:
            entry_errors.append(f"duplicate id {entry_id!r}")
        else:
            seen_ids.add(entry_id)

        if entry.get("family") not in FAMILIES:
            entry_errors.append(f"family must be one of {list(FAMILIES)}")
        if entry.get("role") not in ROLES:
            entry_errors.append(f"role must be one of {list(ROLES)}")
        if not isinstance(entry.get("scene"), str) or not entry.get("scene", "").strip():
            entry_errors.append("scene must be a non-empty string")

        reasons: list[str] = []
        local_path = entry.get("local_path")
        recorded = entry.get("source_sha256")
        file_state = "absent"

        if local_path:
            path = Path(local_path)
            path = path if path.is_absolute() else root / path
            if path.is_file():
                file_state = "present"
                actual = _sha256(path)
                if not recorded:
                    reasons.append("source_sha256 missing")
                elif recorded != actual:
                    entry_errors.append(f"sha256 mismatch: recorded {recorded[:12]}… actual {actual[:12]}…")
                facts = _exif_facts(path)
                for key, value in facts.items():
                    # Flash 0 means "did not fire": present evidence, not a missing tag.
                    if value is None or value == "":
                        reasons.append(f"exif {key} missing")
                # Declared provenance must match the bytes, or the manifest is a claim
                # about a file it never saw. Only compared when both sides carry a value.
                for key in ("camera_make", "camera_model", "iso", "flash"):
                    declared = entry.get(key)
                    actual_value = facts.get(key)
                    if declared in (None, "") or actual_value in (None, ""):
                        continue
                    if _comparable(declared) != _comparable(actual_value):
                        entry_errors.append(
                            f"exif {key} mismatch: manifest {declared!r} vs file {actual_value!r}"
                        )
            else:
                if status == "filled":
                    entry_errors.append(f"local_path not found: {path}")
                else:
                    reasons.append("local_path not found (template)")
        elif status == "filled":
            # Without a path there is nothing to hash or compare, so the entry cannot be
            # evidence. A template placeholder stays merely unverified.
            entry_errors.append("local_path is required for a filled manifest")
        else:
            reasons.append("local_path missing (template)")

        for key in ("camera_make", "camera_model", "iso", "flash", "source", "license"):
            if entry.get(key) in (None, ""):
                reasons.append(f"{key} missing")
        if not entry.get("source_sha256"):
            reasons.append("source_sha256 missing")

        if entry_errors:
            entry_status = "error"
            errors.extend({"scope": label, "reason": reason} for reason in entry_errors)
        elif reasons:
            entry_status = "unverified"
        else:
            entry_status = "verified"

        results.append(
            {
                "id": label,
                "family": entry.get("family"),
                "role": entry.get("role"),
                "file_state": file_state,
                "status": entry_status,
                "reasons": entry_errors + reasons,
            }
        )

    counts = {"entries": len(results), "verified": 0, "unverified": 0, "error": 0}
    per_family = {family: {"entries": 0, "calibration": 0, "holdout": 0} for family in FAMILIES}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        family = item["family"]
        if family in per_family:
            per_family[family]["entries"] += 1
            if item["role"] in ROLES:
                per_family[family][item["role"]] += 1

    if status == "filled":
        for family, plan in per_family.items():
            if plan["entries"] < MIN_PER_FAMILY:
                errors.append(
                    {"scope": family, "reason": f"needs at least {MIN_PER_FAMILY} entries, has {plan['entries']}"}
                )
            if plan["holdout"] < REQUIRED_PER_FAMILY_HOLDOUT:
                errors.append(
                    {
                        "scope": family,
                        "reason": f"needs at least {REQUIRED_PER_FAMILY_HOLDOUT} holdout, has {plan['holdout']}",
                    }
                )
        if counts["unverified"]:
            errors.append(
                {
                    "scope": "manifest",
                    "reason": f"{counts['unverified']} entries are unverified; a filled manifest must be fully verified",
                }
            )

    if status == "partial":
        coverage = manifest.get("coverage")
        if not isinstance(coverage, dict):
            errors.append(
                {"scope": "manifest", "reason": "a partial manifest must declare per-family coverage"}
            )
        else:
            for family in FAMILIES:
                plan = coverage.get(family)
                if not isinstance(plan, dict):
                    errors.append(
                        {
                            "scope": family,
                            "reason": "coverage must name every family, including the missing ones",
                        }
                    )
                    continue
                actual = per_family[family]
                for key in ("calibration", "holdout"):
                    if plan.get(key) != actual[key]:
                        errors.append(
                            {
                                "scope": family,
                                "reason": f"coverage {key}={plan.get(key)!r} does not match entries ({actual[key]})",
                            }
                        )
        if counts["unverified"]:
            errors.append(
                {
                    "scope": "manifest",
                    "reason": f"{counts['unverified']} entries are unverified; a partial manifest may contain only verified entries",
                }
            )

    return {
        "manifest_status": status,
        "partial": status == "partial",
        "result": "fail" if errors else "pass",
        "counts": counts,
        "per_family": per_family,
        "coverage": manifest.get("coverage"),
        "errors": errors,
        "entries": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验参考集清单的字段、哈希与 EXIF 来源证据。")
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=Path("reference_set/manifest.template.json"),
        help="清单路径，默认 reference_set/manifest.template.json",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="相对 local_path 的基准目录，默认清单所在目录（reference_set/）",
    )
    parser.add_argument("--out", type=Path, help="把 JSON 报告写到文件")
    args = parser.parse_args(argv)

    manifest_path = args.manifest.resolve()
    if not manifest_path.is_file():
        print(json.dumps({"result": "fail", "errors": [{"scope": "manifest", "reason": f"not found: {manifest_path}"}]}, ensure_ascii=False), file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = args.root.resolve() if args.root else manifest_path.parent
    report = validate(manifest, root)
    report["manifest"] = str(manifest_path)
    report["root"] = str(root)

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)

    if report["result"] == "pass":
        unverified = report["counts"]["unverified"]
        print(
            f"[verify_reference_set] pass: {report['counts']['entries']} entries, {unverified} unverified",
            file=sys.stderr,
        )
        return 0
    print(f"[verify_reference_set] fail: {len(report['errors'])} problems", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
