# Nangong Wan Action Showcase V2 — Final Fix Report

Date: 2026-07-23 (Asia/Shanghai)

Implementation commit: `bc06cc1` (`fix: harden action showcase v2 publication`)

Scope: all Important findings from `final-v2-review-findings.md`, the safe V2 minor hardening items, regenerated V2 artifacts, and evidence. V1 artwork/sequence was not rebuilt or modified.

## Outcome

All V2 publication gates pass on the newly rebuilt artifact. The accepted output is now bound to a fixed 16-file SHA-256 inventory, rendered as a single-pass frame stream, validated over every encoded frame, and published only as a complete validated directory. Validation succeeds without the original clipboard Temp path.

- Focused suite: `61 passed in 70.72s`
- Full suite (single final run): `360 passed in 247.06s (0:04:07)`
- Build + validation + atomic publication: exit code 0
- Temp-independent `--validate-only`: exit code 0, `allPassed=true`
- Final report: `work/nangongwan-action-showcase-v2/validation-report.json`
- Final master SHA-256: `a6c4e8355a8ef823c48b09ab6233cce3ccb51a7b3962cc5455a6de0f268eb867`

## Finding-by-finding resolution

### 1. Mutable source oracle and incomplete encoded-content gates

Resolution:

- Added `SourceAsset(id, path, role, sha256)` and a fixed 16-file approved inventory.
- Hashes are checked before JSON parsing or sprite decoding when the plan is built.
- The same inventory is embedded in `timeline.json` using portable logical IDs, and validation requires an exact match.
- Validation fails closed if privacy or source-integrity checks fail; source-derived gates are not run on untrusted inputs.
- Encoded background fidelity checks all 2,473 frames in each of four regions covering every pixel outside the 192×208 sprite rectangle. Threshold: PSNR ≥ 40 dB.
- Encoded center fidelity compares all 2,473 native center crops. It requires per-frame PSNR ≥ 29 dB and decoded/expected temporal-change ratio ≥ 0.10 at every genuinely changing boundary.

RED evidence:

- Fixed-inventory selector: `3 failed` before implementation (no inventory and changed atlas was accepted).
- Outside/center selector: `2 failed` before implementation.
- Real H.264 adjacent-repeat regression failed before `_compare_center_sequences` existed.

GREEN evidence:

- Fixed-inventory selector: `3 passed`.
- Real one-frame outside-overlay H.264 regression: `1 passed` (clean encode accepted; overlaid frame rejected).
- Center regressions: `2 passed` (direct sequence and real H.264 clean/repeated pair).
- Final master outside regions: 2,473/2,473 frames checked in top, bottom, left, and right; minimum PSNR `47.42` dB; minimum sampled full-background SSIM `0.9994795728649041`.
- Final master center: 2,473 frames compared; minimum PSNR `29.55700491322666` dB; minimum temporal ratio `0.1188243438428948`; zero failed/content-mismatch frames.

### 2. Full-resolution frame materialization

Resolution:

- Production now passes `iter_segment_frames(...)` directly to `write_silent_video(...)`.
- `write_silent_video` consumes the iterator once, requires an explicit expected count, rejects short and long streams, closes generators, and deletes partial output on producer or FFmpeg failure.
- The only remaining `build_segment_frames` materialization is a focused-test compatibility helper; it is not called by the production renderer.
- Resident full-frame memory is bounded to the current 1600×900 RGB composite plus the small native source-action frames, instead of retaining up to 920 full-resolution composites (about 3.7 GiB raw RGB for V9 alone).

RED/GREEN evidence:

- Streaming selector before implementation: `4 failed`.
- Streaming selector after implementation: `4 passed`.
- Final full build completed successfully through the streaming path.

### 3. Stale approval and mixed publication

Resolution:

- A rebuild immediately removes the public `validation-report.json` and `review/`, so old approval cannot remain beside changing artifacts.
- The complete candidate is built in a sibling staging directory.
- Validation, 45 review PNGs, the contact sheet, and the report are produced inside staging.
- Publication verifies the exact 15-clip set, 45 review PNGs, required artifacts, report approval, and report-bound hashes before renaming.
- Publication swaps complete directories (`public → backup`, `staging → public`) and restores the previous directory if the second rename fails.
- Once the new directory swap has committed, an old locked backup cleanup error is best-effort and cannot falsely report that publication failed.
- Staging is removed in `finally`; no staging or backup directory remains after the real build.

RED/GREEN evidence:

- Publication/Temp selector before implementation: `4 failed`.
- Publication/Temp selector after implementation: `4 passed`.
- Failed staging-validation regression: `1 passed`.
- Rename rollback, exact complete replacement, and locked-backup cleanup behavior are covered.
- Added self-review boundary tests were RED as `3 failed`, then GREEN as `3 passed`.

### 4. Clipboard Temp dependency during validation

Resolution:

- `--build-all` requires an explicit `--background` input.
- `--validate-only` defaults to no external background and treats the built, hash-verified `output/background.png` as authoritative.
- Supplying `--background` to validation is now only an optional explicit comparison.
- No personal Temp path is embedded as a CLI default.

Evidence:

```text
python tools/render_nangongwan_action_showcase_v2.py --validate-only
Validated .../nangongwan-action-showcase-v2-1600x900.mp4; allPassed=true; report=.../validation-report.json
```

This real post-publication run did not pass or read the original Temp path.

### 5. Retained 48-frame CLI compatibility and write safety

Resolution:

- Preview and builder defaults now read the archived anchored-v1 manifest/atlas.
- Builder writes its default output only under `work/moonlit-chestnut-redesign/`.
- Both CLIs reject every custom output located inside either the archive tree or live Nangong Wan pet-resource tree (including nested paths).
- Builder also retains protection against overwriting arbitrary explicitly supplied input atlas/manifest files.
- Help text explicitly describes the archived 48-frame candidate.

Evidence:

- Archive/default/help/metadata selector: `4 passed`.
- Archive/live nested custom-output boundary regression: included in the final `3 passed` self-review selector.

## Minor hardening completed

- CFR validation now requires `r_frame_rate=30`, `avg_frame_rate=30`, time base `1/15360`, exact video duration `2473/30`, exactly 2,473 decoded timestamps, first PTS 0, and a uniform 512-tick step.
- User-facing metadata now says 25–60 seconds and nine resident seated actions.
- Added a real FFmpeg concat regression for apostrophes in output paths.
- Added direct `ShotSpec(kind="action")` rendering coverage.
- Retained CLI custom-output safety and post-commit backup-cleanup semantics were added after final self-review.

The inexpensive ASS runtime style-membership minor is now complete: `write_ass` rejects any event whose style is absent from the styles declared by the actual `ASS_HEADER`. A platform pixel-golden test remains intentionally out of scope. V2 contains no subtitle streams, and pixel output from libass depends on host font discovery/substitution, making it a Windows-specific flaky oracle with no V2 publication benefit.

## Fixed source SHA-256 inventory

| Role | Logical ID | SHA-256 |
|---|---|---|
| background | `background.png` | `1bca26d93bf3126b3c8be30e2b5f944b4912a4032ac55990b72cfb3d99ba745a` |
| manifest | `01-cinematic-36f-v2.4.1/pet.json` | `a4397d9d4d0caeb338ecbfbae88d4c9ada457c5c50c507d2d77eb7d5fb922964` |
| atlas | `01-cinematic-36f-v2.4.1/spritesheet.webp` | `990d1ee9db3632102e9f07984301519606a9cc3591585e8ef892d0ba975a9d3e` |
| manifest | `02-anchored-48f-v1/complete-archive/pet.json` | `3edd549ff49be95758b531ff15dbdeabee1ce44f0dedb4065fcb8e23e7e10bf3` |
| atlas | `02-anchored-48f-v1/complete-archive/spritesheet.webp` | `d224d16c48beea73516a9eb02e4da4543dfbbd2af7bf96cf10efbf7ff11f0d52` |
| sequence | `03-persistent-rooftop-revisions/render-history-v2-v9/preview-sequence-v9.json` | `ce818923d127ba78facd81f8a2ff6afefcccd37319df3325774a0568154fe0fa` |
| manifest | `04-moon-background-variants/01-small-moon-current/pet.json` | `c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131` |
| atlas | `04-moon-background-variants/01-small-moon-current/spritesheet.webp` | `564793e6c2e090d8e882cc4a829ceccb9bde2ab98b54b9f6126c65cf41fac77e` |
| manifest | `04-moon-background-variants/02-full-circle-184/pet.json` | `c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131` |
| atlas | `04-moon-background-variants/02-full-circle-184/spritesheet.webp` | `117b5bcf84e9dbdc45b5ef13590fe3726667823178b5a603e0e83e527902fa5a` |
| manifest | `04-moon-background-variants/03-cropped-disc-232/pet.json` | `c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131` |
| atlas | `04-moon-background-variants/03-cropped-disc-232/spritesheet.webp` | `6f671f19463dd4f6bf293550ad05c24b6e18c851d98264dd3548b0dc5d5cbb92` |
| manifest | `04-moon-background-variants/04-full-frame-moon-surface/pet.json` | `c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131` |
| atlas | `04-moon-background-variants/04-full-frame-moon-surface/spritesheet.webp` | `03393672e282e5bdcca3fea5f9d58928e0775fb42802e1c10b9a11d1d1e15abe` |
| manifest | `06-standing-chestnut-easter-egg/action.json` | `687da2a94210ac5d6907061b5ddd9d39e16d2f51719e311807179eaf01c70d9f` |
| atlas | `06-standing-chestnut-easter-egg/standing-chestnut-10frames.webp` | `9bb9c75b86b82e8903abc8b9099e1be51b5972d72243b6d6c5f10c74a41b275e` |

Final report evidence: `sourceIntegrity.passed=true`, `inventoryComplete=true`, `assetCount=16`, no mismatches/missing/extra declarations, and `timelineInventoryMatches=true`.

## Verification transcript

### Focused RED groups

Before implementation, the intentionally added regressions failed in grouped runs:

- source inventory/oracle: `3 failed`
- encoded visual content: `2 failed`
- streaming/count/cleanup: `4 failed`
- publication/Temp independence: `4 failed`
- CFR/retained CLI/metadata: `4 failed`
- additional real H.264 adjacent-repeat case: failed before comparator implementation
- final self-review boundaries: `3 failed`

### Focused GREEN

```text
python -m pytest -q tests/test_nangongwan_action_showcase_v2.py
61 passed in 70.72s (0:01:10)
```

The focused suite includes realistic clean/tampered H.264 center sequences, a one-frame outside overlay, source mutation after binding, short/long/single-pass streams, failed validation, interrupted rename rollback, complete replacement, validate-only with `None`, exact CFR/PTS, archive/live CLI output rejection, apostrophe concat, and direct action rendering.

### Full suite (run once after the final code change)

```text
python -m pytest -q --ignore=tests/integration/test_frozen_smoke.py
360 passed in 247.06s (0:04:07)
```

### Build, validate, publish

```text
python tools/render_nangongwan_action_showcase_v2.py --build-all --background C:\Users\23644\AppData\Local\Temp\codex-clipboard-fa2f4101-2de0-4c4a-a1c9-01fc1c2a4412.png
Built, validated, and published ...\work\nangongwan-action-showcase-v2\nangongwan-action-showcase-v2-1600x900.mp4
```

The supplied background was checked immediately before the build as SHA-256 `1bca26d93bf3126b3c8be30e2b5f944b4912a4032ac55990b72cfb3d99ba745a`.

### Static checks

- `python -m py_compile` for all touched Python modules/tests: exit 0
- `git diff --check`: exit 0 (only Git's existing LF→CRLF notices)
- Final cached diff check before the implementation commit: exit 0

## Final artifact audit

- Master: 2,703,375 bytes; SHA-256 `a6c4e8355a8ef823c48b09ab6233cce3ccb51a7b3962cc5455a6de0f268eb867`
- Timeline SHA-256: `c78ac8d021b48b7afd7ac6b7a678720ff57ff9fe30bdf0c4886075235c6449d1`
- Background SHA-256: `1bca26d93bf3126b3c8be30e2b5f944b4912a4032ac55990b72cfb3d99ba745a`
- Contact sheet: 4800×540, 916,008 bytes; SHA-256 `24f1ec39ed848d084a0ba04bb487f4a4bd56cc78ab5f414806ec6c5442975fe9`
- Validation report SHA-256 after Temp-independent validation: `9a6be89163bc7fc05d5e3e2253658fc3bc7eb3e670e31d67b4744e9a6ab6bd95`
- Exact output inventory: 65 files = 15 clips + master + background + timeline + report + 45 review PNGs + contact sheet.
- No `.ass`, `.srt`, or `.vtt` sidecar; no sibling V2 staging/backup directory.
- FFprobe: one H.264 High/yuv420p 1600×900 SAR 1:1 stream, 30/1 `r_frame_rate`, 30/1 `avg_frame_rate`, time base 1/15360, `duration_ts=1266176`, 2,473 frames; one AAC-LC 48 kHz stereo stream.
- All 12 report checks are `true`, including `sourceIntegrity`, encoded background, exact center sequence, silent audio, stream shape, order/counts, privacy, and moon parity.

Visual review of the 15×3 contact sheet and original-resolution representative frames (cinematic, anchored, V9 small moon, and full moon) found consistent background placement, centered native sprite rectangles, expected variant changes, and no text overlays.

## Changed files

- `tools/nangongwan_action_showcase_v2.py`
- `tools/render_nangongwan_action_showcase_v2.py`
- `tests/test_nangongwan_action_showcase_v2.py`
- `tools/preview_nangongwan_moonlit_chestnut.py`
- `tools/build_nangongwan_moonlit_chestnut.py`
- `src/shiyi_desktop_pet/resources/pets/nangongwan/pet.json`
- `src/shiyi_desktop_pet/menu_controller.py`
- this report

## Scope and self-review

The following three pre-existing user changes were never staged or modified by this work. Their Git-diff SHA-256 fingerprints remained exactly unchanged before and after implementation/build:

- `tests/test_moonlit_asset_builder.py`: `d09323a91b88ec1cf256b27dde0991e89d96f6f1c53314eddfee1e338e404eb3`
- `tools/build_nangongwan_giant_moon_webp.py`: `86555ee4546ff8ec8f55807a7c4cc4a1d5d5ad16191d6210bb151cff6ceed176`
- `tools/build_nangongwan_moonlit_rooftop_state.py`: `34ddf3db9e42f0a7d12bf070513df5b6e0b43e9976d35c6f824b61eb1ef6bd6b`

No V1 artifact or live atlas/manifest was rebuilt. The only live-resource edits are the requested user-facing 25–60 second/nine-action text corrections.

A theoretical local-filesystem TOCTOU remains in the shared making-of `read_action` helper: V2 verifies a source immediately before that helper reopens its path. Exploiting it would require an external writer racing an in-progress local build and restoring bytes around checks; normal builds, post-build validation, timeline inventory, and atomic publication remain hash-gated. Removing that theoretical race would require changing the shared loader to decode byte snapshots and was not part of the reviewed V2 findings.

## Follow-up re-review: complete retained-CLI collision preflight

Implementation commit: `b258194` (`fix: preflight retained CLI outputs`)

### Remaining Important finding

The retained CLIs previously guarded their primary destination or protected roots, but did not compare all secondary outputs with custom input paths. Consequently, preview could overwrite a custom atlas/manifest named `transition-metrics.json`, while builder could overwrite custom inputs through `audit-48.png` or `frames/frame-*.png`.

Resolution:

- Added the shared, write-free `validate_planned_outputs` preflight. It resolves every input, planned output, and protected root before any source read, directory creation, or file write.
- It rejects any exact resolved input/output intersection, every output under the archive/live-resource trees, and duplicate planned output destinations.
- Preview enumerates its output directory and all six files: three GIFs, the MP4, `transition-metrics.json`, and `hardest-seams.png`.
- Builder enumerates its output directory, `frames/` directory, primary atlas, `audit-48.png`, and all 48 `frames/frame-01.png` through `frame-48.png` files.
- Builder compares those outputs with all eight inputs: six fixed phase/moon/roof assets plus the custom archive atlas and manifest. Preview compares with both custom inputs.
- Both package imports and direct `python tools/...py` invocation are supported.

TDD evidence:

```text
python -m pytest -q tests/test_nangongwan_action_showcase_v2.py tests/test_nangongwan_rooftop_making_of.py -k "input_collision or absent_from_the_declared_header"
7 failed, 135 deselected in 0.48s
```

All six CLI cases failed for the expected missing-preflight reason: both `--atlas`/`--manifest` positions against preview `transition-metrics.json`, and both builder input positions against `audit-48.png` and `frames/frame-01.png`. The ASS event with style `Missing` was written instead of rejected.

After the minimal implementation:

```text
7 passed, 135 deselected in 0.37s
```

A real direct-script check then exposed the new shared module import issue. The added regression was RED as:

```text
python -m pytest -q tests/test_nangongwan_action_showcase_v2.py -k "run_directly_from_the_repository_root"
2 failed, 1 passed, 66 deselected in 0.54s
```

Both failures were `ModuleNotFoundError: No module named 'tools'`. Conditional sibling/package imports fixed the direct-entry path. The combined new regression set then passed:

```text
9 passed, 135 deselected in 0.67s
```

Each collision test verifies the original input bytes remain identical and that no primary or secondary output file was created.

### ASS declared-style membership Minor

`write_ass` now derives the declared style names from the actual `Style: ...` rows in `ASS_HEADER` and validates every event before creating the output parent directory. An unknown style raises `ValueError("subtitle style is not declared in ASS header: Missing")`; the regression also proves no directory/file is created. No font lookup, libass render, or pixel-golden behavior was introduced.

### Complete requested covering tests

```text
python -m pytest -q tests/test_nangongwan_action_showcase_v2.py tests/test_nangongwan_rooftop_making_of.py
144 passed in 175.81s (0:02:55)
```

Static verification:

- `python -m py_compile` for the shared helper, both CLIs, making-of module, and both test files: exit 0.
- `git diff --check`: exit 0, with only existing LF→CRLF notices.
- Cached intended-file diff check before `b258194`: exit 0.

### Follow-up files and self-review

- `tools/nangongwan_output_preflight.py`
- `tools/build_nangongwan_moonlit_chestnut.py`
- `tools/preview_nangongwan_moonlit_chestnut.py`
- `tools/nangongwan_rooftop_making_of.py`
- `tests/test_nangongwan_action_showcase_v2.py`
- `tests/test_nangongwan_rooftop_making_of.py`
- this report

The preflight is the first post-argument-parsing operation in both `main()` functions. It has no write operations. Review confirmed that its enumerated sets match every path subsequently created or written by each CLI. This change does not alter the V2 master/timeline or require artifact regeneration.

The three unrelated dirty files remained unstaged and their Git-diff SHA-256 fingerprints are still exactly:

- `tests/test_moonlit_asset_builder.py`: `d09323a91b88ec1cf256b27dde0991e89d96f6f1c53314eddfee1e338e404eb3`
- `tools/build_nangongwan_giant_moon_webp.py`: `86555ee4546ff8ec8f55807a7c4cc4a1d5d5ad16191d6210bb151cff6ceed176`
- `tools/build_nangongwan_moonlit_rooftop_state.py`: `34ddf3db9e42f0a7d12bf070513df5b6e0b43e9976d35c6f824b61eb1ef6bd6b`

No remaining concern from this re-review is open. The theoretical source-loader TOCTOU noted above is unchanged and unrelated to retained-CLI output collision safety.
