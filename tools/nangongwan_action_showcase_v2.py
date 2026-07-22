"""Immutable source contracts for the simple Nangong Wan action showcase."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from typing import Callable, Literal

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
    entries = _timeline_segments(timeline_document)
    selected = (entries[0], *(entry for entry in entries if not str(entry.get("id", "")).startswith("blink-")))
    frame_indices = tuple(
        (int(entry["startFrame"]) + int(entry["endFrame"]) - 1) // 2
        for entry in selected
    )
    decoded = _extract_raw_frames(master, frame_indices)
    with Image.open(background) as source:
        reference = source.convert("RGB")
    scores = tuple(
        _outside_sprite_ssim(reference, frame) for frame in decoded
    )
    return {
        "passed": bool(scores) and min(scores) >= _SSIM_THRESHOLD,
        "threshold": _SSIM_THRESHOLD,
        "minimumSsim": min(scores) if scores else None,
        "samples": [
            {"segmentId": entry["id"], "frame": index, "ssim": score}
            for entry, index, score in zip(selected, frame_indices, scores, strict=True)
        ],
    }


def _representative_sprites(segment: ShowcaseSegment) -> tuple[Image.Image, ...]:
    timed = _concatenate_actions(segment.source.actions)
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
    timed = tuple(_concatenate_actions(segment.source.actions) for segment in moon_segments)
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
    sources = [plan.background_source]
    sources.extend(
        path
        for segment in plan.segments
        for action in segment.source.actions
        for path in (action.atlas, action.manifest)
    )
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
        passed = passed and not any(marker in encoded.lower() for marker in _FORBIDDEN_SOURCE_MARKERS)
    return {"passed": passed, "resolvedSources": resolved}


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
        "centeredComposition": False,
        "moonFrameParity": False,
    }
    details: dict[str, object] = {}
    try:
        timeline_document = json.loads(timeline.read_text(encoding="utf-8"))
        if not isinstance(timeline_document, dict):
            raise ValueError("timeline root must be an object")
        entries = _timeline_segments(timeline_document)
    except Exception as error:
        timeline_document = {}
        entries = ()
        details["timeline"] = {"passed": False, "error": f"{type(error).__name__}: {error}"}

    def background_detail() -> dict[str, object]:
        encoded_hash, _ = _verified_background_pixels(plan.background_source)
        fidelity = _encoded_background_fidelity(master, plan.background_source, timeline_document)
        passed = (
            encoded_hash == BACKGROUND_SHA256
            and timeline_document.get("backgroundSha256") == BACKGROUND_SHA256
            and fidelity.get("passed") is True
        )
        return {"passed": passed, "sha256": encoded_hash, "encodedFidelity": fidelity}

    checks["backgroundHash"] = _checked_detail(details, "backgroundHash", background_detail)
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
        checks["videoGeometry"] = (
            (video.width, video.height) == FRAME_SIZE
            and video.sample_aspect_ratio == "1:1"
            and video.frame_rate == FPS
        )
        fast_start = _read_mp4_atom_order(master)
        checks["videoEncoding"] = (
            video.codec == "h264"
            and video.profile == "High"
            and video.pixel_format == "yuv420p"
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
            "frames": video.nb_read_frames,
            "moovBeforeMdat": fast_start,
        }
        try:
            silence = _measure_audio_silence(master)
        except Exception as error:
            silence = {"passed": False, "error": f"{type(error).__name__}: {error}"}
        audio = probe.audio
        checks["silentAudio"] = (
            audio is not None
            and audio.codec == "aac"
            and audio.sample_rate == 48_000
            and audio.channels == 2
            and silence.get("passed") is True
        )
        details["audio"] = {
            "passed": checks["silentAudio"],
            "codec": audio.codec if audio else None,
            "sampleRate": audio.sample_rate if audio else None,
            "channels": audio.channels if audio else None,
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
            probe.subtitle_streams == 0 and probe.data_streams == 0 and not sidecars
        )
        details["textStreamsAndSidecars"] = {
            "passed": checks["noTextSidecarsOrStreams"],
            "subtitleStreams": probe.subtitle_streams,
            "dataStreams": probe.data_streams,
            "sidecars": [str(path) for path in sidecars],
        }
    checks["sourcePrivacy"] = _checked_detail(details, "sourcePrivacy", lambda: _source_privacy(plan))
    checks["centeredComposition"] = _checked_detail(
        details, "centeredComposition", lambda: _centered_composition(plan, plan.background_source)
    )
    checks["moonFrameParity"] = _checked_detail(details, "moonFrameParity", lambda: _moon_frame_parity(plan))

    artifact_hashes: dict[str, str] = {}
    for name, path in (("master", master), ("timeline", timeline), ("background", plan.background_source)):
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
