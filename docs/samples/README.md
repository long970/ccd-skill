# Sample before/after images

These five images are the visual evidence for the CCD presets. They are **real photographs**, not synthetic charts, and were produced with the 1.4.1 CLI. The pixel recipe has not changed since 1.4.1 — later releases add batch handling, wording and tooling — so the same settings remain representative of the current 1.5.2 release:

```text
python skills/ccd-photo-enhancer/scripts/apply_ccd.py <source> --preset <preset> --strength <n> --seed 7
```

| File | Source photo | Preset | Strength |
|---|---|---|---|
| `indoor-portrait.jpg` | Pexels photo 220453 | `indoor-flash` | 80 |
| `daylight-landscape.jpg` | Pexels photo 1366909 | `daylight-aged` | 75 |
| `night-city.jpg` | Pexels photo 1699031 | `night-flash` | 80 |
| `strength-ladder.jpg` | Pexels photo 220453 | `indoor-flash` | 50 / 75 / 100 |
| `detail-100-percent.jpg` | Pexels photo 220453 | `indoor-flash` | 80, 100% crop |

Each side-by-side file is `BEFORE` on the left and `AFTER` on the right. The `BEFORE` half is the downloaded photo resized for layout only; no other edit was applied to it. The `AFTER` half is the CLI output, then resized for layout.

## Extended real-photo evaluation

`real-evaluation-overview.jpg` contains 30 before/after runs across 15 photographs at default and recommended strengths, generated with the current 1.5.2 CLI. `real-evaluation.json` records source hashes, exact parameters, `script_version`, dependency versions, clipping and tonal metrics; rerunning `tests/real_photo_eval.py` refreshes all of them, so check those fields before citing a number. The source matrix and page URLs are in `tests/real-photo-manifest.json`; run `python tests/real_photo_eval.py` from the repository root after placing the licensed sources at the manifest paths. The evaluator itself is offline and always invokes the shipped CLI.

## Licensing

The source photographs come from [Pexels](https://www.pexels.com/license/) and are used under the Pexels License: free to use and modify, no attribution required, but the images may not be sold unaltered or used to imply endorsement by the depicted people or by Pexels. Photo pages follow the Pexels URL convention `https://www.pexels.com/photo/<id>/`; image bytes were retrieved from `https://images.pexels.com/photos/<id>/pexels-photo-<id>.jpeg`. Photographer credits are recorded in `tests/real-photo-manifest.json` when available; some photo pages were not accessible from the machine that built the original samples.

If you republish these files, keep the Pexels License terms in mind. If you need a fully self-contained license story, replace them with photos you own and regenerate with the same commands.

## What these images do and do not show

- They show that the pipeline runs on real camera/smartphone photographs at 1600 px long edge, keeps subject geometry and identity untouched, and produces a clearly warmer, higher-contrast, strongly vignetted compact-camera look with visible grain, a deeper black point and warm bloom around highlights. Measured mean absolute pixel change is 15.5/255 (portrait), 14.6/255 (landscape) and 18.9/255 (night).
- `detail-100-percent.jpg` makes per-pixel grain easier to inspect; downscaled pairs average much of it away.
- They do **not** prove that the result "looks like" a specific CCD camera model, and they are not a substitute for a blind human comparison against real CCD files. At the default strength 50 the change is visible but restrained; the strength ladder shows how the effect develops.
- The portrait shows the known limitation that warm highlight gains still shift light skin slightly warmer at strength 100. There is no face or skin detection in L2, so this must be reviewed by eye.
