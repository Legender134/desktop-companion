from hashlib import sha256

from PIL import Image, ImageDraw

from tools.build_nangongwan_moonlit_chestnut import (
    ATLAS_HEIGHT,
    ATLAS_WIDTH,
    CELL_SIZE,
    build_frames,
    extend_atlas,
    extract_keyframes,
)


def _synthetic_storyboard() -> Image.Image:
    storyboard = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(storyboard)
    for index in range(8):
        row, column = divmod(index, 4)
        left = column * 100
        top = row * 100
        color = (40 + index * 20, 90 + index * 10, 180 - index * 12, 255)
        draw.ellipse((left + 18, top + 12, left + 82, top + 92), fill=color)
        draw.rectangle(
            (left + 10 + index, top + 70, left + 45 + index, top + 94),
            fill=(15, 25, 45, 255),
        )
    return storyboard


def test_builder_creates_36_distinct_rgba_frames_from_eight_keyframes():
    keyframes = extract_keyframes(_synthetic_storyboard())

    frames = build_frames(keyframes)

    assert len(keyframes) == 8
    assert len(frames) == 36
    assert all(frame.mode == "RGBA" and frame.size == CELL_SIZE for frame in frames)
    assert all(frame.getbbox() is not None for frame in frames)
    hashes = [sha256(frame.tobytes()).digest() for frame in frames]
    assert len(set(hashes)) == 36
    assert all(left != right for left, right in zip(hashes, hashes[1:]))


def test_builder_appends_frames_and_leaves_unused_cells_transparent():
    source = Image.new("RGBA", (ATLAS_WIDTH, 4784), (0, 0, 0, 0))
    frames = build_frames(extract_keyframes(_synthetic_storyboard()))

    atlas = extend_atlas(source, frames)

    assert atlas.mode == "RGBA"
    assert atlas.size == (ATLAS_WIDTH, ATLAS_HEIGHT)
    for offset in range(36):
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
    for column in range(4, 16):
        cell = atlas.crop(
            (
                column * CELL_SIZE[0],
                25 * CELL_SIZE[1],
                (column + 1) * CELL_SIZE[0],
                26 * CELL_SIZE[1],
            )
        )
        assert cell.getbbox() is None
