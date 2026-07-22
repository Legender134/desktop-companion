from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from typing import Literal, Mapping

from PIL import Image, ImageDraw


CELL_SIZE = (192, 208)
ATLAS_COLUMNS = 16
DESKTOP_SIZE = (960, 540)
REVIEW_FRAME_MILLISECONDS = (
    0,
    17_000,
    18_000,
    57_000,
    58_000,
    97_000,
    98_000,
    137_000,
    138_000,
    177_000,
    178_000,
    264_999,
    265_000,
    279_900,
)


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
    shot_id: str | None = None


@dataclass(frozen=True)
class RenderedSubtitleEvent:
    """A subtitle interval snapped to the delivery frame grid."""

    start_frame: int
    end_frame: int
    text: str
    style: Literal["Title", "Caption", "Action", "Note"]
    shot_id: str | None = None


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
        if event.shot_id is not None:
            row["shotId"] = event.shot_id
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


_FORBIDDEN_SOURCE_MARKERS = (
    "anime-reference",
    "do-not-publish",
    "local-install-backup",
    "private-reference",
)
_PUBLIC_TEXT_PATTERNS = (
    re.compile(r"\b[a-z]:[\\/]", re.IGNORECASE),
    re.compile(r"\\\\(?:\?|\.|[^\\/\s]+)[\\/]", re.IGNORECASE),
    re.compile(
        r"\b(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,63}(?:[/:?#]|\b)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:token|access[_ -]?token|api[_ -]?key|secret)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE),
    re.compile(r"\b(?:user(?:name)?|login)\s*[:=]\s*[\w.@-]+", re.IGNORECASE),
)


def _probe_master(master: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(master),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))
    return json.loads(completed.stdout)


def _float_frame_rate(value: object) -> float:
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _all_source_paths(plan: VideoPlan) -> tuple[Path, ...]:
    paths = list(plan.source_paths)
    for source in plan.action_sources.values():
        paths.extend((source.atlas, source.manifest))
    return tuple(dict.fromkeys(paths))


def _source_is_approved(path: Path) -> bool:
    lowered = str(path.resolve(strict=False)).lower().replace("\\", "/")
    return not (
        any(marker in lowered for marker in _FORBIDDEN_SOURCE_MARKERS)
        or ".reg" in lowered
        or ".exe" in lowered
    )


def _public_plan_strings(plan: VideoPlan) -> tuple[str, ...]:
    strings: list[str] = []
    for chapter in plan.chapters:
        strings.append(chapter.title)
        for shot in chapter.shots:
            strings.extend((shot.title, shot.caption))
    strings.extend(event.text for event in plan.subtitle_events)
    return tuple(strings)


def _public_text_is_safe(strings: tuple[str, ...]) -> bool:
    return not any(pattern.search(value) for value in strings for pattern in _PUBLIC_TEXT_PATTERNS)


def _probe_metadata_strings(probe: dict[str, object]) -> tuple[str, ...]:
    strings: list[str] = []
    raw_streams = probe.get("streams", [])
    streams = raw_streams if isinstance(raw_streams, list) else []
    containers = [probe.get("format", {}), *streams]
    for container in containers:
        if not isinstance(container, dict):
            continue
        tags = container.get("tags", {})
        if isinstance(tags, dict):
            strings.extend(f"{key}={value}" for key, value in tags.items())
    return tuple(strings)


def _timeline_source_paths(value: object, *, parent: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    if isinstance(value, str):
        path = Path(value)
        paths.append(path if path.is_absolute() else parent / path)
    elif isinstance(value, dict):
        for key in ("atlas", "manifest"):
            if isinstance(value.get(key), str):
                path = Path(value[key])
                paths.append(path if path.is_absolute() else parent / path)
    return tuple(paths)


def _sidecar_security(master: Path) -> tuple[bool, bool, tuple[str, ...]]:
    """Scan public sidecar text while treating timeline sources as provenance only."""

    timeline_path = master.parent / "master-v1-timeline.json"
    ass_path = master.parent / "master-v1.ass"
    public_strings: list[str] = []
    sources: list[Path] = []
    if timeline_path.exists():
        try:
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, False, ()
        for key in ("voiceStatus",):
            if isinstance(timeline.get(key), str):
                public_strings.append(timeline[key])
        for chapter in timeline.get("chapters", []):
            if isinstance(chapter.get("title"), str):
                public_strings.append(chapter["title"])
            for shot in chapter.get("shots", []):
                for key in ("title", "caption"):
                    if isinstance(shot.get(key), str):
                        public_strings.append(shot[key])
                sources.extend(
                    _timeline_source_paths(shot.get("source"), parent=timeline_path.parent)
                )
        for event in timeline.get("subtitleEvents", []):
            if isinstance(event.get("text"), str):
                public_strings.append(event["text"])
    if ass_path.exists():
        for line in ass_path.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("Dialogue: "):
                fields = line.split(",", 9)
                if len(fields) == 10:
                    public_strings.append(fields[9])
    resolved = tuple(str(path.resolve(strict=False)) for path in sources)
    provenance_safe = all(path.exists() and _source_is_approved(path) for path in sources)
    return provenance_safe, _public_text_is_safe(tuple(public_strings)), resolved


def _read_mp4_atom_order(master: Path) -> bool:
    """Parse top-level ISO BMFF atoms without scanning payload bytes."""

    try:
        file_size = master.stat().st_size
        offset = 0
        moov_offset: int | None = None
        mdat_offset: int | None = None
        with master.open("rb") as stream:
            while offset < file_size:
                stream.seek(offset)
                header = stream.read(8)
                if len(header) != 8:
                    return False
                size32, atom_type = struct.unpack(">I4s", header)
                header_size = 8
                if size32 == 1:
                    extended = stream.read(8)
                    if len(extended) != 8:
                        return False
                    atom_size = struct.unpack(">Q", extended)[0]
                    header_size = 16
                elif size32 == 0:
                    atom_size = file_size - offset
                else:
                    atom_size = size32
                if atom_size < header_size or atom_size > file_size - offset:
                    return False
                if atom_type == b"moov" and moov_offset is None:
                    moov_offset = offset
                elif atom_type == b"mdat" and mdat_offset is None:
                    mdat_offset = offset
                offset += atom_size
        return offset == file_size and moov_offset is not None and mdat_offset is not None and moov_offset < mdat_offset
    except OSError:
        return False


def _measure_effective_silence(master: Path, *, threshold_dbfs: float = -90.0) -> dict[str, object]:
    """Decode all audio and require its maximum sample level to be at most -90 dBFS."""

    completed = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "info",
            "-i",
            str(master),
            "-map",
            "0:a:0",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    text = completed.stderr.decode("utf-8", errors="replace")
    match = re.search(r"max_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB", text, re.IGNORECASE)
    if completed.returncode or match is None:
        return {
            "passed": False,
            "method": "ffmpeg volumedetect over the full decoded audio stream",
            "thresholdDbfs": threshold_dbfs,
            "maxVolumeDbfs": None,
        }
    value = match.group(1).lower()
    maximum = float("-inf") if value == "-inf" else float(value)
    return {
        "passed": maximum <= threshold_dbfs,
        "method": "ffmpeg volumedetect over the full decoded audio stream",
        "thresholdDbfs": threshold_dbfs,
        "maxVolumeDbfs": "-inf" if maximum == float("-inf") else maximum,
    }


def extract_review_frames(
    master: Path,
    output: Path,
    *,
    timestamps_ms: tuple[int, ...] = REVIEW_FRAME_MILLISECONDS,
) -> tuple[tuple[Path, ...], Path]:
    """Extract exact review offsets and create a labelled seven-column contact sheet."""

    output.mkdir(parents=True, exist_ok=True)
    for pattern in ("frame-*.jpg", "contact-sheet*.jpg", "manifest.json"):
        for obsolete in output.glob(pattern):
            obsolete.unlink()
    frames: list[Path] = []
    for milliseconds in timestamps_ms:
        frame = output / f"frame-{milliseconds:06d}.jpg"
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{milliseconds / 1000:.3f}",
                "-i",
                str(master),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(frame),
            ]
        )
        frames.append(frame)
    columns = 7
    tile_width, image_height, label_height = 480, 270, 30
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * (image_height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (milliseconds, frame) in enumerate(zip(timestamps_ms, frames, strict=True)):
        row, column = divmod(index, columns)
        left = column * tile_width
        top = row * (image_height + label_height)
        with Image.open(frame) as source:
            tile = source.convert("RGB").resize((tile_width, image_height), Image.Resampling.LANCZOS)
        sheet.paste(tile, (left, top + label_height))
        draw.text((left + 8, top + 8), f"{milliseconds / 1000:07.3f}s", fill="black")
    contact_sheet = output / "contact-sheet.jpg"
    sheet.save(contact_sheet, quality=92)
    return tuple(frames), contact_sheet


def review_proxy_timestamps(timeline: dict[str, object]) -> set[int]:
    """Return one offset per second plus every rendered shot/action transition."""

    duration = int(timeline["durationMs"])
    timestamps = set(range(0, duration, 1_000))
    for chapter in timeline["chapters"]:
        for shot in chapter["shots"]:
            for key in ("renderedStartMs", "renderedEndMs"):
                value = round(shot[key])
                if 0 <= value < duration:
                    timestamps.add(value)
    for event in timeline["subtitleEvents"]:
        if event["style"] != "Action":
            continue
        for key in ("renderedStartMs", "renderedEndMs"):
            value = round(event[key])
            if 0 <= value < duration:
                timestamps.add(value)
    return timestamps


def extract_dense_review_proxy(
    master: Path, timeline_path: Path, output: Path
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Extract the auditable full-duration proxy and paginate it for visual review."""

    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    timestamps = tuple(sorted(review_proxy_timestamps(timeline)))
    output.mkdir(parents=True, exist_ok=True)
    for pattern in ("proxy-*.jpg", "contact-sheet-*.jpg", "manifest.json"):
        for obsolete in output.glob(pattern):
            obsolete.unlink()
    frames: list[Path] = []
    for milliseconds in timestamps:
        frame = output / f"proxy-{milliseconds:06d}.jpg"
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{milliseconds / 1000:.3f}",
                "-i",
                str(master),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(frame),
            ]
        )
        frames.append(frame)
    columns, rows = 7, 4
    tile_width, image_height, label_height = 384, 216, 24
    page_capacity = columns * rows
    pages: list[Path] = []
    for page_index, start in enumerate(range(0, len(frames), page_capacity), 1):
        page = Image.new(
            "RGB",
            (columns * tile_width, rows * (image_height + label_height)),
            "white",
        )
        draw = ImageDraw.Draw(page)
        for position, (milliseconds, frame) in enumerate(
            zip(
                timestamps[start : start + page_capacity],
                frames[start : start + page_capacity],
                strict=True,
            )
        ):
            row, column = divmod(position, columns)
            left = column * tile_width
            top = row * (image_height + label_height)
            with Image.open(frame) as source:
                tile = source.convert("RGB").resize(
                    (tile_width, image_height), Image.Resampling.LANCZOS
                )
            page.paste(tile, (left, top + label_height))
            draw.text((left + 5, top + 5), f"{milliseconds / 1000:07.3f}s", fill="black")
        path = output / f"contact-sheet-{page_index:02d}.jpg"
        page.save(path, quality=90)
        pages.append(path)
    return tuple(frames), tuple(pages)


def write_validation_report(
    automated: dict[str, object],
    output: Path,
    *,
    manual_review: dict[str, object] | None,
) -> dict[str, object]:
    """Persist a report that cannot pass until the documented manual gate passes."""

    report = json.loads(json.dumps(automated))
    report["manualReview"] = manual_review or {
        "passed": False,
        "method": "pending inspection of required frames and dense proxy pages",
        "findings": [],
    }
    manual_passed = bool(report.get("checks", {}).get("manualReview"))
    report["allPassed"] = bool(report["allPassed"] and manual_passed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def write_in_progress_validation_report(output: Path) -> dict[str, object]:
    """Invalidate any prior result before work which might raise begins."""

    report = {
        "status": "in-progress",
        "allPassed": False,
        "checks": {"validationComplete": False},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _core_artifact_hashes(master: Path, timeline: Path, ass: Path) -> dict[str, str]:
    return {
        "masterSha256": _sha256_file(master),
        "timelineSha256": _sha256_file(timeline),
        "assSha256": _sha256_file(ass),
    }


def write_review_manifest(
    output: Path,
    *,
    kind: str,
    master: Path,
    timeline: Path,
    ass: Path,
    artifacts: tuple[Path, ...],
) -> dict[str, object]:
    """Hash every reviewed file and the exact master/sidecars it represents."""

    payload = {
        "schemaVersion": 1,
        "kind": kind,
        "binding": _core_artifact_hashes(master, timeline, ass),
        "artifacts": [
            {"path": path.name, "sha256": _sha256_file(path)} for path in artifacts
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _verify_review_manifest(
    manifest: Path,
    master: Path,
    timeline: Path,
    ass: Path,
    *,
    expected_names: set[str] | None = None,
    expected_kind: str | None = None,
) -> bool:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        artifacts = payload["artifacts"]
        if payload.get("schemaVersion") != 1:
            return False
        if expected_kind is not None and payload.get("kind") != expected_kind:
            return False
        if payload.get("binding") != _core_artifact_hashes(master, timeline, ass):
            return False
        if not isinstance(artifacts, list) or not artifacts:
            return False
        recorded_names: list[str] = []
        for record in artifacts:
            name = record["path"]
            if not isinstance(name, str) or Path(name).name != name:
                return False
            artifact = manifest.parent / name
            if not artifact.is_file() or record.get("sha256") != _sha256_file(artifact):
                return False
            recorded_names.append(name)
        unique = len(recorded_names) == len(set(recorded_names))
        return unique and (
            expected_names is None or set(recorded_names) == expected_names
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def build_review_binding(
    master: Path,
    timeline: Path,
    ass: Path,
    required_manifest: Path,
    dense_manifest: Path,
) -> dict[str, str]:
    binding = _core_artifact_hashes(master, timeline, ass)
    binding.update(
        {
            "requiredManifestSha256": _sha256_file(required_manifest),
            "denseManifestSha256": _sha256_file(dense_manifest),
        }
    )
    return binding


def verify_manual_review_binding(
    manual_review: dict[str, object] | None,
    master: Path,
    timeline: Path,
    ass: Path,
    required_manifest: Path,
    dense_manifest: Path,
) -> bool:
    try:
        if not isinstance(manual_review, dict):
            return False
        manifests_valid = _verify_review_manifest(
            required_manifest,
            master,
            timeline,
            ass,
            expected_kind="required-frames",
        ) and _verify_review_manifest(
            dense_manifest,
            master,
            timeline,
            ass,
            expected_kind="dense-proxy",
        )
        return bool(
            manifests_valid
            and manual_review
            and manual_review.get("passed") is True
            and manual_review.get("artifactBinding")
            == build_review_binding(
                master, timeline, ass, required_manifest, dense_manifest
            )
        )
    except (OSError, TypeError, ValueError):
        return False


def _review_artifact_checks(
    master: Path,
    timeline: Path,
    ass: Path,
    expected_timeline: dict[str, object] | None,
    manual_review: dict[str, object] | None,
) -> tuple[bool, bool]:
    required_manifest = master.parent / "review-frames" / "manifest.json"
    dense_manifest = master.parent / "dense-review-proxy" / "manifest.json"
    required_names = {
        *(f"frame-{milliseconds:06d}.jpg" for milliseconds in REVIEW_FRAME_MILLISECONDS),
        "contact-sheet.jpg",
    }
    if expected_timeline is None:
        return False, False
    dense_timestamps = tuple(sorted(review_proxy_timestamps(expected_timeline)))
    page_count = (len(dense_timestamps) + 27) // 28
    dense_names = {
        *(f"proxy-{milliseconds:06d}.jpg" for milliseconds in dense_timestamps),
        *(f"contact-sheet-{index:02d}.jpg" for index in range(1, page_count + 1)),
    }
    manifests_valid = _verify_review_manifest(
        required_manifest,
        master,
        timeline,
        ass,
        expected_names=required_names,
        expected_kind="required-frames",
    ) and _verify_review_manifest(
        dense_manifest,
        master,
        timeline,
        ass,
        expected_names=dense_names,
        expected_kind="dense-proxy",
    )
    actual_required = {path.name for path in required_manifest.parent.glob("*.jpg")}
    actual_dense = {path.name for path in dense_manifest.parent.glob("*.jpg")}
    manifests_valid = bool(
        manifests_valid
        and actual_required == required_names
        and actual_dense == dense_names
    )
    manual_valid = bool(
        manifests_valid
        and verify_manual_review_binding(
            manual_review,
            master,
            timeline,
            ass,
            required_manifest,
            dense_manifest,
        )
    )
    return manifests_valid, manual_valid


def _expected_schedule_checks(plan: VideoPlan) -> dict[str, bool]:
    chapter_frames = [chapter.duration_ms * 30 // 1_000 for chapter in plan.chapters]
    sums_exact = all(
        sum(shot.duration_ms for shot in chapter.shots) == chapter.duration_ms
        for chapter in plan.chapters
    )
    chapter_exact = (
        len(plan.chapters) == 6
        and chapter_frames == [540, 1200, 1200, 1200, 2610, 1650]
        and sum(chapter_frames) == 8400
    )
    v9_boundary = len(chapter_frames) >= 5 and sum(chapter_frames[:5]) == 6750
    moon = next((chapter for chapter in plan.chapters if chapter.id == "moon_variants"), None)
    moon_actions = [] if moon is None else [
        shot for shot in moon.shots if shot.id in {"moon-184", "moon-232", "moon-full"}
    ]
    moon_parity = (
        len(moon_actions) == 3
        and all(round(shot.duration_ms * 30 / 1_000) == 270 for shot in moon_actions)
    )
    return {
        "chapterShotSums": sums_exact,
        "chapterFrameTotals": chapter_exact,
        "v9MoonBoundary": v9_boundary,
        "moonActionFrameParity": moon_parity,
    }


def _timeline_and_ass_checks(
    master: Path, expected_timeline: dict[str, object] | None
) -> dict[str, bool]:
    output = master.parent
    timeline_path = output / "master-v1-timeline.json"
    ass_path = output / "master-v1.ass"
    if not timeline_path.exists() or not ass_path.exists() or expected_timeline is None:
        return {"timelineMatchesPlan": False, "assMatchesTimeline": False}
    try:
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        timeline_ok = timeline == expected_timeline
        expected_ass = ASS_HEADER + "".join(
            "Dialogue: 0,"
            f"{ass_frame_time(event['startFrame'])},"
            f"{ass_frame_time(event['endFrame'])},"
            f"{event['style']},,0,0,0,,{_ass_escape(event['text'])}\n"
            for event in expected_timeline["subtitleEvents"]
        )
        return {
            "timelineMatchesPlan": bool(timeline_ok),
            "assMatchesTimeline": ass_path.read_text(encoding="utf-8-sig") == expected_ass,
        }
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return {"timelineMatchesPlan": False, "assMatchesTimeline": False}


def validate_master(
    master: Path,
    plan: VideoPlan,
    *,
    probe: dict | None = None,
    expected_timeline: dict[str, object] | None = None,
    manual_review: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate the release master, public text, source provenance, and timing sidecars."""

    master_exists = master.is_file()
    probe = probe if probe is not None else (_probe_master(master) if master_exists else {})
    raw_streams = probe.get("streams", []) if isinstance(probe, dict) else []
    streams = raw_streams if isinstance(raw_streams, list) else []
    stream_records_valid = all(isinstance(stream, dict) for stream in streams)
    stream_objects = [stream for stream in streams if isinstance(stream, dict)]
    videos = [stream for stream in stream_objects if stream.get("codec_type") == "video"]
    audios = [stream for stream in stream_objects if stream.get("codec_type") == "audio"]
    video = videos[0] if videos else {}
    audio = audios[0] if audios else {}
    fps = _float_frame_rate(video.get("avg_frame_rate", "0/1"))
    try:
        format_info = probe.get("format", {})
        duration_ms = (
            float(format_info.get("duration", 0)) * 1_000
            if isinstance(format_info, dict)
            else 0.0
        )
    except (TypeError, ValueError):
        duration_ms = 0.0
    sources = _all_source_paths(plan)
    resolved_sources = [str(path.resolve(strict=False)) for path in sources]
    sidecar_provenance, sidecar_public_text, sidecar_sources = _sidecar_security(master)
    resolved_sources.extend(sidecar_sources)
    source_provenance = (
        all(path.exists() and _source_is_approved(path) for path in sources)
        and sidecar_provenance
    )
    metadata_safe = _public_text_is_safe(_probe_metadata_strings(probe))
    public_text_safe = (
        _public_text_is_safe(_public_plan_strings(plan)) and sidecar_public_text
        and metadata_safe
    )
    schedule_checks = _expected_schedule_checks(plan)
    timeline_path = master.parent / "master-v1-timeline.json"
    ass_path = master.parent / "master-v1.ass"
    if manual_review is None:
        manual_path = master.parent / "manual-review.json"
        if manual_path.exists():
            try:
                manual_review = json.loads(manual_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manual_review = None
    artifacts_bound, manual_bound = _review_artifact_checks(
        master, timeline_path, ass_path, expected_timeline, manual_review
    )
    if master_exists:
        sidecar_checks = _timeline_and_ass_checks(master, expected_timeline)
        silence = _measure_effective_silence(master)
        faststart = _read_mp4_atom_order(master)
    else:
        sidecar_checks = {"timelineMatchesPlan": False, "assMatchesTimeline": False}
        silence = {
            "passed": False,
            "method": "ffmpeg volumedetect over the full decoded audio stream",
            "thresholdDbfs": -90.0,
            "maxVolumeDbfs": None,
        }
        faststart = False
    try:
        frame_count_valid = int(video.get("nb_read_frames")) == 8400
    except (TypeError, ValueError):
        frame_count_valid = False
    checks = {
        "masterExists": master_exists,
        "streamCount": (
            stream_records_valid
            and len(streams) == 2
            and len(videos) == 1
            and len(audios) == 1
        ),
        "videoDimensions": video.get("width") == 1920 and video.get("height") == 1080,
        "videoCodec": video.get("codec_name") == "h264",
        "videoProfile": video.get("profile") == "High",
        "videoPixelFormat": video.get("pix_fmt") == "yuv420p",
        "sampleAspectRatio": video.get("sample_aspect_ratio") == "1:1",
        "videoFrameRate": abs(fps - 30.0) < 1e-9,
        "videoFrameCount": frame_count_valid,
        "audioCodec": audio.get("codec_name") == "aac",
        "audioSampleRate": str(audio.get("sample_rate")) == "48000",
        "audioChannels": audio.get("channels") == 2,
        "audioSamplesEffectivelySilent": bool(silence["passed"]),
        "duration": abs(duration_ms - 280_000) <= 100,
        "faststart": faststart,
        "sourceProvenance": source_provenance,
        "publicTextPrivacy": public_text_safe,
        "publicMetadataPrivacy": metadata_safe,
        "reviewArtifactsBound": artifacts_bound,
        "manualReview": manual_bound,
        **schedule_checks,
        **sidecar_checks,
    }
    private_anime_used = any("anime-reference" in path.lower() for path in resolved_sources)
    return {
        "master": str(master.resolve(strict=False)),
        "video": {
            "width": video.get("width"),
            "height": video.get("height"),
            "fps": fps,
            "codec": video.get("codec_name"),
            "pixelFormat": video.get("pix_fmt"),
        },
        "audio": {
            "codec": audio.get("codec_name"),
            "sampleRate": int(audio.get("sample_rate", 0) or 0)
            if str(audio.get("sample_rate", 0) or 0).isdigit()
            else 0,
            "channels": audio.get("channels"),
            "silence": silence,
        },
        "durationMs": duration_ms,
        "resolvedSources": resolved_sources,
        "privateAnimeUsed": private_anime_used,
        "privacyScanPassed": public_text_safe,
        "manualReview": manual_review or {
            "passed": False,
            "method": "pending inspection of exact bound review artifacts",
            "findings": [],
        },
        "checks": checks,
        "allPassed": all(checks.values()) and not private_anime_used,
    }


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
