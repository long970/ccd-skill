# Changelog

This project follows Semantic Versioning.

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
