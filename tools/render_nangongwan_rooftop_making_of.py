import json
from pathlib import Path

from tools.nangongwan_rooftop_making_of import (
    ActionSource,
    ChapterSpec,
    ShotSpec,
    VideoPlan,
)


CHAPTER_DURATIONS = (18000, 40000, 40000, 40000, 87000, 55000)


def build_video_plan(root: Path) -> VideoPlan:
    HISTORY = root / "work" / "nangongwan-moonlit-rooftop-history"
    OUTPUT = root / "work" / "nangongwan-rooftop-making-of-video"
    del OUTPUT

    action_sources = {
        "standing": ActionSource(
            atlas=HISTORY
            / "06-standing-chestnut-easter-egg"
            / "standing-chestnut-10frames.webp",
            manifest=HISTORY / "06-standing-chestnut-easter-egg" / "action.json",
            action_id="tasteCake",
            manifest_kind="action",
            atlas_start_frame=0,
        ),
        "cinematic": ActionSource(
            atlas=HISTORY / "01-cinematic-36f-v2.4.1" / "spritesheet.webp",
            manifest=HISTORY / "01-cinematic-36f-v2.4.1" / "pet.json",
            action_id="moonlitChestnut",
        ),
        "anchored": ActionSource(
            atlas=HISTORY
            / "02-anchored-48f-v1"
            / "complete-archive"
            / "spritesheet.webp",
            manifest=HISTORY
            / "02-anchored-48f-v1"
            / "complete-archive"
            / "pet.json",
            action_id="moonlitChestnut",
        ),
        "small": ActionSource(
            atlas=HISTORY
            / "04-moon-background-variants"
            / "01-small-moon-current"
            / "spritesheet.webp",
            manifest=HISTORY
            / "04-moon-background-variants"
            / "01-small-moon-current"
            / "pet.json",
            action_id="rooftopChestnut",
        ),
        "moon_184": ActionSource(
            atlas=HISTORY
            / "04-moon-background-variants"
            / "02-full-circle-184"
            / "spritesheet.webp",
            manifest=HISTORY
            / "04-moon-background-variants"
            / "02-full-circle-184"
            / "pet.json",
            action_id="rooftopChestnut",
        ),
        "moon_232": ActionSource(
            atlas=HISTORY
            / "04-moon-background-variants"
            / "03-cropped-disc-232"
            / "spritesheet.webp",
            manifest=HISTORY
            / "04-moon-background-variants"
            / "03-cropped-disc-232"
            / "pet.json",
            action_id="rooftopChestnut",
        ),
        "moon_full": ActionSource(
            atlas=HISTORY
            / "04-moon-background-variants"
            / "04-full-frame-moon-surface"
            / "spritesheet.webp",
            manifest=HISTORY
            / "04-moon-background-variants"
            / "04-full-frame-moon-surface"
            / "pet.json",
            action_id="rooftopChestnut",
        ),
    }
    render_history = HISTORY / "03-persistent-rooftop-revisions" / "render-history-v2-v9"
    video_sources = {
        "persistent_v1": render_history / "moonlit-rooftop-all-actions.mp4",
        "v9_all_actions": render_history / "moonlit-rooftop-transparent-v9.mp4",
    }
    v9_labels = json.loads(
        (render_history / "preview-sequence-v9.json").read_text(encoding="utf-8")
    )["sequence"]

    chapter_specs = (
        ("standing_chestnut", "Standing chestnut", action_sources["standing"], ""),
        ("cinematic_36", "Cinematic 36 frames", action_sources["cinematic"], ""),
        ("anchored_48", "Anchored 48 frames", action_sources["anchored"], ""),
        ("persistent_v1", "Persistent rooftop v1", video_sources["persistent_v1"], ""),
        (
            "v9_small_moon",
            "V9 small moon",
            video_sources["v9_all_actions"],
            ", ".join(v9_labels),
        ),
        ("moon_variants", "Moon variants", action_sources["moon_full"], ""),
    )
    return VideoPlan(
        chapters=tuple(
            ChapterSpec(
                id=chapter_id,
                title=title,
                duration_ms=duration_ms,
                shots=(
                    ShotSpec(
                        id=f"{chapter_id}_placeholder",
                        kind="card",
                        duration_ms=duration_ms,
                        source=source,
                        title=title,
                        caption=caption,
                    ),
                ),
            )
            for (chapter_id, title, source, caption), duration_ms in zip(
                chapter_specs, CHAPTER_DURATIONS, strict=True
            )
        ),
        action_sources=action_sources,
    )
