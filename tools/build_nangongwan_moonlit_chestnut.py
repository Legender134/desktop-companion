"""Build the anchored 48-frame Nangong Wan moonlit-chestnut action.

The source art is split into small, independently drawn motion phases.  This
builder crops those panels, locks them to the desktop baseline, adds the
partial moon/eave transition, and writes only atlas rows 23-25.  The archived
2.4.1 WebP is deliberately never opened by this module.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageDraw


CELL_SIZE = (192, 208)
ATLAS_WIDTH = 3072
SOURCE_ATLAS_HEIGHT = 4784
ATLAS_HEIGHT = 5408
ATLAS_COLUMNS = 16
START_CELL = 23 * ATLAS_COLUMNS
FRAME_COUNT = 48

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "tools" / "assets" / "nangongwan-moonlit-redesign"
SIT_PATH = ASSET_DIR / "phase-sit.png"
TASTE_PATH = ASSET_DIR / "phase-taste.png"
RECOVER_PATH = ASSET_DIR / "phase-recover.png"
STAND_PATH = ASSET_DIR / "phase-stand-v2.png"
MOON_PATH = ASSET_DIR / "moon-partial.png"
ROOF_PATH = ASSET_DIR / "roof-eave.png"
ARCHIVE_ROOT = (
    ROOT / "tools" / "archives" / "nangongwan-moonlit-chestnut-anchored-v1"
)
LIVE_PET_ROOT = (
    ROOT / "src" / "shiyi_desktop_pet" / "resources" / "pets" / "nangongwan"
)
ATLAS_PATH = ARCHIVE_ROOT / "spritesheet.webp"
MANIFEST_PATH = ARCHIVE_ROOT / "pet.json"
WORK_DIR = ROOT / "work" / "moonlit-chestnut-redesign"
OUTPUT_ATLAS_PATH = WORK_DIR / "rebuilt-anchored-48-spritesheet.webp"


def extract_grid(
    sheet: Image.Image, columns: int, rows: int, *, inset: int = 2
) -> tuple[Image.Image, ...]:
    """Extract a regular grid and discard generated one-pixel dividers."""

    if columns < 1 or rows < 1:
        raise ValueError("grid dimensions must be positive")
    source = sheet.convert("RGBA")
    if source.width < columns * 16 or source.height < rows * 16:
        raise ValueError("sprite sheet is too small for the requested grid")

    panels: list[Image.Image] = []
    for index in range(columns * rows):
        row, column = divmod(index, columns)
        left = round(source.width * column / columns) + inset
        right = round(source.width * (column + 1) / columns) - inset
        top = round(source.height * row / rows) + inset
        bottom = round(source.height * (row + 1) / rows) - inset
        panel = source.crop((left, top, right, bottom))
        if panel.getbbox() is None:
            raise ValueError(f"sprite sheet panel {index + 1} is empty")
        panels.append(panel)
    return tuple(panels)


def _opacity(image: Image.Image, amount: float) -> Image.Image:
    result = image.convert("RGBA").copy()
    clamped = max(0.0, min(1.0, amount))
    if clamped < 1.0:
        result.putalpha(result.getchannel("A").point(lambda value: round(value * clamped)))
    return result


def _placed_panel(
    panel: Image.Image,
    *,
    scale: float,
    source_foot_y: float,
    target_foot_y: int = 204,
) -> Image.Image:
    """Scale about the source-cell centre and lock a drawn foot baseline."""

    source = panel.convert("RGBA")
    size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    resized = source.resize(size, Image.Resampling.LANCZOS)
    x = round(CELL_SIZE[0] / 2 - source.width * scale / 2)
    y = round(target_foot_y - source_foot_y * scale)
    result = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    result.alpha_composite(resized, (x, y))
    return result


def _prepared_moon(source: Image.Image) -> Image.Image:
    moon = source.convert("RGBA")
    box = moon.getbbox()
    if box is None:
        raise ValueError("partial moon asset is empty")
    moon = moon.crop(box)
    moon.thumbnail((226, 224), Image.Resampling.LANCZOS)
    result = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    result.alpha_composite(moon, (-34, -18))
    return result


def _prepared_roof(source: Image.Image) -> Image.Image:
    roof = source.convert("RGBA")
    box = roof.getbbox()
    if box is None:
        raise ValueError("roof asset is empty")
    roof = roof.crop(box)
    roof.thumbnail((206, 88), Image.Resampling.LANCZOS)
    result = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    result.alpha_composite(roof, (-5, 132))
    return result


def _scene(
    character: Image.Image,
    moon: Image.Image,
    roof: Image.Image,
    *,
    moon_opacity: float,
    roof_opacity: float = 0.0,
) -> Image.Image:
    frame = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    if moon_opacity:
        frame.alpha_composite(_opacity(moon, moon_opacity))
    if roof_opacity:
        frame.alpha_composite(_opacity(roof, roof_opacity))
    frame.alpha_composite(character.convert("RGBA"))
    return frame


def _atlas_frame(
    atlas: Image.Image, manifest: dict, action_id: str, offset: int
) -> Image.Image:
    action = manifest["actions"][action_id]
    start = action["row"] * ATLAS_COLUMNS + action.get("startColumn", 0)
    row, column = divmod(start + offset, ATLAS_COLUMNS)
    return atlas.crop(
        (
            column * CELL_SIZE[0],
            row * CELL_SIZE[1],
            (column + 1) * CELL_SIZE[0],
            (row + 1) * CELL_SIZE[1],
        )
    ).convert("RGBA")


def build_frames(
    idle_frames: tuple[Image.Image, ...],
    sit_panels: tuple[Image.Image, ...],
    taste_panels: tuple[Image.Image, ...],
    recover_panels: tuple[Image.Image, ...],
    stand_panels: tuple[Image.Image, ...],
    moon_source: Image.Image,
    roof_source: Image.Image,
) -> tuple[Image.Image, ...]:
    """Assemble the approved eight phases into 48 direct runtime frames."""

    if len(idle_frames) < 3:
        raise ValueError("at least three idle frames are required")
    if (
        len(sit_panels) != 8
        or len(taste_panels) != 8
        or len(recover_panels) != 3
        or len(stand_panels) != 8
    ):
        raise ValueError("the sit/taste/recover/stand sheets must contain 8/8/3/8 panels")

    moon = _prepared_moon(moon_source)
    roof = _prepared_roof(roof_source)
    idle = tuple(frame.convert("RGBA") for frame in idle_frames[:3])

    sit_scales = (0.64, 0.63, 0.62, 0.61, 0.60, 0.59, 0.59, 0.59)
    sit_feet = (369, 377, 379, 383, 384, 392, 391, 395)
    sit = tuple(
        _placed_panel(panel, scale=scale, source_foot_y=foot)
        for panel, scale, foot in zip(sit_panels, sit_scales, sit_feet)
    )
    taste = tuple(
        _placed_panel(panel, scale=0.59, source_foot_y=390)
        for panel in taste_panels
    )
    recover = tuple(
        _placed_panel(panel, scale=0.37, source_foot_y=630)
        for panel in recover_panels
    )
    stand = tuple(
        _placed_panel(panel, scale=0.54, source_foot_y=395)
        for panel in stand_panels
    )

    frames: list[Image.Image] = []

    # 1-4: exact desktop-pet entrance; the first frame is byte-identical to idle.
    frames.extend((idle[0], idle[1], idle[2], idle[0]))

    # 5-10: moonlight and eave grow around the still-standing character.
    for character, moon_alpha, roof_alpha in zip(
        (idle[1], idle[2], idle[0], idle[1], idle[2], idle[0]),
        (0.06, 0.12, 0.20, 0.29, 0.39, 0.49),
        (0.05, 0.12, 0.22, 0.34, 0.47, 0.60),
    ):
        frames.append(
            _scene(
                character,
                moon,
                roof,
                moon_opacity=moon_alpha,
                roof_opacity=roof_alpha,
            )
        )

    # 11-20: eight independently drawn standing-to-sitting poses plus settling.
    sit_sequence = (0, 1, 2, 3, 4, 5, 6, 7, 7, 7)
    roof_crossfade = (0.68, 0.62, 0.54, 0.42, 0.28, 0.14, 0.04, 0.0, 0.0, 0.0)
    moon_levels = (0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.56, 0.58)
    for panel_index, roof_alpha, moon_alpha in zip(
        sit_sequence, roof_crossfade, moon_levels
    ):
        frames.append(
            _scene(
                sit[panel_index],
                moon,
                roof,
                moon_opacity=moon_alpha,
                roof_opacity=roof_alpha,
            )
        )

    # 21-25: a quiet hold.  Only moonlight breathes; the body and eave stay fixed.
    for moon_alpha in (0.57, 0.59, 0.60, 0.58, 0.57):
        frames.append(_scene(sit[7], moon, roof, moon_opacity=moon_alpha))

    # 26-33: palm light gathers, then the golden chestnut cake arrives.
    for panel_index, moon_alpha in zip(
        (0, 1, 2, 3, 3, 4, 4, 4),
        (0.57, 0.58, 0.59, 0.60, 0.58, 0.59, 0.60, 0.58),
    ):
        frames.append(_scene(taste[panel_index], moon, roof, moon_opacity=moon_alpha))

    # 34-35: raise and taste without any camera close-up.
    for panel_index, moon_alpha in zip((5, 6), (0.58, 0.60)):
        frames.append(_scene(taste[panel_index], moon, roof, moon_opacity=moon_alpha))

    # 36-38: lower and dissolve the cake before putting weight on the roof.
    for panel_index, moon_alpha in zip(range(3), (0.58, 0.56, 0.54)):
        frames.append(_scene(recover[panel_index], moon, roof, moon_opacity=moon_alpha))

    # 39-45: seven independently drawn rising poses; no reversed sitting and
    # no cross-dissolved double body.
    for panel_index, moon_alpha in zip(
        range(1, 8), (0.52, 0.50, 0.48, 0.46, 0.44, 0.42, 0.40)
    ):
        frames.append(_scene(stand[panel_index], moon, roof, moon_opacity=moon_alpha))

    # 46-48: character is already standing; scenery alone disappears.
    frames.append(
        _scene(idle[0], moon, roof, moon_opacity=0.28, roof_opacity=0.52)
    )
    frames.append(
        _scene(idle[0], moon, roof, moon_opacity=0.13, roof_opacity=0.22)
    )
    frames.append(idle[0])

    if len(frames) != FRAME_COUNT:
        raise AssertionError("internal timeline must contain exactly 48 frames")
    if frames[0].tobytes() != idle[0].tobytes():
        raise AssertionError("first frame must match the idle boundary")
    if frames[-1].tobytes() != idle[0].tobytes():
        raise AssertionError("last frame must match the idle boundary")
    hashes = [sha256(frame.tobytes()).digest() for frame in frames]
    if any(left == right for left, right in zip(hashes, hashes[1:])):
        raise ValueError("generated animation contains consecutive duplicate frames")
    return tuple(frames)


def extend_atlas(source: Image.Image, frames: tuple[Image.Image, ...]) -> Image.Image:
    """Replace rows 23-25 while preserving every earlier atlas pixel."""

    if source.width != ATLAS_WIDTH or source.height not in {
        SOURCE_ATLAS_HEIGHT,
        ATLAS_HEIGHT,
    }:
        raise ValueError(
            "source atlas must be 3072x4784 or an already-expanded 3072x5408 atlas"
        )
    if len(frames) != FRAME_COUNT or any(frame.size != CELL_SIZE for frame in frames):
        raise ValueError("exactly 48 frames sized 192x208 are required")

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
                draw.rectangle(
                    (x, y, x + tile - 1, y + tile - 1),
                    fill=(188, 197, 209, 255),
                )

    label_height = 20
    audit = Image.new(
        "RGB",
        (CELL_SIZE[0] * 8, (CELL_SIZE[1] + label_height) * 6),
        (244, 246, 249),
    )
    audit_draw = ImageDraw.Draw(audit)
    for index, frame in enumerate(frames):
        row, column = divmod(index, 8)
        panel = checker.copy()
        panel.alpha_composite(frame)
        x = column * CELL_SIZE[0]
        y = row * (CELL_SIZE[1] + label_height)
        audit.paste(panel.convert("RGB"), (x, y))
        audit_draw.text(
            (x + 5, y + CELL_SIZE[1] + 3),
            f"frame {index + 1:02d}",
            fill=(20, 28, 38),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    audit.save(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild the archived 48-frame moonlit-chestnut candidate into a "
            "separate work output."
        )
    )
    parser.add_argument("--archive-atlas", type=Path, default=ATLAS_PATH)
    parser.add_argument("--archive-manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--output-atlas", type=Path, default=OUTPUT_ATLAS_PATH)
    return parser


def _validate_output_location(path: Path) -> None:
    resolved = path.resolve(strict=False)
    protected = (ARCHIVE_ROOT.resolve(), LIVE_PET_ROOT.resolve())
    if any(resolved == root or resolved.is_relative_to(root) for root in protected):
        raise ValueError("output must not be inside a protected archive or live pet tree")


def main() -> None:
    args = _parser().parse_args()
    _validate_output_location(args.output_atlas)
    if args.output_atlas.resolve() in {
        args.archive_atlas.resolve(),
        args.archive_manifest.resolve(),
    }:
        raise ValueError("output atlas must not overwrite an archived source")
    required = (
        SIT_PATH,
        TASTE_PATH,
        RECOVER_PATH,
        STAND_PATH,
        MOON_PATH,
        ROOF_PATH,
        args.archive_atlas,
        args.archive_manifest,
    )
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing moonlit-chestnut assets: {missing}")

    manifest = json.loads(args.archive_manifest.read_text(encoding="utf-8"))
    with Image.open(args.archive_atlas) as source:
        source_rgba = source.convert("RGBA")
        idle_frames = tuple(
            _atlas_frame(source_rgba, manifest, "idle", index) for index in range(3)
        )
        original_prefix_hash = sha256(
            source_rgba.crop((0, 0, ATLAS_WIDTH, SOURCE_ATLAS_HEIGHT)).tobytes()
        ).hexdigest()
        with (
            Image.open(SIT_PATH) as sit_sheet,
            Image.open(TASTE_PATH) as taste_sheet,
            Image.open(RECOVER_PATH) as recover_sheet,
            Image.open(STAND_PATH) as stand_sheet,
            Image.open(MOON_PATH) as moon_source,
            Image.open(ROOF_PATH) as roof_source,
        ):
            frames = build_frames(
                idle_frames,
                extract_grid(sit_sheet, 4, 2),
                extract_grid(taste_sheet, 4, 2),
                extract_grid(recover_sheet, 3, 1),
                extract_grid(stand_sheet, 4, 2),
                moon_source,
                roof_source,
            )
        atlas = extend_atlas(source_rgba, frames)

    rebuilt_prefix_hash = sha256(
        atlas.crop((0, 0, ATLAS_WIDTH, SOURCE_ATLAS_HEIGHT)).tobytes()
    ).hexdigest()
    if rebuilt_prefix_hash != original_prefix_hash:
        raise AssertionError("builder changed atlas rows 0-22")

    args.output_atlas.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(args.output_atlas, "WEBP", lossless=True, quality=100, method=6, exact=True)
    frame_dir = args.output_atlas.parent / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames, start=1):
        frame.save(frame_dir / f"frame-{index:02d}.png")
    _write_audit(frames, args.output_atlas.parent / "audit-48.png")
    print(f"wrote {FRAME_COUNT} frames to {args.output_atlas}")
    print(f"audit: {args.output_atlas.parent / 'audit-48.png'}")


if __name__ == "__main__":
    main()
