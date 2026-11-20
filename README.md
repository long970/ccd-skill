# CCD Photo Enhancer

[![tests](https://github.com/long970/ccd-skill/actions/workflows/tests.yml/badge.svg)](https://github.com/long970/ccd-skill/actions/workflows/tests.yml)
[![release](https://img.shields.io/github/v/release/long970/ccd-skill?display_name=tag)](https://github.com/long970/ccd-skill/releases)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Turn existing photos into a repeatable early compact-digital-camera look — locally, without uploads or generative reinterpretation.**

CCD Photo Enhancer is a local-first Agent Skill for CCD, Y2K and retro digicam styling. It provides four calibrated presets, deterministic Pillow/NumPy processing, single-image and folder workflows, and strict source-file protection. It is a visual approximation, not a physical simulation of a specific CCD sensor.

**What this is not.** Not a profile of a specific camera model, not a sensor simulation, and not a validated match to real CCD output: no Tier A original (a straight-out-of-camera CCD file) has been compared against it yet. The four presets are design choices explained in [references/ccd-presets.md](skills/ccd-photo-enhancer/references/ccd-presets.md), so "CCD look" here means "it reads as an early compact camera", not "it matches camera X". The skill is also not a film-stock emulation, a restoration tool, or a face/skin protector — L2 has no face or skin mask.

## Why this Skill

- **Private by design.** Photos are processed locally. The CLI makes no network requests and does not upload images.
- **Repeatable.** The same image, parameters, seed and dependency versions produce the same pixels.
- **Non-destructive.** Outputs are new files; existing files and source photos are never overwritten.
- **Useful at collection scale.** Batch mode processes a folder level and reports every success or failure.
- **Clear about its limits.** No face detection, semantic retouching, real flash-shadow reconstruction or claimed camera-model matching.

## At a Glance

| | |
|---|---|
| **Current release** | [v1.6.0](https://github.com/long970/ccd-skill/releases/tag/v1.6.0) |
| **Input** | Static JPEG, PNG and WebP |
| **Output** | New JPEG, PNG or WebP; orientation and dimensions preserved |
| **Presets** | `daylight-clean`, `daylight-aged`, `indoor-flash`, `night-flash` |
| **Workflows** | Single image, metric-only preview, non-recursive folder batch |
| **Runtime** | Python 3.12 with Pillow and NumPy |
| **Tested on** | Ubuntu and Windows through GitHub Actions |
| **License** | MIT |

## Install

### Requirements

- Python 3.12
- [Pillow and NumPy](requirements.txt)
- Node.js 22.20+ only when using the Skills CLI

The processor never installs dependencies. Install them explicitly:

```text
python -m pip install -r requirements.txt
```

### Skills CLI

Install the public GitHub bundle with:

```text
npx skills add long970/ccd-skill --skill ccd-photo-enhancer
```

The Skills CLI installs the Skill files; it does not install the Python runtime dependencies.

### Manual or archive install

Download `ccd-photo-enhancer.zip` from [GitHub Releases](https://github.com/long970/ccd-skill/releases/latest), extract it, and place the `ccd-photo-enhancer` directory in your agent's Skill directory. Alternatively, clone this repository and point the agent at `skills/ccd-photo-enhancer/`.

skills.sh is an external directory. Its website listing and audit metadata are updated asynchronously after the registry indexes this public repository; installation does not depend on the website page being present.

## Quick Start

The commands below use the repository layout. If the Skill is already installed, replace `skills/ccd-photo-enhancer/` with its installed directory.

```bash
# A clearly visible CCD treatment
python skills/ccd-photo-enhancer/scripts/apply_ccd.py photo.jpg \
  --preset daylight-aged --strength 75 --seed 0

# Indoor flash look with reduced grain
python skills/ccd-photo-enhancer/scripts/apply_ccd.py portrait.png \
  --preset indoor-flash --strength 75 --grain-strength 10 --out portrait-ccd.png
```

Every successful run prints a JSON report with the resolved output path, preset, strength, seed, dimensions, clipping metrics and warnings.

### Batch a folder

Create an output directory that is separate from the input directory, then run:

```bash
python skills/ccd-photo-enhancer/scripts/apply_ccd.py photos \
  --batch \
  --preset daylight-aged \
  --strength 75 \
  --seed 7 \
  --out ccd-output
```

Batch mode:

- reads only the first directory level;
- requires an existing `--out` directory different from the input directory;
- uses the explicit seed for each source image;
- emits one JSON summary with every per-image report;
- never writes generated files back into the source directory.

| Exit code | Status | Meaning |
|---:|---|---|
| `0` | `processed` | Every photo was processed |
| `0` | `processed_with_skips` | Photos were processed; some files were explicitly skipped |
| `1` | `partially_processed` | At least one photo failed; per-image reasons are listed |
| `2` | `nothing_processed` | No output was produced: the folder was empty, every file was skipped, or every file failed |

Pass `--skip-unsupported` to record undecodable files (HEIC/HEIF) as `skipped` with a `reason` instead of failing the batch. Skips are counted in `skipped_files` and reported in `notice`; they are not successes, and an all-HEIC folder still exits 2.

Wording is part of the contract, because "no output" is not "failure" and a skip is not a success:

- single file skipped: `已跳过：当前环境不支持 HEIC/HEIF；未生成输出文件。…`, exit 2;
- folder with only skipped files: `未生成输出：N 个文件均因格式不受支持而被跳过。`, exit 2;
- empty folder: `目录中没有可处理照片。`, `nothing_processed`, exit 2;
- folder with real failures: counts and reasons are reported, and only then is the word 失败 used.


Batch mode does not support `--preview`. Preview one representative image first.

### Preview without writing

```bash
python skills/ccd-photo-enhancer/scripts/apply_ccd.py photo.jpg \
  --preset night-flash --strength 50 --preview
```

`--preview` returns in-memory metrics and writes no image. Metrics are measured before JPEG encoding and do not replace viewing the saved result.

## Presets

| Preset | Look | Best for |
|---|---|---|
| `daylight-clean` | Light digital saturation, gentle S-curve, subtle grain and vignette | Daylight portraits, streets, travel |
| `daylight-aged` | Warmer daylight colour, compressed highlights, visible grain and vignette | “Old digital camera” or lightly aged photos |
| `indoor-flash` | Centre-weighted lift, darker edges, warm highlight bloom and visible grain | Indoor parties and close-range snapshots |
| `night-flash` | Cool shadows, warm highlights, strong vignette, grain and deep blacks | Photos that are already shot at night |

The CLI default is strength `50`, which remains intentionally restrained and backwards-compatible. Start at **75–85** when the preset character should be obvious on first viewing. Inspect portraits for warmer skin and deeper shadows at high strength.

Individual sub-effects can be adjusted with `--grain-strength`, `--color-strength`, `--vignette-strength` and `--sharpness-strength`.

## Samples

Real photographs processed with the shipped CLI at `--seed 7`. Each image shows the source on the left and the result on the right. Sources and licensing: [docs/samples/README.md](docs/samples/README.md).

![Indoor portrait, indoor-flash strength 80](docs/samples/indoor-portrait.jpg)

![Daylight landscape, daylight-aged strength 75](docs/samples/daylight-landscape.jpg)

![Night city, night-flash strength 80](docs/samples/night-city.jpg)

Strength ladder on the same portrait at 50 / 75 / 100:

![Strength ladder 50 75 100](docs/samples/strength-ladder.jpg)

Per-pixel grain disappears when a 1600 px photo is scaled down for a web page. This is the same indoor portrait at a 100% crop:

![100% crop before and after](docs/samples/detail-100-percent.jpg)

The samples demonstrate the shipped pipeline on real photos. They do not prove that the result matches a particular CCD model.

### Real-photo evaluation

The offline evaluation covers 15 licensed photographs and 30 runs at restrained and recommended strengths, including low-key and high-key portraits, groups, indoor events, backlight, landscapes, neon and rainy nights. The licensed source files are not committed to this repository; place them at the paths in `tests/real-photo-manifest.json` before running the offline evaluator.

```text
python tests/real_photo_eval.py
```

Results are recorded in the [30-run overview](docs/samples/real-evaluation-overview.jpg) and [JSON report](docs/samples/real-evaluation.json). The current mean absolute pixel change is 11.1/255, with a maximum post-processing near-white ratio of 0.12%. These are technical alerts, not proof of CCD authenticity or aesthetic quality.

### Pipeline self-check (not a CCD baseline)

`tests/ccd_profile.py` measures the tone and colour fingerprint of the shipped pipeline in CIELAB: L\* percentiles, near-white, clipped channels, near-black, highlight and shadow a\*/b\*, centre and corner levels with their relative changes, and grain measured on one smooth-region mask reused for both phases. It runs the production unsharp mask as well as the recipe, so it never describes a pipeline that does not ship. Grain is reported twice: at native pixels, and after area-resampling to a 1600 px long edge, because the same grain spans different pixel counts on a 2 MP compact and a 24 MP phone. It reports per-family intervals, split by `calibration` and `holdout`, and never collapses them into a score: a single number would hide the per-family differences (corner/centre balance, highlight handling, black level) that matter, and pooling the two roles would let a change look justified by the frames it was tuned on.

```text
python tests/ccd_profile.py --manifest tests/real-photo-manifest.json --out docs/samples/pipeline-self-check.json
```

The generated [report](docs/samples/pipeline-self-check.json) is titled `管线自检，非 CCD 基线` and carries `baseline: false`. Its inputs are licensed stock photographs, not verified CCD output, so it describes what the pipeline does — not what a CCD camera does. Guardrails only flag what the step made worse: an increase in near-white or clipped channels, or a corner drop above 45%. A frame that arrives 22% blown and leaves 19% blown is reported, not condemned.

`--ablate <stage>` switches off exactly one stage (`s-curve`, `black-point`, `vignette`, `flash-falloff`, `halation`, `grain`, `sharpness`) so a difference can be attributed instead of guessed; the report records what was zeroed and is marked as an ablation, so it can never pass as the production recipe.

```text
python tests/ccd_profile.py --manifest tests/real-photo-manifest.json --ablate vignette
```

`--reference` is the opposite switch: it measures a manifest of source frames without running the recipe, so the numbers describe the camera instead of this pipeline. Such a report carries `reference: true`, no guardrails, and a title that names the source it actually measured (`源图区间测量：<label>`), so a run over an unrelated folder cannot borrow the pilot's name.

```text
python tests/ccd_profile.py --manifest reference_set/manifest.daylight.json --reference --out docs/samples/ccd-reference-daylight.json
```

That manifest is a **Tier C pilot**: 15 web samples from retro reviews of CCD-era compacts (Canon PowerShot G2/Pro1, Nikon COOLPIX 990, Sony Cyber-shot DSC-F828), kept only where the original EXIF `Make`/`Model` and native resolution survived. Coverage is daylight only — one frame records "flash fired" and none is a night scene — so `indoor-flash` is marked `insufficient` and `night-flash` `missing`. The [generated report](docs/samples/ccd-reference-daylight.json) is descriptive evidence, not a tuning target: no preset may be changed against it, and its corner/centre numbers mix lens falloff with scene composition. One comparison it does support is grain at a common display size: the pilot's frames carry roughly 0.4 L\* while this pipeline's output carries 1.6–1.8 L\*, so the shipped grain is several times heavier than these bodies. That is recorded, not acted on — the recipe stays frozen until Tier A frames exist. See [reference_set/README.md](reference_set/README.md#tier-c-daylight-pilot) for provenance and limits.

The recipe currently has four visible defects — a fused top end, `indoor-flash` dimming the centre, a median shift at restrained strength, and grain crushing dark patches. They are documented with measurements in [tests/KNOWN_ISSUES.md](tests/KNOWN_ISSUES.md) and pinned by `tests/test_known_issues.py`, which is written to fail on purpose (four expected failures) until reference intervals exist. When a fix lands, the test turns red as an unexpected success and the entry is retired.

A green suite therefore means the pipeline and its output contract are intact, **not** that the look is correct: no preset is compared against a family interval, `indoor-flash` has one reference frame and `night-flash` has none. `CCD_STRICT=1` converts the four expected failures into ordinary failures, so an unfixed defect cannot be reported as a passing suite (see [tests/KNOWN_ISSUES.md](tests/KNOWN_ISSUES.md#what-a-green-suite-does-and-does-not-mean)).

`tests/verify_reference_set.py` validates the reference-set manifest before anyone treats its numbers as evidence. It checks the declarative fields, recorded SHA-256 values against local files, and EXIF provenance (`Make`, `Model`, `ISO`, `Flash`, read from IFD0 and the Exif sub-IFD). Declared values must match the file: a manifest that records a marketing name instead of the EXIF `Model`, or a different ISO, is an error rather than a verified entry. Missing provenance marks an entry `unverified` rather than failing, but a `filled` manifest must be fully verified, with a `local_path` on every entry, at least four entries and one holdout per family.

```text
python tests/verify_reference_set.py                      # validates the template
python tests/verify_reference_set.py reference_set/manifest.json
```

The 16-entry [template](reference_set/manifest.template.json) is a plan, not data: every fact field is `null` until a Tier A sample (an original straight-out-of-camera CCD file with intact EXIF) replaces it. See [reference_set/README.md](reference_set/README.md) for the tier rules.


## How It Works

The default path is **L2 local deterministic pixel processing**: colour curves, highlight roll-off, halation, flash falloff, black-point adjustment, vignette, grain and sharpening. The script does not use a generative model, move objects, crop or resize.

The Skill also has two non-default routes:

- **L1 generative editing** for semantic or medium-changing work such as ink painting, only when an authorized editor is available.
- **L3 prompt-only fallback** when no suitable local or generative backend exists. No image is changed in this route.

CCD presets always use the local pixel pipeline.

## Privacy and Safety

- No network access and no image uploads in the local pipeline.
- EXIF/GPS metadata is not copied to outputs.
- Inputs are never overwritten; existing output names receive a numbered suffix.
- Output dimensions and display orientation are preserved.
- Transparent inputs stay transparent; flattening to JPEG without consent is rejected.
- Failed output verification removes the incomplete file created by that run.
- Unsupported formats, corrupt ICC profiles and over-limit images fail explicitly instead of being guessed or silently resized.

### Supported limits

- Static JPEG, PNG and WebP only.
- HEIC/HEIF cannot be decoded here. Single images fail explicitly; batch mode fails them by default, or records them as `skipped` with `--skip-unsupported`.
- Animation, floating-point rasters and unsupported ICC profiles fail explicitly.
- The default pixel ceiling is 60 MP and can be lowered with `--max-pixels`; images above the limit are not automatically resized.
- JPEG output uses quality 94, 4:4:4 chroma sampling and `optimize=False`.

## Reproducibility

The JSON report records the parameters, seed, dependency versions, orientation-corrected size, output format, clipping metrics and warnings. Identical input, parameters, seed and library versions are reproducible for the same image dimensions. Cross-version byte output may differ, and pixel-sized grain changes apparent size when the image is resized.

## Verification

```text
python -m unittest discover -s tests -v
CCD_STRICT=1 python -m unittest discover -s tests   # must fail while the four defects exist
```

- 81 automated tests cover orientation and EXIF removal, alpha preservation, deterministic output, clipping bounds, preset separation, batch safety, skip wording, empty folders and CLI failure reporting, plus the fingerprint instrument in both pipeline and reference modes, the single-stage ablation, the role-split aggregation, the grain-at-display-size metric, and the manifest validator with partial-coverage and EXIF-equality rules. Four of them are deliberate expected failures pinned to the open defects in `tests/KNOWN_ISSUES.md`; `tests/test_strict_switch.py` asserts that `CCD_STRICT=1` turns those four into hard failures, so the strict switch cannot rot.
- GitHub Actions runs the suite on Ubuntu and Windows with Python 3.12.
- Release 1.6.0 was installed into the DSH skill directory and checked file by file: the installed copy reports `script_version` 1.6.0 and all four batch statuses and three exit codes behave as documented. The previous 1.4.1 install is preserved as `ccd-photo-enhancer.bak-1.4.1` for rollback.

## Repository Layout

```text
skills/ccd-photo-enhancer/
  SKILL.md                 Agent routing and output contract
  VERSION                  Current bundle version
  scripts/apply_ccd.py     Local deterministic CLI
  references/              Presets, pipeline rules, artistic routes and tests
tests/
  test_apply_ccd.py        Automated unit tests
  test_reference_tools.py  Fingerprint, ablation and validator tests
  test_known_issues.py     Deliberate failures for the open recipe defects
  KNOWN_ISSUES.md          The four open defects, measurements and gate
  ccd_profile.py           Pipeline fingerprint (not a CCD baseline)
  ccd_ablate.py            Single-stage ablation helper
  verify_reference_set.py  Reference-set manifest validator
  real_photo_eval.py       Offline real-photo evaluation
  real-photo-manifest.json Evaluation sources and licensing
reference_set/             Tier rules, the 16-entry template and the Tier C daylight pilot
docs/samples/              Before/after examples, evaluation and reference output
.github/workflows/         Ubuntu and Windows CI
```

## Versioning and Support

This project follows Semantic Versioning. See [CHANGELOG.md](CHANGELOG.md) for release notes and [GitHub Issues](https://github.com/long970/ccd-skill/issues) for bug reports and feature requests.

## Design References

The structure adapts ideas from related public Skills without copying their provider-specific APIs or implementation code:

- [Meitu image-style-transfer](https://www.skills.sh/meitu/meitu-skills/image-style-transfer): separate single-image presets from reference-guided style transfer.
- [Local Photo Filters](https://www.skills.sh/wendy7756/awesome-photo-filters/local-photo-filters): filter catalog, intensity controls and source preservation.
- [Eachlabs style-transfer](https://www.skills.sh/eachlabs/skills/style-transfer): preserve composition and identity while varying effect strength.
- [Openfilm vintage-film](https://www.skills.sh/openfilm/skills/vintage-film): protect people and moments; do not invent dates or source metadata.
- [Analog Memory Photo Director](https://www.skills.sh/chinelee/chinese-visual-director-skills/analog-memory-photo-director): build nostalgia from camera-era limitations rather than a sepia overlay alone.
- [Aesthetic Atelier](https://github.com/wzj52501/aesthetic-atelier): keep the core workflow concise and load recipes only when needed.

## License

[MIT](LICENSE) © 2026 CCD Photo Enhancer contributors
