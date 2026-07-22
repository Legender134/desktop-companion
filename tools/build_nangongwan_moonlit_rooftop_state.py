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

from PIL import Image, ImageChops, ImageDraw, ImageFilter

try:
    from tools.build_nangongwan_moonlit_chestnut import (
        CELL_SIZE,
        ATLAS_COLUMNS,
        ATLAS_WIDTH,
        SOURCE_ATLAS_HEIGHT,
        _atlas_frame,
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
        _scene,
        extract_grid,
    )


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "tools" / "assets" / "nangongwan-moonlit-redesign"
PET_ROOT = ROOT / "src" / "shiyi_desktop_pet" / "resources" / "pets" / "nangongwan"
ATLAS_PATH = PET_ROOT / "spritesheet.webp"
MANIFEST_PATH = PET_ROOT / "pet.json"
WORK_DIR = ROOT / "work" / "moonlit-rooftop-state"

TRANSITION_PATH = ASSET_DIR / "phase-transition-v4.png"
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

RESIDENT_MOON_OPACITY = 0.78
SEATED_TARGET_ANCHOR = (94, 133)

# The source sheets were generated separately and do not share a canvas origin.
# These points mark the centre of the same waist clasp in every seated panel.
# The clasp is rigidly tied to the pelvis, so it is a dependable proxy for the
# hidden butt/eave contact point.  Do not replace this with a silhouette centre:
# moving hair, sleeves, and props are intentionally allowed to change bounds.
RESIDENT_SEAT_ANCHORS = (
    (232, 249),
    (201, 249),
    (191, 249),
    (170, 249),
    (230, 201),
    (195, 203),
    (190, 201),
    (170, 201),
)
GLANCE_SEAT_ANCHORS = (
    (275, 423),
    (244, 423),
    (231, 423),
    (202, 423),
)
CHESTNUT_SEAT_ANCHORS = (
    (231, 248),
    (200, 248),
    (194, 248),
    (180, 248),
    (231, 204),
    (208, 204),
    (190, 204),
    (180, 204),
)
CHESTNUT_RETURN_SEAT_ANCHORS = (
    (274, 426),
    (247, 426),
    (224, 426),
    (202, 426),
)


def _head_anchor_x(source: Image.Image) -> float:
    """Return the horizontal centre of the painted head region.

    The generated panels do not share a reliable canvas origin: the same face
    can sit dozens of source pixels farther left or right from one panel to the
    next.  The upper 40 percent of the painted silhouette contains the head
    and hair ornament but excludes sleeves, skirts, and wind-blown lower hair,
    making it a stable visual anchor for a seated desktop character.
    """

    alpha = source.convert("RGBA").getchannel("A")
    opaque = alpha.point(lambda value: 255 if value >= 16 else 0)
    painted = opaque.getbbox()
    if painted is None:
        raise ValueError("generated motion panel is empty")
    painted_height = painted[3] - painted[1]
    head_bottom = painted[1] + max(1, round(painted_height * 0.40))
    head = opaque.crop((0, painted[1], source.width, head_bottom)).getbbox()
    if head is None:
        raise ValueError("generated motion panel has no detectable head")
    return (head[0] + head[2]) / 2


def _placed_sequence(
    panels: tuple[Image.Image, ...],
    *,
    target_height: int,
    source_anchors: tuple[tuple[float, float], ...] | None = None,
    target_anchor: tuple[float, float] = SEATED_TARGET_ANCHOR,
) -> tuple[Image.Image, ...]:
    """Place one generated sheet at a shared scale and stable root.

    Generated sheets use different amounts of transparent padding.  Scaling
    the full cells independently makes the character pulse in size, while
    cropping every pose independently makes her horizontal centre wobble.  A
    seated sequence supplies the same anatomical waist/pelvis point for every
    source panel, which is locked in both x and y.  Head, sleeves, hands, hair,
    and props can still animate without sliding the seated contact point.

    Transition panels omit ``source_anchors`` and retain the older head-centre
    plus foot-line placement because standing up and sitting down legitimately
    move the pelvis.
    """

    sources = tuple(panel.convert("RGBA") for panel in panels)
    if source_anchors is not None and len(source_anchors) != len(sources):
        raise ValueError("every seated panel must have one source anchor")
    if source_anchors is not None and any(
        not (0 <= anchor[0] < source.width and 0 <= anchor[1] < source.height)
        for source, anchor in zip(sources, source_anchors)
    ):
        raise ValueError("a seated source anchor lies outside its panel")
    boxes = tuple(source.getbbox() for source in sources)
    if any(box is None for box in boxes):
        raise ValueError("generated motion sheet contains an empty panel")
    painted_heights = tuple(box[3] - box[1] for box in boxes if box is not None)
    scale = target_height / max(painted_heights)
    placed: list[Image.Image] = []
    for index, (source, box) in enumerate(zip(sources, boxes)):
        assert box is not None
        size = (
            max(1, round(source.width * scale)),
            max(1, round(source.height * scale)),
        )
        resized = source.resize(size, Image.Resampling.LANCZOS)
        resized_box = resized.getbbox()
        if resized_box is None:
            raise ValueError("resized motion panel is empty")
        if source_anchors is None:
            x = round(CELL_SIZE[0] / 2 - _head_anchor_x(resized))
            y = 204 - resized_box[3]
        else:
            source_anchor = source_anchors[index]
            scaled_anchor = (
                source_anchor[0] * resized.width / source.width,
                source_anchor[1] * resized.height / source.height,
            )
            x = round(target_anchor[0] - scaled_anchor[0])
            y = round(target_anchor[1] - scaled_anchor[1])
            mapped_anchor = (x + scaled_anchor[0], y + scaled_anchor[1])
            if (
                abs(mapped_anchor[0] - target_anchor[0]) > 0.51
                or abs(mapped_anchor[1] - target_anchor[1]) > 0.51
            ):
                raise AssertionError("integer placement moved the seated root")
        frame = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
        frame.alpha_composite(resized, (x, y))
        placed.append(frame)
    return tuple(placed)


def _prepared_local_moon(source: Image.Image) -> Image.Image:
    """Create the large, unmistakable partial moon behind the seated pet."""

    moon = source.convert("RGBA")
    box = moon.getbbox()
    if box is None:
        raise ValueError("partial moon asset is empty")
    width = box[2] - box[0]
    height = box[3] - box[1]
    side = max(1, round(min(width, height) * 0.70))
    left = box[0] + round((width - side) * 0.16)
    top = box[1] + round((height - side) * 0.16)
    moon = moon.crop((left, top, left + side, top + side)).convert("RGB")
    moon = moon.resize((126, 126), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", moon.size, 0)
    ImageDraw.Draw(mask).ellipse((2, 2, 123, 123), fill=255)
    moon.putalpha(mask.filter(ImageFilter.GaussianBlur(1.0)))
    result = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    # The character occludes the lower-left portion, so the moon reads as a
    # large background presence without using a hard crop at the canvas edge.
    result.alpha_composite(moon, (64, 0))
    return result


def _prepared_local_roof(source: Image.Image) -> Image.Image:
    """Place a compact eave under the pet without touching the canvas corners."""

    roof = source.convert("RGBA")
    box = roof.getbbox()
    if box is None:
        raise ValueError("roof asset is empty")
    roof = roof.crop(box)
    roof.thumbnail((176, 76), Image.Resampling.LANCZOS)
    alpha = roof.getchannel("A")
    fade = Image.new("L", roof.size, 255)
    fade_draw = ImageDraw.Draw(fade)
    fade_width = min(28, max(1, roof.width // 5))
    for offset in range(fade_width):
        value = round(255 * (fade_width - 1 - offset) / max(1, fade_width - 1))
        x = roof.width - fade_width + offset
        fade_draw.line((x, 0, x, roof.height), fill=value)
    roof.putalpha(ImageChops.multiply(alpha, fade))
    result = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    result.alpha_composite(roof, (8, 139))
    return result


def _smoothstep(value: float) -> float:
    clamped = max(0.0, min(1.0, value))
    return clamped * clamped * (3.0 - 2.0 * clamped)


def _boundary(
    resident: tuple[Image.Image, ...], moon: Image.Image, roof: Image.Image
) -> Image.Image:
    return _scene(
        resident[0], moon, roof,
        moon_opacity=RESIDENT_MOON_OPACITY,
        roof_opacity=1.0,
    )


def _translated(image: Image.Image, dx: int, dy: int) -> Image.Image:
    result = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    result.alpha_composite(image.convert("RGBA"), (dx, dy))
    return result


def _resident_scene_clip(
    characters: tuple[Image.Image, ...], moon: Image.Image, roof: Image.Image
) -> tuple[Image.Image, ...]:
    return tuple(
        _scene(
            character,
            moon,
            roof,
            moon_opacity=RESIDENT_MOON_OPACITY,
            roof_opacity=1.0,
        )
        for character in characters
    )


def _validate_desktop_transparency(
    clips: dict[str, tuple[Image.Image, ...]],
) -> None:
    """Reject scene-card frames before they can reach the installed app."""

    corners = (
        (0, 0),
        (CELL_SIZE[0] - 1, 0),
        (0, CELL_SIZE[1] - 1),
        (CELL_SIZE[0] - 1, CELL_SIZE[1] - 1),
    )
    for action_id, frames in clips.items():
        for index, frame in enumerate(frames, start=1):
            alpha = frame.getchannel("A")
            if any(alpha.getpixel(point) > 0 for point in corners):
                raise ValueError(
                    f"{action_id} frame {index} paints a canvas corner"
                )
            visible_pixels = sum(alpha.histogram()[8:])
            if visible_pixels > 24000:
                raise ValueError(
                    f"{action_id} frame {index} covers too much of the desktop canvas: "
                    f"{visible_pixels} pixels"
                )
            if alpha.getbbox() == (0, 0, *CELL_SIZE):
                raise ValueError(
                    f"{action_id} frame {index} forms a full-canvas scene card"
                )


def build_clips(
    idle_frames: tuple[Image.Image, ...],
    transition_panels: tuple[Image.Image, ...],
    resident_panels: tuple[Image.Image, ...],
    glance_panels: tuple[Image.Image, ...],
    chestnut_panels: tuple[Image.Image, ...],
    chestnut_return_panels: tuple[Image.Image, ...],
    moon_source: Image.Image,
    roof_source: Image.Image,
    *,
    seated_source_anchors: dict[
        str, tuple[tuple[float, float], ...]
    ] | None = None,
) -> dict[str, tuple[Image.Image, ...]]:
    if len(idle_frames) < 3:
        raise ValueError("at least three idle frames are required")
    if (
        len(transition_panels) != 8
        or len(resident_panels) != 8
        or len(glance_panels) != 4
        or len(chestnut_panels) != 8
        or len(chestnut_return_panels) != 4
    ):
        raise ValueError("source sheets must contain 8/8/4/8/4 panels")

    idle = tuple(frame.convert("RGBA") for frame in idle_frames[:3])
    anchors = (
        seated_source_anchors
        if seated_source_anchors is not None
        else {
            "resident": RESIDENT_SEAT_ANCHORS,
            "glance": GLANCE_SEAT_ANCHORS,
            "chestnut": CHESTNUT_SEAT_ANCHORS,
            "chestnut-return": CHESTNUT_RETURN_SEAT_ANCHORS,
        }
    )
    if set(anchors) != {"resident", "glance", "chestnut", "chestnut-return"}:
        raise ValueError("seated source anchors must cover all resident sheets")
    moon = _prepared_local_moon(moon_source)
    roof = _prepared_local_roof(roof_source)
    transition = _placed_sequence(transition_panels, target_height=192)
    resident = _placed_sequence(
        resident_panels,
        target_height=184,
        source_anchors=anchors["resident"],
    )
    glance = _placed_sequence(
        glance_panels,
        target_height=184,
        source_anchors=anchors["glance"],
    )
    chestnut = _placed_sequence(
        chestnut_panels,
        target_height=184,
        source_anchors=anchors["chestnut"],
    )
    chestnut_return = _placed_sequence(
        chestnut_return_panels,
        target_height=184,
        source_anchors=anchors["chestnut-return"],
    )
    boundary = _boundary(resident, moon, roof)

    enter: list[Image.Image] = [idle[0], idle[1]]
    transition_path = (
        transition[0],
        _translated(transition[0], 0, -1),
        transition[1],
        _translated(transition[1], 0, -1),
        transition[2],
        _translated(transition[2], 0, -1),
        transition[3],
        transition[4],
        transition[5],
        transition[6],
        transition[7],
        _translated(transition[7], 0, -1),
        resident[0],
        resident[0],
        resident[0],
        resident[0],
    )
    for index, character in enumerate(transition_path, 1):
        progress = index / len(transition_path)
        eased = _smoothstep(progress)
        roof_progress = _smoothstep((progress - 0.05) / 0.60)
        enter.append(
            _scene(
                character,
                moon,
                roof,
                moon_opacity=RESIDENT_MOON_OPACITY * eased,
                roof_opacity=roof_progress,
            )
        )
    enter[-1] = boundary

    idle_path = (
        resident[0],
        resident[0],
        resident[1],
        resident[1],
        resident[2],
        resident[1],
        resident[1],
        resident[0],
        resident[0],
    )
    moon_gaze_path = (
        resident[0],
        resident[3],
        resident[3],
        resident[6],
        resident[6],
        resident[3],
        resident[0],
    )
    rest_peak = resident[4]
    rest_path = (
        resident[0],
        rest_peak,
        rest_peak,
        rest_peak,
        resident[0],
    )
    breeze_path = (
        resident[0],
        resident[1],
        resident[5],
        resident[5],
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
    _validate_desktop_transparency(clips)
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
    checker = Image.new("RGBA", CELL_SIZE, (228, 233, 240, 255))
    checker_draw = ImageDraw.Draw(checker)
    for y in range(0, CELL_SIZE[1], 16):
        for x in range(0, CELL_SIZE[0], 16):
            if (x // 16 + y // 16) % 2:
                checker_draw.rectangle(
                    (x, y, x + 15, y + 15), fill=(186, 196, 209, 255)
                )
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
        panel = checker.copy()
        panel.alpha_composite(frame)
        audit.paste(panel.convert("RGB"), (x, y))
        draw.text((x + 4, y + CELL_SIZE[1] + 4), f"{key} {index:02d}", fill=(18, 25, 36))
    path.parent.mkdir(parents=True, exist_ok=True)
    audit.save(path)


def main() -> None:
    required = (
        TRANSITION_PATH,
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
    frame_dir = WORK_DIR / "frames-transparent-v6"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for key in CLIP_ORDER:
        for index, frame in enumerate(clips[key], 1):
            frame.save(frame_dir / f"{key}-{index:02d}.png")
    _write_audit(clips, WORK_DIR / "audit-87-transparent-v6.png")
    print(f"wrote {sum(map(len, clips.values()))} state frames to {ATLAS_PATH}")
    print(f"audit: {WORK_DIR / 'audit-87-transparent-v6.png'}")


if __name__ == "__main__":
    main()
