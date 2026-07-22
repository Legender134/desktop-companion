"""Immutable source contracts for the simple Nangong Wan action showcase."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
from pathlib import Path
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
