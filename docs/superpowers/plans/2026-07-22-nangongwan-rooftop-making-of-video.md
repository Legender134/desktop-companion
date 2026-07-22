# 南宫婉“月下屋檐”制作过程视频实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一支约4分40秒、1920×1080、无配音但具备完整字幕和正式时序的南宫婉“月下屋檐”制作过程审片版。

**Architecture:** 新增一个只读素材渲染库和一个命令行编排器。渲染库负责从历史WebP／JSON读取精确动作、统一合成桌面背景、生成MP4与ASS字幕；编排器按六章节镜头表构建缺失素材、章节片段、最终母版和验证报告。所有输出只写入Git忽略的 `work/nangongwan-rooftop-making-of-video/`，不改安装资源和历史归档。

**Tech Stack:** Python 3.12、Pillow、标准库 `subprocess/json/dataclasses/pathlib`、FFmpeg/FFprobe、pytest。

## Global Constraints

- 六个阶段固定顺序：站立吃栗子→36帧影视版→48帧原地版→第一版屋檐常驻→V9小圆月全部动作→三种新月亮背景。
- 不展示下半身整块固定、多手、明显位置错乱等严重制作事故。
- 不读取或引用 `07-private-anime-reference-DO-NOT-PUBLISH/` 中的动漫视频。
- 36帧与48帧版本完整播放一次；V9完整展示入口、九种常驻动作和退出。
- 三种新月亮背景只播放同一套8990毫秒 `rooftopChestnut`，人物、动作、位置与时序必须一致。
- 首稿不生成AI旁白、不使用来源不明的音乐；输出带48kHz双声道静音AAC轨，便于后续替换旁白。
- 输出为1920×1080、30fps、H.264 High Profile、yuv420p、AAC、`+faststart`。
- 不修改、覆盖或重新编码历史归档源文件；不进入安装包、GitHub或Gitee。
- 真实反馈只使用脱敏后的重排文字，不嵌入原始聊天截图。

---

## File Structure

- Create: `tools/nangongwan_rooftop_making_of.py` — 数据模型、图集读取、桌面合成、MP4/静帧镜头、ASS字幕、FFprobe验证。
- Create: `tools/render_nangongwan_rooftop_making_of.py` — 六章镜头表、源文件定位、生成流程和命令行入口。
- Create: `tests/test_nangongwan_rooftop_making_of.py` — 时间线、历史素材、月亮公平对比、隐私边界和短视频编码测试。
- Create locally: `work/nangongwan-rooftop-making-of-video/master-v1-no-voice-1920x1080.mp4` — 首次审片母版。
- Create locally: `work/nangongwan-rooftop-making-of-video/master-v1.ass` — 后续可编辑字幕。
- Create locally: `work/nangongwan-rooftop-making-of-video/master-v1-timeline.json` — 精确章节、镜头、源文件和字幕时码。
- Create locally: `work/nangongwan-rooftop-making-of-video/intermediates/*.mp4` — 动作与章节中间片段。
- Create locally: `work/nangongwan-rooftop-making-of-video/review-frames/*.jpg` — 章节首尾和字幕安全区检查图。
- Create locally: `work/nangongwan-rooftop-making-of-video/validation-report.json` — 编码、时长、素材和隐私验证结果。

---

### Task 1: 建立时间线与素材安全契约

**Files:**
- Create: `tests/test_nangongwan_rooftop_making_of.py`
- Create: `tools/nangongwan_rooftop_making_of.py`
- Create: `tools/render_nangongwan_rooftop_making_of.py`

**Interfaces:**
- Produces: `ActionSource`, `ShotSpec`, `ChapterSpec`, `VideoPlan`, `build_video_plan(root: Path) -> VideoPlan`。
- Consumes: 历史素材库根目录 `work/nangongwan-moonlit-rooftop-history/`。

- [ ] **Step 1: 写入时间线失败测试**

```python
from pathlib import Path

from tools.render_nangongwan_rooftop_making_of import build_video_plan


ROOT = Path(__file__).resolve().parents[1]


def test_video_plan_has_the_approved_six_chapters_and_exact_duration():
    plan = build_video_plan(ROOT)
    assert [chapter.id for chapter in plan.chapters] == [
        "standing_chestnut",
        "cinematic_36",
        "anchored_48",
        "persistent_v1",
        "v9_small_moon",
        "moon_variants",
    ]
    assert [chapter.duration_ms for chapter in plan.chapters] == [
        18_000, 40_000, 40_000, 40_000, 87_000, 55_000
    ]
    assert plan.duration_ms == 280_000


def test_video_plan_never_reads_private_anime_or_rejected_failure_media():
    plan = build_video_plan(ROOT)
    source_text = "\n".join(str(path).lower() for path in plan.source_paths)
    assert "07-private-anime-reference-do-not-publish" not in source_text
    assert "anime-reference" not in source_text
    assert "rejected-transition" not in source_text
    assert "seat-anchor-diagnostic" not in source_text
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_rooftop_making_of.py -q
```

Expected: collection fails because the two new modules do not exist.

- [ ] **Step 3: 建立不可变数据模型**

In `tools/nangongwan_rooftop_making_of.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping


@dataclass(frozen=True)
class ActionSource:
    atlas: Path
    manifest: Path
    action_id: str
    manifest_kind: Literal["pet", "action"] = "pet"
    atlas_start_frame: int | None = None


@dataclass(frozen=True)
class ShotSpec:
    id: str
    kind: Literal["action", "video", "still", "card"]
    duration_ms: int
    source: Path | ActionSource | None
    title: str = ""
    caption: str = ""
    loop: bool = False


@dataclass(frozen=True)
class ChapterSpec:
    id: str
    title: str
    duration_ms: int
    shots: tuple[ShotSpec, ...]


@dataclass(frozen=True)
class VideoPlan:
    chapters: tuple[ChapterSpec, ...]
    action_sources: Mapping[str, ActionSource]

    @property
    def duration_ms(self) -> int:
        return sum(chapter.duration_ms for chapter in self.chapters)

    @property
    def source_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for chapter in self.chapters:
            for shot in chapter.shots:
                if isinstance(shot.source, Path):
                    paths.append(shot.source)
                elif isinstance(shot.source, ActionSource):
                    paths.extend((shot.source.atlas, shot.source.manifest))
        return tuple(paths)
```

In `tools/render_nangongwan_rooftop_making_of.py`, define `CHAPTER_DURATIONS` exactly as `(18000, 40000, 40000, 40000, 87000, 55000)` and build six chapters whose shot durations add exactly to each chapter duration. Use only these source roots:

```python
HISTORY = root / "work" / "nangongwan-moonlit-rooftop-history"
OUTPUT = root / "work" / "nangongwan-rooftop-making-of-video"
```

The first implementation may use one placeholder `card` shot per chapter; later tasks replace each placeholder while preserving chapter totals.

`build_video_plan()` must populate `action_sources` from the approved archive with these stable keys and exact sources:

```text
standing   06-standing-chestnut-easter-egg/standing-chestnut-10frames.webp + action.json + tasteCake
cinematic  01-cinematic-36f-v2.4.1/spritesheet.webp + pet.json + moonlitChestnut
anchored   02-anchored-48f-v1/complete-archive/spritesheet.webp + pet.json + moonlitChestnut
small      04-moon-background-variants/01-small-moon-current/spritesheet.webp + pet.json + rooftopChestnut
moon_184   04-moon-background-variants/02-full-circle-184/spritesheet.webp + pet.json + rooftopChestnut
moon_232   04-moon-background-variants/03-cropped-disc-232/spritesheet.webp + pet.json + rooftopChestnut
moon_full  04-moon-background-variants/04-full-frame-moon-surface/spritesheet.webp + pet.json + rooftopChestnut
```

The `standing` source uses `manifest_kind="action"` and `atlas_start_frame=0` because its archive is a cropped ten-frame strip even though `action.json` retains the original row metadata. All other sources use the default `pet` manifest and atlas coordinates.

Also register these existing video sources explicitly: `persistent_v1` is `03-persistent-rooftop-revisions/render-history-v2-v9/moonlit-rooftop-all-actions.mp4`; `v9_all_actions` is `03-persistent-rooftop-revisions/render-history-v2-v9/moonlit-rooftop-transparent-v9.mp4`; V9 labels come from the sibling `preview-sequence-v9.json`. Do not substitute `smooth-v2/v3` or transparent v4–v8 for either approved stage.

- [ ] **Step 4: 运行测试确认时间线通过**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_rooftop_making_of.py -q`

Expected: 2 passed.

- [ ] **Step 5: 提交时间线契约**

```powershell
git add tools/nangongwan_rooftop_making_of.py tools/render_nangongwan_rooftop_making_of.py tests/test_nangongwan_rooftop_making_of.py
git commit -m "test: define Nangong Wan making-of timeline"
```

---

### Task 2: 实现动作读取与统一桌面素材渲染

**Files:**
- Modify: `tools/nangongwan_rooftop_making_of.py`
- Modify: `tests/test_nangongwan_rooftop_making_of.py`

**Interfaces:**
- Consumes: `ActionSource`。
- Produces: `TimedFrames`, `read_action(source: ActionSource) -> TimedFrames`, `compose_desktop(frame: Image.Image) -> Image.Image`, `write_action_mp4(timed: TimedFrames, out: Path) -> None`。

- [ ] **Step 1: 写入动作读取和编码测试**

```python
import json
import subprocess
import pytest
from PIL import Image, ImageDraw

from tools.nangongwan_rooftop_making_of import ActionSource, TimedFrames, read_action, write_action_mp4


@pytest.fixture
def synthetic_timed_frames():
    return TimedFrames(
        frames=(
            Image.new("RGBA", (192, 208), (70, 110, 170, 255)),
            Image.new("RGBA", (192, 208), (110, 150, 210, 255)),
        ),
        durations_ms=(200, 300),
    )


def test_read_action_supports_cross_row_frames_and_exact_durations(tmp_path):
    atlas = Image.new("RGBA", (192 * 16, 208 * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(atlas)
    for linear, color in zip((15, 16, 17), ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))):
        row, column = divmod(linear, 16)
        draw.rectangle((column * 192, row * 208, column * 192 + 191, row * 208 + 207), fill=color)
    atlas_path = tmp_path / "atlas.webp"
    atlas.save(atlas_path, "WEBP", lossless=True)
    manifest_path = tmp_path / "pet.json"
    manifest_path.write_text(json.dumps({"actions": {"demo": {"row": 0, "startColumn": 15, "frameCount": 3, "frameDurations": [100, 200, 300]}}}), encoding="utf-8")
    timed = read_action(ActionSource(atlas_path, manifest_path, "demo"))
    assert timed.durations_ms == (100, 200, 300)
    assert timed.duration_ms == 600
    assert [frame.getpixel((96, 104))[:3] for frame in timed.frames] == [(255, 0, 0), (0, 255, 0), (0, 0, 255)]


def test_write_action_mp4_produces_960x540_h264_with_exact_length(tmp_path, synthetic_timed_frames):
    output = tmp_path / "clip.mp4"
    write_action_mp4(synthetic_timed_frames, output)
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)]))
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"], video["codec_name"]) == (960, 540, "h264")
    assert abs(float(probe["format"]["duration"]) - synthetic_timed_frames.duration_ms / 1000) < 0.03
```

- [ ] **Step 2: 运行定向测试确认失败**

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_rooftop_making_of.py -q`

Expected: failures for undefined `TimedFrames`, `read_action`, and `write_action_mp4`.

- [ ] **Step 3: 实现逐帧读取和桌面合成**

Add to `tools/nangongwan_rooftop_making_of.py`:

```python
@dataclass(frozen=True)
class TimedFrames:
    frames: tuple[Image.Image, ...]
    durations_ms: tuple[int, ...]

    @property
    def duration_ms(self) -> int:
        return sum(self.durations_ms)


def read_action(source: ActionSource) -> TimedFrames:
    document = json.loads(source.manifest.read_text(encoding="utf-8"))
    action = document if source.manifest_kind == "action" else document["actions"][source.action_id]
    durations = tuple(action.get("frameDurations") or [action["frameMs"]] * action["frameCount"])
    if len(durations) != action["frameCount"] or any(value <= 0 or value % 10 for value in durations):
        raise ValueError(f"invalid durations for {source.action_id}")
    start = source.atlas_start_frame
    if start is None:
        start = action["row"] * 16 + action.get("startColumn", 0)
    with Image.open(source.atlas) as atlas_source:
        atlas = atlas_source.convert("RGBA")
        frames = []
        for offset in range(action["frameCount"]):
            row, column = divmod(start + offset, 16)
            frames.append(atlas.crop((column * 192, row * 208, (column + 1) * 192, (row + 1) * 208)))
    return TimedFrames(tuple(frames), durations)
```

`compose_desktop()` must produce a 960×540 RGB frame: restrained blue desktop gradient, centered 432×468 pet area, and a visible bottom taskbar with four generic icons. Reuse the composition geometry from `tools/preview_nangongwan_rooftop_moon_vote.py::_desktop_frame` without importing private anime references.

`write_action_mp4()` streams RGB24 frames to FFmpeg at100fps, repeats each frame `duration_ms // 10` times, encodes H.264/yuv420p, disables audio and writes `+faststart`. Raise `CalledProcessError` on nonzero exit.

Before reading pixels, validate that the atlas width is exactly `16 * 192` for full atlases or `frameCount * 192` for a cropped strip, its height is a multiple of208, and every requested crop remains within bounds. `manifest_kind="action"` is only valid together with an explicit `atlas_start_frame`.

- [ ] **Step 4: 运行测试并生成五段缺失动作素材**

Run tests, then call the renderer for:

```text
standing-chestnut.mp4                  10 frames / 2080 ms
cinematic-36.mp4                       36 frames / 9100 ms
moon-full-circle-184-chestnut.mp4      44 frames / 8990 ms
moon-cropped-disc-232-chestnut.mp4     44 frames / 8990 ms
moon-full-frame-chestnut.mp4           44 frames / 8990 ms
```

Expected: all files under `work/nangongwan-rooftop-making-of-video/intermediates/actions/`, 960×540 H.264, exact duration tolerance ±30ms.

- [ ] **Step 5: 增加月亮公平性测试**

```python
def test_three_moon_variants_share_character_motion_and_timing():
    plan = build_video_plan(ROOT)
    variants = [plan.action_sources[name] for name in ("moon_184", "moon_232", "moon_full")]
    timed = [read_action(source) for source in variants]
    assert {item.durations_ms for item in timed} == {timed[0].durations_ms}
    assert all(item.duration_ms == 8990 and len(item.frames) == 44 for item in timed)
```

Additionally compare each frame after masking the known moon background and assert the character/roof foreground hashes are identical. The mask must come from the alpha difference between the small-moon and variant backgrounds; do not use visual similarity thresholds.

For this test, compute a foreground mask once from the union of non-background pixels in the archived transparent character/roof layer, then hash the RGBA bytes under that identical mask for each variant. Do not derive a different mask independently for each moon version, because that would make unequal foreground pixels disappear from comparison.

- [ ] **Step 6: 提交动作渲染器**

```powershell
git add tools/nangongwan_rooftop_making_of.py tests/test_nangongwan_rooftop_making_of.py
git commit -m "tools: render making-of action clips"
```

---

### Task 3: 构建六章镜头表和可编辑ASS字幕

**Files:**
- Modify: `tools/render_nangongwan_rooftop_making_of.py`
- Modify: `tools/nangongwan_rooftop_making_of.py`
- Modify: `tests/test_nangongwan_rooftop_making_of.py`

**Interfaces:**
- Consumes: Task 2 action MP4s and existing historical MP4s。
- Produces: `build_shots(root: Path) -> tuple[ShotSpec, ...]`, `write_ass(events: tuple[SubtitleEvent, ...], out: Path)`, `write_timeline_json(plan: VideoPlan, out: Path)`。

- [ ] **Step 1: 写入镜头和字幕契约测试**

```python
def test_every_chapter_shot_sum_matches_approved_duration():
    plan = build_video_plan(ROOT)
    for chapter in plan.chapters:
        assert sum(shot.duration_ms for shot in chapter.shots) == chapter.duration_ms


def test_v9_caption_explains_sequential_demo_vs_random_runtime():
    plan = build_video_plan(ROOT)
    chapter = next(item for item in plan.chapters if item.id == "v9_small_moon")
    captions = "\n".join(shot.caption for shot in chapter.shots)
    assert "九种动作会按权重随机出现" in captions
    assert "演示视频为方便观看而依次播放" in captions


def test_public_text_is_privacy_safe():
    plan = build_video_plan(ROOT)
    text = "\n".join((shot.title + "\n" + shot.caption) for chapter in plan.chapters for shot in chapter.shots)
    forbidden = ("c:\\users", "d:\\workspace", "gitee", "github token", "私人令牌")
    assert not any(value in text.lower() for value in forbidden)
```

- [ ] **Step 2: 定义精确镜头表**

Replace chapter placeholders with these exact shot totals:

```text
standing_chestnut  18,000 = 2,080 full action + 4,160 repeated close view + 11,760 still/card
cinematic_36       40,000 = 3,000 title + 9,100 full action + 9,100 labeled replay + 8,000 contact sheet + 10,800 feedback card
anchored_48        40,000 = 3,000 title + 9,600 full action + 9,600 labeled replay + 7,000 comparison still + 10,800 feedback card
persistent_v1      40,000 = 3,000 title + 12,000 historic video + 12,000 repeated resident section + 13,000 state-explanation card
v9_small_moon      87,000 = 3,000 title + 30,680 full sequence + 30,680 labeled replay + 14,000 nine-action grid + 8,640 random-play explanation
moon_variants      55,000 = 3,000 title + 8,990×3 action videos + 15,030 three-way comparison + 10,000 audience-choice card
```

For V9, derive action label intervals from `preview-sequence-v9.json::clipFrameRanges` and current `pet.json::frameDurations`; never estimate labels by dividing the 30.68-second video evenly.

- [ ] **Step 3: 实现ASS生成器**

Add:

```python
@dataclass(frozen=True)
class SubtitleEvent:
    start_ms: int
    end_ms: int
    text: str
    style: Literal["Title", "Caption", "Action", "Note"]


def ass_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{milliseconds // 10:02d}"
```

The ASS header must define `PlayResX=1920`, `PlayResY=1080`, `Microsoft YaHei UI`, bottom caption safe margin 76px, top action label margin 58px, white text with 70% black outline/shadow. Escape `{`, `}`, and newline before writing dialogue rows. All subtitles must remain editable in `master-v1.ass` even though the review MP4 burns them in.

- [ ] **Step 4: 输出时间线JSON并测试**

`master-v1-timeline.json` must include: schemaVersion=1, 280000ms total, six chapters, every shot start/end/source, every subtitle event, `voiceStatus="pending-openai-api-key"`, `aiVoiceDisclosureRequired=true`, and `privateAnimeUsed=false`.

Run: `& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_rooftop_making_of.py -q`

Expected: all unit tests pass.

- [ ] **Step 5: 提交镜头与字幕结构**

```powershell
git add tools/render_nangongwan_rooftop_making_of.py tools/nangongwan_rooftop_making_of.py tests/test_nangongwan_rooftop_making_of.py
git commit -m "feat: define making-of shots and subtitles"
```

---

### Task 4: 合成章节与无配音横屏母版

**Files:**
- Modify: `tools/nangongwan_rooftop_making_of.py`
- Modify: `tools/render_nangongwan_rooftop_making_of.py`
- Modify: `tests/test_nangongwan_rooftop_making_of.py`

**Interfaces:**
- Consumes: `ShotSpec` sequence、动作MP4、历史MP4、审计图。
- Produces: `run_ffmpeg(args: list[str]) -> None`, `render_shot()`, `concat_shots()`, `burn_ass_and_add_silence()`, final MP4。

- [ ] **Step 1: 写入FFmpeg命令与失败传播测试**

```python
def test_run_ffmpeg_raises_with_command_and_stderr(monkeypatch):
    def fail(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, b"", b"bad filter")
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="bad filter"):
        run_ffmpeg(["ffmpeg", "-version"])
```

`run_ffmpeg()` must call `subprocess.run(..., stdout=PIPE, stderr=PIPE, check=False)` and raise `RuntimeError` containing both the argument list and decoded stderr when the return code is nonzero. The synthetic integration test must build its own two short `TimedFrames` objects inside `tmp_path`; it must not depend on the history archive.

Add an integration test marked `@pytest.mark.integration` that renders two synthetic 500ms shots, concatenates them, burns one Chinese caption, adds silent AAC, and verifies a 1.0±0.05s 1920×1080 output.

- [ ] **Step 2: 实现四种镜头渲染**

`render_shot()` behavior:

- `action`/`video`: scale source to fit within 1600×900, place centered over the same restrained desktop background, preserve aspect ratio, and loop only when `ShotSpec.loop=True`.
- `still`: use `-loop 1`, fit within 1660×900, apply a 0.4%/second slow zoom capped at 104%, then end at exact duration.
- `card`: generate a 1920×1080 PNG with Pillow using the desktop background, short title, at most three lines of caption, and no decorative character art.
- Every shot encodes H.264/yuv420p/30fps with no audio. Normalize sample aspect ratio to1:1 and set color range toTV.

- [ ] **Step 3: 合成章节和母版**

For each shot, write `intermediates/shots/{index:02d}-{id}.mp4`. Concatenate through an FFmpeg concat demuxer using absolute paths escaped for single quotes. Burn `master-v1.ass` and add silence:

```text
ffmpeg -i master-base.mp4 \
  -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 \
  -vf "ass=master-v1.ass" \
  -map 0:v:0 -map 1:a:0 -c:v libx264 -profile:v high -level 4.1 \
  -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k -shortest -movflags +faststart \
  master-v1-no-voice-1920x1080.mp4
```

Use subprocess argument arrays, not a shell string. On Windows, pass the ASS path through FFmpeg's path escaping helper and verify that Chinese workspace paths succeed.

To make subtitle filtering reliable on Windows, copy the generated ASS file to an ASCII-only temporary directory before invoking the `ass` filter, escape drive-colon/backslash/single-quote characters for libass, and delete only that temporary copy after successful encoding. Keep the editable canonical `master-v1.ass` beside the master.

- [ ] **Step 4: 运行完整生成命令**

```powershell
& .\.venv\Scripts\python.exe tools\render_nangongwan_rooftop_making_of.py --build-all
```

Expected outputs:

```text
work/nangongwan-rooftop-making-of-video/master-v1-no-voice-1920x1080.mp4
work/nangongwan-rooftop-making-of-video/master-v1.ass
work/nangongwan-rooftop-making-of-video/master-v1-timeline.json
work/nangongwan-rooftop-making-of-video/intermediates/actions/*.mp4
work/nangongwan-rooftop-making-of-video/intermediates/shots/*.mp4
```

- [ ] **Step 5: 提交母版构建器**

```powershell
git add tools/nangongwan_rooftop_making_of.py tools/render_nangongwan_rooftop_making_of.py tests/test_nangongwan_rooftop_making_of.py
git commit -m "feat: render Nangong Wan making-of master"
```

---

### Task 5: 隐私、视觉和媒体完整性验收

**Files:**
- Modify: `tools/nangongwan_rooftop_making_of.py`
- Modify: `tests/test_nangongwan_rooftop_making_of.py`
- Create locally: `work/nangongwan-rooftop-making-of-video/review-frames/*.jpg`
- Create locally: `work/nangongwan-rooftop-making-of-video/validation-report.json`

**Interfaces:**
- Consumes: final MP4、ASS、timeline JSON。
- Produces: `validate_master(master: Path, plan: VideoPlan, *, probe: dict | None = None) -> dict[str, object]`。

- [ ] **Step 1: 写入最终报告测试**

```python
def test_validation_report_requires_every_release_gate(tmp_path):
    valid_probe = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
             "pix_fmt": "yuv420p", "avg_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
        ],
        "format": {"duration": "280.000"},
    }
    approved_plan = build_video_plan(ROOT)
    report = validate_master(tmp_path / "master.mp4", approved_plan, probe=valid_probe)
    assert report["video"] == {
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "codec": "h264",
        "pixelFormat": "yuv420p",
    }
    assert report["audio"]["codec"] == "aac"
    assert report["audio"]["sampleRate"] == 48000
    assert report["durationMs"] == pytest.approx(280000, abs=100)
    assert report["privateAnimeUsed"] is False
    assert report["privacyScanPassed"] is True
    assert report["allPassed"] is True
```

- [ ] **Step 2: 实现媒体和隐私检查**

`validate_master()` must:

1. Parse `ffprobe -show_streams -show_format -of json`.
2. Require one1920×1080 H.264/yuv420p video stream at30fps.
3. Require one48kHz stereo AAC audio stream.
4. Require total duration280000±100ms.
5. Resolve every timeline source and reject any path containing `anime-reference`, `DO-NOT-PUBLISH`, `local-install-backup`, `.reg`, `.exe`, or `private-reference`.
6. Scan only public-facing strings (`title`, `caption`, ASS dialogue text, and explicitly exported metadata) with case-insensitive patterns for Windows absolute paths, URL tokens, 32+ character hex secrets, `gitee.com`, `github.com`, and usernames. Timeline `source` fields are internal provenance and may contain absolute paths, so they are validated by rule5 but excluded from the public-text scan.
7. Confirm chapter and shot sums remain exact after rendering.

- [ ] **Step 3: 抽取视觉审片帧**

Use FFmpeg to capture frames at milliseconds:

```text
0, 17000, 18000, 57000, 58000, 97000, 98000, 137000,
138000, 177000, 178000, 264999, 265000, 279900
```

Create `review-frames/contact-sheet.jpg` with seven columns and two rows. Confirm manually:

- no severe anatomy/anchor failure is visible;
- desktop/taskbar context is readable;
- character remains centered;
- bottom subtitles and top action labels do not overlap the face or chestnut;
- moon variant labels match the actual background;
- transition frames do not expose transparent checkerboards or black rectangles.

- [ ] **Step 4: 运行完整测试和验证**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_nangongwan_rooftop_making_of.py -q
& .\.venv\Scripts\python.exe -m pytest -q --ignore=tests/integration/test_frozen_smoke.py
& .\.venv\Scripts\python.exe tools\render_nangongwan_rooftop_making_of.py --validate-only
```

Expected: all tests pass; `validation-report.json::allPassed=true`.

- [ ] **Step 5: 完整观看母版**

Watch from00:00 to04:40 at normal speed. Record any unreadable subtitle, repeated scene that feels longer than its information content, mislabeled action, or accidental severe-failure frame. If any exists, change only the relevant `ShotSpec` or subtitle event, rebuild, and repeat validation.

- [ ] **Step 6: 提交验证逻辑**

```powershell
git add tools/nangongwan_rooftop_making_of.py tools/render_nangongwan_rooftop_making_of.py tests/test_nangongwan_rooftop_making_of.py
git commit -m "test: validate making-of review master"
```

---

### Task 6: 向用户交付首稿并停止在审片门

**Files:**
- No tracked file changes.
- Deliver locally: `work/nangongwan-rooftop-making-of-video/master-v1-no-voice-1920x1080.mp4`
- Deliver locally: `work/nangongwan-rooftop-making-of-video/review-frames/contact-sheet.jpg`
- Deliver locally: `work/nangongwan-rooftop-making-of-video/validation-report.json`

**Interfaces:**
- Consumes: validated outputs from Task 5.
- Produces: user review decision; no automatic voice generation or vertical cut.

- [ ] **Step 1: 展示首稿与验证摘要**

Provide clickable absolute paths to the MP4, contact sheet, ASS, timeline JSON, and validation report. State explicitly that the audio track is silent and reserved for later AI narration.

- [ ] **Step 2: 收集一轮结构反馈**

Ask the user to focus on only four questions: six-stage order、each stage duration、subtitle readability、whether the three moon comparisons are long enough. Do not ask for final voice or vertical framing in the same review round.

- [ ] **Step 3: 停止**

Do not generate AI voice, add music, make the9:16 cut, update the installer, or publish to GitHub/Gitee until the user approves the horizontal no-voice review master.
