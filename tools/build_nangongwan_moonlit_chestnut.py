"""Build the Nangong Wan moonlit chestnut animation atlas rows.

The tracked source is an eight-panel transparent storyboard.  This script keeps
the expensive visual choices in that source asset and deterministically builds
the 36 runtime frames, the extended WebP atlas, and a local checkerboard audit.
"""

from __future__ import annotations

import math
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageDraw


CELL_SIZE = (192, 208)
ATLAS_WIDTH = 3072
SOURCE_ATLAS_HEIGHT = 4784
ATLAS_HEIGHT = 5408
ATLAS_COLUMNS = 16
START_CELL = 23 * ATLAS_COLUMNS
FRAME_COUNT = 36

ROOT = Path(__file__).resolve().parents[1]
STORYBOARD_PATH = (
    ROOT / "tools" / "assets" / "nangongwan-moonlit-chestnut-keyframes.png"
)
ATLAS_PATH = (
    ROOT
    / "src"
    / "shiyi_desktop_pet"
    / "resources"
    / "pets"
    / "nangongwan"
    / "spritesheet.webp"
)
WORK_DIR = ROOT / "work" / "moonlit-chestnut"


def extract_keyframes(storyboard: Image.Image) -> tuple[Image.Image, ...]:
    """Extract the regular 4x2 grid while discarding generated white gutters."""

    source = storyboard.convert("RGBA")
    width, height = source.size
    if width < 40 or height < 20:
        raise ValueError("storyboard is too small for a 4x2 grid")

    frames: list[Image.Image] = []
    gutter = max(1, round(min(width / 4, height / 2) * 0.012))
    for index in range(8):
        row, column = divmod(index, 4)
        left = round(width * column / 4) + (gutter if column else 0)
        right = round(width * (column + 1) / 4) - (gutter if column < 3 else 0)
        top = round(height * row / 2) + (gutter if row else 0)
        bottom = round(height * (row + 1) / 2) - (gutter if row < 1 else 0)
        panel = source.crop((left, top, right, bottom))
        if panel.getbbox() is None:
            raise ValueError(f"storyboard panel {index + 1} is empty")
        frames.append(panel)
    return tuple(frames)


def _normalized(panel: Image.Image) -> Image.Image:
    return panel.resize(CELL_SIZE, Image.Resampling.LANCZOS).convert("RGBA")


def _motion(
    image: Image.Image,
    index: int,
    opacity: float = 1.0,
    camera_scale: float = 1.0,
) -> Image.Image:
    """Apply restrained sub-pixel camera/breathing motion to avoid frozen holds."""

    scale = camera_scale * (1.0 + 0.0045 * math.sin((index + 1) * 0.83))
    dx = 0.75 * math.sin((index + 1) * 1.17)
    dy = 0.55 * math.cos((index + 1) * 0.71)
    inverse = 1.0 / scale
    center_x = CELL_SIZE[0] / 2
    center_y = CELL_SIZE[1] / 2
    moved = image.transform(
        CELL_SIZE,
        Image.Transform.AFFINE,
        (
            inverse,
            0.0,
            center_x - (center_x + dx) * inverse,
            0.0,
            inverse,
            center_y - (center_y + dy) * inverse,
        ),
        resample=Image.Resampling.BICUBIC,
    )
    if opacity < 1.0:
        alpha = moved.getchannel("A").point(
            lambda value: round(value * max(0.0, min(1.0, opacity)))
        )
        moved.putalpha(alpha)
    return moved


def build_frames(keyframes: tuple[Image.Image, ...]) -> tuple[Image.Image, ...]:
    """Create the approved 36-frame far/near/far sequence."""

    if len(keyframes) != 8:
        raise ValueError("exactly eight keyframes are required")

    # The official sequence uses a camera push followed by clean cuts to hand
    # and lips close-ups.  A dissolve would produce double faces and is not
    # faithful to the animation, so every runtime frame uses one keyframe.
    timeline: list[tuple[int, float, float]] = []
    timeline.extend((0, scale, opacity) for scale, opacity in (
        (0.94, 0.38), (0.96, 0.58), (0.98, 0.78), (1.0, 1.0)
    ))
    timeline.extend((1, scale, 1.0) for scale in (0.92, 0.96, 1.0, 1.04))
    timeline.extend((1, scale, 1.0) for scale in (1.1, 1.18, 1.28, 1.4, 1.55))
    timeline.append((2, 1.0, 1.0))
    timeline.extend((2, scale, 1.0) for scale in (1.02, 1.05, 1.08))
    timeline.append((3, 1.0, 1.0))
    timeline.extend((3, scale, 1.0) for scale in (1.02, 1.04))
    timeline.extend((4, scale, 1.0) for scale in (0.98, 1.0, 1.02))
    timeline.extend((4, scale, 1.0) for scale in (1.04, 1.08))
    timeline.extend((5, scale, 1.0) for scale in (0.96, 1.0, 1.04))
    timeline.append((5, 1.08, 1.0))
    timeline.extend((6, scale, 1.0) for scale in (0.98, 1.0))
    timeline.extend((7, scale, 1.0) for scale in (1.0, 1.02, 0.96, 0.9))
    timeline.append((1, 0.94, 0.56))
    if len(timeline) != FRAME_COUNT:
        raise AssertionError("internal timeline must contain exactly 36 frames")

    frames = tuple(
        _motion(_normalized(keyframes[keyframe]), index, opacity, camera_scale)
        for index, (keyframe, camera_scale, opacity) in enumerate(timeline)
    )
    hashes = [sha256(frame.tobytes()).digest() for frame in frames]
    if len(set(hashes)) != FRAME_COUNT:
        raise ValueError("generated animation contains duplicate frames")
    return frames


def extend_atlas(source: Image.Image, frames: tuple[Image.Image, ...]) -> Image.Image:
    """Append frames from row 23 and leave the last twelve cells transparent."""

    if source.width != ATLAS_WIDTH or source.height not in {
        SOURCE_ATLAS_HEIGHT,
        ATLAS_HEIGHT,
    }:
        raise ValueError(
            "source atlas must be 3072x4784 or an already-expanded 3072x5408 atlas"
        )
    if len(frames) != FRAME_COUNT or any(frame.size != CELL_SIZE for frame in frames):
        raise ValueError("exactly 36 frames sized 192x208 are required")

    atlas = Image.new("RGBA", (ATLAS_WIDTH, ATLAS_HEIGHT), (0, 0, 0, 0))
    base = source.convert("RGBA").crop((0, 0, ATLAS_WIDTH, SOURCE_ATLAS_HEIGHT))
    atlas.alpha_composite(base, (0, 0))
    for offset, frame in enumerate(frames):
        row, column = divmod(START_CELL + offset, ATLAS_COLUMNS)
        atlas.alpha_composite(frame.convert("RGBA"), (column * 192, row * 208))
    return atlas


def _write_audit(frames: tuple[Image.Image, ...], path: Path) -> None:
    checker = Image.new("RGBA", CELL_SIZE, (226, 231, 238, 255))
    draw = ImageDraw.Draw(checker)
    tile = 16
    for y in range(0, CELL_SIZE[1], tile):
        for x in range(0, CELL_SIZE[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(188, 197, 209, 255))

    label_height = 20
    audit = Image.new(
        "RGB",
        (CELL_SIZE[0] * 6, (CELL_SIZE[1] + label_height) * 6),
        (244, 246, 249),
    )
    audit_draw = ImageDraw.Draw(audit)
    for index, frame in enumerate(frames):
        row, column = divmod(index, 6)
        panel = checker.copy()
        panel.alpha_composite(frame)
        x = column * CELL_SIZE[0]
        y = row * (CELL_SIZE[1] + label_height)
        audit.paste(panel.convert("RGB"), (x, y))
        audit_draw.text((x + 5, y + CELL_SIZE[1] + 3), f"frame {index + 1:02d}", fill=(20, 28, 38))
    path.parent.mkdir(parents=True, exist_ok=True)
    audit.save(path)


def main() -> None:
    if not STORYBOARD_PATH.is_file():
        raise FileNotFoundError(f"missing approved keyframes: {STORYBOARD_PATH}")
    if not ATLAS_PATH.is_file():
        raise FileNotFoundError(f"missing Nangong Wan atlas: {ATLAS_PATH}")

    keyframes = extract_keyframes(Image.open(STORYBOARD_PATH))
    frames = build_frames(keyframes)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    keyframe_dir = WORK_DIR / "keyframes"
    frame_dir = WORK_DIR / "frames"
    keyframe_dir.mkdir(parents=True, exist_ok=True)
    frame_dir.mkdir(parents=True, exist_ok=True)
    for index, keyframe in enumerate(keyframes, start=1):
        _normalized(keyframe).save(keyframe_dir / f"keyframe-{index:02d}.png")
    for index, frame in enumerate(frames, start=1):
        frame.save(frame_dir / f"frame-{index:02d}.png")

    with Image.open(ATLAS_PATH) as source:
        atlas = extend_atlas(source, frames)
    atlas.save(ATLAS_PATH, "WEBP", lossless=True, quality=100, method=6, exact=True)
    _write_audit(frames, WORK_DIR / "audit.png")
    print(f"wrote {FRAME_COUNT} frames to {ATLAS_PATH}")
    print(f"audit: {WORK_DIR / 'audit.png'}")


if __name__ == "__main__":
    main()
