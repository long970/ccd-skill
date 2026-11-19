# Reference set

This directory holds a **plan** for collecting reference photos, not the photos themselves and not a baseline. The 16 entries in [manifest.template.json](manifest.template.json) are placeholders: every fact field is `null`, and the validator reports all of them as `unverified`. Nothing in this repository may be described as a "CCD baseline" until a manifest is filled, validated, and the samples are actually CCD output.

## Why a reference set

The pipeline currently has engineering targets (deterministic output, no clipping regressions, batch safety) but no verifiable visual target. Adding more grain or more vignette by intuition is how a preset drifts away from the look it claims to reproduce. A reference set gives each family a measured interval to aim at, and a holdout to check that the aim generalises.

## Tiers

| Tier | What it is | Used for |
| --- | --- | --- |
| A | Original straight-out-of-camera file from a CCD compact, EXIF `Make`/`Model`/`ISO`/`Flash` intact | The only tier allowed in calibration or holdout intervals |
| B | Phone photo of the same scene, taken at the same time | Sanity comparison only; never enters an interval |
| C | Stock or web photos | Pipeline self-check inputs only; never enters an interval |

Tier A is the hard requirement. A web image that "looks CCD" is Tier C no matter how convincing it is, because its tone curve has already been through an unknown editor, a resizer and often a re-encoder.

What disqualifies an otherwise usable file:

- Re-exported by a messaging app, social platform or screenshot tool (dimensions, EXIF and sharpening all change).
- Resized or cropped by an editor; a 4MP compact frame resized to 12MP no longer carries the original grain scale.
- EXIF stripped. Without `Make`/`Model` the file cannot be attributed, and without `ISO`/`Flash` the exposure conditions are unknown.
- Heavy in-camera processing that the user cannot describe (some compacts apply "vivid" or "soft skin" modes).

## The 16-entry pilot

Four families, four entries each: three `calibration` plus one `holdout`. The holdout frame is never used while tuning; it exists to catch a change that fits the calibration frames and nothing else.

| Family | Scenes |
| --- | --- |
| `indoor-flash` | close-up portrait, group of three or more, low-light mixed tungsten, backlit interior |
| `night-flash` | subject with direct flash, neon street, rain-soaked reflection, subject on a dark background |
| `daylight-aged` | backlit daylight, overcast street, high-contrast street, contrasty landscape |
| `daylight-clean` | high-key studio, window light, low-contrast interior, even outdoor daylight |

The high-key studio entry is mandatory: a previous tuning pass flattened its near-white end, and only a frame that starts bright enough will catch a repeat.

When expanding to 30–40 entries, keep whole camera models out of calibration so the holdout tests a body the tuning never saw, not just a new frame from a known body.

## Required fields

`id`, `family`, `scene`, `role`, `camera_make`, `camera_model`, `iso`, `flash`, `source`, `license`, `source_sha256`, `local_path`.

- `source` says where the file came from (camera and date, or a URL); `license` says whether it may be committed. Do not commit a file you cannot license.
- `source_sha256` pins the exact bytes. Update it whenever the file is replaced, otherwise the validator fails, which is the point.
- `local_path` may live outside the repository. Only commit files whose license allows it; a manifest with external paths and hashes is still reproducible for the person who holds the originals.

## Fill and validate

1. Copy the template to `reference_set/manifest.json` and set `status` to `filled`.
2. Fill one entry at a time; compute `source_sha256` from the file you actually measured.
3. Validate:

   ```text
   python tests/verify_reference_set.py reference_set/manifest.json --root .
   ```

   Exit 0 means the structure is coherent. `unverified` entries are reported but do not fail a template; a `filled` manifest with any unverified entry, a missing file, a hash mismatch, fewer than four entries per family or no holdout fails.

4. Only then measure: `python tests/ccd_profile.py --manifest reference_set/manifest.json`.

## What this can and cannot support

Supported once Tier A samples exist: per-family intervals for L\* distribution, highlight and shadow chroma, corner/centre balance, and grain; a holdout check that a recipe change generalises.

Not supported by any amount of manifest work:

- Claiming the output matches a specific camera model. The presets are `CCD-inspired`, not a sensor or firmware simulation.
- Replacing a blind comparison. Intervals say "this family sits here"; they cannot say "this looks like a CCD to a viewer".
- Inferring a CCD response from phone or stock photos. Different optics, sensor size, demosaic and in-camera processing.

## Privacy

Tier A photos are often personal. Keep paths and hashes, commit files only with the subject's and photographer's permission, and prefer a local-only manifest if the frames show identifiable people.
