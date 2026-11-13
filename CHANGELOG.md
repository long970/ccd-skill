# Changelog

This project follows Semantic Versioning.

## 1.4.1 — 2026-11-13

- Build halation from a quarter-resolution source and upsample one shared 8-bit glow map. This removes full-frame float32 RGB/luma/mask intermediates and keeps interpolation continuous across tile boundaries.
- Replace direct-multiplication flash lift with a bounded quadratic lift, preventing new saturated-channel clipping. Raise indoor/night flash coefficients to 0.18/0.22 so the existing strength-80 preset-separation targets remain meaningful without weakening the tests.
- Add dedicated regressions for warm localized halation, tile-seam continuity, black-point behaviour and saturated-colour flash lift. The suite now contains 33 tests.
- Correct stale sample counts, strength descriptions and real-photo documentation.
- Remove a dead branch in the flash-falloff stage (`np.clip(falloff, -1, 0)` was always zero, so the "edge darkening" multiply never ran and its comment was misleading).
- Correct the README separation figures, which still said ~1.6–1.8/255 at strength 50 and ≥2.4/255 at strength 80 while the code, tests and preset reference all say 2.2–2.3 and ≥3.4.
- Regenerate all five sample composites with 1.4.1 and replace the self-referential halation test (it re-implemented the algorithm) with an independent tile-seam assertion.

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
