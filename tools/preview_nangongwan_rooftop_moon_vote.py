"""Render matched A/B videos for the two moonlit-rooftop compositions."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from tools import build_nangongwan_moonlit_rooftop_state as rooftop
    from tools.preview_nangongwan_moonlit_chestnut import _gradient, _write_mp4
except ModuleNotFoundError:  # Direct ``python tools/<script>.py`` execution.
    import build_nangongwan_moonlit_rooftop_state as rooftop
    from preview_nangongwan_moonlit_chestnut import _gradient, _write_mp4


ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = ROOT / "work" / "moonlit-rooftop-moon-vote"
SEQUENCE = rooftop.CLIP_ORDER


def _build_clips(manifest: dict, moon_variant: str) -> dict[str, tuple[Image.Image, ...]]:
    with Image.open(rooftop.ATLAS_PATH) as atlas:
        atlas_rgba = atlas.convert("RGBA")
        idle_frames = tuple(
            rooftop._atlas_frame(atlas_rgba, manifest, "idle", index)
            for index in range(3)
        )
    with (
        Image.open(rooftop.TRANSITION_PATH) as transition_sheet,
        Image.open(rooftop.RESIDENT_PATH) as resident_sheet,
        Image.open(rooftop.GLANCE_PATH) as glance_sheet,
        Image.open(rooftop.CHESTNUT_PATH) as chestnut_sheet,
        Image.open(rooftop.CHESTNUT_RETURN_PATH) as chestnut_return_sheet,
        Image.open(rooftop.CHESTNUT_LINGER_PATH) as chestnut_linger_sheet,
        Image.open(rooftop.DROWSY_PATH) as drowsy_sheet,
        Image.open(rooftop.HAIR_PATH) as hair_sheet,
        Image.open(rooftop.BRACELET_PATH) as bracelet_sheet,
        Image.open(rooftop.MOON_PATH) as moon_source,
        Image.open(rooftop.ROOF_PATH) as roof_source,
    ):
        chestnut_linger_panels = tuple(
            rooftop._clean_generated_panel(panel)
            for panel in rooftop.extract_grid(chestnut_linger_sheet, 4, 2, inset=4)
        )
        drowsy_panels = tuple(
            rooftop._clean_generated_panel(
                panel,
                clear_regions=((118, 132, 178, 170),) if index == 4 else (),
            )
            for index, panel in enumerate(
                rooftop.extract_grid(drowsy_sheet, 4, 2, inset=4)
            )
        )
        hair_panels = tuple(
            rooftop._clean_generated_panel(panel)
            for panel in rooftop.extract_grid(hair_sheet, 4, 2, inset=4)
        )
        bracelet_panels = tuple(
            rooftop._clean_generated_panel(
                panel,
                clear_regions=((0, 496, panel.width, panel.height),)
                if index in {2, 3}
                else (),
            )
            for index, panel in enumerate(
                rooftop.extract_grid(bracelet_sheet, 4, 2, inset=4)
            )
        )
        return rooftop.build_clips(
            idle_frames,
            rooftop.extract_grid(transition_sheet, 4, 2, inset=4),
            rooftop.extract_grid(resident_sheet, 4, 2, inset=4),
            rooftop.extract_grid(glance_sheet, 4, 1, inset=4),
            rooftop.extract_grid(chestnut_sheet, 4, 2, inset=4),
            rooftop.extract_grid(chestnut_return_sheet, 4, 1, inset=4),
            chestnut_linger_panels,
            drowsy_panels,
            hair_panels,
            bracelet_panels,
            moon_source,
            roof_source,
            moon_variant=moon_variant,
        )


def _desktop_frame(frame: Image.Image) -> Image.Image:
    size = (960, 540)
    canvas = _gradient(size, (11, 24, 46), (36, 62, 91)).convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.ellipse((-180, 20, 560, 760), fill=(33, 116, 214, 54))
    draw.ellipse((420, -280, 1190, 490), fill=(97, 179, 242, 36))
    draw.arc((-120, 70, 740, 780), 195, 342, fill=(100, 192, 255, 65), width=18)

    scaled = frame.resize((432, 468), Image.Resampling.LANCZOS)
    position = ((size[0] - scaled.width) // 2, 21)
    canvas.alpha_composite(scaled, position)

    taskbar_y = 500
    draw.rounded_rectangle(
        (280, taskbar_y, 680, 536), radius=12, fill=(18, 27, 43, 205)
    )
    icon_x = 398
    for index, color in enumerate(
        ((63, 151, 245, 255), (241, 244, 249, 255), (36, 158, 103, 255), (190, 93, 218, 255))
    ):
        left = icon_x + index * 42
        draw.rounded_rectangle(
            (left, taskbar_y + 7, left + 24, taskbar_y + 31),
            radius=5,
            fill=color,
        )
    return canvas.convert("RGB")


def _flatten(
    clips: dict[str, tuple[Image.Image, ...]], manifest: dict
) -> tuple[tuple[Image.Image, ...], list[int]]:
    frames: list[Image.Image] = []
    durations: list[int] = []
    for action_id in SEQUENCE:
        action_frames = clips[action_id]
        action_durations = manifest["actions"][action_id]["frameDurations"]
        if len(action_frames) != len(action_durations):
            raise AssertionError(f"duration mismatch for {action_id}")
        frames.extend(action_frames)
        durations.extend(action_durations)
    return tuple(frames), durations


def main() -> None:
    manifest = json.loads(rooftop.MANIFEST_PATH.read_text(encoding="utf-8"))
    current = _build_clips(manifest, "current")
    anime = _build_clips(manifest, "anime")
    if {key: len(value) for key, value in current.items()} != {
        key: len(value) for key, value in anime.items()
    }:
        raise AssertionError("moon variants do not have matching action frames")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    current_frames, durations = _flatten(current, manifest)
    anime_frames, anime_durations = _flatten(anime, manifest)
    if durations != anime_durations:
        raise AssertionError("moon variants do not have matching timing")

    current_preview = tuple(_desktop_frame(frame) for frame in current_frames)
    anime_preview = tuple(_desktop_frame(frame) for frame in anime_frames)
    current_path = WORK_DIR / "A-current-moon.mp4"
    anime_path = WORK_DIR / "B-anime-giant-moon.mp4"
    _write_mp4(current_preview, durations, current_path)
    _write_mp4(anime_preview, durations, anime_path)

    still_a = _desktop_frame(current["rooftopIdle"][0])
    still_b = _desktop_frame(anime["rooftopIdle"][0])
    comparison = Image.new("RGB", (1920, 540), (0, 0, 0))
    comparison.paste(still_a, (0, 0))
    comparison.paste(still_b, (960, 0))
    comparison_path = WORK_DIR / "A-B-moon-comparison.png"
    comparison.save(comparison_path)

    report = {
        "A": str(current_path),
        "B": str(anime_path),
        "comparison": str(comparison_path),
        "sequence": list(SEQUENCE),
        "frameCount": len(current_frames),
        "durationMs": sum(durations),
        "note": "Both videos use identical actions, timing, scale, desktop background, and placement; only the moon composition differs.",
    }
    report_path = WORK_DIR / "moon-vote-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(current_path)
    print(anime_path)
    print(comparison_path)
    print(report_path)


if __name__ == "__main__":
    main()
