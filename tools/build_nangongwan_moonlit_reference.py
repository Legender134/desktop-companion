"""Build the fixed visual reference board for the moonlit-chestnut redesign."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
PET_ROOT = ROOT / "src/shiyi_desktop_pet/resources/pets/nangongwan"
ATLAS_PATH = PET_ROOT / "spritesheet-moonlit-chestnut-v2.4.1-legacy.webp"
MANIFEST_PATH = PET_ROOT / "pet.json"
OUTPUT_PATH = ROOT / "tools/assets/nangongwan-moonlit-chestnut-redesign-reference.png"
IDLE_OUTPUT_PATH = ROOT / "tools/assets/nangongwan-moonlit-chestnut-idle-reference.png"
AUDIT_PATH = ROOT / "work/moonlit-chestnut-redesign/reference-audit.png"

CELL = (192, 208)
ATLAS_COLUMNS = 16
BOARD_CELL = (256, 276)
SELECTIONS = (
    ("idle", 0, "idle front 1"),
    ("idle", 3, "idle front 2"),
    ("idle", 6, "idle front 3"),
    ("gaze", 0, "head scale"),
    ("foldArms", 0, "blue-silver dress"),
    ("foldArms", 4, "arm proportion"),
    ("foldArms", 7, "front silhouette"),
    ("listen", 4, "side turn"),
    ("tasteCake", 0, "cake pose 1"),
    ("tasteCake", 3, "cake pose 2"),
    ("tasteCake", 6, "cake pose 3"),
    ("tasteCake", 9, "cake pose 4"),
    ("moonHalo", 1, "moonlight edge"),
    ("moonHalo", 5, "moonlight palette"),
    ("sealLight", 4, "right-hand glow"),
    ("reincarnationLight", 3, "purple light"),
)


def _frame(atlas: Image.Image, manifest: dict, action_id: str, offset: int) -> Image.Image:
    action = manifest["actions"][action_id]
    start = action["row"] * ATLAS_COLUMNS + action.get("startColumn", 0)
    row, column = divmod(start + offset, ATLAS_COLUMNS)
    return atlas.crop(
        (
            column * CELL[0],
            row * CELL[1],
            (column + 1) * CELL[0],
            (row + 1) * CELL[1],
        )
    ).convert("RGBA")


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    with Image.open(ATLAS_PATH) as source:
        atlas = source.convert("RGBA")
        board = Image.new(
            "RGBA", (BOARD_CELL[0] * 4, BOARD_CELL[1] * 4), (24, 255, 54, 255)
        )
        draw = ImageDraw.Draw(board)
        for index, (action_id, offset, label) in enumerate(SELECTIONS):
            row, column = divmod(index, 4)
            frame = _frame(atlas, manifest, action_id, offset)
            x = column * BOARD_CELL[0] + (BOARD_CELL[0] - CELL[0]) // 2
            y = row * BOARD_CELL[1] + 16
            board.alpha_composite(frame, (x, y))
            baseline = y + 190
            draw.line((column * BOARD_CELL[0] + 12, baseline, (column + 1) * BOARD_CELL[0] - 12, baseline), fill=(255, 50, 190, 255), width=2)
            draw.text((column * BOARD_CELL[0] + 12, row * BOARD_CELL[1] + 246), label, fill=(0, 0, 0, 255))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    board.convert("RGB").save(OUTPUT_PATH, "PNG")
    with Image.open(ATLAS_PATH) as source:
        idle = _frame(source.convert("RGBA"), manifest, "idle", 0)
    idle_large = Image.new("RGBA", (1024, 1024), (24, 255, 54, 255))
    scaled = idle.resize((768, 832), Image.Resampling.LANCZOS)
    idle_large.alpha_composite(scaled, ((1024 - 768) // 2, 120))
    idle_large.convert("RGB").save(IDLE_OUTPUT_PATH, "PNG")
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    board.convert("RGB").save(AUDIT_PATH, "PNG")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
