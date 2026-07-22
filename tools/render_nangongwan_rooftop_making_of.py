import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.nangongwan_rooftop_making_of import (
    ActionSource,
    ChapterSpec,
    RenderedSubtitleEvent,
    ShotSpec,
    SubtitleEvent,
    VideoPlan,
    burn_ass_and_add_silence,
    concat_shots,
    frame_milliseconds,
    read_action,
    render_shot,
    write_action_mp4,
    write_ass,
    write_timeline_json,
)


CHAPTER_DURATIONS = (18_000, 40_000, 40_000, 40_000, 87_000, 55_000)
MOON_COMPARISON_FRAME_INDEX = 20
FRAMES_PER_SECOND = 30


@dataclass(frozen=True)
class ScheduledShot:
    index: int
    shot: ShotSpec
    start_frame: int
    end_frame: int

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame


@dataclass(frozen=True)
class ScheduledChapter:
    chapter: ChapterSpec
    start_frame: int
    end_frame: int
    shots: tuple[ScheduledShot, ...]

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame

    @property
    def start_ms(self) -> int | float:
        return frame_milliseconds(self.start_frame)

    @property
    def end_ms(self) -> int | float:
        return frame_milliseconds(self.end_frame)


def _round_to_frame(milliseconds: int) -> int:
    """Round a millisecond offset to the nearest 30fps frame, half upward."""

    return (milliseconds * FRAMES_PER_SECOND + 500) // 1_000


def _chapter_frame_counts(chapter: ChapterSpec, chapter_frames: int) -> tuple[int, ...]:
    """Use cumulative rounding, with a locked frame count for moon variant parity."""

    cumulative_ms = 0
    previous_relative_frame = 0
    counts: list[int] = []
    for position, shot in enumerate(chapter.shots):
        cumulative_ms += shot.duration_ms
        relative_end = (
            chapter_frames
            if position == len(chapter.shots) - 1
            else _round_to_frame(cumulative_ms)
        )
        counts.append(relative_end - previous_relative_frame)
        previous_relative_frame = relative_end
    if cumulative_ms != chapter.duration_ms or sum(counts) != chapter_frames:
        raise ValueError(f"chapter {chapter.id} frame allocation does not match its duration")
    if chapter.id == "moon_variants":
        action_indexes = [
            index
            for index, shot in enumerate(chapter.shots)
            if shot.id in {"moon-184", "moon-232", "moon-full"}
        ]
        comparison_index = next(
            index for index, shot in enumerate(chapter.shots) if shot.id == "moon-compare"
        )
        action_frames = _round_to_frame(chapter.shots[action_indexes[0]].duration_ms)
        if any(_round_to_frame(chapter.shots[index].duration_ms) != action_frames for index in action_indexes):
            raise ValueError("moon variant action durations must remain identical")
        delta = sum(action_frames - counts[index] for index in action_indexes)
        for index in action_indexes:
            counts[index] = action_frames
        counts[comparison_index] -= delta
        if counts[comparison_index] <= 0 or sum(counts) != chapter_frames:
            raise ValueError("moon variant parity cannot fit in its chapter frame budget")
    return tuple(counts)


def build_frame_schedule(plan: VideoPlan) -> tuple[ScheduledChapter, ...]:
    """Allocate frames cumulatively within each chapter so no drift crosses a cut."""

    schedule: list[ScheduledChapter] = []
    frame_cursor = 0
    shot_index = 1
    for chapter in plan.chapters:
        chapter_frames, remainder = divmod(chapter.duration_ms * FRAMES_PER_SECOND, 1_000)
        if remainder:
            raise ValueError(f"chapter {chapter.id} is not frame-aligned at 30fps")
        chapter_start = frame_cursor
        scheduled_shots: list[ScheduledShot] = []
        relative_frame = 0
        for shot, count in zip(
            chapter.shots, _chapter_frame_counts(chapter, chapter_frames), strict=True
        ):
            start_frame = chapter_start + relative_frame
            end_frame = start_frame + count
            if end_frame <= start_frame:
                raise ValueError(f"shot {shot.id} has no allocated frames")
            scheduled_shots.append(ScheduledShot(shot_index, shot, start_frame, end_frame))
            shot_index += 1
            relative_frame += count
        if relative_frame != chapter_frames:
            raise ValueError(f"chapter {chapter.id} frame allocation does not match its duration")
        frame_cursor = chapter_start + chapter_frames
        schedule.append(
            ScheduledChapter(chapter, chapter_start, frame_cursor, tuple(scheduled_shots))
        )
    if frame_cursor != plan.duration_ms * FRAMES_PER_SECOND // 1_000:
        raise ValueError("frame allocation does not match plan duration")
    return tuple(schedule)


def quantize_subtitle_events(
    events: tuple[SubtitleEvent, ...],
) -> tuple[RenderedSubtitleEvent, ...]:
    """Snap public subtitle timing to the same frame grid as the rendered master."""

    rendered: list[RenderedSubtitleEvent] = []
    for event in events:
        start_frame = _round_to_frame(event.start_ms)
        end_frame = _round_to_frame(event.end_ms)
        if end_frame <= start_frame:
            raise ValueError(f"subtitle {event.text!r} has no rendered frames")
        rendered.append(RenderedSubtitleEvent(start_frame, end_frame, event.text, event.style))
    return tuple(rendered)


def _sources(root: Path) -> tuple[dict[str, ActionSource], dict[str, Path], dict[str, Path]]:
    history = root / "work" / "nangongwan-moonlit-rooftop-history"
    output = root / "work" / "nangongwan-rooftop-making-of-video"
    actions = output / "intermediates" / "actions"
    action_sources = {
        "standing": ActionSource(
            atlas=history / "06-standing-chestnut-easter-egg" / "standing-chestnut-10frames.webp",
            manifest=history / "06-standing-chestnut-easter-egg" / "action.json",
            action_id="tasteCake",
            manifest_kind="action",
            atlas_start_frame=0,
        ),
        "cinematic": ActionSource(
            atlas=history / "01-cinematic-36f-v2.4.1" / "spritesheet.webp",
            manifest=history / "01-cinematic-36f-v2.4.1" / "pet.json",
            action_id="moonlitChestnut",
        ),
        "anchored": ActionSource(
            atlas=history / "02-anchored-48f-v1" / "complete-archive" / "spritesheet.webp",
            manifest=history / "02-anchored-48f-v1" / "complete-archive" / "pet.json",
            action_id="moonlitChestnut",
        ),
        "small": ActionSource(
            atlas=history / "04-moon-background-variants" / "01-small-moon-current" / "spritesheet.webp",
            manifest=history / "04-moon-background-variants" / "01-small-moon-current" / "pet.json",
            action_id="rooftopChestnut",
        ),
        "moon_184": ActionSource(
            atlas=history / "04-moon-background-variants" / "02-full-circle-184" / "spritesheet.webp",
            manifest=history / "04-moon-background-variants" / "02-full-circle-184" / "pet.json",
            action_id="rooftopChestnut",
        ),
        "moon_232": ActionSource(
            atlas=history / "04-moon-background-variants" / "03-cropped-disc-232" / "spritesheet.webp",
            manifest=history / "04-moon-background-variants" / "03-cropped-disc-232" / "pet.json",
            action_id="rooftopChestnut",
        ),
        "moon_full": ActionSource(
            atlas=history / "04-moon-background-variants" / "04-full-frame-moon-surface" / "spritesheet.webp",
            manifest=history / "04-moon-background-variants" / "04-full-frame-moon-surface" / "pet.json",
            action_id="rooftopChestnut",
        ),
    }
    render_history = history / "03-persistent-rooftop-revisions" / "render-history-v2-v9"
    videos = {
        "standing": actions / "standing-chestnut.mp4",
        "cinematic": actions / "cinematic-36.mp4",
        "anchored": history / "02-anchored-48f-v1" / "complete-archive" / "moonlit-chestnut-9600ms.mp4",
        "persistent": render_history / "moonlit-rooftop-all-actions.mp4",
        "v9": render_history / "moonlit-rooftop-transparent-v9.mp4",
        "moon_184": actions / "moon-full-circle-184-chestnut.mp4",
        "moon_232": actions / "moon-cropped-disc-232-chestnut.mp4",
        "moon_full": actions / "moon-full-frame-chestnut.mp4",
    }
    stills = {
        "cinematic_sheet": output / "intermediates" / "stills" / "cinematic-36-contact-sheet.png",
        "anchored_compare": history / "02-anchored-48f-v1" / "complete-archive" / "audit-48.png",
        "v9_grid": render_history / "audit-166-transparent-v9.png",
        "moon_compare": output / "intermediates" / "stills" / "moon-variants-three-panel.png",
    }
    return action_sources, videos, stills


def build_review_stills(root: Path) -> tuple[Path, Path]:
    """Generate the two review stills from only their approved action frames."""

    action_sources, _, stills = _sources(root)
    cinematic_frames = read_action(action_sources["cinematic"]).frames
    if len(cinematic_frames) != 36:
        raise ValueError("cinematic contact sheet requires exactly 36 frames")
    contact_sheet = Image.new("RGBA", (6 * 192, 6 * 208), (0, 0, 0, 0))
    for index, frame in enumerate(cinematic_frames):
        row, column = divmod(index, 6)
        contact_sheet.alpha_composite(frame, (column * 192, row * 208))
    contact_sheet_path = stills["cinematic_sheet"]
    contact_sheet_path.parent.mkdir(parents=True, exist_ok=True)
    contact_sheet.save(contact_sheet_path)

    variant_names = ("moon_184", "moon_232", "moon_full")
    variant_frames = [
        read_action(action_sources[name]).frames[MOON_COMPARISON_FRAME_INDEX]
        for name in variant_names
    ]
    comparison = Image.new("RGBA", (3 * 192, 208 + 36), (0, 0, 0, 0))
    draw = ImageDraw.Draw(comparison)
    draw.rectangle((0, 0, comparison.width, 35), fill=(14, 24, 42, 255))
    for column, (label, frame) in enumerate(
        zip(("Moon 184", "Moon 232", "Full Moon"), variant_frames, strict=True)
    ):
        left = column * 192
        draw.text((left + 8, 11), label, fill=(255, 255, 255, 255))
        comparison.alpha_composite(frame, (left, 36))
    comparison_path = stills["moon_compare"]
    comparison.save(comparison_path)
    return contact_sheet_path, comparison_path


def build_shots(root: Path) -> tuple[ShotSpec, ...]:
    """Build the approved public-facing shot list in chronological order."""

    _, videos, stills = _sources(root)
    return (
        ShotSpec("standing-full", "video", 2_080, videos["standing"], "栗糕轻尝", "十帧动作完整播放：动作虽短，认真程度不打折。"),
        ShotSpec("standing-replay", "video", 4_160, videos["standing"], "近看一遍", "同一动作回放两次，给眼睛一点确认时间。", True),
        ShotSpec("standing-feedback", "card", 11_760, None, "小彩蛋，大回忆", "栗糕该保留吗？请投票：保留、加快，还是再来一口？"),
        ShotSpec("cinematic-title", "card", 3_000, None, "36 帧电影感版本", "第一版长动作：先把月下屋檐做得像一段小镜头。"),
        ShotSpec("cinematic-full", "video", 9_100, videos["cinematic"], "36 帧完整播放", "完整动作一次看完，月色、屋檐和栗子依次入镜。"),
        ShotSpec("cinematic-replay", "video", 9_100, videos["cinematic"], "36 帧标注回放", "再看一遍：重点是姿态衔接，不是让栗子抢戏。", True),
        ShotSpec("cinematic-sheet", "still", 8_000, stills["cinematic_sheet"], "36 帧接触表", "逐帧检查动作是否连贯，也方便挑出最有感觉的一格。"),
        ShotSpec("cinematic-feedback", "card", 10_800, None, "第一轮反馈", "你更在意动作流畅、月景氛围，还是栗糕出现的时机？"),
        ShotSpec("anchored-title", "card", 3_000, None, "48 帧锚定版本", "增加帧数，同时把坐姿和屋檐位置固定下来。"),
        ShotSpec("anchored-full", "video", 9_600, videos["anchored"], "48 帧完整播放", "更长的动作让停顿和回望都有了落点。"),
        ShotSpec("anchored-replay", "video", 9_600, videos["anchored"], "48 帧标注回放", "重看锚点：人物不漂，屋檐也不偷偷搬家。", True),
        ShotSpec("anchored-compare", "still", 7_000, stills["anchored_compare"], "锚定对照", "对照图用于检查坐姿、月亮和檐角是否始终对齐。"),
        ShotSpec("anchored-feedback", "card", 10_800, None, "第二轮反馈", "固定位置之后，画面更稳了吗？欢迎挑刺，锚点不怕。"),
        ShotSpec("persistent-title", "card", 3_000, None, "第一次常驻屋檐", "从单个动作，尝试走向一个会停留的小场景。"),
        ShotSpec("persistent-history", "video", 12_000, videos["persistent"], "历史常驻演示", "早期版本先验证：屋檐状态可以持续存在。"),
        ShotSpec("persistent-resident", "video", 12_000, videos["persistent"], "居民动作回放", "重复播放只为观察常驻节奏；当时动作库还在长大。", True),
        ShotSpec("persistent-explainer", "card", 13_000, None, "从动作到状态", "常驻状态需要进入、停留与离开；不是把一段视频按下循环键。"),
        ShotSpec("v9-title", "card", 3_000, None, "V9：小月亮与九种居民动作", "月色缩小后，角色和屋檐仍是画面的主角。"),
        ShotSpec("v9-sequence", "video", 30_680, videos["v9"], "V9 全动作序列", "进入、九种居民动作与离开，按制作顺序完整展示。"),
        ShotSpec("v9-replay", "video", 30_680, videos["v9"], "V9 标注回放", "逐段标注动作名，方便核对节奏与画面细节。", True),
        ShotSpec("v9-grid", "still", 14_000, stills["v9_grid"], "九种居民动作一览", "静坐、望月、含栗、欲眠、拂袖、回眸、拢发、触环、白鹤掠月。"),
        ShotSpec("v9-random", "card", 8_640, None, "实际运行并不按剧本", "实际运行时，九种动作会按权重随机出现；演示视频为方便观看而依次播放。"),
        ShotSpec("moon-title", "card", 3_000, None, "三种新月景", "同一段屋檐含栗动作，只替换月亮背景。"),
        ShotSpec("moon-184", "video", 8_990, videos["moon_184"], "满圆月 184", "第一种月景：月面完整，角色动作保持不变。"),
        ShotSpec("moon-232", "video", 8_990, videos["moon_232"], "裁切月盘 232", "第二种月景：更靠近画面边缘，留出屋檐呼吸感。"),
        ShotSpec("moon-full", "video", 8_990, videos["moon_full"], "满幅月面", "第三种月景：月亮更有存在感，栗子仍按原节奏登场。"),
        ShotSpec("moon-compare", "still", 15_030, stills["moon_compare"], "三种月景对照", "动作、屋檐和人物前景一致，区别只在月亮背景。"),
        ShotSpec("moon-choice", "card", 10_000, None, "请选你想留下的月亮", "投票选一个最适合桌面的版本；月亮很大，选择可以很轻松。"),
    )


def _v9_action_events(root: Path, start_ms: int) -> tuple[SubtitleEvent, ...]:
    history = root / "work" / "nangongwan-moonlit-rooftop-history" / "03-persistent-rooftop-revisions" / "render-history-v2-v9"
    preview = json.loads((history / "preview-sequence-v9.json").read_text(encoding="utf-8"))
    pet = json.loads((root / "src" / "shiyi_desktop_pet" / "resources" / "pets" / "nangongwan" / "pet.json").read_text(encoding="utf-8"))
    sequence = preview["sequence"]
    ranges = preview["clipFrameRanges"]
    frame_times = [0]
    for action_id in sequence:
        action = pet["actions"][action_id]
        durations = action.get("frameDurations")
        if durations is None:
            durations = [action["frameMs"]] * action["frameCount"]
        if len(durations) != action["frameCount"]:
            raise ValueError(f"invalid frame durations for {action_id}")
        frame_times.extend(frame_times[-1] + duration for duration in durations)
    if len(frame_times) != preview["frameCount"] + 1 or frame_times[-1] != preview["durationMs"]:
        raise ValueError("V9 frame timing does not match preview metadata")
    events = []
    for action_id in sequence:
        start_frame, end_frame = ranges[action_id]
        events.append(
            SubtitleEvent(
                start_ms + frame_times[start_frame],
                start_ms + frame_times[end_frame],
                pet["actions"][action_id]["label"],
                "Action",
            )
        )
    return tuple(events)


def _subtitle_events(root: Path, chapters: tuple[ChapterSpec, ...]) -> tuple[SubtitleEvent, ...]:
    events: list[SubtitleEvent] = []
    cursor = 0
    for chapter in chapters:
        for shot in chapter.shots:
            end = cursor + shot.duration_ms
            if shot.title and shot.id not in {"v9-sequence", "v9-replay"}:
                events.append(SubtitleEvent(cursor, min(cursor + 2_700, end), shot.title, "Title"))
            if shot.caption:
                events.append(SubtitleEvent(cursor, end, shot.caption, "Caption"))
            if shot.id in {"v9-sequence", "v9-replay"}:
                events.extend(_v9_action_events(root, cursor))
            cursor = end
    return tuple(events)


def build_video_plan(root: Path) -> VideoPlan:
    action_sources, _, _ = _sources(root)
    shots = build_shots(root)
    grouped = {
        "standing_chestnut": shots[0:3],
        "cinematic_36": shots[3:8],
        "anchored_48": shots[8:13],
        "persistent_v1": shots[13:17],
        "v9_small_moon": shots[17:22],
        "moon_variants": shots[22:28],
    }
    titles = {
        "standing_chestnut": "栗糕彩蛋",
        "cinematic_36": "36 帧电影感版本",
        "anchored_48": "48 帧锚定版本",
        "persistent_v1": "第一次常驻屋檐",
        "v9_small_moon": "V9 小月亮版本",
        "moon_variants": "月亮背景方案",
    }
    chapters = tuple(
        ChapterSpec(chapter_id, titles[chapter_id], duration, grouped[chapter_id])
        for chapter_id, duration in zip(titles, CHAPTER_DURATIONS, strict=True)
    )
    return VideoPlan(chapters, action_sources, _subtitle_events(root, chapters))


def build_action_clips(root: Path) -> tuple[Path, ...]:
    """Regenerate only the five public action clips used by the master."""

    action_sources, videos, _ = _sources(root)
    clip_sources = {
        "standing": "standing",
        "cinematic": "cinematic",
        "moon_184": "moon_184",
        "moon_232": "moon_232",
        "moon_full": "moon_full",
    }
    rendered: list[Path] = []
    for action_name, video_name in clip_sources.items():
        target = videos[video_name]
        write_action_mp4(read_action(action_sources[action_name]), target)
        rendered.append(target)
    return tuple(rendered)


def build_master(root: Path) -> Path:
    """Build the silent horizontal review master and its editable sidecars."""

    output = root / "work" / "nangongwan-rooftop-making-of-video"
    shots_dir = output / "intermediates" / "shots"
    build_action_clips(root)
    build_review_stills(root)
    plan = build_video_plan(root)
    frame_schedule = build_frame_schedule(plan)
    rendered_events = quantize_subtitle_events(plan.subtitle_events)
    ass = output / "master-v1.ass"
    timeline = output / "master-v1-timeline.json"
    write_ass(rendered_events, ass)
    write_timeline_json(
        plan,
        timeline,
        frame_schedule=frame_schedule,
        subtitle_events=rendered_events,
    )

    rendered_shots: list[Path] = []
    for scheduled_chapter in frame_schedule:
        for scheduled_shot in scheduled_chapter.shots:
            target = shots_dir / f"{scheduled_shot.index:02d}-{scheduled_shot.shot.id}.mp4"
            render_shot(
                scheduled_shot.shot,
                target,
                frame_count=scheduled_shot.frame_count,
            )
            rendered_shots.append(target)
    master_base = output / "master-base.mp4"
    concat_shots(tuple(rendered_shots), master_base)
    master = output / "master-v1-no-voice-1920x1080.mp4"
    burn_ass_and_add_silence(master_base, ass, master)
    return master


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the Nangong Wan making-of review master.")
    parser.add_argument("--build-all", action="store_true", help="render all actions, shots, and the master")
    arguments = parser.parse_args()
    if not arguments.build_all:
        parser.error("--build-all is required")
    root = Path(__file__).resolve().parents[1]
    print(build_master(root))


if __name__ == "__main__":
    main()
