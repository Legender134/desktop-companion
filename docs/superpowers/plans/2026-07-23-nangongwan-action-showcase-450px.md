# 南宫婉纯动作展示视频 450px 版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改任何动作素材和现有小尺寸成片的前提下，把南宫婉动作画布固定放大到450×488，并重新生成严格位于1600×900几何中心的纯动作展示视频。

**Architecture:** 把当前含义混合的 `SPRITE_SIZE` 拆成192×208源素材尺寸和450×488视频渲染尺寸；源读取、动作时序和哈希清单继续使用源尺寸，只有Lanczos预乘Alpha缩放、合成、中心裁取、背景遮罩和时间线使用渲染尺寸。现有流式编码、暂存验证和原子发布架构保持不变，但输出切换到独立的450px目录，旧V2目录只读保留。

**Tech Stack:** Python 3.12、Pillow（预乘Alpha与Lanczos）、FFmpeg/FFprobe、pytest、标准库 `dataclasses/fractions/hashlib/json/pathlib/subprocess`。

## Global Constraints

- 成片固定1600×900、30fps、2473帧、约82.433333秒。
- 源动作帧始终为192×208 RGBA；不得修改任何WebP、JSON或动作索引。
- 渲染画布固定450×488；固定左上角 `(575,206)`；画布中心严格为 `(800,450)`。
- 所有帧采用同一个固定矩形；不得按不透明包围盒逐帧缩放、裁切或漂移。
- 使用预乘Alpha Lanczos缩放；不得添加锐化、阴影、描边、色彩变换或边缘光晕。
- 15段顺序、每段帧数、八个15帧眨眼和三个月亮版本共享映射保持不变。
- 背景仍为SHA-256 `1bca26d93bf3126b3c8be30e2b5f944b4912a4032ac55990b72cfb3d99ba745a` 的1600×900 RGB截图。
- 新输出写入 `work/nangongwan-action-showcase-450px/`；主视频名为 `nangongwan-action-showcase-450px-1600x900.mp4`。
- `work/nangongwan-action-showcase-v2/` 及其中所有文件不得覆盖、重命名或删除。
- 输出继续使用H.264 High、yuv420p、SAR1:1、48kHz双声道静音AAC、fast-start、无其他流。
- 不得添加标题、字幕、卡片、故事文字、投票、旁白、音乐、转场或旧蓝色背景。
- 禁止读取 `07-private-anime-reference-DO-NOT-PUBLISH/`；16项不可变素材SHA-256清单必须继续通过。
- 构建必须先进入暂存目录，全部验证通过后原子发布；失败时不得留下旧的通过报告或混合产物。
- 不修改安装包、桌面宠物本体、GitHub或Gitee仓库。
- 保持三个既有未提交文件完全不动：`tests/test_moonlit_asset_builder.py`、`tools/build_nangongwan_giant_moon_webp.py`、`tools/build_nangongwan_moonlit_rooftop_state.py`。

---

## File Structure

- Modify: `tools/nangongwan_action_showcase_v2.py` — 区分源尺寸和渲染尺寸，新增预乘Alpha缩放，所有合成与媒体验证改用450×488矩形。
- Modify: `tools/render_nangongwan_action_showcase_v2.py` — 新输出目录/文件名、时间线schema2、渲染几何门禁和独立原子发布。
- Modify: `tests/test_nangongwan_action_showcase_v2.py` — 几何、缩放边缘、时间线、逐帧验证、旧版保留和真实FFmpeg回归。
- Create locally: `work/nangongwan-action-showcase-450px/` — 15个片段、背景、时间线、主视频、验证报告和审片图；保持Git忽略。

### Task 1: 拆分源尺寸与渲染尺寸并实现高质量固定缩放

**Files:**
- Modify: `tools/nangongwan_action_showcase_v2.py`
- Modify: `tests/test_nangongwan_action_showcase_v2.py`

**Interfaces:**
- Produces: `SOURCE_SPRITE_SIZE`, `RENDERED_SPRITE_SIZE`, `RENDERED_SPRITE_ORIGIN`, `RENDERED_SPRITE_BOX`, `RENDER_SCALE`, `scale_sprite(sprite: Image.Image) -> Image.Image`, `compose_frame(background: Image.Image, sprite: Image.Image) -> Image.Image`, `_rendered_sprite_crop_filter() -> str` and all450px-aware core center/background validators。
- Consumes: 192×208 RGBA frames from `TimedFrames` and the existing1600×900 RGB background contract。

- [ ] **Step 1: 写入450px几何与预乘Alpha失败测试**

Append these tests to `tests/test_nangongwan_action_showcase_v2.py` and replace the old 192×208 composition assertions:

```python
from fractions import Fraction

from PIL import Image, ImageChops, ImageDraw


def test_450px_render_geometry_is_exactly_centered():
    assert showcase_module.SOURCE_SPRITE_SIZE == (192, 208)
    assert showcase_module.RENDERED_SPRITE_SIZE == (450, 488)
    assert showcase_module.RENDERED_SPRITE_ORIGIN == (575, 206)
    assert showcase_module.RENDERED_SPRITE_BOX == (575, 206, 1025, 694)
    assert showcase_module.RENDER_SCALE == Fraction(75, 32)
    x, y = showcase_module.RENDERED_SPRITE_ORIGIN
    width, height = showcase_module.RENDERED_SPRITE_SIZE
    assert (x + width / 2, y + height / 2) == (800, 450)


def test_scale_sprite_uses_fixed_premultiplied_lanczos_without_hidden_color_fringe():
    sprite = Image.new(
        "RGBA", showcase_module.SOURCE_SPRITE_SIZE, (255, 0, 0, 0)
    )
    ImageDraw.Draw(sprite).rectangle((48, 52, 143, 155), fill=(0, 255, 0, 255))
    original = sprite.tobytes()

    scaled = showcase_module.scale_sprite(sprite)

    assert scaled.mode == "RGBA"
    assert scaled.size == (450, 488)
    assert sprite.tobytes() == original
    antialiased = [
        pixel for pixel in scaled.getdata() if 0 < pixel[3] < 255
    ]
    assert antialiased
    assert all(red == 0 and blue == 0 for red, _, blue, _ in antialiased)


def test_compose_frame_changes_only_the_450px_center_rectangle():
    background = Image.effect_noise((1600, 900), 80).convert("RGB")
    sprite = Image.new("RGBA", (192, 208), (20, 120, 240, 180))

    composed = showcase_module.compose_frame(background, sprite)

    changed = ImageChops.difference(background, composed).getbbox()
    assert changed is not None
    assert 575 <= changed[0] < changed[2] <= 1025
    assert 206 <= changed[1] < changed[3] <= 694
    assert composed.size == (1600, 900)


def test_decoded_center_crop_uses_450px_geometry():
    assert showcase_module._rendered_sprite_crop_filter() == (
        "crop=450:488:575:206"
    )
```

- [ ] **Step 2: 运行聚焦测试确认RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q -k "450px_render_geometry or scale_sprite_uses_fixed or compose_frame_changes_only or decoded_center_crop"
```

Expected: collection or assertions fail because the new constants/functions do not exist and composition still uses `(704,346,192,208)`。

- [ ] **Step 3: 实现源/渲染常量和预乘Alpha缩放**

Replace the ambiguous constants at the top of `tools/nangongwan_action_showcase_v2.py`:

```python
FPS = 30
FRAME_SIZE = (1600, 900)
SOURCE_SPRITE_SIZE = (192, 208)
RENDERED_SPRITE_SIZE = (450, 488)
RENDERED_SPRITE_ORIGIN = (575, 206)
RENDERED_SPRITE_BOX = (575, 206, 1025, 694)
RENDER_SCALE = Fraction(75, 32)
```

Add the scaler and replace `compose_frame()`:

```python
def scale_sprite(sprite: Image.Image) -> Image.Image:
    """Resize one fixed source canvas without transparent-RGB color bleed."""

    if sprite.mode != "RGBA" or sprite.size != SOURCE_SPRITE_SIZE:
        raise ValueError(
            f"sprite must be an RGBA image sized {SOURCE_SPRITE_SIZE}"
        )
    premultiplied = sprite.convert("RGBa")
    resized = premultiplied.resize(
        RENDERED_SPRITE_SIZE, Image.Resampling.LANCZOS
    )
    return resized.convert("RGBA")


def compose_frame(background: Image.Image, sprite: Image.Image) -> Image.Image:
    """Scale and alpha-composite one source sprite at the fixed video center."""

    if background.size != FRAME_SIZE or background.mode != "RGB":
        raise ValueError(f"background must be an RGB image sized {FRAME_SIZE}")
    canvas = background.copy().convert("RGBA")
    canvas.alpha_composite(scale_sprite(sprite), RENDERED_SPRITE_ORIGIN)
    return canvas.convert("RGB")
```

Update `_validate_timed_frames()` to require `SOURCE_SPRITE_SIZE`; do not resize inside source validation, resampling, blink creation or source-index selection。Update every core geometry consumer in the same task:

- `_iter_expected_center_frames()` crops `RENDERED_SPRITE_BOX` and composites `scale_sprite()`。
- `_iter_decoded_center_frames()` uses `_rendered_sprite_crop_filter()` and450×488 raw frames。
- `_center_frame_psnr()` and `_compare_center_sequences()` require450×488 RGB images and report `450x488 center crop`。
- `_outside_sprite_ssim()` and `_encoded_background_fidelity()` mask/crop the450×488 rendered rectangle。
- `_centered_composition()` accepts changes only within `RENDERED_SPRITE_BOX`。

Use these exact helper and expected-frame implementations:

```python
def _rendered_sprite_crop_filter() -> str:
    return (
        f"crop={RENDERED_SPRITE_SIZE[0]}:{RENDERED_SPRITE_SIZE[1]}:"
        f"{RENDERED_SPRITE_ORIGIN[0]}:{RENDERED_SPRITE_ORIGIN[1]}"
    )


def _iter_expected_center_frames(
    plan: ShowcasePlan, background: Path
) -> Iterator[Image.Image]:
    with Image.open(background) as source:
        center_background = (
            source.convert("RGB").crop(RENDERED_SPRITE_BOX).convert("RGBA")
        )
    for segment in plan.segments:
        timed = _concatenate_actions(segment.source)
        source_indices = _segment_source_indices(segment, timed)
        if len(source_indices) != segment.output_frames:
            raise ValueError("expected center sequence does not match segment frames")
        for source_index in source_indices:
            center = center_background.copy()
            center.alpha_composite(
                scale_sprite(timed.frames[source_index]), (0, 0)
            )
            yield center.convert("RGB")
```

In `_iter_decoded_center_frames()`, use `"-vf", _rendered_sprite_crop_filter()` and calculate `frame_bytes` from `RENDERED_SPRITE_SIZE`。Use `RENDERED_SPRITE_BOX` for the SSIM mask and centered-composition bound test; calculate all four FFmpeg outside regions from the rendered origin and size。

- [ ] **Step 4: 替换歧义常量并跑GREEN**

Within the core module, source operations must use `SOURCE_SPRITE_SIZE`; every rendered rectangle, full-video composition, FFmpeg crop, SSIM/PSNR mask and center comparison must use `RENDERED_SPRITE_SIZE`, `RENDERED_SPRITE_ORIGIN` or `RENDERED_SPRITE_BOX`。Run:

```powershell
rg -n "\bSPRITE_SIZE\b|\bSPRITE_ORIGIN\b" tools\nangongwan_action_showcase_v2.py
& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q -k "geometry or scale_sprite or compose_frame or resample or blink"
```

Expected: `rg` returns no matches; selected tests pass with no warnings。Existing source-size rejection tests must still reject191×208 or192×207 inputs。

- [ ] **Step 5: 提交核心缩放器**

```powershell
git add tools/nangongwan_action_showcase_v2.py tests/test_nangongwan_action_showcase_v2.py
git commit -m "feat: scale showcase sprites to 450px"
```

### Task 2: 更新时间线门禁和独立450px输出

**Files:**
- Modify: `tools/nangongwan_action_showcase_v2.py`
- Modify: `tools/render_nangongwan_action_showcase_v2.py`
- Modify: `tests/test_nangongwan_action_showcase_v2.py`

**Interfaces:**
- Consumes: Task1 `scale_sprite()`, source/render constants, existing `ShowcasePlan`, streaming encoder and atomic publisher。
- Produces: schema2 `_timeline_document()`, `_timeline_render_geometry(document: dict[str, object]) -> dict[str, object]`, `build_showcase()` publishing only to the new output directory。

- [ ] **Step 1: 写入时间线、输出隔离与验证矩形失败测试**

Add/update these tests:

```python
def test_450px_timeline_records_source_and_render_geometry(showcase_plan):
    timeline = render_module._timeline_document(
        showcase_plan, showcase_module.BACKGROUND_SHA256
    )
    assert timeline["schemaVersion"] == 2
    assert timeline["sourceSpriteSize"] == [192, 208]
    assert timeline["renderedSpriteRectangle"] == {
        "x": 575,
        "y": 206,
        "width": 450,
        "height": 488,
    }
    assert timeline["renderScale"] == {"numerator": 75, "denominator": 32}
    assert "spriteRectangle" not in timeline
    assert timeline["totalFrames"] == 2473


def test_timeline_render_geometry_rejects_legacy_native_rectangle():
    document = {
        "schemaVersion": 2,
        "sourceSpriteSize": [192, 208],
        "renderedSpriteRectangle": {
            "x": 704, "y": 346, "width": 192, "height": 208
        },
        "renderScale": {"numerator": 75, "denominator": 32},
    }
    detail = showcase_module._timeline_render_geometry(document)
    assert detail["passed"] is False


def test_450px_output_names_are_isolated_from_existing_v2():
    assert render_module._OUTPUT_DIRECTORY == (
        Path("work") / "nangongwan-action-showcase-450px"
    )
    assert render_module._MASTER_NAME == (
        "nangongwan-action-showcase-450px-1600x900.mp4"
    )
    assert "nangongwan-action-showcase-v2" not in str(
        render_module._OUTPUT_DIRECTORY
    )
```

Update the exact final-check-set assertion to include `"renderGeometry": True` in addition to the existing12 gates。

- [ ] **Step 2: 运行测试确认RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q -k "450px_timeline or timeline_render_geometry or output_names_are_isolated"
```

Expected: three failures because timeline remains schema1, the render-geometry gate is absent, and output names still target V2。

- [ ] **Step 3: 增加时间线渲染几何门禁**

In `tools/nangongwan_action_showcase_v2.py`:

Add the exact geometry gate:

```python
def _timeline_render_geometry(document: dict[str, object]) -> dict[str, object]:
    expected_rectangle = {
        "x": RENDERED_SPRITE_ORIGIN[0],
        "y": RENDERED_SPRITE_ORIGIN[1],
        "width": RENDERED_SPRITE_SIZE[0],
        "height": RENDERED_SPRITE_SIZE[1],
    }
    actual_source = document.get("sourceSpriteSize")
    actual_rectangle = document.get("renderedSpriteRectangle")
    actual_scale = document.get("renderScale")
    passed = (
        document.get("schemaVersion") == 2
        and actual_source == list(SOURCE_SPRITE_SIZE)
        and actual_rectangle == expected_rectangle
        and actual_scale == {
            "numerator": RENDER_SCALE.numerator,
            "denominator": RENDER_SCALE.denominator,
        }
    )
    return {
        "passed": passed,
        "sourceSpriteSize": actual_source,
        "renderedSpriteRectangle": actual_rectangle,
        "renderScale": actual_scale,
    }
```

Call it from `validate_showcase()` and add `renderGeometry` to `checks`; `allPassed` must still be `all(checks.values())`。

- [ ] **Step 4: 更新时间线schema和输出常量**

In `tools/render_nangongwan_action_showcase_v2.py`, import the four new geometry constants and set:

```python
_OUTPUT_DIRECTORY = Path("work") / "nangongwan-action-showcase-450px"
_MASTER_NAME = "nangongwan-action-showcase-450px-1600x900.mp4"
_VIDEO_ONLY_NAME = "nangongwan-action-showcase-450px-video-only.mp4"
```

Replace `_timeline_document()` geometry keys with:

```python
"schemaVersion": 2,
"sourceSpriteSize": list(SOURCE_SPRITE_SIZE),
"renderedSpriteRectangle": {
    "x": RENDERED_SPRITE_ORIGIN[0],
    "y": RENDERED_SPRITE_ORIGIN[1],
    "width": RENDERED_SPRITE_SIZE[0],
    "height": RENDERED_SPRITE_SIZE[1],
},
"renderScale": {
    "numerator": RENDER_SCALE.numerator,
    "denominator": RENDER_SCALE.denominator,
},
```

Use `_VIDEO_ONLY_NAME` in `_build_showcase_directory()`。Update CLI/output error text from V2 to450px without changing source paths or asset hashes。

- [ ] **Step 5: 锁定旧版目录不变并跑聚焦GREEN**

Add this regression, which creates `root/work/nangongwan-action-showcase-v2/sentinel.bin`, exercises a fully monkeypatched successful `build_showcase()`, and proves the old directory is untouched:

```python
def test_build_showcase_publishes_450px_without_touching_existing_v2(
    tmp_path, monkeypatch
):
    old_output = tmp_path / "work" / "nangongwan-action-showcase-v2"
    old_output.mkdir(parents=True)
    sentinel = old_output / "sentinel.bin"
    sentinel.write_bytes(b"keep-the-small-version")
    old_inventory = tuple(path.relative_to(old_output) for path in old_output.rglob("*"))

    def fake_build(root, background, staging):
        master = staging / render_module._MASTER_NAME
        master.write_bytes(b"staged")
        return master

    def fake_validate(root, background_source=None, **kwargs):
        output = kwargs["output_directory"]
        return output / render_module._MASTER_NAME, output / "validation-report.json"

    def fake_publish(staging, output):
        output.mkdir(parents=True)
        (output / render_module._MASTER_NAME).write_bytes(b"published")

    monkeypatch.setattr(render_module, "_build_showcase_directory", fake_build)
    monkeypatch.setattr(render_module, "_validate_final_showcase", fake_validate)
    monkeypatch.setattr(render_module, "_publish_staged_directory", fake_publish)

    result = render_module.build_showcase(tmp_path, tmp_path / "background.png")

    assert result == (
        tmp_path
        / "work"
        / "nangongwan-action-showcase-450px"
        / "nangongwan-action-showcase-450px-1600x900.mp4"
    )
    assert sentinel.read_bytes() == b"keep-the-small-version"
    assert tuple(path.relative_to(old_output) for path in old_output.rglob("*")) == old_inventory
```

Then run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q
rg -n "704|346|crop=192:208|over every 192x208 center crop|nangongwan-action-showcase-v2-video-only" tools\nangongwan_action_showcase_v2.py tools\render_nangongwan_action_showcase_v2.py
```

Expected: focused suite passes; `rg` returns no obsolete rendered-geometry/output matches。References to192×208 are allowed only for `SOURCE_SPRITE_SIZE`, source fixtures and source validation。

- [ ] **Step 6: 运行真实两段FFmpeg回归和完整验证单元门禁**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q -k "encode or concat or validate or center or background or timeline or publication"
```

Expected: all selected tests pass; realistic adjacent-frame tampering still fails the450×488 center comparator, one-frame outside overlay still fails the all-frame background gate, and clean H.264 samples pass。

- [ ] **Step 7: 提交450px时间线和验证器**

```powershell
git add tools/nangongwan_action_showcase_v2.py tools/render_nangongwan_action_showcase_v2.py tests/test_nangongwan_action_showcase_v2.py
git commit -m "feat: validate isolated 450px showcase"
```

### Task 3: 生成、验证并人工审查正式450px成片

**Files:**
- Create locally: `work/nangongwan-action-showcase-450px/background.png`
- Create locally: `work/nangongwan-action-showcase-450px/clips/*.mp4`
- Create locally: `work/nangongwan-action-showcase-450px/nangongwan-action-showcase-450px-1600x900.mp4`
- Create locally: `work/nangongwan-action-showcase-450px/timeline.json`
- Create locally: `work/nangongwan-action-showcase-450px/validation-report.json`
- Create locally: `work/nangongwan-action-showcase-450px/review/contact-sheet.jpg`
- Create locally: `work/nangongwan-action-showcase-450px/review/*.png`

**Interfaces:**
- Consumes: Task2 CLI, schema2 timeline, fixed background and16-item source hash inventory。
- Produces: one user-review draft plus validation/report/review artifacts; no tracked artifact commit。

- [ ] **Step 1: 记录旧版四个关键文件哈希**

Run before building:

```powershell
$old = 'work\nangongwan-action-showcase-v2'
Get-FileHash -Algorithm SHA256 `
  "$old\nangongwan-action-showcase-v2-1600x900.mp4", `
  "$old\timeline.json", `
  "$old\validation-report.json", `
  "$old\review\contact-sheet.jpg"
```

Expected hashes:

```text
master     a6c4e8355a8ef823c48b09ab6233cce3ccb51a7b3962cc5455a6de0f268eb867
timeline   c78ac8d021b48b7afd7ac6b7a678720ff57ff9fe30bdf0c4886075235c6449d1
report     9a6be89163bc7fc05d5e3e2253658fc3bc7eb3e670e31d67b4744e9a6ab6bd95
sheet      24f1ec39ed848d084a0ba04bb487f4a4bd56cc78ab5f414806ec6c5442975fe9
```

If any hash differs, stop and report the external change before building。

- [ ] **Step 2: 跑聚焦测试和一次完整测试套件**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q
& .\.venv\Scripts\python.exe -m pytest -q --ignore=tests/integration/test_frozen_smoke.py
```

Expected: both commands exit0 with pristine output。Do not rerun the full suite merely to obtain different timing output。

- [ ] **Step 3: 通过暂存验证和原子发布生成新版本**

```powershell
& .\.venv\Scripts\python.exe tools\render_nangongwan_action_showcase_v2.py `
  --build-all `
  --background 'C:\Users\23644\AppData\Local\Temp\codex-clipboard-fa2f4101-2de0-4c4a-a1c9-01fc1c2a4412.png'
```

Expected: prints `Built, validated, and published ...\work\nangongwan-action-showcase-450px\nangongwan-action-showcase-450px-1600x900.mp4` and exits0。No sibling staging/backup directory may remain。

- [ ] **Step 4: 运行不依赖Temp截图的正式验证**

```powershell
& .\.venv\Scripts\python.exe tools\render_nangongwan_action_showcase_v2.py --validate-only
```

Expected: exit0 and `allPassed=true`。Inspect `validation-report.json` and require:

```text
13/13 checks true, including renderGeometry and sourceIntegrity;
2473 encoded center frames compared, zero failed;
2473 frames x four outside regions checked, zero failed;
sourceSpriteSize 192x208;
renderedSpriteRectangle 575,206,450,488;
exact15 clips,45 review PNGs,one4800x540 contact sheet;
one1600x900 H.264 High/yuv420p/SAR1:1/30fps/2473-frame video;
one48k stereo silent AAC aligned to video; no other streams or text sidecars.
```

- [ ] **Step 5: 复查旧版未变化**

Repeat Step1 `Get-FileHash` command。Expected: all four hashes remain byte-for-byte identical。Also run:

```powershell
git status --short
```

Expected: only the three known pre-existing unstaged files are shown; ignored450px artifacts are not staged。

- [ ] **Step 6: 人工审片**

Open at original resolution:

```text
work/nangongwan-action-showcase-450px/review/contact-sheet.jpg
work/nangongwan-action-showcase-450px/review/02-standing-chestnut-middle.png
work/nangongwan-action-showcase-450px/review/04-cinematic-36-middle.png
work/nangongwan-action-showcase-450px/review/06-anchored-48-middle.png
work/nangongwan-action-showcase-450px/review/08-v9-small-moon-middle.png
work/nangongwan-action-showcase-450px/review/10-moon-184-middle.png
work/nangongwan-action-showcase-450px/review/12-moon-232-middle.png
work/nangongwan-action-showcase-450px/review/14-moon-full-middle.png
```

Confirm the450×488 canvas is visibly larger, centered at `(800,450)`, never clipped, and has no transparent-edge color bleed。Confirm background/taskbar unchanged, three moon versions distinct, blink visible, and no text/black/checkerboard/extra transitions。

- [ ] **Step 7: 停在用户审片门**

Deliver clickable paths to the450px MP4, contact sheet, timeline and validation report。Do not merge, upload, install, delete the small version, create a vertical cut or change the action design before user review。
