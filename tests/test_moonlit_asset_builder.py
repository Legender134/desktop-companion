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
    CLIP_ORDER,
    _head_anchor_x,
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
    clips = build_state_clips(
        _idle_frames(),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        resident,
        extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1),
        moon,
        roof,
    )

    assert tuple(clips) == CLIP_ORDER
    assert {key: len(value) for key, value in clips.items()} == {
        "moonlitChestnut": 18,
        "rooftopIdle": 9,
        "rooftopMoonGaze": 7,
        "rooftopChestnut": 14,
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
    clips = build_state_clips(
        _idle_frames(),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1),
        moon,
        roof,
    )
    source = Image.new("RGBA", (ATLAS_WIDTH, 5408), (11, 17, 29, 255))
    prefix = source.crop((0, 0, ATLAS_WIDTH, 4784))

    atlas = extend_state_atlas(source, clips)

    assert atlas.size == (ATLAS_WIDTH, 6032)
    assert sha256(atlas.crop((0, 0, ATLAS_WIDTH, 4784)).tobytes()).digest() == sha256(
        prefix.tobytes()
    ).digest()


def test_persistent_state_builder_keeps_every_canvas_corner_transparent():
    moon, roof = _moon_and_roof()
    clips = build_state_clips(
        _idle_frames(),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1),
        extract_grid(_panel_sheet(4, 2, size=(800, 800)), 4, 2),
        extract_grid(_panel_sheet(4, 1, size=(800, 400)), 4, 1),
        moon,
        roof,
    )

    corners = ((0, 0), (191, 0), (0, 207), (191, 207))
    for frames in clips.values():
        for frame in frames:
            alpha = frame.getchannel("A")
            assert all(alpha.getpixel(point) == 0 for point in corners)
            assert sum(alpha.histogram()[8:]) <= 24000


def test_seated_panels_lock_the_head_to_one_horizontal_anchor():
    panels = []
    for offset in (-54, -22, 18, 49):
        panel = Image.new("RGBA", (320, 360), (0, 0, 0, 0))
        draw = ImageDraw.Draw(panel)
        centre = 160 + offset
        draw.ellipse((centre - 42, 22, centre + 42, 112), fill=(220, 228, 244, 255))
        draw.polygon(
            ((centre - 36, 102), (centre + 36, 102), (centre + 78, 328), (centre - 64, 328)),
            fill=(35, 70, 130, 255),
        )
        panels.append(panel)

    placed = _placed_sequence(tuple(panels), target_height=184)
    anchors = tuple(_head_anchor_x(frame) for frame in placed)

    assert max(anchors) - min(anchors) <= 1.5
    assert all(abs(anchor - 96) <= 1 for anchor in anchors)


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
