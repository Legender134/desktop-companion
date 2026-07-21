"""Build Nangong Wan's persistent moonlit-rooftop state atlas clips.

The runtime state is deliberately assembled from finite clips with one exact
resident boundary pose.  Every resident clip begins and ends on that same
pixel-identical frame, so the scheduler can choose a new seated action without
cross-fades, camera jumps, or a duplicate body.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from tools.build_nangongwan_moonlit_chestnut import (
        CELL_SIZE,
        ATLAS_COLUMNS,
        ATLAS_WIDTH,
        SOURCE_ATLAS_HEIGHT,
        _atlas_frame,
        _placed_panel,
        _prepared_moon,
        _prepared_roof,
        _scene,
        extract_grid,
    )
except ModuleNotFoundError:  # Direct ``python tools/<script>.py`` execution.
    from build_nangongwan_moonlit_chestnut import (
        CELL_SIZE,
        ATLAS_COLUMNS,
        ATLAS_WIDTH,
        SOURCE_ATLAS_HEIGHT,
        _atlas_frame,
        _placed_panel,
        _prepared_moon,
        _prepared_roof,
        _scene,
        extract_grid,
    )


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "tools" / "assets" / "nangongwan-moonlit-redesign"
PET_ROOT = ROOT / "src" / "shiyi_desktop_pet" / "resources" / "pets" / "nangongwan"
ATLAS_PATH = PET_ROOT / "spritesheet.webp"
MANIFEST_PATH = PET_ROOT / "pet.json"
WORK_DIR = ROOT / "work" / "moonlit-rooftop-state"

SIT_PATH = ASSET_DIR / "phase-sit.png"
TASTE_PATH = ASSET_DIR / "phase-taste.png"
RECOVER_PATH = ASSET_DIR / "phase-recover.png"
STAND_PATH = ASSET_DIR / "phase-stand-v2.png"
RESIDENT_PATH = ASSET_DIR / "phase-resident-v1.png"
MOON_PATH = ASSET_DIR / "moon-partial.png"
ROOF_PATH = ASSET_DIR / "roof-eave.png"

START_CELL = 23 * ATLAS_COLUMNS
CLIP_ORDER = (
    "moonlitChestnut",
    "rooftopIdle",
    "rooftopMoonGaze",
    "rooftopChestnut",
    "rooftopRest",
    "rooftopBreeze",
    "rooftopGlance",
    "rooftopExit",
)


def _resident_panel(panel: Image.Image) -> Image.Image:
    """Use one fixed source canvas and baseline for all generated key poses."""

    return _placed_panel(panel, scale=0.50, source_foot_y=426)


def _boundary(
    resident: tuple[Image.Image, ...], moon: Image.Image, roof: Image.Image
) -> Image.Image:
    del roof
    return _scene(resident[0], moon, Image.new("RGBA", CELL_SIZE), moon_opacity=0.58)


def _resident_clip(
    boundary: Image.Image,
    resident: tuple[Image.Image, ...],
    moon: Image.Image,
    indices: tuple[int, ...],
    moon_levels: tuple[float, ...],
) -> tuple[Image.Image, ...]:
    if len(indices) != len(moon_levels):
        raise ValueError("resident clip indices and moon levels must match")
    middle = tuple(
        _scene(
            resident[index],
            moon,
            Image.new("RGBA", CELL_SIZE),
            moon_opacity=moon_alpha,
        )
        for index, moon_alpha in zip(indices, moon_levels)
    )
    return (boundary, *middle, boundary)


def build_clips(
    idle_frames: tuple[Image.Image, ...],
    sit_panels: tuple[Image.Image, ...],
    taste_panels: tuple[Image.Image, ...],
    recover_panels: tuple[Image.Image, ...],
    stand_panels: tuple[Image.Image, ...],
    resident_panels: tuple[Image.Image, ...],
    moon_source: Image.Image,
    roof_source: Image.Image,
) -> dict[str, tuple[Image.Image, ...]]:
    if len(idle_frames) < 3:
        raise ValueError("at least three idle frames are required")
    if (
        len(sit_panels) != 8
        or len(taste_panels) != 8
        or len(recover_panels) != 3
        or len(stand_panels) != 8
        or len(resident_panels) != 8
    ):
        raise ValueError("source sheets must contain 8/8/3/8/8 panels")

    idle = tuple(frame.convert("RGBA") for frame in idle_frames[:3])
    moon = _prepared_moon(moon_source)
    roof = _prepared_roof(roof_source)
    resident = tuple(_resident_panel(panel) for panel in resident_panels)
    boundary = _boundary(resident, moon, roof)

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

    enter: list[Image.Image] = [idle[0], idle[1], idle[2], idle[0]]
    for character, moon_alpha, roof_alpha in zip(
        (idle[1], idle[2], idle[0], idle[1], idle[2], idle[0]),
        (0.06, 0.12, 0.20, 0.29, 0.39, 0.49),
        (0.05, 0.12, 0.22, 0.34, 0.47, 0.60),
    ):
        enter.append(
            _scene(
                character,
                moon,
                roof,
                moon_opacity=moon_alpha,
                roof_opacity=roof_alpha,
            )
        )
    for panel_index, roof_alpha, moon_alpha in zip(
        range(8),
        (0.68, 0.62, 0.54, 0.42, 0.28, 0.14, 0.04, 0.0),
        (0.50, 0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57),
    ):
        enter.append(
            _scene(
                sit[panel_index],
                moon,
                roof,
                moon_opacity=moon_alpha,
                roof_opacity=roof_alpha,
            )
        )
    enter.extend((boundary, boundary))

    clips: dict[str, tuple[Image.Image, ...]] = {
        "moonlitChestnut": tuple(enter),
        "rooftopIdle": _resident_clip(
            boundary,
            resident,
            moon,
            (1, 0, 1, 0, 1, 0),
            (0.59, 0.60, 0.59, 0.57, 0.58, 0.59),
        ),
        "rooftopMoonGaze": _resident_clip(
            boundary,
            resident,
            moon,
            (2, 3, 3, 3, 2, 0),
            (0.60, 0.62, 0.64, 0.63, 0.61, 0.59),
        ),
        "rooftopRest": _resident_clip(
            boundary,
            resident,
            moon,
            (4, 4, 4, 4, 4, 0),
            (0.58, 0.57, 0.56, 0.57, 0.58, 0.59),
        ),
        "rooftopBreeze": _resident_clip(
            boundary,
            resident,
            moon,
            (5, 5, 5, 5, 1, 0),
            (0.60, 0.61, 0.62, 0.61, 0.60, 0.59),
        ),
        "rooftopGlance": _resident_clip(
            boundary,
            resident,
            moon,
            (6, 6, 7, 7, 6, 0),
            (0.59, 0.60, 0.60, 0.59, 0.58, 0.59),
        ),
    }

    chestnut_middle: list[Image.Image] = []
    for panel_index, moon_alpha in zip(
        (0, 1, 2, 3, 4, 5, 6, 7),
        (0.58, 0.59, 0.60, 0.61, 0.60, 0.61, 0.62, 0.60),
    ):
        chestnut_middle.append(
            _scene(taste[panel_index], moon, roof, moon_opacity=moon_alpha)
        )
    for panel_index, moon_alpha in zip((0, 1), (0.59, 0.58)):
        chestnut_middle.append(
            _scene(recover[panel_index], moon, roof, moon_opacity=moon_alpha)
        )
    clips["rooftopChestnut"] = (boundary, *chestnut_middle, boundary)

    exit_frames: list[Image.Image] = [boundary]
    for panel_index, moon_alpha in zip(
        range(1, 8), (0.55, 0.52, 0.49, 0.45, 0.40, 0.32, 0.22)
    ):
        exit_frames.append(
            _scene(stand[panel_index], moon, roof, moon_opacity=moon_alpha)
        )
    exit_frames.append(idle[0])
    clips["rooftopExit"] = tuple(exit_frames)

    expected = {
        "moonlitChestnut": 20,
        "rooftopIdle": 8,
        "rooftopMoonGaze": 8,
        "rooftopChestnut": 12,
        "rooftopRest": 8,
        "rooftopBreeze": 8,
        "rooftopGlance": 8,
        "rooftopExit": 9,
    }
    if {key: len(value) for key, value in clips.items()} != expected:
        raise AssertionError("persistent rooftop clips have an invalid frame count")
    for key in (
        "rooftopIdle",
        "rooftopMoonGaze",
        "rooftopChestnut",
        "rooftopRest",
        "rooftopBreeze",
        "rooftopGlance",
    ):
        if clips[key][0].tobytes() != boundary.tobytes() or clips[key][-1].tobytes() != boundary.tobytes():
            raise AssertionError(f"{key} does not use the exact resident boundary")
    if clips["moonlitChestnut"][-1].tobytes() != boundary.tobytes():
        raise AssertionError("enter clip must end on the resident boundary")
    if clips["rooftopExit"][0].tobytes() != boundary.tobytes():
        raise AssertionError("exit clip must start on the resident boundary")
    return {key: clips[key] for key in CLIP_ORDER}


def extend_atlas(
    source: Image.Image, clips: dict[str, tuple[Image.Image, ...]]
) -> Image.Image:
    if source.width != ATLAS_WIDTH or source.height < SOURCE_ATLAS_HEIGHT:
        raise ValueError("source atlas must contain the complete rows 0 through 22")
    frames = tuple(frame for key in CLIP_ORDER for frame in clips[key])
    rows = (START_CELL + len(frames) + ATLAS_COLUMNS - 1) // ATLAS_COLUMNS
    atlas = Image.new("RGBA", (ATLAS_WIDTH, rows * CELL_SIZE[1]), (0, 0, 0, 0))
    atlas.alpha_composite(
        source.convert("RGBA").crop((0, 0, ATLAS_WIDTH, SOURCE_ATLAS_HEIGHT)),
        (0, 0),
    )
    for offset, frame in enumerate(frames):
        row, column = divmod(START_CELL + offset, ATLAS_COLUMNS)
        atlas.alpha_composite(frame, (column * CELL_SIZE[0], row * CELL_SIZE[1]))
    return atlas


def _write_audit(clips: dict[str, tuple[Image.Image, ...]], path: Path) -> None:
    frames = [(key, index, frame) for key in CLIP_ORDER for index, frame in enumerate(clips[key], 1)]
    columns = 9
    label_height = 28
    rows = (len(frames) + columns - 1) // columns
    audit = Image.new(
        "RGB",
        (CELL_SIZE[0] * columns, (CELL_SIZE[1] + label_height) * rows),
        (225, 230, 237),
    )
    draw = ImageDraw.Draw(audit)
    for offset, (key, index, frame) in enumerate(frames):
        row, column = divmod(offset, columns)
        x = column * CELL_SIZE[0]
        y = row * (CELL_SIZE[1] + label_height)
        audit.paste(frame, (x, y), frame)
        draw.text((x + 4, y + CELL_SIZE[1] + 4), f"{key} {index:02d}", fill=(18, 25, 36))
    path.parent.mkdir(parents=True, exist_ok=True)
    audit.save(path)


def main() -> None:
    required = (
        SIT_PATH,
        TASTE_PATH,
        RECOVER_PATH,
        STAND_PATH,
        RESIDENT_PATH,
        MOON_PATH,
        ROOF_PATH,
        ATLAS_PATH,
        MANIFEST_PATH,
    )
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing persistent-rooftop assets: {missing}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    with Image.open(ATLAS_PATH) as source:
        source_rgba = source.convert("RGBA")
        prefix_hash = sha256(
            source_rgba.crop((0, 0, ATLAS_WIDTH, SOURCE_ATLAS_HEIGHT)).tobytes()
        ).digest()
        idle_frames = tuple(
            _atlas_frame(source_rgba, manifest, "idle", index) for index in range(3)
        )
        with (
            Image.open(SIT_PATH) as sit_sheet,
            Image.open(TASTE_PATH) as taste_sheet,
            Image.open(RECOVER_PATH) as recover_sheet,
            Image.open(STAND_PATH) as stand_sheet,
            Image.open(RESIDENT_PATH) as resident_sheet,
            Image.open(MOON_PATH) as moon_source,
            Image.open(ROOF_PATH) as roof_source,
        ):
            clips = build_clips(
                idle_frames,
                extract_grid(sit_sheet, 4, 2),
                extract_grid(taste_sheet, 4, 2),
                extract_grid(recover_sheet, 3, 1),
                extract_grid(stand_sheet, 4, 2),
                extract_grid(resident_sheet, 4, 2, inset=8),
                moon_source,
                roof_source,
            )
        atlas = extend_atlas(source_rgba, clips)

    if sha256(
        atlas.crop((0, 0, ATLAS_WIDTH, SOURCE_ATLAS_HEIGHT)).tobytes()
    ).digest() != prefix_hash:
        raise AssertionError("builder changed atlas rows 0 through 22")

    atlas.save(ATLAS_PATH, "WEBP", lossless=True, quality=100, method=6, exact=True)
    frame_dir = WORK_DIR / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for key in CLIP_ORDER:
        for index, frame in enumerate(clips[key], 1):
            frame.save(frame_dir / f"{key}-{index:02d}.png")
    _write_audit(clips, WORK_DIR / "audit-81.png")
    print(f"wrote {sum(map(len, clips.values()))} state frames to {ATLAS_PATH}")
    print(f"audit: {WORK_DIR / 'audit-81.png'}")


if __name__ == "__main__":
    main()
