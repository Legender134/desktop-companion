"""Immutable source contracts for the simple Nangong Wan action showcase."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Literal

from PIL import Image

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


@dataclass(frozen=True)
class AudioProbe:
    codec: str
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class MediaProbe:
    video: VideoProbe
    audio: AudioProbe | None
    subtitle_streams: int
    data_streams: int


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
    video = VideoProbe(
        width=_required_int(video_stream, "width"),
        height=_required_int(video_stream, "height"),
        codec=_required_string(video_stream, "codec_name"),
        profile=_required_string(video_stream, "profile"),
        pixel_format=_required_string(video_stream, "pix_fmt"),
        sample_aspect_ratio=_required_string(video_stream, "sample_aspect_ratio"),
        frame_rate=_frame_rate(video_stream),
        nb_read_frames=frame_count,
    )
    audio = None
    if audios:
        audio_stream = audios[0]
        audio = AudioProbe(
            codec=_required_string(audio_stream, "codec_name"),
            sample_rate=_required_int(audio_stream, "sample_rate"),
            channels=_required_int(audio_stream, "channels"),
        )
    return MediaProbe(
        video=video,
        audio=audio,
        subtitle_streams=sum(stream.get("codec_type") == "subtitle" for stream in streams),
        data_streams=sum(stream.get("codec_type") == "data" for stream in streams),
    )


def write_silent_video(frames: SegmentFrames, output: Path) -> None:
    """Stream exact RGB frames into a normalized silent H.264 clip."""

    if not frames.frames:
        raise ValueError("a video segment needs at least one frame")
    if any(frame.size != FRAME_SIZE or frame.mode != "RGB" for frame in frames.frames):
        raise ValueError(f"video frames must be RGB images sized {FRAME_SIZE}")
    output.parent.mkdir(parents=True, exist_ok=True)
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
        str(len(frames.frames)),
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
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as error:
        raise RuntimeError(f"could not start ffmpeg: {error}") from error
    assert process.stdin is not None
    try:
        for frame in frames.frames:
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr is not None else b""
        returncode = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        output.unlink(missing_ok=True)
        raise
    if returncode:
        output.unlink(missing_ok=True)
        message = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg failed with exit code {returncode}:\n{message}")


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


def _resample_at_positions(
    timed: TimedFrames, positions: tuple[Fraction, ...]
) -> SegmentFrames:
    _validate_timed_frames(timed)
    cumulative_durations: list[int] = []
    cumulative = 0
    for duration in timed.durations_ms:
        cumulative += duration
        cumulative_durations.append(cumulative)

    source_indices = [
        next(
            source_index
            for source_index, source_end in enumerate(cumulative_durations)
            if source_end > timestamp
        )
        for timestamp in positions
    ]
    source_indices[0] = 0
    if len(source_indices) > 1:
        source_indices[-1] = len(timed.frames) - 1
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


def _concatenate_actions(actions: tuple[ActionSource, ...]) -> TimedFrames:
    if not actions:
        raise ValueError("showcase source needs at least one action")
    timed_actions = tuple(read_action(action) for action in actions)
    for timed in timed_actions:
        _validate_timed_frames(timed)
    return TimedFrames(
        tuple(frame for timed in timed_actions for frame in timed.frames),
        tuple(duration for timed in timed_actions for duration in timed.durations_ms),
    )


def build_segment_frames(segment: ShowcaseSegment, background: Image.Image) -> SegmentFrames:
    """Read, time-resample, and fixed-center compose every frame in one segment."""

    timed = _concatenate_actions(segment.source.actions)
    if segment.source.kind == "blink":
        sprites = make_blink(timed)
    elif segment.source.kind in {"action", "sequence"}:
        if segment.id in _MOON_SEGMENT_IDS:
            if (timed.duration_ms, segment.output_frames) != (
                _MOON_DURATION_MS,
                _MOON_OUTPUT_FRAMES,
            ):
                raise ValueError("moon segments must use the approved shared time positions")
            sprites = _resample_at_positions(timed, _MOON_SAMPLE_POSITIONS)
        else:
            sprites = resample_action(timed, segment.output_frames)
    else:
        raise ValueError(f"unknown showcase source kind: {segment.source.kind}")

    if len(sprites.frames) != segment.output_frames:
        raise ValueError("segment frame count does not match its plan")
    return SegmentFrames(tuple(compose_frame(background, sprite) for sprite in sprites.frames))


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
