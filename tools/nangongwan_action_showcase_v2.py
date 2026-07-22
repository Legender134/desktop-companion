"""Immutable source contracts for the simple Nangong Wan action showcase."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
from itertools import zip_longest
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from typing import BinaryIO, Callable, Iterable, Iterator, Literal

from PIL import Image, ImageChops, ImageStat

from tools.nangongwan_rooftop_making_of import ActionSource, TimedFrames, read_action


FPS = 30
FRAME_SIZE = (1600, 900)
SPRITE_SIZE = (192, 208)
SPRITE_ORIGIN = (704, 346)
BACKGROUND_SHA256 = "1bca26d93bf3126b3c8be30e2b5f944b4912a4032ac55990b72cfb3d99ba745a"
BLINK_SOURCE_INDICES = (0, 0, 0, 1, 2, 3, 2, 1, 0, 0, 0, 0, 0, 0, 0)
_MOON_SEGMENT_IDS = frozenset(("moon-184", "moon-232", "moon-full"))
_MOON_DURATION_MS = 8_990
_MOON_OUTPUT_FRAMES = 270
_EXPECTED_SEGMENT_IDS = (
    "blink-00",
    "standing-chestnut",
    "blink-01",
    "cinematic-36",
    "blink-02",
    "anchored-48",
    "blink-03",
    "v9-small-moon",
    "blink-04",
    "moon-184",
    "blink-05",
    "moon-232",
    "blink-06",
    "moon-full",
    "blink-07",
)
_EXPECTED_OUTPUT_FRAMES = (15, 62, 15, 273, 15, 288, 15, 920, 15, 270, 15, 270, 15, 270, 15)
_EXPECTED_TOTAL_FRAMES = 2473
_FORBIDDEN_SOURCE_MARKERS = ("anime-reference", "do-not-publish")
_SSIM_THRESHOLD = 0.995
_OUTSIDE_MIN_PSNR_DB = 40.0
_CENTER_MIN_PSNR_DB = 29.0
_CENTER_MIN_TEMPORAL_RATIO = 0.10
_EXPECTED_VIDEO_TIME_BASE = Fraction(1, 15_360)


@dataclass(frozen=True)
class SourceAsset:
    path: Path
    sha256: str
    role: Literal["background", "atlas", "manifest", "sequence"]
    id: str = ""


@dataclass(frozen=True)
class ShowcaseSource:
    kind: Literal["blink", "action", "sequence"]
    actions: tuple[ActionSource, ...]
    assets: tuple[SourceAsset, ...] = ()


@dataclass(frozen=True)
class ShowcaseSegment:
    id: str
    source: ShowcaseSource
    output_frames: int


@dataclass(frozen=True)
class ShowcasePlan:
    background_source: Path
    segments: tuple[ShowcaseSegment, ...]
    sequence_sources: tuple[Path, ...] = ()
    source_inventory: tuple[SourceAsset, ...] = ()

    @property
    def total_frames(self) -> int:
        return sum(segment.output_frames for segment in self.segments)


@dataclass(frozen=True)
class SegmentFrames:
    frames: tuple[Image.Image, ...]


@dataclass(frozen=True)
class VideoProbe:
    width: int
    height: int
    codec: str
    profile: str
    pixel_format: str
    sample_aspect_ratio: str
    frame_rate: Fraction
    nb_read_frames: int | None
    average_frame_rate: Fraction = Fraction(FPS, 1)
    time_base: Fraction = _EXPECTED_VIDEO_TIME_BASE
    duration: Fraction = Fraction(0, 1)


@dataclass(frozen=True)
class AudioProbe:
    codec: str
    sample_rate: int
    channels: int
    duration: Fraction


@dataclass(frozen=True)
class MediaProbe:
    video: VideoProbe
    audio: AudioProbe | None
    subtitle_streams: int
    data_streams: int
    other_streams: int = 0


def _validate_source_asset_paths(assets: tuple[SourceAsset, ...]) -> None:
    seen: dict[Path, str] = {}
    ids: set[str] = set()
    for asset in assets:
        resolved = asset.path.resolve(strict=False)
        encoded = str(resolved).lower()
        if any(marker in encoded for marker in _FORBIDDEN_SOURCE_MARKERS):
            raise ValueError(f"showcase source is not public: {asset.path}")
        if not asset.path.is_file():
            raise ValueError(f"showcase source is missing: {asset.path}")
        if not re.fullmatch(r"[0-9a-f]{64}", asset.sha256):
            raise ValueError(f"source SHA-256 is invalid for {asset.path}")
        if not asset.id or asset.id in ids:
            raise ValueError(f"source inventory id is missing or duplicated: {asset.id!r}")
        ids.add(asset.id)
        previous = seen.setdefault(resolved, asset.sha256)
        if previous != asset.sha256:
            raise ValueError(f"conflicting source SHA-256 values for {asset.path}")


def _verified_source_snapshots(
    assets: tuple[SourceAsset, ...],
) -> dict[Path, bytes]:
    """Hash every declared public input before any caller parses or decodes it."""

    _validate_source_asset_paths(assets)
    snapshots: dict[Path, bytes] = {}
    mismatches: list[str] = []
    for asset in assets:
        resolved = asset.path.resolve()
        if resolved in snapshots:
            continue
        encoded = asset.path.read_bytes()
        actual = sha256(encoded).hexdigest()
        if actual != asset.sha256:
            mismatches.append(
                f"{asset.path} expected {asset.sha256}, found {actual}"
            )
        snapshots[resolved] = encoded
    if mismatches:
        raise ValueError("source SHA-256 mismatch: " + "; ".join(mismatches))
    return snapshots


def _run_capture(command: list[str], *, tool: str) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise RuntimeError(f"could not start {tool}: {error}") from error
    if completed.returncode:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"{tool} failed with exit code {completed.returncode}:\n{stderr}")
    return completed


def _probe_document(path: Path, *, count_frames: bool = False) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"media file is missing: {path}")
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command.append("-count_frames")
    command.extend(("-show_streams", "-of", "json", str(path)))
    completed = _run_capture(command, tool="ffprobe")
    try:
        document = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("ffprobe returned invalid JSON") from error
    if not isinstance(document, dict):
        raise ValueError("ffprobe JSON must be an object")
    return document


def _streams(document: dict[str, object]) -> tuple[dict[str, object], ...]:
    streams = document.get("streams")
    if not isinstance(streams, list) or not all(
        isinstance(stream, dict) for stream in streams
    ):
        raise ValueError("ffprobe JSON does not contain a valid stream list")
    return tuple(streams)


def _required_string(stream: dict[str, object], key: str) -> str:
    value = stream.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"ffprobe stream has no valid {key}")
    return value


def _required_int(stream: dict[str, object], key: str) -> int:
    value = stream.get(key)
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"ffprobe stream has no valid {key}") from error
    return parsed


def _frame_rate(stream: dict[str, object]) -> Fraction:
    value = _required_string(stream, "r_frame_rate")
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("ffprobe stream has no valid r_frame_rate") from error
    if rate <= 0:
        raise ValueError("ffprobe stream frame rate must be positive")
    return rate


def _rational_field(stream: dict[str, object], key: str) -> Fraction:
    value = _required_string(stream, key)
    try:
        parsed = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f"ffprobe stream has no valid {key}") from error
    if parsed <= 0:
        raise ValueError(f"ffprobe stream {key} must be positive")
    return parsed


def _positive_fraction(stream: dict[str, object], key: str) -> Fraction:
    value = _required_string(stream, key)
    try:
        parsed = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f"ffprobe stream has no valid {key}") from error
    if parsed <= 0:
        raise ValueError(f"ffprobe stream {key} must be positive")
    return parsed


def probe_media(path: Path, *, count_frames: bool = False) -> MediaProbe:
    """Read exact stream metadata from one media file with FFprobe."""

    streams = _streams(_probe_document(path, count_frames=count_frames))
    videos = tuple(stream for stream in streams if stream.get("codec_type") == "video")
    audios = tuple(stream for stream in streams if stream.get("codec_type") == "audio")
    if len(videos) != 1:
        raise ValueError(f"media must contain exactly one video stream, found {len(videos)}")
    if len(audios) > 1:
        raise ValueError(f"media must contain at most one audio stream, found {len(audios)}")

    video_stream = videos[0]
    raw_frames = video_stream.get("nb_read_frames")
    if raw_frames in (None, "N/A"):
        frame_count = None
    else:
        try:
            frame_count = int(raw_frames)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise ValueError("ffprobe stream has invalid nb_read_frames") from error
    video_time_base = _rational_field(video_stream, "time_base")
    video = VideoProbe(
        width=_required_int(video_stream, "width"),
        height=_required_int(video_stream, "height"),
        codec=_required_string(video_stream, "codec_name"),
        profile=_required_string(video_stream, "profile"),
        pixel_format=_required_string(video_stream, "pix_fmt"),
        sample_aspect_ratio=_required_string(video_stream, "sample_aspect_ratio"),
        frame_rate=_frame_rate(video_stream),
        nb_read_frames=frame_count,
        average_frame_rate=_rational_field(video_stream, "avg_frame_rate"),
        time_base=video_time_base,
        duration=_required_int(video_stream, "duration_ts") * video_time_base,
    )
    audio = None
    if audios:
        audio_stream = audios[0]
        audio = AudioProbe(
            codec=_required_string(audio_stream, "codec_name"),
            sample_rate=_required_int(audio_stream, "sample_rate"),
            channels=_required_int(audio_stream, "channels"),
            duration=_positive_fraction(audio_stream, "duration"),
        )
    return MediaProbe(
        video=video,
        audio=audio,
        subtitle_streams=sum(stream.get("codec_type") == "subtitle" for stream in streams),
        data_streams=sum(stream.get("codec_type") == "data" for stream in streams),
        other_streams=sum(
            stream.get("codec_type") not in {"video", "audio", "subtitle", "data"}
            for stream in streams
        ),
    )


def _probe_video_timestamps(master: Path, expected_frames: int) -> dict[str, object]:
    completed = _run_capture(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp",
            "-of",
            "json",
            str(master),
        ],
        tool="ffprobe",
    )
    try:
        document = json.loads(completed.stdout)
        frames = document["frames"]
        timestamps = tuple(int(frame["best_effort_timestamp"]) for frame in frames)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("ffprobe returned invalid decoded video timestamps") from error
    step = _EXPECTED_VIDEO_TIME_BASE.denominator // FPS
    mismatches = [
        index
        for index, timestamp in enumerate(timestamps)
        if timestamp != index * step
    ]
    return {
        "passed": len(timestamps) == expected_frames and not mismatches,
        "frameCount": len(timestamps),
        "firstPts": timestamps[0] if timestamps else None,
        "lastPts": timestamps[-1] if timestamps else None,
        "step": step,
        "firstMismatchFrame": mismatches[0] if mismatches else None,
    }


def write_silent_video(
    frames: Iterable[Image.Image], output: Path, *, expected_frames: int
) -> None:
    """Consume one frame iterator once and encode exactly ``expected_frames``."""

    if expected_frames <= 0:
        raise ValueError("expected frame count must be positive")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        f"{FRAME_SIZE[0]}x{FRAME_SIZE[1]}",
        "-framerate",
        str(FPS),
        "-i",
        "-",
        "-vf",
        "setsar=1",
        "-frames:v",
        str(expected_frames),
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
        str(FPS),
        "-movflags",
        "+faststart",
        str(output),
    ]
    iterator = iter(frames)
    close_source = getattr(iterator, "close", None)
    process: subprocess.Popen[bytes] | None = None
    try:
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except OSError as error:
            raise RuntimeError(f"could not start ffmpeg: {error}") from error
        assert process.stdin is not None
        for index in range(expected_frames):
            try:
                frame = next(iterator)
            except StopIteration as error:
                raise ValueError(
                    f"frame stream ended at {index}; expected {expected_frames} frames"
                ) from error
            if frame.size != FRAME_SIZE or frame.mode != "RGB":
                raise ValueError(f"video frames must be RGB images sized {FRAME_SIZE}")
            process.stdin.write(frame.tobytes())
        try:
            next(iterator)
        except StopIteration:
            pass
        else:
            raise ValueError(
                f"frame stream contains more than expected {expected_frames} frames"
            )
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr is not None else b""
        returncode = process.wait()
        if returncode:
            message = stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"ffmpeg failed with exit code {returncode}:\n{message}")
    except BaseException:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        output.unlink(missing_ok=True)
        raise
    finally:
        if callable(close_source):
            close_source()


def _video_stream_signature(path: Path) -> tuple[object, ...]:
    streams = _streams(_probe_document(path))
    videos = tuple(stream for stream in streams if stream.get("codec_type") == "video")
    if len(videos) != 1:
        raise ValueError(f"clip must contain exactly one video stream: {path}")
    if any(stream.get("codec_type") != "video" for stream in streams):
        raise ValueError(f"concat clip must contain video only: {path}")
    video = videos[0]
    keys = (
        "codec_name",
        "profile",
        "width",
        "height",
        "pix_fmt",
        "sample_aspect_ratio",
        "r_frame_rate",
        "time_base",
    )
    if any(video.get(key) in (None, "") for key in keys):
        raise ValueError(f"clip has incomplete video metadata: {path}")
    return tuple(video[key] for key in keys)


def _concat_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", r"'\''")


def concat_clips(clips: tuple[Path, ...], output: Path) -> None:
    """Losslessly concatenate normalized, video-only clips in exact order."""

    if not clips:
        raise ValueError("at least one clip is required")
    signatures = tuple(_video_stream_signature(clip) for clip in clips)
    if any(signature != signatures[0] for signature in signatures[1:]):
        raise ValueError("all concat clips must have identical video parameters and timebase")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="nangongwan-concat-",
            suffix=".txt",
            delete=False,
        ) as stream:
            manifest = Path(stream.name)
            stream.writelines(f"file '{_concat_path(clip)}'\n" for clip in clips)
        _run_capture(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
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
                str(output),
            ],
            tool="ffmpeg",
        )
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    finally:
        if manifest is not None:
            manifest.unlink(missing_ok=True)


def add_silent_aac(video: Path, output: Path, *, expected_frames: int) -> None:
    """Copy video unchanged while adding a silent 48 kHz stereo AAC track."""

    if expected_frames <= 0:
        raise ValueError("expected frame count must be positive")
    source = probe_media(video, count_frames=True)
    if source.audio is not None or source.video.nb_read_frames != expected_frames:
        raise ValueError("input must be silent and have the explicit expected frame count")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run_capture(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(video),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-frames:v",
                str(expected_frames),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output),
            ],
            tool="ffmpeg",
        )
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    result = probe_media(output, count_frames=True)
    if result.video.nb_read_frames != expected_frames:
        output.unlink(missing_ok=True)
        raise ValueError("final video frame count does not match expected_frames")


def make_blink(idle: TimedFrames) -> SegmentFrames:
    """Build the approved fifteen-frame open-close-open idle blink."""

    if len(idle.frames) < 4:
        raise ValueError("idle action needs at least four frames")
    return SegmentFrames(
        tuple(idle.frames[index].copy() for index in BLINK_SOURCE_INDICES)
    )


def _validate_timed_frames(timed: TimedFrames) -> None:
    if not timed.frames:
        raise ValueError("action needs at least one frame")
    if len(timed.frames) != len(timed.durations_ms):
        raise ValueError("action frames and durations must have matching counts")
    if any(frame.size != SPRITE_SIZE for frame in timed.frames):
        raise ValueError(f"action frames must be {SPRITE_SIZE}")
    if any(not isinstance(duration, int) or duration <= 0 for duration in timed.durations_ms):
        raise ValueError("action durations must be positive integers")


def _midpoint_positions(total_duration_ms: int, output_frames: int) -> tuple[Fraction, ...]:
    return tuple(
        Fraction((2 * index + 1) * total_duration_ms, 2 * output_frames)
        for index in range(output_frames)
    )


_MOON_SAMPLE_POSITIONS = _midpoint_positions(_MOON_DURATION_MS, _MOON_OUTPUT_FRAMES)


def _source_indices_at_positions(
    timed: TimedFrames, positions: tuple[Fraction, ...]
) -> tuple[int, ...]:
    _validate_timed_frames(timed)
    if not positions:
        raise ValueError("resampling positions must not be empty")
    cumulative_durations: list[int] = []
    cumulative = 0
    for duration in timed.durations_ms:
        cumulative += duration
        cumulative_durations.append(cumulative)

    source_indices = tuple(
        next(
            source_index
            for source_index, source_end in enumerate(cumulative_durations)
            if source_end > timestamp
        )
        for timestamp in positions
    )
    if len(source_indices) == 1:
        return (0,)
    return (0, *source_indices[1:-1], len(timed.frames) - 1)


def _resample_at_positions(
    timed: TimedFrames, positions: tuple[Fraction, ...]
) -> SegmentFrames:
    source_indices = _source_indices_at_positions(timed, positions)
    return SegmentFrames(tuple(timed.frames[index].copy() for index in source_indices))


def resample_action(timed: TimedFrames, output_frames: int) -> SegmentFrames:
    """Resample one native action at exact output-frame midpoint timestamps."""

    if output_frames <= 0:
        raise ValueError("output frame count must be positive")
    _validate_timed_frames(timed)
    return _resample_at_positions(
        timed, _midpoint_positions(timed.duration_ms, output_frames)
    )


def compose_frame(background: Image.Image, sprite: Image.Image) -> Image.Image:
    """Alpha-composite one unscaled native sprite at the approved center."""

    if background.size != FRAME_SIZE or background.mode != "RGB":
        raise ValueError(f"background must be an RGB image sized {FRAME_SIZE}")
    if sprite.size != SPRITE_SIZE or sprite.mode != "RGBA":
        raise ValueError(f"sprite must be an RGBA image sized {SPRITE_SIZE}")
    canvas = background.copy().convert("RGBA")
    canvas.alpha_composite(sprite, SPRITE_ORIGIN)
    return canvas.convert("RGB")


def _concatenate_actions(source: ShowcaseSource) -> TimedFrames:
    if not source.actions:
        raise ValueError("showcase source needs at least one action")
    if source.assets:
        _verified_source_snapshots(source.assets)
    timed_actions = tuple(read_action(action) for action in source.actions)
    for timed in timed_actions:
        _validate_timed_frames(timed)
    return TimedFrames(
        tuple(frame for timed in timed_actions for frame in timed.frames),
        tuple(duration for timed in timed_actions for duration in timed.durations_ms),
    )


def _segment_source_indices(
    segment: ShowcaseSegment, timed: TimedFrames
) -> tuple[int, ...]:
    if segment.source.kind == "blink":
        if len(timed.frames) < 4 or segment.output_frames != len(BLINK_SOURCE_INDICES):
            raise ValueError("blink segment does not match the approved source mapping")
        return BLINK_SOURCE_INDICES
    if segment.source.kind not in {"action", "sequence"}:
        raise ValueError(f"unknown showcase source kind: {segment.source.kind}")
    if segment.id in _MOON_SEGMENT_IDS:
        if (timed.duration_ms, segment.output_frames) != (
            _MOON_DURATION_MS,
            _MOON_OUTPUT_FRAMES,
        ):
            raise ValueError("moon segments must use the approved shared time positions")
        positions = _MOON_SAMPLE_POSITIONS
    else:
        positions = _midpoint_positions(timed.duration_ms, segment.output_frames)
    return _source_indices_at_positions(timed, positions)


def _iter_expected_center_frames(
    plan: ShowcasePlan, background: Path
) -> Iterator[Image.Image]:
    """Yield all 2473 expected native center crops without full-frame buffering."""

    rectangle = (
        SPRITE_ORIGIN[0],
        SPRITE_ORIGIN[1],
        SPRITE_ORIGIN[0] + SPRITE_SIZE[0],
        SPRITE_ORIGIN[1] + SPRITE_SIZE[1],
    )
    with Image.open(background) as source:
        center_background = source.convert("RGB").crop(rectangle).convert("RGBA")
    for segment in plan.segments:
        timed = _concatenate_actions(segment.source)
        source_indices = _segment_source_indices(segment, timed)
        if len(source_indices) != segment.output_frames:
            raise ValueError("expected center sequence does not match segment frames")
        for source_index in source_indices:
            center = center_background.copy()
            center.alpha_composite(timed.frames[source_index], (0, 0))
            yield center.convert("RGB")


def iter_segment_frames(
    segment: ShowcaseSegment, background: Image.Image
) -> Iterator[Image.Image]:
    """Yield full-resolution composites one at a time in exact approved order."""

    timed = _concatenate_actions(segment.source)
    source_indices = _segment_source_indices(segment, timed)
    if len(source_indices) != segment.output_frames:
        raise ValueError("segment frame count does not match its plan")
    for source_index in source_indices:
        yield compose_frame(background, timed.frames[source_index])


def build_segment_frames(segment: ShowcaseSegment, background: Image.Image) -> SegmentFrames:
    """Materialize a segment only for focused tests; production uses the iterator."""

    return SegmentFrames(tuple(iter_segment_frames(segment, background)))


def _verified_background_snapshot(source: Path) -> tuple[str, bytes, bytes]:
    encoded = source.read_bytes()
    encoded_hash = sha256(encoded).hexdigest()
    if encoded_hash != BACKGROUND_SHA256:
        raise ValueError("background SHA-256 does not match the approved source")
    with Image.open(BytesIO(encoded)) as image:
        if image.size != FRAME_SIZE:
            raise ValueError(f"background size must be {FRAME_SIZE}")
        if image.mode != "RGB":
            raise ValueError("background mode must be RGB")
        image.load()
        pixels = image.tobytes()
    return encoded_hash, encoded, pixels


def _verified_background_pixels(source: Path) -> tuple[str, bytes]:
    encoded_hash, _, pixels = _verified_background_snapshot(source)
    return encoded_hash, pixels


def copy_verified_background(source: Path, output: Path) -> str:
    """Copy only the approved RGB desktop background without re-encoding it."""

    encoded_hash, encoded, source_pixels = _verified_background_snapshot(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)

    copied_hash = sha256(output.read_bytes()).hexdigest()
    if copied_hash != encoded_hash:
        raise ValueError("copied background SHA-256 does not match the source")
    with Image.open(output) as copied:
        if copied.size != FRAME_SIZE or copied.mode != "RGB":
            raise ValueError("copied background no longer has the approved RGB pixels")
        copied.load()
        if copied.tobytes() != source_pixels:
            raise ValueError("copied background RGB pixels do not match the source")
    return copied_hash


def _read_mp4_atom_order(master: Path) -> bool:
    """Require a structurally valid top-level moov atom before mdat."""

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
        return (
            offset == file_size
            and moov_offset is not None
            and mdat_offset is not None
            and moov_offset < mdat_offset
        )
    except OSError:
        return False


def _measure_audio_silence(master: Path) -> dict[str, object]:
    completed = _run_capture(
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
        tool="ffmpeg",
    )
    output = completed.stderr.decode("utf-8", errors="replace")
    match = re.search(
        r"max_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB", output, re.IGNORECASE
    )
    if match is None:
        raise ValueError("ffmpeg volumedetect did not report max_volume")
    encoded = match.group(1).lower()
    maximum = float("-inf") if encoded == "-inf" else float(encoded)
    return {
        "passed": maximum <= -90.0,
        "thresholdDbfs": -90.0,
        "maxVolumeDbfs": "-inf" if math.isinf(maximum) else maximum,
    }


def _extract_raw_frames(master: Path, frame_indices: tuple[int, ...]) -> tuple[Image.Image, ...]:
    if not frame_indices or any(index < 0 for index in frame_indices):
        raise ValueError("frame indices must be non-empty and non-negative")
    expression = "+".join(f"eq(n\\,{index})" for index in frame_indices)
    completed = _run_capture(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(master),
            "-map",
            "0:v:0",
            "-vf",
            f"select={expression}",
            "-fps_mode",
            "vfr",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        tool="ffmpeg",
    )
    frame_bytes = FRAME_SIZE[0] * FRAME_SIZE[1] * 3
    expected_bytes = frame_bytes * len(frame_indices)
    if len(completed.stdout) != expected_bytes:
        raise ValueError(
            f"decoded {len(completed.stdout)} bytes, expected {expected_bytes}"
        )
    return tuple(
        Image.frombytes(
            "RGB",
            FRAME_SIZE,
            completed.stdout[offset : offset + frame_bytes],
        )
        for offset in range(0, expected_bytes, frame_bytes)
    )


def _outside_sprite_ssim(reference: Image.Image, candidate: Image.Image) -> float:
    if reference.size != FRAME_SIZE or candidate.size != FRAME_SIZE:
        raise ValueError("SSIM inputs must have the final video geometry")
    mask = Image.new("L", FRAME_SIZE, 255)
    mask.paste(
        0,
        (
            SPRITE_ORIGIN[0],
            SPRITE_ORIGIN[1],
            SPRITE_ORIGIN[0] + SPRITE_SIZE[0],
            SPRITE_ORIGIN[1] + SPRITE_SIZE[1],
        ),
    )
    first = reference.convert("L")
    second = candidate.convert("L")
    first_stat = ImageStat.Stat(first, mask)
    second_stat = ImageStat.Stat(second, mask)
    mean_first = first_stat.mean[0]
    mean_second = second_stat.mean[0]
    variance_first = first_stat.var[0]
    variance_second = second_stat.var[0]
    outside_regions = (
        (0, 0, FRAME_SIZE[0], SPRITE_ORIGIN[1]),
        (0, SPRITE_ORIGIN[1] + SPRITE_SIZE[1], FRAME_SIZE[0], FRAME_SIZE[1]),
        (0, SPRITE_ORIGIN[1], SPRITE_ORIGIN[0], SPRITE_ORIGIN[1] + SPRITE_SIZE[1]),
        (
            SPRITE_ORIGIN[0] + SPRITE_SIZE[0],
            SPRITE_ORIGIN[1],
            FRAME_SIZE[0],
            SPRITE_ORIGIN[1] + SPRITE_SIZE[1],
        ),
    )
    product_sum = 0
    pixel_count = 0
    for box in outside_regions:
        first_pixels = first.crop(box).tobytes()
        second_pixels = second.crop(box).tobytes()
        product_sum += sum(
            first_value * second_value
            for first_value, second_value in zip(first_pixels, second_pixels, strict=True)
        )
        pixel_count += len(first_pixels)
    product_mean = product_sum / pixel_count
    covariance = product_mean - mean_first * mean_second
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    numerator = (2 * mean_first * mean_second + c1) * (2 * covariance + c2)
    denominator = (mean_first**2 + mean_second**2 + c1) * (
        variance_first + variance_second + c2
    )
    return max(-1.0, min(1.0, numerator / denominator))


def _timeline_segments(document: dict[str, object]) -> tuple[dict[str, object], ...]:
    entries = document.get("segments")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError("timeline has no valid segment list")
    return tuple(entries)


def _encoded_background_fidelity(
    master: Path, background: Path, timeline_document: dict[str, object]
) -> dict[str, object]:
    expected_frames = timeline_document.get("totalFrames")
    if not isinstance(expected_frames, int) or expected_frames <= 0:
        raise ValueError("timeline totalFrames must be a positive integer")
    regions = {
        "top": (FRAME_SIZE[0], SPRITE_ORIGIN[1], 0, 0),
        "bottom": (
            FRAME_SIZE[0],
            FRAME_SIZE[1] - SPRITE_ORIGIN[1] - SPRITE_SIZE[1],
            0,
            SPRITE_ORIGIN[1] + SPRITE_SIZE[1],
        ),
        "left": (SPRITE_ORIGIN[0], SPRITE_SIZE[1], 0, SPRITE_ORIGIN[1]),
        "right": (
            FRAME_SIZE[0] - SPRITE_ORIGIN[0] - SPRITE_SIZE[0],
            SPRITE_SIZE[1],
            SPRITE_ORIGIN[0] + SPRITE_SIZE[0],
            SPRITE_ORIGIN[1],
        ),
    }
    region_scores: dict[str, tuple[float, ...]] = {}
    for name, (width, height, x, y) in regions.items():
        completed = _run_capture(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(master),
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-i",
                str(background),
                "-filter_complex",
                (
                    f"[0:v]trim=end_frame={expected_frames},crop={width}:{height}:{x}:{y},"
                    "setpts=PTS-STARTPTS[encoded];"
                    f"[1:v]trim=end_frame={expected_frames},crop={width}:{height}:{x}:{y},"
                    "setpts=PTS-STARTPTS[reference];"
                    "[encoded][reference]psnr=stats_file=-[checked]"
                ),
                "-map",
                "[checked]",
                "-f",
                "null",
                "-",
            ],
            tool="ffmpeg",
        )
        rows = tuple(
            (
                int(match.group(1)),
                float("inf")
                if match.group(2).lower() == b"inf"
                else float(match.group(2)),
            )
            for match in re.finditer(
                rb"n:\s*(\d+).*?psnr_avg:\s*(inf|[-+0-9.eE]+)",
                completed.stdout,
                re.IGNORECASE,
            )
        )
        if tuple(index for index, _ in rows) != tuple(range(1, expected_frames + 1)):
            raise ValueError(
                f"outside-region PSNR for {name} checked {len(rows)} of {expected_frames} frames"
            )
        region_scores[name] = tuple(score for _, score in rows)

    failed = [
        (frame_index, name, score)
        for name, scores in region_scores.items()
        for frame_index, score in enumerate(scores)
        if score < _OUTSIDE_MIN_PSNR_DB
    ]
    minimum = min(score for scores in region_scores.values() for score in scores)
    sampled_ssim: list[dict[str, object]] = []
    try:
        entries = _timeline_segments(timeline_document)
    except ValueError:
        entries = ()
    if entries:
        selected = (
            entries[0],
            *(
                entry
                for entry in entries
                if not str(entry.get("id", "")).startswith("blink-")
            ),
        )
        sample_indices = tuple(
            (int(entry["startFrame"]) + int(entry["endFrame"]) - 1) // 2
            for entry in selected
        )
        decoded = _extract_raw_frames(master, sample_indices)
        with Image.open(background) as source:
            reference = source.convert("RGB")
        sampled_ssim = [
            {"frame": index, "ssim": _outside_sprite_ssim(reference, frame)}
            for index, frame in zip(sample_indices, decoded, strict=True)
        ]
    sampled_ssim_passed = not sampled_ssim or min(
        sample["ssim"] for sample in sampled_ssim
    ) >= _SSIM_THRESHOLD
    return {
        "passed": not failed and sampled_ssim_passed,
        "thresholdPsnrDb": _OUTSIDE_MIN_PSNR_DB,
        "minimumPsnrDb": "inf" if math.isinf(minimum) else minimum,
        "sampledSsimThreshold": _SSIM_THRESHOLD,
        "minimumSampledSsim": (
            min(sample["ssim"] for sample in sampled_ssim)
            if sampled_ssim
            else None
        ),
        "sampledSsim": sampled_ssim,
        "framesChecked": expected_frames,
        "regionFrameCounts": {
            name: len(scores) for name, scores in region_scores.items()
        },
        "firstFailedFrame": min((frame for frame, _, _ in failed), default=None),
        "failures": [
            {"frame": frame, "region": name, "psnrDb": score}
            for frame, name, score in failed[:20]
        ],
    }


def _representative_sprites(segment: ShowcaseSegment) -> tuple[Image.Image, ...]:
    timed = _concatenate_actions(segment.source)
    output_indices = (0, (segment.output_frames - 1) // 2, segment.output_frames - 1)
    if segment.source.kind == "blink":
        blink = make_blink(timed)
        return tuple(blink.frames[index] for index in output_indices)
    _validate_timed_frames(timed)
    cumulative: list[int] = []
    total = 0
    for duration in timed.durations_ms:
        total += duration
        cumulative.append(total)
    source_indices: list[int] = []
    for output_index in output_indices:
        if output_index == 0:
            source_indices.append(0)
        elif output_index == segment.output_frames - 1:
            source_indices.append(len(timed.frames) - 1)
        else:
            timestamp = Fraction(
                (2 * output_index + 1) * timed.duration_ms,
                2 * segment.output_frames,
            )
            source_indices.append(
                next(index for index, end in enumerate(cumulative) if end > timestamp)
            )
    return tuple(timed.frames[index] for index in source_indices)


def _read_raw_frame(stream: BinaryIO, frame_bytes: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = frame_bytes
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if not chunks:
                return None
            raise ValueError("decoded center stream ended inside a frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _iter_decoded_center_frames(master: Path) -> Iterator[Image.Image]:
    """Stream only the encoded 192x208 center crop from the final master."""

    command = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(master),
        "-map",
        "0:v:0",
        "-vf",
        f"crop={SPRITE_SIZE[0]}:{SPRITE_SIZE[1]}:{SPRITE_ORIGIN[0]}:{SPRITE_ORIGIN[1]}",
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "-",
    ]
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as error:
        raise RuntimeError(f"could not start ffmpeg: {error}") from error
    assert process.stdout is not None
    completed = False
    try:
        frame_bytes = SPRITE_SIZE[0] * SPRITE_SIZE[1] * 3
        while True:
            encoded = _read_raw_frame(process.stdout, frame_bytes)
            if encoded is None:
                break
            yield Image.frombytes("RGB", SPRITE_SIZE, encoded)
        stderr = process.stderr.read() if process.stderr is not None else b""
        returncode = process.wait()
        completed = True
        if returncode:
            message = stderr.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"ffmpeg failed with exit code {returncode}:\n{message}"
            )
    finally:
        if not completed and process.poll() is None:
            process.kill()
            process.wait()


def _center_frame_psnr(expected: Image.Image, actual: Image.Image) -> float:
    if (
        expected.size != SPRITE_SIZE
        or actual.size != SPRITE_SIZE
        or expected.mode != "RGB"
        or actual.mode != "RGB"
    ):
        raise ValueError("center comparison frames must be native RGB sprite crops")
    difference = ImageChops.difference(expected, actual)
    rms = ImageStat.Stat(difference).rms
    mean_squared_error = sum(value * value for value in rms) / len(rms)
    if mean_squared_error == 0:
        return float("inf")
    return 10 * math.log10((255 * 255) / mean_squared_error)


def _changed_pixel_mask(first: Image.Image, second: Image.Image) -> Image.Image:
    difference = ImageChops.difference(first, second)
    red, green, blue = difference.split()
    maximum = ImageChops.lighter(red, ImageChops.lighter(green, blue))
    return maximum.point(lambda value: 255 if value else 0)


def _masked_rgb_mse(
    expected: Image.Image, actual: Image.Image, mask: Image.Image
) -> float:
    if mask.getbbox() is None:
        return 0.0
    rms = ImageStat.Stat(ImageChops.difference(expected, actual), mask).rms
    return sum(value * value for value in rms) / len(rms)


def _frame_rms_difference(first: Image.Image, second: Image.Image) -> float:
    rms = ImageStat.Stat(ImageChops.difference(first, second)).rms
    return math.sqrt(sum(value * value for value in rms) / len(rms))


def _compare_center_sequences(
    expected_source: Iterable[Image.Image],
    actual_source: Iterable[Image.Image],
    *,
    expected_frames: int,
) -> dict[str, object]:
    """Compare lossy centers while requiring every genuine temporal change."""

    missing = object()
    minimum_psnr = float("inf")
    failed_indices: list[int] = []
    content_mismatches: list[int] = []
    nearest_neighbor_mismatches: list[int] = []
    minimum_temporal_ratio = float("inf")
    compared = 0
    previous_expected: Image.Image | None = None
    previous_actual: Image.Image | None = None
    for index, (expected, actual) in enumerate(
        zip_longest(
            expected_source,
            actual_source,
            fillvalue=missing,
        )
    ):
        compared += 1
        if expected is missing or actual is missing:
            failed_indices.append(index)
            continue
        assert isinstance(expected, Image.Image)
        assert isinstance(actual, Image.Image)
        psnr = _center_frame_psnr(expected, actual)
        minimum_psnr = min(minimum_psnr, psnr)
        if psnr < _CENTER_MIN_PSNR_DB:
            failed_indices.append(index)
        if previous_expected is not None and previous_actual is not None:
            changed_mask = _changed_pixel_mask(expected, previous_expected)
            if changed_mask.getbbox() is not None:
                current_error = _masked_rgb_mse(expected, actual, changed_mask)
                prior_error = _masked_rgb_mse(previous_expected, actual, changed_mask)
                if current_error >= prior_error:
                    nearest_neighbor_mismatches.append(index)
                expected_change = _frame_rms_difference(expected, previous_expected)
                actual_change = _frame_rms_difference(actual, previous_actual)
                temporal_ratio = actual_change / expected_change
                minimum_temporal_ratio = min(
                    minimum_temporal_ratio, temporal_ratio
                )
                if temporal_ratio < _CENTER_MIN_TEMPORAL_RATIO:
                    content_mismatches.append(index)
                    if index not in failed_indices:
                        failed_indices.append(index)
        previous_expected = expected
        previous_actual = actual
    failed_indices.sort()
    return {
        "passed": compared == expected_frames and not failed_indices,
        "method": (
            "per-frame RGB PSNR plus expected-to-decoded temporal-change ratio "
            "over every 192x208 center crop"
        ),
        "thresholdPsnrDb": _CENTER_MIN_PSNR_DB,
        "minimumTemporalChangeRatio": _CENTER_MIN_TEMPORAL_RATIO,
        "framesCompared": compared,
        "minimumPsnrDb": (
            "inf" if math.isinf(minimum_psnr) else minimum_psnr
        ),
        "failedFrameCount": len(failed_indices),
        "firstFailedFrame": failed_indices[0] if failed_indices else None,
        "failedFrames": failed_indices[:20],
        "contentMismatchFrameCount": len(content_mismatches),
        "contentMismatchFrames": content_mismatches[:20],
        "observedMinimumTemporalRatio": (
            "inf"
            if math.isinf(minimum_temporal_ratio)
            else minimum_temporal_ratio
        ),
        "nearestNeighborMismatchFrameCount": len(nearest_neighbor_mismatches),
        "nearestNeighborMismatchFrames": nearest_neighbor_mismatches[:20],
    }


def _encoded_center_sequence(
    master: Path, plan: ShowcasePlan, background: Path
) -> dict[str, object]:
    """Compare every encoded center frame with its exact planned counterpart."""

    return _compare_center_sequences(
        _iter_expected_center_frames(plan, background),
        _iter_decoded_center_frames(master),
        expected_frames=_EXPECTED_TOTAL_FRAMES,
    )


def _centered_composition(plan: ShowcasePlan, background: Path) -> dict[str, object]:
    with Image.open(background) as source:
        backdrop = source.convert("RGB")
    bounds: list[dict[str, object]] = []
    passed = True
    for segment in plan.segments:
        for position, sprite in zip(
            ("first", "middle", "last"), _representative_sprites(segment), strict=True
        ):
            composed = compose_frame(backdrop, sprite)
            changed = ImageChops.difference(backdrop, composed).getbbox()
            inside = changed is not None and (
                SPRITE_ORIGIN[0] <= changed[0] < changed[2] <= SPRITE_ORIGIN[0] + SPRITE_SIZE[0]
                and SPRITE_ORIGIN[1] <= changed[1] < changed[3] <= SPRITE_ORIGIN[1] + SPRITE_SIZE[1]
            )
            passed = passed and inside
            bounds.append(
                {
                    "segmentId": segment.id,
                    "position": position,
                    "changedBounds": list(changed) if changed is not None else None,
                    "passed": inside,
                }
            )
    return {"passed": passed and len(bounds) == 45, "sampledFrames": len(bounds), "samples": bounds}


def _moon_frame_parity(plan: ShowcasePlan) -> dict[str, object]:
    moon_segments = tuple(segment for segment in plan.segments if segment.id in _MOON_SEGMENT_IDS)
    timed = tuple(_concatenate_actions(segment.source) for segment in moon_segments)
    passed = (
        tuple(segment.id for segment in moon_segments) == ("moon-184", "moon-232", "moon-full")
        and all(segment.output_frames == _MOON_OUTPUT_FRAMES for segment in moon_segments)
        and all((len(item.frames), item.duration_ms) == (44, _MOON_DURATION_MS) for item in timed)
        and len({item.durations_ms for item in timed}) == 1
    )
    return {
        "passed": passed,
        "segmentIds": [segment.id for segment in moon_segments],
        "outputFrames": [segment.output_frames for segment in moon_segments],
        "sourceFrameCounts": [len(item.frames) for item in timed],
        "sourceDurationsMs": [item.duration_ms for item in timed],
    }


def _source_privacy(plan: ShowcasePlan) -> dict[str, object]:
    sources = [plan.background_source, *plan.sequence_sources]
    sources.extend(
        path
        for segment in plan.segments
        for action in segment.source.actions
        for path in (action.atlas, action.manifest)
    )
    sources.extend(asset.path for asset in plan.source_inventory)
    resolved: list[str] = []
    passed = True
    for source in sources:
        try:
            path = source.resolve(strict=True)
        except OSError:
            passed = False
            path = source.resolve(strict=False)
        encoded = str(path)
        resolved.append(encoded)
        passed = (
            passed
            and path.is_file()
            and not any(
                marker in encoded.lower() for marker in _FORBIDDEN_SOURCE_MARKERS
            )
        )
    return {"passed": passed, "resolvedSources": resolved}


def _source_integrity(plan: ShowcasePlan) -> dict[str, object]:
    required = {
        path.resolve()
        for path in (
            plan.background_source,
            *plan.sequence_sources,
            *(
                path
                for segment in plan.segments
                for action in segment.source.actions
                for path in (action.atlas, action.manifest)
            ),
        )
    }
    declared = {asset.path.resolve() for asset in plan.source_inventory}
    mismatches: list[dict[str, object]] = []
    actual_inventory: list[dict[str, object]] = []
    for asset in plan.source_inventory:
        try:
            actual = sha256(asset.path.read_bytes()).hexdigest()
        except OSError as error:
            actual = None
            mismatches.append(
                {
                    "path": str(asset.path.resolve(strict=False)),
                    "role": asset.role,
                    "expectedSha256": asset.sha256,
                    "actualSha256": None,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
        else:
            if actual != asset.sha256:
                mismatches.append(
                    {
                        "path": str(asset.path.resolve()),
                        "role": asset.role,
                        "expectedSha256": asset.sha256,
                        "actualSha256": actual,
                    }
                )
        actual_inventory.append(
            {
                "id": asset.id,
                "path": str(asset.path.resolve(strict=False)),
                "role": asset.role,
                "sha256": actual,
            }
        )
    complete = bool(plan.source_inventory) and declared == required
    return {
        "passed": complete and not mismatches,
        "inventoryComplete": complete,
        "assetCount": len(plan.source_inventory),
        "inventory": actual_inventory,
        "mismatches": mismatches,
        "missingDeclarations": [
            str(path) for path in sorted(required - declared, key=str)
        ],
        "extraDeclarations": [
            str(path) for path in sorted(declared - required, key=str)
        ],
    }


def _checked_detail(
    details: dict[str, object], key: str, function: Callable[[], dict[str, object]]
) -> bool:
    try:
        result = function()
    except Exception as error:
        details[key] = {"passed": False, "error": f"{type(error).__name__}: {error}"}
        return False
    details[key] = result
    return result.get("passed") is True


def validate_showcase(master: Path, plan: ShowcasePlan, timeline: Path) -> dict[str, object]:
    """Return a fail-closed report for every final V2 publication gate."""

    checks = {
        "backgroundHash": False,
        "segmentOrder": False,
        "segmentFrameCounts": False,
        "totalFrames": False,
        "videoGeometry": False,
        "videoEncoding": False,
        "silentAudio": False,
        "noTextSidecarsOrStreams": False,
        "sourcePrivacy": False,
        "sourceIntegrity": False,
        "centeredComposition": False,
        "moonFrameParity": False,
    }
    details: dict[str, object] = {}
    checks["sourcePrivacy"] = _checked_detail(
        details, "sourcePrivacy", lambda: _source_privacy(plan)
    )
    sources_are_private = not checks["sourcePrivacy"]
    if sources_are_private:
        details["sourceIntegrity"] = {
            "passed": False,
            "skipped": "source privacy failed before source hashing",
            "mismatches": [],
        }
    else:
        checks["sourceIntegrity"] = _checked_detail(
            details, "sourceIntegrity", lambda: _source_integrity(plan)
        )
    sources_are_untrusted = sources_are_private or not checks["sourceIntegrity"]
    try:
        timeline_document = json.loads(timeline.read_text(encoding="utf-8"))
        if not isinstance(timeline_document, dict):
            raise ValueError("timeline root must be an object")
        entries = _timeline_segments(timeline_document)
    except Exception as error:
        timeline_document = {}
        entries = ()
        details["timeline"] = {"passed": False, "error": f"{type(error).__name__}: {error}"}

    expected_timeline_inventory = [
        {
            "id": asset.id,
            "role": asset.role,
            "sha256": asset.sha256,
        }
        for asset in plan.source_inventory
    ]
    timeline_inventory_matches = (
        timeline_document.get("sourceSha256") == expected_timeline_inventory
    )
    if isinstance(details.get("sourceIntegrity"), dict):
        details["sourceIntegrity"][
            "timelineInventoryMatches"
        ] = timeline_inventory_matches
        details["sourceIntegrity"]["passed"] = (
            details["sourceIntegrity"].get("passed") is True
            and timeline_inventory_matches
        )
    checks["sourceIntegrity"] = (
        checks["sourceIntegrity"] and timeline_inventory_matches
    )
    sources_are_untrusted = sources_are_private or not checks["sourceIntegrity"]

    def background_detail() -> dict[str, object]:
        encoded_hash, _ = _verified_background_pixels(plan.background_source)
        fidelity = _encoded_background_fidelity(master, plan.background_source, timeline_document)
        passed = (
            encoded_hash == BACKGROUND_SHA256
            and timeline_document.get("backgroundSha256") == BACKGROUND_SHA256
            and fidelity.get("passed") is True
        )
        return {"passed": passed, "sha256": encoded_hash, "encodedFidelity": fidelity}

    if sources_are_untrusted:
        details["backgroundHash"] = {
            "passed": False,
            "skipped": "source privacy or integrity failed before background reads",
        }
    else:
        checks["backgroundHash"] = _checked_detail(
            details, "backgroundHash", background_detail
        )
    plan_ids = tuple(segment.id for segment in plan.segments)
    timeline_ids = tuple(entry.get("id") for entry in entries)
    checks["segmentOrder"] = plan_ids == _EXPECTED_SEGMENT_IDS and timeline_ids == _EXPECTED_SEGMENT_IDS
    details["segmentOrder"] = {
        "passed": checks["segmentOrder"],
        "plan": list(plan_ids),
        "timeline": list(timeline_ids),
    }
    plan_counts = tuple(segment.output_frames for segment in plan.segments)
    timeline_counts = tuple(entry.get("outputFrames") for entry in entries)
    checks["segmentFrameCounts"] = (
        plan_counts == _EXPECTED_OUTPUT_FRAMES and timeline_counts == _EXPECTED_OUTPUT_FRAMES
    )
    details["segmentFrameCounts"] = {
        "passed": checks["segmentFrameCounts"],
        "plan": list(plan_counts),
        "timeline": list(timeline_counts),
    }

    probe: MediaProbe | None = None
    try:
        probe = probe_media(master, count_frames=True)
    except Exception as error:
        details["mediaProbe"] = {"passed": False, "error": f"{type(error).__name__}: {error}"}
    continuous = bool(entries) and len(entries) == 15
    expected_start = 0
    for entry in entries:
        start = entry.get("startFrame")
        end = entry.get("endFrame")
        count = entry.get("outputFrames")
        if not all(isinstance(value, int) for value in (start, end, count)):
            continuous = False
            break
        continuous = continuous and start == expected_start and end == start + count
        expected_start = end
    checks["totalFrames"] = (
        continuous
        and expected_start == _EXPECTED_TOTAL_FRAMES
        and timeline_document.get("totalFrames") == _EXPECTED_TOTAL_FRAMES
        and plan.total_frames == _EXPECTED_TOTAL_FRAMES
        and probe is not None
        and probe.video.nb_read_frames == _EXPECTED_TOTAL_FRAMES
    )
    details["totalFrames"] = {"passed": checks["totalFrames"], "timelineEnd": expected_start}
    if probe is not None:
        video = probe.video
        try:
            timestamps = _probe_video_timestamps(master, _EXPECTED_TOTAL_FRAMES)
        except Exception as error:
            timestamps = {
                "passed": False,
                "error": f"{type(error).__name__}: {error}",
            }
        expected_video_duration = Fraction(_EXPECTED_TOTAL_FRAMES, FPS)
        checks["videoGeometry"] = (
            (video.width, video.height) == FRAME_SIZE
            and video.sample_aspect_ratio == "1:1"
            and video.frame_rate == FPS
            and video.average_frame_rate == FPS
        )
        fast_start = _read_mp4_atom_order(master)
        checks["videoEncoding"] = (
            video.codec == "h264"
            and video.profile == "High"
            and video.pixel_format == "yuv420p"
            and video.time_base == _EXPECTED_VIDEO_TIME_BASE
            and video.duration == expected_video_duration
            and timestamps.get("passed") is True
            and fast_start
        )
        details["video"] = {
            "passed": checks["videoGeometry"] and checks["videoEncoding"],
            "width": video.width,
            "height": video.height,
            "codec": video.codec,
            "profile": video.profile,
            "pixelFormat": video.pixel_format,
            "sampleAspectRatio": video.sample_aspect_ratio,
            "frameRate": str(video.frame_rate),
            "averageFrameRate": str(video.average_frame_rate),
            "timeBase": str(video.time_base),
            "duration": str(video.duration),
            "expectedDuration": str(expected_video_duration),
            "frames": video.nb_read_frames,
            "moovBeforeMdat": fast_start,
            "timestamps": timestamps,
        }
        try:
            silence = _measure_audio_silence(master)
        except Exception as error:
            silence = {"passed": False, "error": f"{type(error).__name__}: {error}"}
        audio = probe.audio
        expected_audio_duration = Fraction(_EXPECTED_TOTAL_FRAMES, FPS)
        audio_duration_tolerance = Fraction(1024, 48_000)
        duration_aligned = (
            audio is not None
            and abs(audio.duration - expected_audio_duration) <= audio_duration_tolerance
        )
        checks["silentAudio"] = (
            audio is not None
            and audio.codec == "aac"
            and audio.sample_rate == 48_000
            and audio.channels == 2
            and duration_aligned
            and silence.get("passed") is True
        )
        details["audio"] = {
            "passed": checks["silentAudio"],
            "codec": audio.codec if audio else None,
            "sampleRate": audio.sample_rate if audio else None,
            "channels": audio.channels if audio else None,
            "duration": str(audio.duration) if audio else None,
            "expectedDuration": str(expected_audio_duration),
            "durationTolerance": str(audio_duration_tolerance),
            "durationAligned": duration_aligned,
            "silence": silence,
        }
        try:
            sidecars = tuple(
                path
                for path in master.parent.rglob("*")
                if path.is_file() and path.suffix.lower() in {".ass", ".srt", ".vtt"}
            )
        except OSError as error:
            sidecars = (master.parent / f"scan-error-{error}",)
        checks["noTextSidecarsOrStreams"] = (
            probe.subtitle_streams == 0
            and probe.data_streams == 0
            and probe.other_streams == 0
            and not sidecars
        )
        details["textStreamsAndSidecars"] = {
            "passed": checks["noTextSidecarsOrStreams"],
            "subtitleStreams": probe.subtitle_streams,
            "dataStreams": probe.data_streams,
            "otherStreams": probe.other_streams,
            "sidecars": [str(path) for path in sidecars],
        }
    if sources_are_untrusted:
        details["centeredComposition"] = {
            "passed": False,
            "skipped": "source privacy or integrity failed before source-derived reads",
        }
        details["moonFrameParity"] = {
            "passed": False,
            "skipped": "source privacy or integrity failed before source-derived reads",
        }
    else:
        def composition_detail() -> dict[str, object]:
            pre_encode = _centered_composition(plan, plan.background_source)
            encoded = _encoded_center_sequence(
                master, plan, plan.background_source
            )
            return {
                "passed": (
                    pre_encode.get("passed") is True
                    and encoded.get("passed") is True
                ),
                "preEncode": pre_encode,
                "encodedSequence": encoded,
            }

        checks["centeredComposition"] = _checked_detail(
            details, "centeredComposition", composition_detail
        )
        checks["moonFrameParity"] = _checked_detail(
            details, "moonFrameParity", lambda: _moon_frame_parity(plan)
        )

    artifact_hashes: dict[str, str] = {}
    artifacts = [("master", master), ("timeline", timeline)]
    if not sources_are_untrusted:
        artifacts.append(("background", plan.background_source))
    for name, path in artifacts:
        try:
            artifact_hashes[name] = sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    return {
        "schemaVersion": 1,
        "master": str(master.resolve(strict=False)),
        "timeline": str(timeline.resolve(strict=False)),
        "checks": checks,
        "allPassed": all(checks.values()),
        "details": details,
        "artifactSha256": artifact_hashes,
    }


def _extract_selected_frames(
    master: Path, frame_indices: tuple[int, ...], destinations: tuple[Path, ...]
) -> None:
    if len(frame_indices) != len(destinations) or not frame_indices:
        raise ValueError("review frame indices and destinations must match")
    output = destinations[0].parent
    temporary_pattern = output / ".review-%03d.png"
    expression = "+".join(f"eq(n\\,{index})" for index in frame_indices)
    try:
        _run_capture(
            [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(master),
                "-map",
                "0:v:0",
                "-vf",
                f"select={expression}",
                "-fps_mode",
                "vfr",
                "-frames:v",
                str(len(frame_indices)),
                str(temporary_pattern),
            ],
            tool="ffmpeg",
        )
        temporary = tuple(output / f".review-{index:03d}.png" for index in range(1, len(destinations) + 1))
        if not all(path.is_file() for path in temporary):
            raise ValueError("ffmpeg did not extract every requested review frame")
        for source, destination in zip(temporary, destinations, strict=True):
            source.replace(destination)
    finally:
        for path in output.glob(".review-*.png"):
            path.unlink(missing_ok=True)


def extract_review_frames(master: Path, timeline: Path, output: Path) -> tuple[Path, ...]:
    """Extract original-size first/middle/last frames and a 15-by-3 sheet."""

    document = json.loads(timeline.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("timeline root must be an object")
    entries = _timeline_segments(document)
    if tuple(entry.get("id") for entry in entries) != _EXPECTED_SEGMENT_IDS:
        raise ValueError("review extraction requires the approved segment order")
    output.mkdir(parents=True, exist_ok=True)
    for obsolete in (*output.glob("*.png"), *output.glob("contact-sheet*.jpg")):
        obsolete.unlink()
    positions = ("first", "middle", "last")
    frame_indices = tuple(
        {
            "first": int(entry["startFrame"]),
            "middle": (int(entry["startFrame"]) + int(entry["endFrame"]) - 1) // 2,
            "last": int(entry["endFrame"]) - 1,
        }[position]
        for position in positions
        for entry in entries
    )
    destinations = tuple(
        output / f"{index:02d}-{entry['id']}-{position}.png"
        for position in positions
        for index, entry in enumerate(entries, start=1)
    )
    chronological = tuple(sorted(zip(frame_indices, destinations, strict=True)))
    _extract_selected_frames(
        master,
        tuple(frame_index for frame_index, _ in chronological),
        tuple(destination for _, destination in chronological),
    )
    sheet = Image.new("RGB", (15 * 320, 3 * 180), "black")
    for position_index in range(3):
        for segment_index in range(15):
            frame = destinations[position_index * 15 + segment_index]
            with Image.open(frame) as source:
                if source.size != FRAME_SIZE:
                    raise ValueError(f"review frame has wrong geometry: {frame}")
                tile = source.convert("RGB").resize((320, 180), Image.Resampling.LANCZOS)
            sheet.paste(tile, (segment_index * 320, position_index * 180))
    sheet.save(output / "contact-sheet.jpg", quality=94, subsampling=0)
    return destinations
