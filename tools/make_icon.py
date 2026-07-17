"""Build the Windows application icon from the approved idle sprite."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
ATLAS_PATH = (
    REPO_ROOT
    / "src"
    / "shiyi_desktop_pet"
    / "resources"
    / "pets"
    / "ziling"
    / "spritesheet.webp"
)
ICON_PATH = REPO_ROOT / "src" / "shiyi_desktop_pet" / "resources" / "app.ico"
IDLE_CELL = (0, 0, 192, 208)
ICON_SIZES = (16, 32, 48, 256)
MASTER_SIZE = max(ICON_SIZES)
PADDING_FRACTION = 0.08


def build_icon() -> None:
    """Crop, alpha-trim, and center idle frame 0 in a padded square ICO."""
    with Image.open(ATLAS_PATH) as atlas:
        idle_frame = atlas.convert("RGBA").crop(IDLE_CELL)

    alpha_bounds = idle_frame.getchannel("A").getbbox()
    if alpha_bounds is None:
        raise ValueError("approved idle sprite has no visible pixels")

    trimmed = idle_frame.crop(alpha_bounds)
    content_fraction = 1.0 - (2.0 * PADDING_FRACTION)
    square_size = math.ceil(max(trimmed.size) / content_fraction)
    canvas = Image.new("RGBA", (square_size, square_size), (0, 0, 0, 0))
    offset = (
        (square_size - trimmed.width) // 2,
        (square_size - trimmed.height) // 2,
    )
    canvas.alpha_composite(trimmed, offset)
    master = canvas.resize(
        (MASTER_SIZE, MASTER_SIZE),
        resample=Image.Resampling.LANCZOS,
    )

    ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    master.save(ICON_PATH, format="ICO", sizes=[(size, size) for size in ICON_SIZES])


if __name__ == "__main__":
    build_icon()
