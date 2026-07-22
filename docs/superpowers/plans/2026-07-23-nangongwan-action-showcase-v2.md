# 南宫婉纯动作展示视频 V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一支约82.43秒、只在用户指定桌面截图中央依次播放八次眨眼与七段南宫婉动作的1600×900无文字横屏视频。

**Architecture:** 新增一个与旧制作纪录片完全隔离的展示渲染库和一个薄CLI。渲染库只负责素材时序、30fps重采样、固定坐标alpha合成、MP4片段与最终验证；CLI固化背景、按15段顺序生成、拼接并加入静音AAC。复用现有 `ActionSource`、`TimedFrames`、`read_action()` 与 `run_ffmpeg()`，不复用旧卡片、ASS、蓝色背景或制作纪录片镜头表。

**Tech Stack:** Python 3.12、Pillow、FFmpeg/FFprobe、标准库 `dataclasses/hashlib/json/pathlib/subprocess`、pytest。

## Global Constraints

- 唯一背景是1600×900 RGB截图，SHA-256必须为 `1bca26d93bf3126b3c8be30e2b5f944b4912a4032ac55990b72cfb3d99ba745a`。
- 192×208宠物画布保持100%原生尺寸，左上角固定 `(704, 346)`，中心固定 `(800, 450)`。
- 不得生成或烧录标题、字幕、卡片、故事文字、投票、旁白、音乐、转场或旧蓝色桌面背景。
- 固定15段：8个15帧眨眼缓冲与7个主动作；全部硬切且每段只播放一次。
- 七个主动作顺序固定：站立吃栗子、36帧版、48帧版、V9小圆月、184月亮含栗、232月亮含栗、满屏月面含栗。
- 三个月亮含栗片段必须各270帧并使用相同的源动作时序映射。
- 禁止读取 `07-private-anime-reference-DO-NOT-PUBLISH/`；历史素材只读；旧V1视频不覆盖。
- 输出1600×900、30fps、H.264 High、yuv420p、SAR1:1、2473帧、约82.433333秒、48kHz双声道静音AAC、`+faststart`。
- 所有输出写入Git忽略的 `work/nangongwan-action-showcase-v2/`，不修改安装包、不上传仓库。

---

## File Structure

- Create: `tools/nangongwan_action_showcase_v2.py` — 数据模型、源动作装配、眨眼、重采样、固定背景合成、片段编码、拼接与验证。
- Create: `tools/render_nangongwan_action_showcase_v2.py` — 精确素材定位、背景固化、15段构建、CLI与审片工件。
- Create: `tests/test_nangongwan_action_showcase_v2.py` — 顺序、帧数、时序、中心坐标、背景完整性、编码和隐私测试。
- Create locally: `work/nangongwan-action-showcase-v2/background.png` — 用户截图的SHA-256固定副本。
- Create locally: `work/nangongwan-action-showcase-v2/clips/*.mp4` — 15段无音频中间片段。
- Create locally: `work/nangongwan-action-showcase-v2/nangongwan-action-showcase-v2-1600x900.mp4` — 新首稿。
- Create locally: `work/nangongwan-action-showcase-v2/timeline.json` — 15段的源帧、输出帧和累计帧边界。
- Create locally: `work/nangongwan-action-showcase-v2/review/contact-sheet.jpg` — 每段首中尾审片图。
- Create locally: `work/nangongwan-action-showcase-v2/validation-report.json` — 媒体和视觉契约结果。

### Task 1: 固定背景、素材与15段顺序契约

**Files:**
- Create: `tools/nangongwan_action_showcase_v2.py`
- Create: `tools/render_nangongwan_action_showcase_v2.py`
- Create: `tests/test_nangongwan_action_showcase_v2.py`

**Interfaces:**
- Produces: `ShowcaseSource`, `ShowcaseSegment`, `ShowcasePlan`, `build_showcase_plan(root: Path, background_source: Path) -> ShowcasePlan`, `copy_verified_background(source: Path, output: Path) -> str`。
- Consumes: `ActionSource` from `tools.nangongwan_rooftop_making_of` and `work/nangongwan-moonlit-rooftop-history/`。

- [ ] **Step 1: 写入背景与顺序失败测试**

```python
from pathlib import Path

import pytest
from PIL import Image

from tools.render_nangongwan_action_showcase_v2 import build_showcase_plan
from tools.nangongwan_action_showcase_v2 import copy_verified_background

ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = Path(r"C:\Users\23644\AppData\Local\Temp\codex-clipboard-fa2f4101-2de0-4c4a-a1c9-01fc1c2a4412.png")


def test_showcase_plan_has_exact_fifteen_segments_and_output_frames():
    plan = build_showcase_plan(ROOT, BACKGROUND)
    assert [segment.id for segment in plan.segments] == [
        "blink-00", "standing-chestnut", "blink-01", "cinematic-36",
        "blink-02", "anchored-48", "blink-03", "v9-small-moon",
        "blink-04", "moon-184", "blink-05", "moon-232",
        "blink-06", "moon-full", "blink-07",
    ]
    assert [segment.output_frames for segment in plan.segments] == [
        15, 62, 15, 273, 15, 288, 15, 920, 15, 270, 15, 270, 15, 270, 15
    ]
    assert plan.total_frames == 2473


def test_copy_verified_background_rejects_wrong_pixels(tmp_path):
    wrong = tmp_path / "wrong.png"
    Image.new("RGB", (1600, 900), "black").save(wrong)
    with pytest.raises(ValueError, match="background SHA-256"):
        copy_verified_background(wrong, tmp_path / "background.png")
```

- [ ] **Step 2: 运行测试确认RED**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q`

Expected: collection fails because the two new modules do not exist.

- [ ] **Step 3: 建立数据模型和精确素材映射**

In `tools/nangongwan_action_showcase_v2.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tools.nangongwan_rooftop_making_of import ActionSource

FPS = 30
FRAME_SIZE = (1600, 900)
SPRITE_SIZE = (192, 208)
SPRITE_ORIGIN = (704, 346)
BACKGROUND_SHA256 = "1bca26d93bf3126b3c8be30e2b5f944b4912a4032ac55990b72cfb3d99ba745a"


@dataclass(frozen=True)
class ShowcaseSource:
    kind: Literal["blink", "action", "sequence"]
    actions: tuple[ActionSource, ...]


@dataclass(frozen=True)
class ShowcaseSegment:
    id: str
    source: ShowcaseSource
    output_frames: int


@dataclass(frozen=True)
class ShowcasePlan:
    background_source: Path
    segments: tuple[ShowcaseSegment, ...]

    @property
    def total_frames(self) -> int:
        return sum(segment.output_frames for segment in self.segments)
```

`build_showcase_plan()` must define these sources exactly:

```text
blink        04-moon-background-variants/01-small-moon-current/spritesheet.webp + pet.json + idle
standing     06-standing-chestnut-easter-egg/standing-chestnut-10frames.webp + action.json + tasteCake (standalone, start0)
cinematic    01-cinematic-36f-v2.4.1/spritesheet.webp + pet.json + moonlitChestnut
anchored     02-anchored-48f-v1/complete-archive/spritesheet.webp + pet.json + moonlitChestnut
v9 sequence  04-moon-background-variants/01-small-moon-current spritesheet/pet.json actions ordered by preview-sequence-v9.json
moon-184     04-moon-background-variants/02-full-circle-184 + rooftopChestnut
moon-232     04-moon-background-variants/03-cropped-disc-232 + rooftopChestnut
moon-full    04-moon-background-variants/04-full-frame-moon-surface + rooftopChestnut
```

Validate every path exists, every action id exists, no resolved source contains `anime-reference` or `DO-NOT-PUBLISH`, V9 contains166 source frames/30680ms, and the moon sources each contain44 frames/8990ms.

- [ ] **Step 4: 实现背景固化并跑GREEN**

`copy_verified_background()` must hash the encoded source bytes against the fixed SHA before any decode, open through Pillow, require exactly `(1600, 900)` and mode `RGB`, then copy the original PNG byte-for-byte to `background.png`. Reopen the copy and confirm its encoded hash and decoded RGB pixel bytes both equal the source. Reject RGBA, palette, resized or re-encoded substitutes even when they look similar.

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q`

Expected: 2 passed.

- [ ] **Step 5: 提交契约**

```powershell
git add tools/nangongwan_action_showcase_v2.py tools/render_nangongwan_action_showcase_v2.py tests/test_nangongwan_action_showcase_v2.py
git commit -m "test: define simple action showcase contract"
```

### Task 2: 实现眨眼、动作重采样和固定中心合成

**Files:**
- Modify: `tools/nangongwan_action_showcase_v2.py`
- Modify: `tests/test_nangongwan_action_showcase_v2.py`

**Interfaces:**
- Produces: `SegmentFrames`, `make_blink(idle: TimedFrames) -> SegmentFrames`, `resample_action(timed: TimedFrames, output_frames: int) -> SegmentFrames`, `compose_frame(background: Image.Image, sprite: Image.Image) -> Image.Image`, `build_segment_frames(segment: ShowcaseSegment, background: Image.Image) -> SegmentFrames`。
- Consumes: `TimedFrames`, `read_action()` from `tools.nangongwan_rooftop_making_of`。

- [ ] **Step 1: 写入眨眼与中心像素失败测试**

```python
from PIL import Image, ImageChops

from tools.nangongwan_action_showcase_v2 import compose_frame, make_blink


def test_blink_is_exactly_fifteen_frames_and_returns_to_open_pose(idle_frames):
    blink = make_blink(idle_frames)
    assert len(blink.frames) == 15
    assert blink.frames[0].tobytes() == idle_frames.frames[0].tobytes()
    assert blink.frames[-1].tobytes() == idle_frames.frames[0].tobytes()
    assert blink.frames[6].tobytes() != blink.frames[0].tobytes()


def test_compose_frame_changes_only_the_centered_sprite_rectangle():
    background = Image.effect_noise((1600, 900), 80).convert("RGB")
    sprite = Image.new("RGBA", (192, 208), (200, 50, 80, 128))
    composed = compose_frame(background, sprite)
    changed_bounds = ImageChops.difference(background, composed).getbbox()
    assert changed_bounds is not None
    left, top, right, bottom = changed_bounds
    assert 704 <= left < right <= 896
    assert 346 <= top < bottom <= 554
    assert not np.array_equal(before[346:554, 704:896], after[346:554, 704:896])
```

- [ ] **Step 2: 运行测试确认RED**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q`

Expected: failures for undefined `make_blink`, `compose_frame`, and fixtures.

- [ ] **Step 3: 实现15帧眨眼与累计时序重采样**

```python
@dataclass(frozen=True)
class SegmentFrames:
    frames: tuple[Image.Image, ...]


BLINK_SOURCE_INDICES = (0, 0, 0, 1, 2, 3, 2, 1, 0, 0, 0, 0, 0, 0, 0)


def make_blink(idle: TimedFrames) -> SegmentFrames:
    if len(idle.frames) < 4:
        raise ValueError("idle action needs at least four frames")
    return SegmentFrames(tuple(idle.frames[index].copy() for index in BLINK_SOURCE_INDICES))
```

`resample_action()` must calculate each output frame's source timestamp at the output-frame midpoint, select the first cumulative source duration greater than that timestamp, and explicitly force output frame0/source frame0 and output last/source last. It must reject nonpositive output counts, missing frames, duration-count mismatches, and non-192×208 inputs. Concatenating the eleven V9 actions must retain every action's source order and duration before one cumulative resample to920 frames. The three moon actions must use one shared tuple of source-time sample positions so their mappings are identical.

- [ ] **Step 4: 实现固定中心alpha合成并跑GREEN**

`compose_frame()` must require a1600×900 RGB background and192×208 RGBA sprite, copy the background, and call `alpha_composite(sprite, SPRITE_ORIGIN)` on an RGBA working copy before returning RGB. No scale, crop, shadow, label, overlay, color transform, or background redraw is allowed.

Add exact tests:

```python
def test_all_segment_frame_counts_and_moon_mapping_are_exact(showcase_plan, background_image):
    built = {s.id: build_segment_frames(s, background_image) for s in showcase_plan.segments}
    assert {key: len(built[key].frames) for key in ("moon-184", "moon-232", "moon-full")} == {
        "moon-184": 270, "moon-232": 270, "moon-full": 270
    }
    assert all(len(built[s.id].frames) == s.output_frames for s in showcase_plan.segments)
```

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q`

Expected: all Task1-2 tests pass.

- [ ] **Step 5: 提交帧合成器**

```powershell
git add tools/nangongwan_action_showcase_v2.py tests/test_nangongwan_action_showcase_v2.py
git commit -m "feat: compose centered showcase frames"
```

### Task 3: 编码15段并生成无文字完整视频

**Files:**
- Modify: `tools/nangongwan_action_showcase_v2.py`
- Modify: `tools/render_nangongwan_action_showcase_v2.py`
- Modify: `tests/test_nangongwan_action_showcase_v2.py`

**Interfaces:**
- Produces: `VideoProbe`, `AudioProbe`, `MediaProbe`, `probe_media(path: Path, *, count_frames: bool = False) -> MediaProbe`, `write_silent_video(frames: SegmentFrames, output: Path) -> None`, `concat_clips(clips: tuple[Path, ...], output: Path) -> None`, `add_silent_aac(video: Path, output: Path, *, expected_frames: int) -> None`, `build_showcase(root: Path, background_source: Path) -> Path`。
- Consumes: fifteen `SegmentFrames` from Task2。

- [ ] **Step 1: 写入编码与无文字输出失败测试**

```python
def test_two_segment_encode_has_exact_frames_and_no_subtitle_stream(tmp_path, tiny_segments):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    joined = tmp_path / "joined.mp4"
    final = tmp_path / "final.mp4"
    write_silent_video(tiny_segments[0], first)
    write_silent_video(tiny_segments[1], second)
    concat_clips((first, second), joined)
    add_silent_aac(joined, final, expected_frames=30)
    probe = probe_media(final, count_frames=True)
    assert probe.video.nb_read_frames == 30
    assert probe.video.width == 1600 and probe.video.height == 900
    assert probe.video.codec == "h264" and probe.video.profile == "High"
    assert probe.audio.codec == "aac" and probe.audio.sample_rate == 48000
    assert probe.subtitle_streams == 0
```

- [ ] **Step 2: 运行测试确认RED**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q`

Expected: undefined encoder/concat/probe functions.

- [ ] **Step 3: 实现无音频片段、拼接和静音AAC**

Define frozen probe dataclasses with exactly the fields consumed by tests and validation: `VideoProbe(width, height, codec, profile, pixel_format, sample_aspect_ratio, frame_rate, nb_read_frames)`, `AudioProbe(codec, sample_rate, channels)`, and `MediaProbe(video, audio, subtitle_streams, data_streams)`. `probe_media()` must parse `ffprobe -show_streams -of json`, require exactly one video stream, allow zero or one audio stream according to the caller, and parse rational frame rate without floating-point equality.

`write_silent_video()` streams1600×900 RGB24 frames to FFmpeg stdin at30fps and encodes `libx264 -profile:v high -level 4.1 -pix_fmt yuv420p -r 30 -an -movflags +faststart` with exact `-frames:v` count. `concat_clips()` writes an ASCII-safe concat list with resolved absolute paths and validates every input has identical codec geometry/timebase. `add_silent_aac()` adds `anullsrc=channel_layout=stereo:sample_rate=48000`, maps video without changing frame count, encodes AAC192k, uses `-shortest` and `+faststart`, and requires the output frame count to equal its explicit `expected_frames` argument. The tiny test passes30; `build_showcase()` passes2473.

- [ ] **Step 4: 实现CLI完整构建和时间线**

CLI arguments:

```text
--background PATH   default exact user Temp PNG
--build-all         copy/verify background, build15 clips, timeline, final, review sheet
--validate-only     validate existing V2 output without rebuilding
```

`timeline.json` must contain `schemaVersion=1`, background SHA, frame size, sprite rectangle, totalFrames2473, and fifteen entries with id, source action ids, startFrame, endFrame, outputFrames and sourceDurationMs. It must not contain title/caption/text fields.

Run:

```powershell
& .\.venv\Scripts\python.exe tools\render_nangongwan_action_showcase_v2.py --build-all
```

Expected: final MP4 plus15 clips and timeline under `work/nangongwan-action-showcase-v2/`; no `.ass`, subtitle stream or old blue-background file.

- [ ] **Step 5: 提交编码器**

```powershell
git add tools/nangongwan_action_showcase_v2.py tools/render_nangongwan_action_showcase_v2.py tests/test_nangongwan_action_showcase_v2.py
git commit -m "feat: render simple Nangong Wan showcase"
```

### Task 4: 验证背景、中心、顺序和最终媒体

**Files:**
- Modify: `tools/nangongwan_action_showcase_v2.py`
- Modify: `tools/render_nangongwan_action_showcase_v2.py`
- Modify: `tests/test_nangongwan_action_showcase_v2.py`
- Create locally: `work/nangongwan-action-showcase-v2/review/contact-sheet.jpg`
- Create locally: `work/nangongwan-action-showcase-v2/validation-report.json`

**Interfaces:**
- Produces: `validate_showcase(master: Path, plan: ShowcasePlan, timeline: Path) -> dict[str, object]`, `extract_review_frames(master: Path, timeline: Path, output: Path) -> tuple[Path, ...]`。
- Consumes: final MP4, fixed background and timeline from Task3。

- [ ] **Step 1: 写入最终门禁失败测试**

```python
def test_validation_requires_every_v2_gate(valid_showcase_fixture):
    report = validate_showcase(**valid_showcase_fixture)
    assert report["allPassed"] is True
    assert report["checks"] == {
        "backgroundHash": True,
        "segmentOrder": True,
        "segmentFrameCounts": True,
        "totalFrames": True,
        "videoGeometry": True,
        "videoEncoding": True,
        "silentAudio": True,
        "noTextSidecarsOrStreams": True,
        "sourcePrivacy": True,
        "centeredComposition": True,
        "moonFrameParity": True,
    }
```

- [ ] **Step 2: 运行测试确认RED**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q`

Expected: undefined validator and review extractor.

- [ ] **Step 3: 实现自动门禁和接触表**

`validate_showcase()` must fail closed unless:

```text
background hash fixed; exact15 ids/order; exact output frame vector;
timeline continuous0..2473; three moon clips270 each;
one1600x900 H.264 High/yuv420p/SAR1:1/30fps/2473-frame video;
one48k stereo AAC with max_volume <= -90dBFS; no subtitle/data stream;
moov atom before mdat; no ASS/SRT/VTT sidecar in output;
all resolved sources exist and none contain anime-reference/DO-NOT-PUBLISH;
every pre-encode composed test frame changes pixels only inside704:896,346:554.
```

For encoded background fidelity, decode one blink frame and each main segment midpoint, mask the192×208 sprite rectangle, and require outside-region SSIM>=0.995 against the fixed screenshot. `extract_review_frames()` must extract first/middle/last frames for all15 segments and build a15-column×3-row contact sheet without adding labels to the video itself.

- [ ] **Step 4: 运行完整验证与人工检查**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_action_showcase_v2.py -q
& .\.venv\Scripts\python.exe -m pytest -q --ignore=tests/integration/test_frozen_smoke.py
& .\.venv\Scripts\python.exe tools\render_nangongwan_action_showcase_v2.py --validate-only
```

Expected: focused and full tests pass; validator exit0 and `allPassed=true`. Inspect the original-size first/middle/last frame set and contact sheet for exact background, strict center, 100% scale, visible blink, no text/black/checkerboard, complete V9 and three distinct moon backgrounds.

- [ ] **Step 5: 提交验证逻辑并停止在用户审片门**

```powershell
git add tools/nangongwan_action_showcase_v2.py tools/render_nangongwan_action_showcase_v2.py tests/test_nangongwan_action_showcase_v2.py
git commit -m "test: validate simple action showcase"
```

Deliver clickable paths to the new MP4, contact sheet, timeline and validation report. Do not modify/delete V1, add voice/music/text, make a vertical cut, update installer, or upload repositories before the user reviews V2.
