# Reference set

This directory holds a **plan** for collecting reference photos, not the photos themselves and not a baseline. The 16 entries in [manifest.template.json](manifest.template.json) are placeholders: every fact field is `null`, and the validator reports all of them as `unverified`. [manifest.daylight.json](manifest.daylight.json) is a smaller Tier C pilot filled from web samples; it is descriptive evidence only, never a calibration target. Nothing in this repository may be described as a "CCD baseline" until a manifest is filled with Tier A samples, validated, and actually measured.

## Why a reference set

The pipeline currently has engineering targets (deterministic output, no clipping regressions, batch safety) but no verifiable visual target. Adding more grain or more vignette by intuition is how a preset drifts away from the look it claims to reproduce. A reference set gives each family a measured interval to aim at, and a holdout to check that the aim generalises.

## Tiers

| Tier | What it is | Used for |
| --- | --- | --- |
| A | Original straight-out-of-camera file from a CCD compact, EXIF `Make`/`Model`/`ISO`/`Flash` intact | The only tier allowed in calibration or holdout intervals |
| B | Phone photo of the same scene, taken at the same time | Sanity comparison only; never enters an interval |
| C | Stock or web photos | Pipeline self-check inputs only; never enters a calibration interval (see the Tier C daylight pilot below) |

Tier A is the hard requirement. A web image that "looks CCD" is Tier C no matter how convincing it is, because its tone curve has already been through an unknown editor, a resizer and often a re-encoder.

## Tier C daylight pilot

`manifest.daylight.json` holds 15 entries measured from web samples. It exists to prove the tooling end to end and to record what daylight CCD frames measure like — it is not a baseline and it must not steer the presets.

Where the frames come from: the retro reviews on cameralabs.com of CCD-era compacts (Canon PowerShot G2 and Pro1, Nikon COOLPIX 990, Sony Cyber-shot DSC-F828). Every sample image in those reviews was downloaded (115 files); only 25 kept `Make`/`Model`, and of those 15 were native-resolution, non-duplicate frames usable here. Coverage is unresolved by construction:

| Family | Calibration | Holdout | Status |
| --- | --- | --- | --- |
| `daylight-clean` | 5 | 2 | `pilot` |
| `daylight-aged` | 5 | 2 | `pilot` |
| `indoor-flash` | 1 | 0 | `insufficient` |
| `night-flash` | 0 | 0 | `missing` |

Only one frame carries "flash fired" and none is a night scene, so the two flash families cannot be characterised from this source at all. The scenes are also narrow: mostly Brighton seafront, street and shopfront daylight from one reviewer's shoot.

Licensing: the sample files are the publisher's, so they are analysis-only. The originals live under `reference_set/originals/` (gitignored), the manifest records the source URL and the SHA-256 of the exact bytes measured, and nothing is redistributed.

Because the bytes are not redistributed, nobody can recompute these numbers from the repository alone: they would have to re-download from the recorded URLs and verify the hashes, and if a publisher later replaces or removes an image the pilot stops being reproducible. That is acceptable only because the pilot is descriptive — no claim, preset or release depends on it. If it ever becomes a calibration target, the frames need a licence that allows redistribution, or a Tier A replacement.

Measure it without running the recipe:

```text
python tests/ccd_profile.py --manifest reference_set/manifest.daylight.json --reference --out docs/samples/ccd-reference-daylight.json
```

What this pilot supports: that the reference path works end to end; that these daylight CCD frames sit at L\* medians around 45 (`daylight-clean`) and 57 (`daylight-aged`), with near-white reaching 14% and 6% respectively; and that the `daylight-clean` frames lose roughly 20% of centre luminance in the corners. That deficit is consistent with a real in-camera falloff, but scene composition contributes to it as much as optics — the `daylight-aged` frames measure corners *brighter* than centre because their sky is at the edges — so it is not a per-body measurement and cannot be read as "this camera vignettes by 20%".

What it cannot support: any statement about flash behaviour, night behaviour, a specific camera body, or a population of CCD output. One reviewer's daylight shoot with unknown in-camera settings is a sample of convenience. Because of that, the presets stay untuned until Tier A frames arrive, and no result measured here may be described as "matching CCD".

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
- `local_path` may live outside the repository. Only commit files whose license allows it; a manifest with external paths and hashes is still reproducible for the person who holds the originals. A `filled` entry without a path is an error: there would be nothing to hash or compare.
- `camera_make`, `camera_model`, `iso` and `flash` must equal the file's EXIF values, not the marketing name. A Cyber-shot that writes `CYBERSHOT` in `Model` must be recorded as `CYBERSHOT`; `COOLPIX 990` was the box name, while the file says `E990`. The validator compares them and fails the entry on a mismatch, because otherwise the manifest describes a file it never saw. Text comparison ignores case and spacing; `ISO`/`Flash` are compared numerically, so `"100"` and `100` agree.

## Fill and validate

1. Copy the template to `reference_set/manifest.json` and set `status` to `filled`.
2. Fill one entry at a time; compute `source_sha256` from the file you actually measured.
3. Validate:

   ```text
   python tests/verify_reference_set.py reference_set/manifest.json
   ```

   Exit 0 means the structure is coherent. `unverified` entries are reported but do not fail a template; a `filled` manifest with any unverified entry, a missing file, a missing `local_path`, a hash mismatch, an EXIF value that disagrees with the file, fewer than four entries per family or no holdout fails.

4. Only then measure: `python tests/ccd_profile.py --manifest reference_set/manifest.json`.

Intervals are aggregated per family **and per role**: `calibration` frames are the only ones a change may be justified against, and `holdout` frames are acceptance evidence. The report never pools them, so a preset cannot be tuned on the frames that then certify it. Grain is reported both at native pixels and after area-resampling to a 1600 px long edge, because native-pixel noise is not comparable between a 2 MP compact and a 24 MP phone.

## What this can and cannot support

Supported once Tier A samples exist: per-family intervals for L\* distribution, highlight and shadow chroma, corner/centre balance, and grain; a holdout check that a recipe change generalises.

Not supported by any amount of manifest work:

- Claiming the output matches a specific camera model. The presets are `CCD-inspired`, not a sensor or firmware simulation.
- Replacing a blind comparison. Intervals say "this family sits here"; they cannot say "this looks like a CCD to a viewer".
- Inferring a CCD response from phone or stock photos. Different optics, sensor size, demosaic and in-camera processing.

## Privacy

Tier A photos are often personal. Keep paths and hashes, commit files only with the subject's and photographer's permission, and prefer a local-only manifest if the frames show identifiable people.
