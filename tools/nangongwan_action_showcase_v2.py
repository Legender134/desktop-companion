"""Immutable source contracts for the simple Nangong Wan action showcase."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image

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
