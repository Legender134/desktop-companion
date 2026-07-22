from __future__ import annotations

import json
import subprocess
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
        else:
            crops = tuple((0, offset) for offset in range(frame_count))

        rows = height // CELL_SIZE[1]
        if any(row >= rows or column >= ATLAS_COLUMNS for row, column in crops):
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
