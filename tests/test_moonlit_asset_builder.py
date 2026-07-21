from hashlib import sha256

from PIL import Image, ImageDraw

from tools.build_nangongwan_moonlit_chestnut import (
    ATLAS_HEIGHT,
    ATLAS_WIDTH,
    CELL_SIZE,
    build_frames,
    extend_atlas,
    extract_grid,
)
from tools.build_nangongwan_moonlit_rooftop_state import (
    CHESTNUT_HAND_TARGET,
    CLIP_ORDER,
    LOWER_BODY_LOCK_Y,
    SEATED_TARGET_ANCHOR,
    _chestnut_flight_frame,
    _placed_sequence,
    _prepared_local_moon,
    build_clips as build_state_clips,
    extend_atlas as extend_state_atlas,
)


def _panel_sheet(columns: int, rows: int, *, size: tuple[int, int]) -> Image.Image:
    sheet = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for index in range(columns * rows):
        row, column = divmod(index, columns)
        left = round(size[0] * column / columns)
        right = round(size[0] * (column + 1) / columns)
        top = round(size[1] * row / rows)
        bottom = round(size[1] * (row + 1) / rows)
        color = (40 + index * 18, 90 + index * 9, 180 - index * 10, 255)
        draw.ellipse((left + 40, top + 24, right - 40, bottom - 32), fill=color)
        draw.rectangle((left + 18, bottom - 90, right - 18, bottom - 28), fill=(20, 30, 70, 255))
    return sheet


def _idle_frames() -> tuple[Image.Image, ...]:
    frames = []
    for index in range(3):
        frame = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.ellipse((48, 8 + index, 144, 112 + index), fill=(220, 228, 244, 255))
        draw.rectangle((64, 92, 128, 204), fill=(35 + index, 70, 130, 255))
        frames.append(frame)
    return tuple(frames)


def _moon_and_roof() -> tuple[Image.Image, Image.Image]:
    moon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(moon).ellipse((-40, -30, 220, 230), fill=(195, 215, 250, 230))
    roof = Image.new("RGBA", (256, 128), (0, 0, 0, 0))
    ImageDraw.Draw(roof).polygon(((8, 50), (248, 36), (248, 108), (20, 96)), fill=(25, 38, 78, 255))
    return moon, roof


def _synthetic_seat_anchors(
    resident: tuple[Image.Image, ...],
    glance: tuple[Image.Image, ...],
    chestnut: tuple[Image.Image, ...],
    chestnut_return: tuple[Image.Image, ...],
) -> dict[str, tuple[tuple[float, float], ...]]:
    def anchors(panels: tuple[Image.Image, ...]) -> tuple[tuple[float, float], ...]:
        return tuple((panel.width / 2, panel.height - 88) for panel in panels)

    return {
        "resident": anchors(resident),
        "glance": anchors(glance),
        "chestnut": anchors(chestnut),
        "chestnut-return": anchors(chestnut_return),
    }


def _build_synthetic_frames() -> tuple[Image.Image, ...]:
    moon, roof = _moon_and_roof()
    return build_frames(
        _idle_frames(),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(3, 1, size=(900, 400)), 3, 1),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        moon,
        roof,
    )


def test_builder_creates_48_rgba_frames_with_exact_idle_boundaries():
    idle = _idle_frames()
    moon, roof = _moon_and_roof()
    frames = build_frames(
        idle,
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(3, 1, size=(900, 400)), 3, 1),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        moon,
        roof,
    )

    assert len(frames) == 48
    assert all(frame.mode == "RGBA" and frame.size == CELL_SIZE for frame in frames)
    assert all(frame.getbbox() is not None for frame in frames)
    assert frames[0].tobytes() == idle[0].tobytes()
    assert frames[-1].tobytes() == idle[0].tobytes()
    hashes = [sha256(frame.tobytes()).digest() for frame in frames]
    assert all(left != right for left, right in zip(hashes, hashes[1:]))


def test_builder_fills_all_three_rows_and_preserves_the_prefix():
    source = Image.new("RGBA", (ATLAS_WIDTH, 4784), (11, 17, 29, 255))
    prefix_hash = sha256(source.tobytes()).digest()

    atlas = extend_atlas(source, _build_synthetic_frames())

    assert atlas.mode == "RGBA"
    assert atlas.size == (ATLAS_WIDTH, ATLAS_HEIGHT)
    assert sha256(atlas.crop((0, 0, ATLAS_WIDTH, 4784)).tobytes()).digest() == prefix_hash
    for offset in range(48):
        row, column = divmod(23 * 16 + offset, 16)
        cell = atlas.crop(
            (
                column * CELL_SIZE[0],
                row * CELL_SIZE[1],
                (column + 1) * CELL_SIZE[0],
                (row + 1) * CELL_SIZE[1],
            )
        )
        assert cell.getbbox() is not None


def test_persistent_state_builder_uses_one_exact_boundary_for_every_resident_clip():
    moon, roof = _moon_and_roof()
    resident = extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2)
    glance = extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1)
    chestnut = extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2)
    chestnut_return = extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1)
    clips = build_state_clips(
        _idle_frames(),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        resident,
        glance,
        chestnut,
        chestnut_return,
        moon,
        roof,
        seated_source_anchors=_synthetic_seat_anchors(
            resident, glance, chestnut, chestnut_return
        ),
    )

    assert tuple(clips) == CLIP_ORDER
    assert {key: len(value) for key, value in clips.items()} == {
        "moonlitChestnut": 18,
        "rooftopIdle": 9,
        "rooftopMoonGaze": 7,
        "rooftopChestnut": 28,
        "rooftopRest": 5,
        "rooftopBreeze": 7,
        "rooftopGlance": 9,
        "rooftopExit": 18,
    }
    boundary = clips["moonlitChestnut"][-1].tobytes()
    for key in CLIP_ORDER[1:-1]:
        assert clips[key][0].tobytes() == boundary
        assert clips[key][-1].tobytes() == boundary
    assert clips["rooftopExit"][0].tobytes() == boundary


def test_persistent_state_builder_preserves_rows_zero_through_twenty_two():
    moon, roof = _moon_and_roof()
    resident = extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2)
    glance = extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1)
    chestnut = extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2)
    chestnut_return = extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1)
    clips = build_state_clips(
        _idle_frames(),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        resident,
        glance,
        chestnut,
        chestnut_return,
        moon,
        roof,
        seated_source_anchors=_synthetic_seat_anchors(
            resident, glance, chestnut, chestnut_return
        ),
    )
    source = Image.new("RGBA", (ATLAS_WIDTH, 5408), (11, 17, 29, 255))
    prefix = source.crop((0, 0, ATLAS_WIDTH, 4784))

    atlas = extend_state_atlas(source, clips)

    assert atlas.size == (ATLAS_WIDTH, 6240)
    assert sha256(atlas.crop((0, 0, ATLAS_WIDTH, 4784)).tobytes()).digest() == sha256(
        prefix.tobytes()
    ).digest()


def test_persistent_state_builder_keeps_every_canvas_corner_transparent():
    moon, roof = _moon_and_roof()
    resident = extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2)
    glance = extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1)
    chestnut = extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2)
    chestnut_return = extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1)
    clips = build_state_clips(
        _idle_frames(),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        resident,
        glance,
        chestnut,
        chestnut_return,
        moon,
        roof,
        seated_source_anchors=_synthetic_seat_anchors(
            resident, glance, chestnut, chestnut_return
        ),
    )

    corners = ((0, 0), (191, 0), (0, 207), (191, 207))
    for frames in clips.values():
        for frame in frames:
            alpha = frame.getchannel("A")
            assert all(alpha.getpixel(point) == 0 for point in corners)
            assert sum(alpha.histogram()[8:]) <= 24000


def test_every_resident_action_keeps_the_complete_lower_body_pixel_identical():
    moon, roof = _moon_and_roof()
    resident = extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2)
    glance = extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1)
    chestnut = extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2)
    chestnut_return = extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1)
    clips = build_state_clips(
        _idle_frames(),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        resident,
        glance,
        chestnut,
        chestnut_return,
        moon,
        roof,
        seated_source_anchors=_synthetic_seat_anchors(
            resident, glance, chestnut, chestnut_return
        ),
    )

    boundary_lower_body = clips["moonlitChestnut"][-1].crop(
        (0, LOWER_BODY_LOCK_Y, CELL_SIZE[0], CELL_SIZE[1])
    ).tobytes()
    for action_id in CLIP_ORDER[1:-1]:
        for frame in clips[action_id]:
            assert frame.crop(
                (0, LOWER_BODY_LOCK_Y, CELL_SIZE[0], CELL_SIZE[1])
            ).tobytes() == boundary_lower_body


def test_chestnut_flies_from_the_far_left_and_decelerates_at_the_open_hand():
    open_hand = Image.new("RGBA", CELL_SIZE, (0, 0, 0, 0))
    flight = tuple(
        _chestnut_flight_frame(open_hand, index / 9) for index in range(10)
    )

    def golden_centre(frame: Image.Image) -> tuple[float, float]:
        points = []
        for y in range(frame.height):
            for x in range(frame.width):
                red, green, blue, alpha = frame.getpixel((x, y))
                if alpha >= 220 and red >= 180 and 70 <= green <= 210 and blue < 100:
                    points.append((x, y))
        assert points
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    centres = tuple(golden_centre(frame) for frame in flight)
    assert centres[0][0] <= 4
    assert all(left[0] <= right[0] for left, right in zip(centres, centres[1:]))
    assert abs(centres[-1][0] - CHESTNUT_HAND_TARGET[0]) <= 1.5
    assert abs(centres[-1][1] - CHESTNUT_HAND_TARGET[1]) <= 1.5
    early_step = centres[2][0] - centres[1][0]
    late_step = centres[-1][0] - centres[-2][0]
    assert early_step > late_step


def test_seated_panels_lock_the_pelvis_in_both_axes_while_heads_can_move():
    panels = []
    source_anchors = []
    for index, offset in enumerate((-54, -22, 18, 49)):
        panel = Image.new("RGBA", (320, 360), (0, 0, 0, 0))
        draw = ImageDraw.Draw(panel)
        centre = 160 + offset
        head_centre = centre + index * 7
        draw.ellipse(
            (head_centre - 42, 22 + index * 3, head_centre + 42, 112 + index * 3),
            fill=(220, 228, 244, 255),
        )
        draw.polygon(
            ((centre - 36, 102), (centre + 36, 102), (centre + 78, 328), (centre - 64, 328)),
            fill=(35, 70, 130, 255),
        )
        draw.rectangle((centre - 2, 198, centre + 2, 202), fill=(0, 255, 255, 255))
        panels.append(panel)
        source_anchors.append((centre, 200))

    placed = _placed_sequence(
        tuple(panels),
        target_height=184,
        source_anchors=tuple(source_anchors),
    )

    for frame in placed:
        target_x, target_y = SEATED_TARGET_ANCHOR
        crop = frame.crop((target_x - 2, target_y - 2, target_x + 3, target_y + 3))
        cyan_pixels = [
            crop.getpixel((x, y))
            for y in range(crop.height)
            for x in range(crop.width)
            if crop.getpixel((x, y))[1] > 180
            and crop.getpixel((x, y))[2] > 180
            and crop.getpixel((x, y))[0] < 80
        ]
        assert cyan_pixels


def test_prepared_moon_is_large_bright_and_keeps_canvas_corners_clear():
    moon, _ = _moon_and_roof()
    prepared = _prepared_local_moon(moon)
    alpha = prepared.getchannel("A")

    assert alpha.getbbox()[2] - alpha.getbbox()[0] >= 120
    assert alpha.getbbox()[3] - alpha.getbbox()[1] >= 120
    assert sum(alpha.histogram()[17:]) >= 8500
    assert all(
        alpha.getpixel(point) == 0
        for point in ((0, 0), (191, 0), (0, 207), (191, 207))
    )
