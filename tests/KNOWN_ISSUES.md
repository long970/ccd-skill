# Known issues in the pixel recipe

These four defects are visible, reproducible and **not fixed yet**. The recipe is frozen
until the reference intervals exist (`reference_set/README.md`): fixing tone without a
target just moves the look somewhere else. Each defect therefore has a regression test
that fails on purpose in `tests/test_known_issues.py`.

`unittest` reports these as *expected failures*, so the suite stays green. When one of
them starts passing, the suite turns red with an **unexpected success** — that is the
prompt to delete the `@unittest.expectedFailure` decorator and the row below.

All numbers are from VERSION 1.5.2, measured on synthetic fixtures so they can be
re-derived without any external photo. `L*` is CIELAB lightness; `near_black` is the
fraction of pixels at `L* <= 2`, `near_white` the fraction at `L* >= 97`.

| id | symptom | measured now | target | likely cause |
| --- | --- | --- | --- | --- |
| KI-01 | Top-end fuses into one value | inputs 247–255 all print as 254; longest equal run 9; 20 of 31 levels survive a 225–255 ladder | longest equal run ≤ 2 | exposure lift (+10 at 225) plus S-curve steepening, while the ceiling sits below 255 |
| KI-02 | `indoor-flash` dims the centre | centre −0.94% L*, corners −23.7% on a mid-grey field at strength 100 | centre delta ≥ 0 | vignette 0.85 and flash falloff 0.18 outweigh the flash lift |
| KI-03 | Restrained strength shifts the median | strength 50 moves L*50 by −1.20 (clean) to −2.25 (night) on neutral grey | \|Δ\| ≤ 1.5 at strength 50 | black point, contrast and highlight compression all pull down together |
| KI-04 | Grain crushes dark patches | at strength 50 a flat level-18 patch goes from 0% to 13–20% `near_black` | increase ≤ 0.05 | additive grain with no shadow envelope; with grain off the same patch stays at 0% |

## How to reproduce

```bash
python tests/test_known_issues.py -v
python tests/ccd_profile.py --manifest tests/real-photo-manifest.json --ablate grain
```

`--ablate` switches off exactly one stage (`s-curve`, `black-point`, `vignette`,
`flash-falloff`, `halation`, `grain`, `sharpness`) and records what it zeroed in the
report, so an ablated run can never be mistaken for the production recipe.

## Attribution notes

- **KI-04 is not the black point.** With `--ablate grain` the level-18 patch stays at
  0% `near_black`; the crush appears only with grain on. Any fix has to touch the noise
  envelope (luma-weighted sigma, or a strength-dependent floor), not the black point.
- **KI-02 is not a vignette bug.** Vignetting a direct-flash frame is the look. The
  defect is the *centre* going negative while the corners drop 25x harder; see
  `--ablate vignette` to separate the two contributions.
- **KI-01 is not clipping.** No channel reaches 255 in the ladder; the values fuse just
  below the ceiling, so it cannot be caught by the `clipped_channel` guardrail.

## What is explicitly *not* a defect

- Darker corners on `indoor-flash` / `night-flash`: that is the flash impression. Only
  the centre delta is asserted.
- Grain on a real photo: the guardrail is `near_black` on a *flat* patch, where grain
  should be visible but must not quantise to pure black.

## Gate

Do not change `PRESETS` to close any of these until `reference_set/manifest.json` is
filled with Tier A originals and `tests/ccd_profile.py` produces per-family intervals.
When that happens, close the issues one ablation stage at a time and record the before
and after interval in `CHANGELOG.md`.
