# Changelog

This project follows Semantic Versioning.

## Unreleased — evidence semantics and reference wording

Tooling and documentation only: no pixel recipe change, one CLI constraint, and no `VERSION` bump, so the shipped bundle stays 1.6.0 until the next release.

- Reference reports choose their wording from the manifest's declared tier, and an input that failed validation can no longer borrow Tier A's language. `reference_note(tier, verified)` returns one of four texts, and the unverified one calls the numbers a descriptive measurement of unverified images. `--reference` now also requires `--manifest` and refuses a `status: "template"` manifest, so an arbitrary folder can no longer be reported as a CCD reference.
- Split evidence roles from evidence tiers. `calibration` and `holdout` are reserved for `evidence_tier: "A"`; Tier C web samples use `pilot` / `holdout_preview`. The validator rejects a Tier C calibration entry, a Tier A pilot entry, and any non-template entry without a tier. `reference_set/manifest.daylight.json` was migrated to `pilot` / `holdout_preview` with `evidence_tier: "C"`, and the template carries `evidence_tier: null` until a real frame replaces it.
- The validator reports `provenance_consistent` and explicitly `tier_a_claim: false`, with a note that matching fields, EXIF and hashes cannot prove a CCD sensor, an unedited frame or a same-scene comparison.
- Fix the display-size grain probe, which derived a fresh smooth-region mask for each phase and therefore compared different regions. `_scaled_probe()` builds one mask from the source at the 1600 px long edge and both phases reuse it.
- Correct the grain comparison published in 1.6.0. That bullet compared a native-pixel MAD with a resampled MAD and concluded the pipeline was 3.5–4.5× noisier. At the same 1600 px scale the ordering reverses: the reference pilot measures 0.393 / 0.426 / 0.494 L\* (medians for `daylight-clean`, `daylight-aged`, and the single `indoor-flash` frame) while the pipeline lands at 0.0155 / 0.237 / 0.181 / 0.046 (including `night-flash`). The pipeline is lighter, not heavier — and because the frames depict different content, neither figure calibrates the other.
- Reports now record `generated_at` (UTC) and `profiler_commit`, so a number can be traced to the instrument that produced it rather than to the version string it mentions.
- Documentation: the Tier C model list now matches the manifest (Nikon E990, Sony CYBERSHOT, Sony DSC-F828; the Canon samples kept no `Make`/`Model` and the DSC-F717 frames were excluded as in-camera ND/mono experiments), the presets are described as hand-tuned rather than calibrated, and 1.6.0 is stated to be a tooling release rather than the tone work that the four open defects still block.
- Tests grow from 81 to 90.

## 1.6.0 — 2026-11-20

Tooling, evidence and wording only. The pixel recipe, the CLI surface and the report schema are unchanged from 1.5.2, so images produced by 1.5.2 and 1.6.0 are identical.

- Add `tests/ccd_profile.py`, a CIELAB fingerprint of the shipped pipeline. It reports L\* percentiles, near-white, clipped channels, near-black, highlight and shadow a\*/b\*, centre and corner levels with their relative changes, and grain, grouped into per-family intervals. It never emits a composite score, and it refuses to call its output a baseline: every report carries `baseline: false` and the title `管线自检，非 CCD 基线`.
- Fix two instrument defects found while wiring it up. The grain probe now derives one mask from the source and reuses it for both phases; deriving a mask per phase compared different regions and produced changes no viewer could see. Guardrails now judge only what the step made worse: a source frame that arrives 22% blown and leaves 19% blown is reported, not condemned, while an increase in near-white or clipped channels still fails.
- Add `tests/verify_reference_set.py`, which validates a manifest's fields, SHA-256 values and EXIF provenance (`Make`, `Model`, `ISO`, `Flash`, read from IFD0 and the Exif sub-IFD). Missing provenance marks an entry `unverified`; a `filled` manifest with unverified entries, missing files, hash mismatches, fewer than four entries per family or no holdout fails.
- Add `reference_set/` with the tier rules (Tier A straight-out-of-camera CCD files only; B and C never enter an interval) and a 16-entry template: four families, three calibration frames and one holdout each. Every fact field is `null` until a real sample replaces it.
- Generate `docs/samples/pipeline-self-check.json` from the existing 15 licensed photographs to prove the tooling runs end to end. It is a pipeline self-check, not a CCD baseline, and the note in the report says so.
- Add `tests/ccd_ablate.py` and `python tests/ccd_profile.py --ablate <stage>`, which switch off exactly one stage (`s-curve`, `black-point`, `vignette`, `flash-falloff`, `halation`, `grain`, `sharpness`) and record what was zeroed. Ablation changes nothing in the bundle and cannot be mistaken for the production recipe. It is the instrument the gated tone work will use, so a difference is attributed rather than guessed.
- Add `tests/KNOWN_ISSUES.md` and `tests/test_known_issues.py`: four visible defects of the current recipe (fused top end, `indoor-flash` dimming the centre, median shift at restrained strength, grain crushing dark patches), each measured on synthetic fixtures and pinned by an expected failure. The suite stays green; a fix turns the test into an unexpected success, which is the prompt to retire the entry.
- Record one correction to the earlier diagnosis: the dark-patch crush is grain-driven, not the black point. With grain ablated the same patch stays at 0% near-black, so the fix belongs in the noise envelope.
- Suite grows from 45 to 59 tests, then to 67 with the ablation and known-issue regressions.
- Add `--reference` to `tests/ccd_profile.py`: it measures the source frames of a manifest without running the recipe, reports `before == after` with an empty delta, drops the guardrails and titles itself `CCD 参考区间（…）`. This is the only honest way to ask "what does a CCD frame measure like?" with the same code that measures the pipeline.
- Add `reference_set/manifest.daylight.json`, a Tier C pilot of 15 web samples from retro reviews of CCD-era compacts (PowerShot G2/Pro1, COOLPIX 990, Cyber-shot DSC-F828): 5 calibration + 2 holdout for `daylight-clean`, the same for `daylight-aged`, 1 frame for `indoor-flash` and none for `night-flash`. Of 115 downloaded samples only 25 retained `Make`/`Model`, and only 15 were usable, which is exactly why the coverage block is explicit instead of implied. Originals are gitignored and analysis-only; the manifest records the URL and the measured SHA-256.
- Record what the pilot actually shows: daylight CCD frames sit at L\* medians near 45 and 57, near-white reaching 14% and 6%, and the `daylight-clean` frames lose about 20% of centre luminance in the corners. The deficit is consistent with real in-camera falloff, but composition contributes as much as optics (`daylight-aged` measures corners brighter than centre), so it is not a per-body figure. It still cannot characterise flash or night, so presets stay gated and the report cannot be cited as a baseline.
- Allow `status: "partial"` in `tests/verify_reference_set.py`, but only with a per-family `coverage` block that must match the entries exactly and may not contain `unverified` entries. Fix a falsy bug that treated `Flash = 0` ("did not fire") as missing provenance, and default `--root` to the manifest's own directory so manifests under `reference_set/` resolve.
- Suite grows to 74 tests (reference mode, partial-manifest coverage, flash-zero provenance, and a guard that the shipped Tier C pilot still validates).
- Narrow the claims (P3). `SKILL.md` now forbids describing the result as restoring a specific camera, matching a real CCD sensor, or reaching camera-level accuracy, and states that the recipe has not been blind-tested against Tier A originals; `README.md` gains a "What this is not" block. No pixel, CLI or report change, so 1.5.2 kept its wording and the narrowed claims land in this release; the bundle is otherwise unchanged.

- Add `CCD_STRICT=1`, which removes the `expectedFailure` protection from the four known-issue regressions so they fail as ordinary tests; `tests/test_strict_switch.py` asserts both directions, so a green suite can no longer be read as "the look is validated while four defects are open". Suite grows to 76 tests.
- State the scope of the evidence where it can be read: `tests/KNOWN_ISSUES.md` now carries a per-preset table of reference frames (7 / 7 / 1 / 0 for `daylight-clean`, `daylight-aged`, `indoor-flash`, `night-flash`), and both it and `README.md` say plainly that a green suite means the pipeline and its contract are intact, not that any preset matches a family interval. No pixel, CLI or bundle change.
- Extract the unsharp mask into `sharpness_parameters()` and `apply_sharpness()` so the file pipeline and the measurement harness share one implementation instead of drifting copies; output pixels are unchanged (max |Δ| 0 against the pre-refactor build). Pin the sRGB profile's header timestamp: `ImageCms` stamps a creation date into the ICC header, so two runs over the same input produced identical pixels and different PNG bytes. Repeated runs are now byte-identical.
- The fingerprint now applies the production unsharp mask. Before this it measured a pipeline that never ships, and `--ablate sharpness` returned identical numbers, so a no-op could be read as evidence.
- Report grain at a common display size as well as at native pixels (`flat_noise_scaled`, area-resampled to a 1600 px long edge). Native-pixel noise is not comparable between a 2 MP compact and a 24 MP phone; frames smaller than the reference edge report `null` rather than being upsampled.
- Aggregate intervals by family **and** role: `calibration` is the only role a change may be justified against, `holdout` is acceptance evidence, and the two are never pooled. A family the manifest declares but no image covers is listed as `absent` instead of disappearing from the report.
- Title reference reports after the source they measured (`源图区间测量：<label>`), so a run over an arbitrary folder can no longer borrow the Tier C pilot's title.
- Make the validator compare declared `Make`/`Model`/`ISO`/`Flash` with the file's EXIF, and treat a `filled` entry without `local_path` as an error. This immediately caught 13 pilot entries that recorded marketing names (`COOLPIX 990`, `CYBERSHOT (DSC-F717)`) instead of the EXIF `Model` (`E990`, `CYBERSHOT`); the manifest was corrected to the bytes.
- Regenerate both evidence files with the corrected instrument. One comparison the pilot now supports: its daylight frames carry about 0.4 L\* of grain at a 1600 px display size while this pipeline's output carries 1.6–1.8 L\*, so the shipped grain is several times heavier than those bodies. Recorded, not acted on — the recipe stays frozen until Tier A frames exist. Suite grows to 81 tests.

## 1.5.2 — 2026-11-19

- Make skip and no-output wording explicit, uniform and testable. A skipped file reads `已跳过：<原因>；未生成输出文件。…`; no code path describes a skip as success.
- An empty folder, or one holding only non-photo files, now reports `nothing_processed` with `目录中没有可处理照片。` instead of raising a generic "no files" error, so the four batch statuses cover every outcome.
- An all-skipped folder reports `未生成输出：N 个文件均因格式不受支持而被跳过。`; a folder with no output but mixed skips and failures reports both counts. Failure wording stays reserved for files that actually failed.
- The batch `notice` with skips reads `已跳过 N 个文件：当前环境不支持这些格式；未生成对应输出文件。`
- Align `SKILL.md`, `references/image-pipeline.md` and `README.md` with the wording rules; the suite grows from 41 to 45 tests (empty folder, all-skipped wording, single skip reason, partial-skip notice).

## 1.5.1 — 2026-11-19

- Close the batch status model. `processed` means every file succeeded (exit 0), `processed_with_skips` means explicit skips but no failures (exit 0), `partially_processed` means at least one failure (exit 1), and `nothing_processed` means no image was produced at all (exit 2). Skips are therefore neither failures nor silent successes, and an all-HEIC folder can no longer report success.
- Add `--skip-unsupported`: undecodable files (HEIC/HEIF) are recorded as `skipped` with a `reason` instead of `not_processed` with an `error`. The report gains `skipped_files` and a `notice` line.
- Single-file HEIC stays explicit: with `--skip-unsupported` it reports `skipped` and `image_written: false`, and still exits 2 because no image was written.
- Describe the flag, the four statuses and the exit-code mapping in `SKILL.md`, `references/image-pipeline.md` and `README.md`.
- Add three batch skip/single-skip regressions, bringing the suite to 41 tests.

## 1.5.0 — 2026-11-18

- Add non-recursive directory batch processing with a required, separate output directory, per-image JSON reports, collision-safe names and explicit all/partial/no-success exit codes.
- Preserve the single-image default strength of 50 for reproducibility while changing the quick-start recommendation to 75 for a clearly visible first result.
- Add five batch/default-contract regressions, bringing the suite to 38 tests, and declare the bundle as agent-created for standard skill packaging.

## 1.4.1 — 2026-11-13

- Build halation from a quarter-resolution source and upsample one shared 8-bit glow map. This removes full-frame float32 RGB/luma/mask intermediates and keeps interpolation continuous across tile boundaries.
- Replace direct-multiplication flash lift with a bounded quadratic lift, preventing new saturated-channel clipping. Raise indoor/night flash coefficients to 0.18/0.22 so the existing strength-80 preset-separation targets remain meaningful without weakening the tests.
- Add dedicated regressions for warm localized halation, tile-seam continuity, black-point behaviour and saturated-colour flash lift. The suite now contains 33 tests.
- Correct stale sample counts, strength descriptions and real-photo documentation.
- Remove a dead branch in the flash-falloff stage (`np.clip(falloff, -1, 0)` was always zero, so the "edge darkening" multiply never ran and its comment was misleading).
- Correct the README separation figures, which still said ~1.6–1.8/255 at strength 50 and ≥2.4/255 at strength 80 while the code, tests and preset reference all say 2.2–2.3 and ≥3.4.
- Regenerate all five sample composites with 1.4.1 and replace the self-referential halation test (it re-implemented the algorithm) with an independent tile-seam assertion.
- Add a repeatable offline real-photo evaluator with 15 licensed photographs, 30 CLI runs, source hashes, per-image comparisons, an overview and JSON metrics. Record the low-key portrait's near-black increase as a visual-review warning rather than changing the calibrated presets.

## 1.4.0 — 2026-11-13

The previous release was criticised for producing before/after pairs that were hard to tell apart. Root cause: grain was effectively invisible (sigma 0.014), the vignette was capped at 20%, and nothing else carried a recognisable "small sensor" signature.

- Add **halation** (warm bloom around blown highlights) and **flash falloff** (centre-weighted lift of shadows and midtones with darker edges). Both are asymptotic, so neither can push pixels past 1.0 or create a white plateau.
- Add a **black-point toe** so shadows deepen instead of staying milky.
- Raise grain roughly 4x (indoor 0.014 → 0.055, night 0.045 → 0.075), raise the vignette cap from 20% to 45%, and strengthen the warm-highlight / cool-shadow split.
- Retune all four presets for a clearly visible result at strength 75-85. Measured mean absolute pixel change on real photos: 15.4/255 (portrait), 14.6/255 (landscape), 19.0/255 (night).
- Re-verify the earlier safety bounds after strengthening: 205 grey stays at 217-229 instead of clipping, longest flat highlight shelf is 5-9 levels (not 26-42), skin patch at strength 50 moves `+11R/+5G/+1B`, preset separation at strength 80 rises to ≥3.4/255.
- Add `docs/samples/detail-100-percent.jpg` because per-pixel grain is invisible once a 1600 px photo is scaled down for a web page.
- Update the vignette (5-45%), clipping (205 grey), separation (≥3.4) and shelf (≤10) test bounds to the new calibration.

## 1.3.1 — 2026-11-13

- Reduce `indoor-flash` saturation (0.12 → 0.06) and lift its blue highlight gain (0.982 → 0.992). On a real portrait the strength-100 skin shift improves from `+11R/+4G/−13B` to `+9R/+4G/−8B`, and preset separation at strength 80 rises from 2.48 to 2.76/255 on the calibration fixture.
- Add `docs/samples/` with three real-photo before/after pairs (indoor portrait, daylight landscape, night city) and a 50/75/100 strength ladder, plus source and Pexels License notes. The photos are resized for layout only; the "after" halves are CLI output.

## 1.3.0 — 2026-11-13

- Replace linear contrast with an endpoint-pinned S-curve and replace the saturating exponential shoulder with a "lift toward white" gain. Longest flat highlight shelf drops from 27 to 8 output levels at strength 100 (5 at strength 50) and the top of the range still reaches 255.
- Add a regression that measures the longest same-value run across a 150–255 gradient (≤6 levels at 50, ≤9 at 100) instead of only checking monotonicity.
- Add a second photo-like fixture (sky, ground, subject blob, specular) and assert preset separation at strength 80 (≥2.3/255 calibration, ≥2.5/255 photo-like). Document that the default strength 50 is intentionally subtle (~1.6–1.8/255) and that strength 70–90 is needed for obvious preset character.
- Shorten the skill `description` to two sentences so directory listings do not truncate the routing triggers.
- Add `git` repository metadata support (`.gitignore`, initial commit) so the bundle can be published and installed with `npx skills add`.

## 1.2.0 — 2026-11-09

- Disable optimized JPEG Huffman encoding to avoid libjpeg failures on high-entropy photos; add high-entropy JPEG regression fixtures.
- Replace the direct-flash hard boost with a soft shoulder and a bounded source-near-white clip; add checks for mid-gray whitening and clipping ratios.
- Retune flash/CCD presets for lower skin warmth, visible night/indoor vignette on dark backgrounds, and color/tone distinction with grain disabled.
- Add synthetic skin, dark-background, highlight-gradient, no-grain pairwise and monotonic-shoulder assertions.
- Raise the default pixel ceiling to 60 MP, add `--max-pixels`, and improve over-limit guidance without resizing input.
- Add `--preview` to compute and report pixel metrics without writing an image.
- Normalize sharpening radius to image size; document the remaining resolution dependence of pixel-sized grain.
- Move the discoverable skill to `skills/ccd-photo-enhancer/`; add MIT license, pinned test requirements, and Windows/Linux CI.
- Make test scratch selection fall back from an unwritable bundle directory to a user temp location and print the selected path.

Real-photo before/after examples are not included in this release; they require an authorized photographic sample and human visual review.
