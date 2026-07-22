"""Render a deterministic all-subaction preview of the persistent rooftop state."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

try:
    from tools.preview_nangongwan_moonlit_chestnut import (
        _desktop_preview,
        _runtime_frames,
        _write_gif,
        _write_mp4,
    )
except ModuleNotFoundError:  # Direct ``python tools/<script>.py`` execution.
    from preview_nangongwan_moonlit_chestnut import (
        _desktop_preview,
        _runtime_frames,
        _write_gif,
        _write_mp4,
    )


ROOT = Path(__file__).resolve().parents[1]
PET_ROOT = ROOT / "src" / "shiyi_desktop_pet" / "resources" / "pets" / "nangongwan"
ATLAS_PATH = PET_ROOT / "spritesheet.webp"
MANIFEST_PATH = PET_ROOT / "pet.json"
WORK_DIR = ROOT / "work" / "moonlit-rooftop-state"
SEQUENCE = (
    "moonlitChestnut",
    "rooftopIdle",
    "rooftopMoonGaze",
    "rooftopChestnut",
    "rooftopRest",
    "rooftopBreeze",
    "rooftopGlance",
    "rooftopExit",
)


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    frames: list[Image.Image] = []
    durations: list[int] = []
    boundaries: dict[str, tuple[int, int]] = {}
    with Image.open(ATLAS_PATH) as atlas:
        atlas_rgba = atlas.convert("RGBA")
        for action_id in SEQUENCE:
            action = manifest["actions"][action_id]
            start = len(frames)
            frames.extend(_runtime_frames(atlas_rgba, action))
            durations.extend(action["frameDurations"])
            boundaries[action_id] = (start, len(frames))

    enter_boundary = frames[boundaries["moonlitChestnut"][1] - 1].tobytes()
    for action_id in SEQUENCE[1:-1]:
        start, end = boundaries[action_id]
        if frames[start].tobytes() != enter_boundary or frames[end - 1].tobytes() != enter_boundary:
            raise AssertionError(f"{action_id} does not share the resident boundary")
    exit_start, _ = boundaries["rooftopExit"]
    if frames[exit_start].tobytes() != enter_boundary:
        raise AssertionError("rooftopExit does not begin on the resident boundary")

    preview = tuple(_desktop_preview(frame) for frame in frames)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    gif_path = WORK_DIR / "moonlit-rooftop-transparent-v8.gif"
    mp4_path = WORK_DIR / "moonlit-rooftop-transparent-v8.mp4"
    report_path = WORK_DIR / "preview-sequence-v8.json"
    _write_gif(preview, durations, gif_path)
    _write_mp4(preview, durations, mp4_path)
    report_path.write_text(
        json.dumps(
            {
                "note": "Transparent v8 preview: individually redrawn seated poses, root-and-footline geometry normalization without pasted body pixels, anime-derived violet chestnut flight, fixed moon and eave, and every resident action once.",
                "sequence": list(SEQUENCE),
                "frameCount": len(frames),
                "durationMs": sum(durations),
                "clipFrameRanges": boundaries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(gif_path)
    print(mp4_path)
    print(report_path)


if __name__ == "__main__":
    main()
