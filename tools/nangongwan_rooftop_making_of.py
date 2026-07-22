from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from PIL import Image, ImageDraw


CELL_SIZE = (192, 208)
ATLAS_COLUMNS = 16
DESKTOP_SIZE = (960, 540)


@dataclass(frozen=True)
class ActionSource:
    atlas: Path
    manifest: Path
    action_id: str
    manifest_kind: Literal["pet", "action"] = "pet"
    atlas_start_frame: int | None = None


@dataclass(frozen=True)
class TimedFrames:
    frames: tuple[Image.Image, ...]
    durations_ms: tuple[int, ...]

    @property
    def duration_ms(self) -> int:
        return sum(self.durations_ms)


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
class SubtitleEvent:
    start_ms: int
    end_ms: int
    text: str
    style: Literal["Title", "Caption", "Action", "Note"]


@dataclass(frozen=True)
class RenderedSubtitleEvent:
    """A subtitle interval snapped to the delivery frame grid."""

    start_frame: int
    end_frame: int
    text: str
    style: Literal["Title", "Caption", "Action", "Note"]


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
    subtitle_events: tuple[SubtitleEvent, ...] = ()

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


def ass_time(milliseconds: int) -> str:
    """Format a non-negative millisecond offset for an ASS dialogue row."""

    if milliseconds < 0:
        raise ValueError("ASS timestamps cannot be negative")
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{milliseconds // 10:02d}"


def frame_milliseconds(frame: int) -> int | float:
    """Represent a 30fps frame boundary in milliseconds without inventing drift."""

    milliseconds, remainder = divmod(frame * 1_000, 30)
    return milliseconds if remainder == 0 else round(frame * 1_000 / 30, 6)


def ass_frame_time(frame: int) -> str:
    """Format a frame-grid boundary at ASS's nearest available centisecond."""

    centiseconds = (frame * 100 + 15) // 30
    return ass_time(centiseconds * 10)


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Title,Microsoft YaHei UI,54,&H00FFFFFF,&H000000FF,&H4D000000,&H4D000000,-1,0,0,0,100,100,0,0,1,3,2,8,76,76,76,1
Style: Caption,Microsoft YaHei UI,42,&H00FFFFFF,&H000000FF,&H4D000000,&H4D000000,0,0,0,0,100,100,0,0,1,3,2,2,76,76,76,1
Style: Action,Microsoft YaHei UI,38,&H00FFFFFF,&H000000FF,&H4D000000,&H4D000000,-1,0,0,0,100,100,0,0,1,3,2,8,58,58,58,1
Style: Note,Microsoft YaHei UI,34,&H00FFFFFF,&H000000FF,&H4D000000,&H4D000000,0,0,0,0,100,100,0,0,1,3,2,2,76,76,126,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")


def write_ass(
    events: tuple[SubtitleEvent | RenderedSubtitleEvent, ...], out: Path
) -> None:
    """Write the review subtitles as a human-editable UTF-8 ASS script."""

    rows = [ASS_HEADER]
    for event in events:
        if isinstance(event, RenderedSubtitleEvent):
            if event.end_frame <= event.start_frame:
                raise ValueError("subtitle events must have a positive duration")
            start, end = ass_frame_time(event.start_frame), ass_frame_time(event.end_frame)
        else:
            if event.end_ms <= event.start_ms:
                raise ValueError("subtitle events must have a positive duration")
            start, end = ass_time(event.start_ms), ass_time(event.end_ms)
        rows.append(
            "Dialogue: 0,"
            f"{start},{end},{event.style},"
            f",0,0,0,,{_ass_escape(event.text)}\n"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(rows), encoding="utf-8-sig")


def _source_json(source: Path | ActionSource | None) -> object:
    if source is None:
        return None
    if isinstance(source, Path):
        return str(source)
    return {
        "atlas": str(source.atlas),
        "manifest": str(source.manifest),
        "actionId": source.action_id,
        "manifestKind": source.manifest_kind,
        "atlasStartFrame": source.atlas_start_frame,
    }


def write_timeline_json(
    plan: VideoPlan,
    out: Path,
    *,
    frame_schedule: tuple[object, ...] | None = None,
    subtitle_events: tuple[SubtitleEvent | RenderedSubtitleEvent, ...] | None = None,
) -> None:
    """Persist exact shot and subtitle timing for review and later rendering."""

    chapters: list[dict[str, object]] = []
    cursor = 0
    if frame_schedule is not None and len(frame_schedule) != len(plan.chapters):
        raise ValueError("frame schedule does not match chapter count")
    for chapter_index, chapter in enumerate(plan.chapters):
        scheduled_chapter = frame_schedule[chapter_index] if frame_schedule is not None else None
        shot_cursor = cursor
        shots: list[dict[str, object]] = []
        for shot_index, shot in enumerate(chapter.shots):
            end = shot_cursor + shot.duration_ms
            row: dict[str, object] = {
                "id": shot.id,
                "kind": shot.kind,
                "startMs": shot_cursor,
                "endMs": end,
                "durationMs": shot.duration_ms,
                "source": _source_json(shot.source),
                "title": shot.title,
                "caption": shot.caption,
                "loop": shot.loop,
            }
            if scheduled_chapter is not None:
                scheduled_shot = scheduled_chapter.shots[shot_index]
                row.update(
                    {
                        "startFrame": scheduled_shot.start_frame,
                        "endFrame": scheduled_shot.end_frame,
                        "renderedStartMs": frame_milliseconds(scheduled_shot.start_frame),
                        "renderedEndMs": frame_milliseconds(scheduled_shot.end_frame),
                    }
                )
            shots.append(row)
            shot_cursor = end
        if shot_cursor != cursor + chapter.duration_ms:
            raise ValueError(f"chapter {chapter.id} shots do not match its duration")
        chapter_row: dict[str, object] = {
            "id": chapter.id,
            "title": chapter.title,
            "startMs": cursor,
            "endMs": shot_cursor,
            "durationMs": chapter.duration_ms,
            "shots": shots,
        }
        if scheduled_chapter is not None:
            chapter_row.update(
                {
                    "startFrame": scheduled_chapter.start_frame,
                    "endFrame": scheduled_chapter.end_frame,
                    "renderedStartMs": frame_milliseconds(scheduled_chapter.start_frame),
                    "renderedEndMs": frame_milliseconds(scheduled_chapter.end_frame),
                }
            )
        chapters.append(chapter_row)
        cursor = shot_cursor
    if cursor != plan.duration_ms:
        raise ValueError("timeline duration does not match plan duration")
    rendered_events = subtitle_events if subtitle_events is not None else plan.subtitle_events
    subtitle_rows: list[dict[str, object]] = []
    for event in rendered_events:
        row: dict[str, object] = {"text": event.text, "style": event.style}
        if isinstance(event, RenderedSubtitleEvent):
            row.update(
                {
                    "startFrame": event.start_frame,
                    "endFrame": event.end_frame,
                    "renderedStartMs": frame_milliseconds(event.start_frame),
                    "renderedEndMs": frame_milliseconds(event.end_frame),
                }
            )
        else:
            row.update({"startMs": event.start_ms, "endMs": event.end_ms})
        subtitle_rows.append(row)
    payload = {
        "schemaVersion": 1,
        "durationMs": plan.duration_ms,
        "chapters": chapters,
        "subtitleEvents": subtitle_rows,
        "voiceStatus": "pending-openai-api-key",
        "aiVoiceDisclosureRequired": True,
        "privateAnimeUsed": False,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_action(source: ActionSource) -> TimedFrames:
    """Read one manifest action from either a full atlas or a cropped strip."""

    document = json.loads(source.manifest.read_text(encoding="utf-8"))
    if source.manifest_kind == "action":
        if source.atlas_start_frame is None:
            raise ValueError("action manifests require an explicit atlas_start_frame")
        action = document
    else:
        action = document["actions"][source.action_id]

    frame_count = action["frameCount"]
    durations = tuple(
        action.get("frameDurations") or [action["frameMs"]] * frame_count
    )
    if (
        len(durations) != frame_count
        or any(not isinstance(value, int) or value <= 0 or value % 10 for value in durations)
    ):
        raise ValueError(f"invalid durations for {source.action_id}")

    with Image.open(source.atlas) as atlas_source:
        width, height = atlas_source.size
        is_full_atlas = width == ATLAS_COLUMNS * CELL_SIZE[0]
        is_strip = width == frame_count * CELL_SIZE[0]
        if not (is_full_atlas or is_strip):
            raise ValueError(f"invalid atlas width for {source.action_id}: {width}")
        if height % CELL_SIZE[1]:
            raise ValueError(f"invalid atlas height for {source.action_id}: {height}")

        if is_full_atlas:
            start = source.atlas_start_frame
            if start is None:
                start = action["row"] * ATLAS_COLUMNS + action.get("startColumn", 0)
            if start < 0:
                raise ValueError(f"invalid atlas start for {source.action_id}")
            crops = tuple(divmod(start + offset, ATLAS_COLUMNS) for offset in range(frame_count))
            crop_columns = ATLAS_COLUMNS
        else:
            crops = tuple((0, offset) for offset in range(frame_count))
            crop_columns = frame_count

        rows = height // CELL_SIZE[1]
        if any(row >= rows or column >= crop_columns for row, column in crops):
            raise ValueError(f"atlas crop exceeds bounds for {source.action_id}")

        atlas = atlas_source.convert("RGBA")
        frames = tuple(
            atlas.crop(
                (
                    column * CELL_SIZE[0],
                    row * CELL_SIZE[1],
                    (column + 1) * CELL_SIZE[0],
                    (row + 1) * CELL_SIZE[1],
                )
            )
            for row, column in crops
        )
    return TimedFrames(frames, durations)


def compose_desktop(frame: Image.Image) -> Image.Image:
    """Place an action frame on a neutral desktop with a small visible taskbar."""

    canvas = Image.new("RGBA", DESKTOP_SIZE)
    pixels = canvas.load()
    for y in range(DESKTOP_SIZE[1]):
        progress = y / (DESKTOP_SIZE[1] - 1)
        color = (
            round(11 + (36 - 11) * progress),
            round(24 + (62 - 24) * progress),
            round(46 + (91 - 46) * progress),
            255,
        )
        for x in range(DESKTOP_SIZE[0]):
            pixels[x, y] = color

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.ellipse((-180, 20, 560, 760), fill=(33, 116, 214, 54))
    draw.ellipse((420, -280, 1190, 490), fill=(97, 179, 242, 36))
    draw.arc((-120, 70, 740, 780), 195, 342, fill=(100, 192, 255, 65), width=18)

    pet = frame.convert("RGBA").resize((432, 468), Image.Resampling.LANCZOS)
    canvas.alpha_composite(pet, ((DESKTOP_SIZE[0] - pet.width) // 2, 21))

    taskbar_y = 500
    draw.rounded_rectangle((280, taskbar_y, 680, 536), radius=12, fill=(18, 27, 43, 205))
    for index, color in enumerate(
        ((63, 151, 245, 255), (241, 244, 249, 255), (36, 158, 103, 255), (190, 93, 218, 255))
    ):
        left = 398 + index * 42
        draw.rounded_rectangle((left, taskbar_y + 7, left + 24, taskbar_y + 31), radius=5, fill=color)
    return canvas.convert("RGB")


def write_action_mp4(timed: TimedFrames, out: Path) -> None:
    """Encode desktop-composited action frames at 100fps for exact 10ms timing."""

    if not timed.frames or len(timed.frames) != len(timed.durations_ms):
        raise ValueError("frames and durations must be non-empty and have matching lengths")
    if any(duration <= 0 or duration % 10 for duration in timed.durations_ms):
        raise ValueError("durations must be positive multiples of 10ms")

    out.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        f"{DESKTOP_SIZE[0]}x{DESKTOP_SIZE[1]}",
        "-framerate",
        "100",
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for frame, duration in zip(timed.frames, timed.durations_ms, strict=True):
            rgb = compose_desktop(frame).tobytes()
            for _ in range(duration // 10):
                process.stdin.write(rgb)
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr is not None else b""
        returncode = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    if returncode:
        raise subprocess.CalledProcessError(returncode, command, stderr=stderr)


MASTER_SIZE = (1920, 1080)


def run_ffmpeg(args: list[str]) -> None:
    """Run FFmpeg without a shell and retain useful failures for callers."""

    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg command failed: {args!r}\nstderr:\n{stderr}")


def _duration_frames(duration_ms: int) -> int:
    frames = round(duration_ms * 30 / 1_000)
    if duration_ms <= 0 or frames <= 0:
        raise ValueError("shot duration must produce at least one frame")
    return frames


def _desktop_background() -> Image.Image:
    """Return the established desktop context at the delivery resolution."""

    transparent_pet = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    return compose_desktop(transparent_pet).resize(MASTER_SIZE, Image.Resampling.LANCZOS)


def _font(size: int):
    windows_font = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc"
    if windows_font.exists():
        from PIL import ImageFont

        return ImageFont.truetype(windows_font, size)
    from PIL import ImageFont

    return ImageFont.load_default()


def _caption_lines(text: str, font, max_width: int) -> list[str]:
    """Wrap a short card caption while keeping it within the three-line contract."""

    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and font.getlength(candidate) > max_width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
    if len(lines) > 3:
        lines = lines[:3]
        while font.getlength(lines[-1] + "…") > max_width and lines[-1]:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines or [""]


def _write_card(shot: ShotSpec, out: Path) -> Path:
    """Create a text-only chapter card over the restrained desktop background."""

    card = _desktop_background().convert("RGB")
    draw = ImageDraw.Draw(card, "RGBA")
    draw.rounded_rectangle((250, 260, 1670, 830), radius=42, fill=(12, 23, 42, 198))
    title_font = _font(64)
    caption_font = _font(40)
    title = shot.title or shot.id
    draw.text((360, 360), title, font=title_font, fill=(255, 255, 255, 255))
    y = 490
    for line in _caption_lines(shot.caption, caption_font, 1180):
        draw.text((360, y), line, font=caption_font, fill=(223, 234, 248, 255))
        y += 66
    out.parent.mkdir(parents=True, exist_ok=True)
    card.save(out)
    return out


def _write_still_canvas(source: Path, out: Path) -> Path:
    """Place a still inside its 1660x900 display area on the desktop background."""

    with Image.open(source) as image_source:
        content = image_source.convert("RGBA")
    content.thumbnail((1660, 900), Image.Resampling.LANCZOS)
    canvas = _desktop_background().convert("RGBA")
    canvas.alpha_composite(
        content,
        ((canvas.width - content.width) // 2, (canvas.height - content.height) // 2),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out)
    return out


def _encode_still_image(source: Path, out: Path, frame_count: int, *, zoom: bool) -> None:
    filters = ["setsar=1"]
    if zoom:
        filters.insert(
            0,
            "zoompan=z='min(1.04,1+0.004*on/30)':d=1:s=1920x1080:fps=30",
        )
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(source),
            "-vf",
            ",".join(filters),
            "-frames:v",
            str(frame_count),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-color_range",
            "tv",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )


def render_shot(shot: ShotSpec, out: Path, *, frame_count: int | None = None) -> None:
    """Render one plan shot as a 1920x1080 silent, square-pixel H.264 clip."""

    out.parent.mkdir(parents=True, exist_ok=True)
    frame_count = _duration_frames(shot.duration_ms) if frame_count is None else frame_count
    if frame_count <= 0:
        raise ValueError("shot frame count must be positive")
    prepared = out.with_suffix(".png")
    if shot.kind == "card":
        _encode_still_image(_write_card(shot, prepared), out, frame_count, zoom=False)
        return
    if shot.kind == "still":
        if not isinstance(shot.source, Path):
            raise ValueError("still shots require an image path")
        _encode_still_image(_write_still_canvas(shot.source, prepared), out, frame_count, zoom=True)
        return

    source: Path
    generated_action: Path | None = None
    if isinstance(shot.source, ActionSource):
        generated_action = out.with_suffix(".action-source.mp4")
        write_action_mp4(read_action(shot.source), generated_action)
        source = generated_action
    elif isinstance(shot.source, Path):
        source = shot.source
    else:
        raise ValueError(f"{shot.kind} shots require a media source")
    background = out.with_suffix(".background.png")
    _desktop_background().save(background)
    command = ["ffmpeg", "-y"]
    if shot.loop:
        command.extend(("-stream_loop", "-1"))
    command.extend(
        (
            "-i",
            str(source),
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(background),
            "-filter_complex",
            "[0:v]scale=1600:900:force_original_aspect_ratio=decrease,setsar=1[media];"
            "[1:v][media]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p",
            "-frames:v",
            str(frame_count),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-profile:v",
            "high",
            "-level",
            "4.1",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-color_range",
            "tv",
            "-movflags",
            "+faststart",
            str(out),
        )
    )
    run_ffmpeg(command)
    background.unlink(missing_ok=True)
    if generated_action is not None:
        generated_action.unlink(missing_ok=True)


def _concat_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", r"'\''")


def concat_shots(shots: tuple[Path, ...], out: Path) -> None:
    """Join already-normalized silent shots with an absolute-path concat manifest."""

    if not shots:
        raise ValueError("at least one shot is required")
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = out.with_suffix(".concat.txt")
    manifest.write_text(
        "".join(f"file '{_concat_path(shot)}'\n" for shot in shots), encoding="utf-8"
    )
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-safe",
            "0",
            "-f",
            "concat",
            "-i",
            str(manifest),
            "-an",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )
    manifest.unlink(missing_ok=True)


def _ascii_ass_copy(ass: Path) -> tuple[Path, Path]:
    system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/")
    candidates = (
        Path(f"{system_drive}\\Temp"),
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Temp",
        Path(tempfile.gettempdir()),
    )
    for parent in candidates:
        try:
            parent.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix="nangongwan-ass-", dir=parent))
        except OSError:
            continue
        if str(directory).isascii():
            copied = directory / "master-v1.ass"
            shutil.copy2(ass, copied)
            return directory, copied
        shutil.rmtree(directory, ignore_errors=True)
    raise RuntimeError("could not create an ASCII-only temporary directory for ASS filtering")


def _ffmpeg_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", r"\'").replace(":", r"\:")


def burn_ass_and_add_silence(master_base: Path, ass: Path, out: Path) -> None:
    """Burn editable ASS subtitles and add a silent 48kHz stereo AAC track."""

    out.parent.mkdir(parents=True, exist_ok=True)
    directory, temporary_ass = _ascii_ass_copy(ass)
    completed = False
    try:
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(master_base),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-vf",
                f"ass=filename='{_ffmpeg_filter_path(temporary_ass)}'",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-profile:v",
                "high",
                "-level",
                "4.1",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                "-color_range",
                "tv",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
        completed = True
    finally:
        if completed:
            shutil.rmtree(directory, ignore_errors=True)
