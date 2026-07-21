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

TRANSITION_PATH = ASSET_DIR / "phase-transition-v2.png"
TRANSITION_BRIDGES_PATH = ASSET_DIR / "phase-transition-bridges-v2.png"
RESIDENT_PATH = ASSET_DIR / "phase-resident-v2.png"
GLANCE_PATH = ASSET_DIR / "phase-glance-v2.png"
CHESTNUT_PATH = ASSET_DIR / "phase-rooftop-chestnut-v2.png"
CHESTNUT_RETURN_PATH = ASSET_DIR / "phase-rooftop-chestnut-return-v2.png"
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


def _placed_sequence(
    panels: tuple[Image.Image, ...], *, target_height: int
) -> tuple[Image.Image, ...]:
    """Place one generated sheet at a shared scale and foot baseline.

    Generated sheets use different amounts of transparent padding.  Scaling
    the full cells independently makes the character pulse in size, while
    cropping every pose independently makes her horizontal centre wobble.
    This routine derives one scale from the tallest painted pose, preserves
    each cell's source alignment, and locks every pose to the same foot line.
    """

    sources = tuple(panel.convert("RGBA") for panel in panels)
    boxes = tuple(source.getbbox() for source in sources)
    if any(box is None for box in boxes):
        raise ValueError("generated motion sheet contains an empty panel")
    painted_heights = tuple(box[3] - box[1] for box in boxes if box is not None)
    scale = target_height / max(painted_heights)
    placed: list[Image.Image] = []
    for source, box in zip(sources, boxes):
        assert box is not None
        size = (
            max(1, round(source.width * scale)),
            max(1, round(source.height * scale)),
        )
        resized = source.resize(size, Image.Resampling.LANCZOS)
        x = round(CELL_SIZE[0] / 2 - source.width * scale / 2)
        y = round(204 - box[3] * scale)
        frame = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
        frame.alpha_composite(resized, (x, y))
        placed.append(frame)
    return tuple(placed)


def _boundary(
    resident: tuple[Image.Image, ...], moon: Image.Image, roof: Image.Image
) -> Image.Image:
    return _scene(
        resident[0], moon, roof, moon_opacity=0.60, roof_opacity=1.0
    )


def _translated(image: Image.Image, dx: int, dy: int) -> Image.Image:
    result = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    result.alpha_composite(image.convert("RGBA"), (dx, dy))
    return result


def _resident_scene_clip(
    characters: tuple[Image.Image, ...], moon: Image.Image, roof: Image.Image
) -> tuple[Image.Image, ...]:
    return tuple(
        _scene(character, moon, roof, moon_opacity=0.60, roof_opacity=1.0)
        for character in characters
    )


def build_clips(
    idle_frames: tuple[Image.Image, ...],
    transition_panels: tuple[Image.Image, ...],
    transition_bridge_panels: tuple[Image.Image, ...],
    resident_panels: tuple[Image.Image, ...],
    glance_panels: tuple[Image.Image, ...],
    chestnut_panels: tuple[Image.Image, ...],
    chestnut_return_panels: tuple[Image.Image, ...],
    moon_source: Image.Image,
    roof_source: Image.Image,
) -> dict[str, tuple[Image.Image, ...]]:
    if len(idle_frames) < 3:
        raise ValueError("at least three idle frames are required")
    if (
        len(transition_panels) != 8
        or len(transition_bridge_panels) != 8
        or len(resident_panels) != 8
        or len(glance_panels) != 4
        or len(chestnut_panels) != 8
        or len(chestnut_return_panels) != 4
    ):
        raise ValueError("source sheets must contain 8/8/8/4/8/4 panels")

    idle = tuple(frame.convert("RGBA") for frame in idle_frames[:3])
    moon = _prepared_moon(moon_source)
    roof = _prepared_roof(roof_source)
    transition = _placed_sequence(transition_panels, target_height=192)
    transition_bridges = _placed_sequence(
        transition_bridge_panels, target_height=192
    )
    resident = _placed_sequence(resident_panels, target_height=174)
    glance = _placed_sequence(glance_panels, target_height=174)
    chestnut = _placed_sequence(chestnut_panels, target_height=174)
    chestnut_return = _placed_sequence(
        chestnut_return_panels, target_height=174
    )
    boundary = _boundary(resident, moon, roof)

    enter: list[Image.Image] = [idle[0]]
    transition_path = (
        transition[0],
        transition[1],
        *transition_bridges[:4],
        *transition[2:],
        *transition_bridges[4:],
        resident[0],
    )
    for index, character in enumerate(transition_path, 1):
        progress = index / len(transition_path)
        enter.append(
            _scene(
                character,
                moon,
                roof,
                moon_opacity=0.05 + 0.55 * progress,
                roof_opacity=0.03 + 0.97 * progress,
            )
        )
    enter[-1] = boundary

    idle_path = (
        resident[0],
        _translated(resident[0], 0, -1),
        resident[1],
        _translated(resident[1], 0, -1),
        resident[2],
        _translated(resident[1], 0, -1),
        resident[1],
        _translated(resident[0], 0, -1),
        resident[0],
    )
    moon_gaze_path = (
        resident[0],
        resident[3],
        _translated(resident[3], 0, -1),
        resident[6],
        _translated(resident[6], 0, -1),
        resident[3],
        resident[0],
    )
    rest_peak = resident[4]
    rest_path = (
        resident[0],
        rest_peak,
        _translated(rest_peak, 0, 1),
        rest_peak,
        resident[0],
    )
    breeze_path = (
        resident[0],
        resident[1],
        resident[5],
        _translated(resident[5], 0, -1),
        resident[5],
        resident[1],
        resident[0],
    )
    glance_path = (
        resident[0],
        *glance,
        *tuple(reversed(glance[:-1])),
        resident[0],
    )
    chestnut_path = (
        resident[0],
        *chestnut,
        *chestnut_return,
        resident[0],
    )

    clips: dict[str, tuple[Image.Image, ...]] = {
        "moonlitChestnut": tuple(enter),
        "rooftopIdle": _resident_scene_clip(idle_path, moon, roof),
        "rooftopMoonGaze": _resident_scene_clip(moon_gaze_path, moon, roof),
        "rooftopChestnut": _resident_scene_clip(chestnut_path, moon, roof),
        "rooftopRest": _resident_scene_clip(rest_path, moon, roof),
        "rooftopBreeze": _resident_scene_clip(breeze_path, moon, roof),
        "rooftopGlance": _resident_scene_clip(glance_path, moon, roof),
        "rooftopExit": tuple(reversed(enter)),
    }

    expected = {
        "moonlitChestnut": 18,
        "rooftopIdle": 9,
        "rooftopMoonGaze": 7,
        "rooftopChestnut": 14,
        "rooftopRest": 5,
        "rooftopBreeze": 7,
        "rooftopGlance": 9,
        "rooftopExit": 18,
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
        TRANSITION_PATH,
        TRANSITION_BRIDGES_PATH,
        RESIDENT_PATH,
        GLANCE_PATH,
        CHESTNUT_PATH,
        CHESTNUT_RETURN_PATH,
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
            Image.open(TRANSITION_PATH) as transition_sheet,
            Image.open(TRANSITION_BRIDGES_PATH) as transition_bridges_sheet,
            Image.open(RESIDENT_PATH) as resident_sheet,
            Image.open(GLANCE_PATH) as glance_sheet,
            Image.open(CHESTNUT_PATH) as chestnut_sheet,
            Image.open(CHESTNUT_RETURN_PATH) as chestnut_return_sheet,
            Image.open(MOON_PATH) as moon_source,
            Image.open(ROOF_PATH) as roof_source,
        ):
            clips = build_clips(
                idle_frames,
                extract_grid(transition_sheet, 4, 2, inset=4),
                extract_grid(transition_bridges_sheet, 4, 2, inset=4),
                extract_grid(resident_sheet, 4, 2, inset=4),
                extract_grid(glance_sheet, 4, 1, inset=4),
                extract_grid(chestnut_sheet, 4, 2, inset=4),
                extract_grid(chestnut_return_sheet, 4, 1, inset=4),
                moon_source,
                roof_source,
            )
        atlas = extend_atlas(source_rgba, clips)

    if sha256(
        atlas.crop((0, 0, ATLAS_WIDTH, SOURCE_ATLAS_HEIGHT)).tobytes()
    ).digest() != prefix_hash:
        raise AssertionError("builder changed atlas rows 0 through 22")

    atlas.save(ATLAS_PATH, "WEBP", lossless=True, quality=100, method=6, exact=True)
    frame_dir = WORK_DIR / "frames-smooth-v3"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for key in CLIP_ORDER:
        for index, frame in enumerate(clips[key], 1):
            frame.save(frame_dir / f"{key}-{index:02d}.png")
    _write_audit(clips, WORK_DIR / "audit-87.png")
    print(f"wrote {sum(map(len, clips.values()))} state frames to {ATLAS_PATH}")
    print(f"audit: {WORK_DIR / 'audit-87.png'}")


if __name__ == "__main__":
    main()
