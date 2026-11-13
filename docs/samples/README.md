# Sample before/after images

These four images are the visual evidence for the CCD presets. They are **real photographs**, not synthetic charts, and were produced with the shipped CLI:

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

## Licensing

The source photographs come from [Pexels](https://www.pexels.com/license/) and are used under the Pexels License: free to use and modify, no attribution required, but the images may not be sold unaltered or used to imply endorsement by the depicted people or by Pexels. Photo pages follow the Pexels URL convention `https://www.pexels.com/photo/<id>/`; the image bytes here were retrieved from `https://images.pexels.com/photos/<id>/pexels-photo-<id>.jpeg`, because the `www.pexels.com` HTML endpoints returned HTTP 403 from the machine that built these samples, so the individual photo pages were not fetched and their photographer credits could not be recorded.

If you republish these files, keep the Pexels License terms in mind. If you need a fully self-contained license story, replace them with photos you own and regenerate with the same commands.

## What these images do and do not show

- They show that the pipeline runs on real camera/smartphone photographs at 1600 px long edge, keeps subject geometry and identity untouched, and produces a clearly warmer, higher-contrast, strongly vignetted compact-camera look with visible grain, a deeper black point and warm bloom around highlights. Measured mean absolute pixel change is about 15/255 for the portrait and landscape and 19/255 for the night frame.
- `detail-100-percent.jpg` is the only place where per-pixel grain is visible; downscaled pairs average it away.
- They do **not** prove that the result "looks like" a specific CCD camera model, and they are not a substitute for a blind human comparison against real CCD files. The treatment is deliberately conservative: at the default strength 50 the change is subtle, which is why the strength ladder is included.
- The portrait shows the known limitation that warm highlight gains still shift light skin slightly warmer at strength 100. There is no face or skin detection in L2, so this must be reviewed by eye.
