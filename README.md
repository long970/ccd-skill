# CCD Photo Enhancer

A local-first Agent Skill for editing an existing photo or photo folder with a repeatable early compact-digital-camera (CCD-look) treatment. It is designed for privacy-conscious photographers and Agent power users who want deterministic, local results rather than generative reinterpretation. The repository keeps the discoverable skill bundle under `skills/ccd-photo-enhancer/`; tests and release metadata live at the repository root.

## Repository layout

```text
skills/ccd-photo-enhancer/
  SKILL.md
  VERSION
  references/
  scripts/apply_ccd.py
tests/test_apply_ccd.py
.github/workflows/tests.yml
LICENSE
CHANGELOG.md
requirements.txt
```

The skill separates three capability levels: local deterministic pixel processing for CCD effects (L2), an explicitly available and authorized generative image-edit backend for semantic/medium changes such as ink painting (L1), and prompt-only fallback (L3). It does not claim that pixel filters reproduce a particular sensor or reconstruct real flash shadows.

## Samples

Real photographs, processed by the shipped CLI with `--seed 7`. Left is the unmodified photo, right is the result. Sources and licensing: [docs/samples/README.md](docs/samples/README.md).

![Indoor portrait, indoor-flash strength 80](docs/samples/indoor-portrait.jpg)

![Daylight landscape, daylight-aged strength 75](docs/samples/daylight-landscape.jpg)

![Night city, night-flash strength 80](docs/samples/night-city.jpg)

Strength semantics on the same portrait (50 / 75 / 100). The default 50 is visible but restrained; 75-85 is where the preset character is obvious:

![Strength ladder 50 75 100](docs/samples/strength-ladder.jpg)

Grain and highlight bloom are per-pixel effects, so they disappear when a 1600 px photo is scaled down for a web page. This is the same indoor portrait at 100% crop:

![100% crop before and after](docs/samples/detail-100-percent.jpg)

These show the pipeline working on real photos. They do not prove the look matches a specific CCD model. Known limitation: warm highlight gains still shift light skin warmer at high strength, and L2 has no face or skin detection, so portrait output needs a visual check.

### Extended real-photo evaluation

The repeatable offline evaluation covers 15 licensed photographs and 30 CLI runs at default and recommended strengths, including low-key and high-key portraits, groups, indoor events, backlight, landscapes, neon and rainy nights. It records source hashes, dependency versions, clipping and tonal metrics, and writes side-by-side comparisons.

```text
python tests/real_photo_eval.py
```

See the [30-run overview](docs/samples/real-evaluation-overview.jpg) and [JSON report](docs/samples/real-evaluation.json). The current mean absolute pixel change is 11.1/255 and the maximum near-white ratio after processing is 0.12%. These measurements are technical alerts, not proof of CCD authenticity or aesthetic quality.

## Run the local CCD processor

The CLI requires Python, Pillow, and NumPy in the chosen interpreter. It never installs dependencies or accesses the network.

```text
# First result with clearly visible preset character
python skills/ccd-photo-enhancer/scripts/apply_ccd.py photo.jpg --preset daylight-aged --strength 75 --seed 0

# Single-image custom output and sub-effect control
python skills/ccd-photo-enhancer/scripts/apply_ccd.py portrait.png --preset indoor-flash --strength 75 --grain-strength 10 --out portrait-ccd.png

# Inspect metrics without writing an image
python skills/ccd-photo-enhancer/scripts/apply_ccd.py photo.jpg --preset night-flash --strength 50 --preview

# Process one folder level into an existing, separate output folder
python skills/ccd-photo-enhancer/scripts/apply_ccd.py photos --batch --preset daylight-aged --strength 75 --seed 7 --out ccd-output
```

Strength 50 remains the CLI default for backwards-compatible, restrained output. Start at 75–85 when the goal is an immediately recognizable CCD treatment; review portraits for warmer skin and darker shadows.

For batch mode, create `ccd-output` first and keep it different from the input folder. Batch mode reads only the first directory level, does not recurse, uses the explicit seed for each source image, and never mixes generated images back into the source folder. It returns one JSON summary containing every per-image report. Exit codes are 0 for complete success, 1 for partial success, and 2 when no image was processed; partial success never claims that the whole folder succeeded.

`--preview` reports in-memory pixel metrics and never writes an image; those metrics are measured before JPEG encoding and are not a substitute for viewing the saved result. Batch mode does not support `--preview`; preview a representative single image first.

The CLI prints a JSON report on success and writes errors to stderr with a non-zero exit. It never overwrites an existing file; collisions receive a numbered suffix. PNG inputs and alpha-bearing images default to PNG; opaque JPEG/WebP inputs default to JPEG. JPEG uses quality 94, 4:4:4 chroma sampling, and `optimize=False` to avoid encoder failures on high-entropy content; output sizes vary by image. EXIF/GPS metadata is not copied. HEIC/HEIF, animation, unsupported ICC profiles, and floating-point rasters fail explicitly. The default pixel cap is 60MP; `--max-pixels` can be set from 1 to 60MP, with no automatic resizing.

## Tests and CI

```text
python -m unittest discover -s tests -v
```

The tests use `os.makedirs`-created unique child directories. They prefer `tests/.test-work` or `CCD_TEST_TMP`; if neither is writable, they fall back to `LOCALAPPDATA`, `TEMP`, or `TMP` and print the chosen path. They do not rely on `tempfile`'s private temporary-directory ACLs.

GitHub Actions runs the same suite on Windows and Ubuntu with the pinned dependencies in `requirements.txt`. The preset separation, dark vignette, and highlight assertions use generated calibration and photo-like fixtures. Measured with grain disabled: closest preset pair is about 2.2–2.3/255 at strength 50 and ≥3.4/255 at strength 80, so the documented "obvious preset character" applies from about strength 75 upward. Real-photo before/after examples are included above; the synthetic calibration fixtures below complement rather than replace visual review of those photographs.

## Install

The public repository is [long970/ccd-skill](https://github.com/long970/ccd-skill). Install the discoverable `ccd-photo-enhancer` bundle with the Skills CLI:

```text
npx skills add long970/ccd-skill --skill ccd-photo-enhancer
```

Release archives and version notes are available on the [GitHub Releases](https://github.com/long970/ccd-skill/releases) page. Directory indexing, install counts and security audit results on skills.sh are maintained by that service after discovery.

### Install in DeepSeek Harness

The skill manifest slug is `ccd-photo-enhancer`. Copy only `skills/ccd-photo-enhancer/` as a one-level child of the user skill root, for example:

```powershell
Copy-Item -Recurse 'C:\work\ccd-skill\skills\ccd-photo-enhancer' 'C:\Users\user\.dsh\skills\ccd-photo-enhancer'
```

## Design references

The structure adapts ideas from related public skills without copying their provider-specific APIs or implementation code:

- [Meitu image-style-transfer](https://www.skills.sh/meitu/meitu-skills/image-style-transfer): separate single-image presets from reference-guided style transfer.
- [Local Photo Filters](https://www.skills.sh/wendy7756/awesome-photo-filters/local-photo-filters): filter catalog, intensity controls, and source preservation.
- [Eachlabs style-transfer](https://www.skills.sh/eachlabs/skills/style-transfer): preserve composition and identity while varying effect strength.
- [Openfilm vintage-film](https://www.skills.sh/openfilm/skills/vintage-film): protect people and moments; do not invent dates or source metadata.
- [Analog Memory Photo Director](https://www.skills.sh/chinelee/chinese-visual-director-skills/analog-memory-photo-director): build nostalgia from camera-era limitations rather than a sepia overlay alone.
- [Aesthetic Atelier](https://github.com/wzj52501/aesthetic-atelier): keep the core workflow concise and load recipes and regression guidance only when needed.
