"""Plan the fixed sequence for the simple Nangong Wan action showcase."""

from __future__ import annotations

import json
from pathlib import Path

from tools.nangongwan_action_showcase_v2 import (
    BACKGROUND_SHA256,
    ShowcasePlan,
    ShowcaseSegment,
    ShowcaseSource,
    _verified_background_pixels,
)
from tools.nangongwan_rooftop_making_of import ActionSource


_FORBIDDEN_SOURCE_MARKERS = ("anime-reference", "do-not-publish")


def _history(root: Path) -> Path:
    return root / "work" / "nangongwan-moonlit-rooftop-history"


def _validate_public_path(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"showcase source is missing: {path}")
    resolved = str(path.resolve()).lower()
    if any(marker in resolved for marker in _FORBIDDEN_SOURCE_MARKERS):
        raise ValueError(f"showcase source is not public: {path}")


def _source(
    atlas: Path,
    manifest: Path,
    action_id: str,
    *,
    manifest_kind: str = "pet",
    atlas_start_frame: int | None = None,
) -> ActionSource:
    return ActionSource(
        atlas=atlas,
        manifest=manifest,
        action_id=action_id,
        manifest_kind=manifest_kind,  # type: ignore[arg-type]
        atlas_start_frame=atlas_start_frame,
    )


def _action_metadata(source: ActionSource) -> tuple[int, int]:
    for path in (source.atlas, source.manifest):
        _validate_public_path(path)

    document = json.loads(source.manifest.read_text(encoding="utf-8"))
    if source.manifest_kind == "action":
        action = document
        if action.get("id") != source.action_id:
            raise ValueError(f"action manifest does not contain {source.action_id}")
        if source.atlas_start_frame is None:
            raise ValueError("standalone action source requires an atlas start frame")
    else:
        actions = document.get("actions")
        if not isinstance(actions, dict) or source.action_id not in actions:
            raise ValueError(f"pet manifest does not contain {source.action_id}")
        action = actions[source.action_id]

    if not isinstance(action, dict) or not isinstance(action.get("frameCount"), int):
        raise ValueError(f"invalid action metadata for {source.action_id}")
    frame_count = action["frameCount"]
    durations = action.get("frameDurations")
    if durations is None:
        durations = [action.get("frameMs")] * frame_count
    if (
        frame_count <= 0
        or not isinstance(durations, list)
        or len(durations) != frame_count
        or any(not isinstance(duration, int) or duration <= 0 for duration in durations)
    ):
        raise ValueError(f"invalid frame durations for {source.action_id}")
    return frame_count, sum(durations)


def _validate_source(source: ShowcaseSource) -> tuple[int, int]:
    if not source.actions:
        raise ValueError("showcase source must contain actions")
    metadata = tuple(_action_metadata(action) for action in source.actions)
    return sum(frame_count for frame_count, _ in metadata), sum(
        duration_ms for _, duration_ms in metadata
    )


def _pet_source(history: Path, variant: str, action_id: str) -> ActionSource:
    directory = history / "04-moon-background-variants" / variant
    return _source(directory / "spritesheet.webp", directory / "pet.json", action_id)


def build_showcase_plan(root: Path, background_source: Path) -> ShowcasePlan:
    """Build and validate the approved fifteen-segment action sequence."""

    background_hash, _ = _verified_background_pixels(background_source)
    if background_hash != BACKGROUND_SHA256:
        raise ValueError("background SHA-256 does not match the approved source")

    history = _history(root)
    small = "01-small-moon-current"
    blink_action = _pet_source(history, small, "idle")
    standing_directory = history / "06-standing-chestnut-easter-egg"
    standing = _source(
        standing_directory / "standing-chestnut-10frames.webp",
        standing_directory / "action.json",
        "tasteCake",
        manifest_kind="action",
        atlas_start_frame=0,
    )
    cinematic_directory = history / "01-cinematic-36f-v2.4.1"
    cinematic = _source(
        cinematic_directory / "spritesheet.webp",
        cinematic_directory / "pet.json",
        "moonlitChestnut",
    )
    anchored_directory = history / "02-anchored-48f-v1" / "complete-archive"
    anchored = _source(
        anchored_directory / "spritesheet.webp",
        anchored_directory / "pet.json",
        "moonlitChestnut",
    )
    preview_path = (
        history
        / "03-persistent-rooftop-revisions"
        / "render-history-v2-v9"
        / "preview-sequence-v9.json"
    )
    _validate_public_path(preview_path)
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    sequence = preview.get("sequence")
    if not isinstance(sequence, list) or not all(isinstance(action_id, str) for action_id in sequence):
        raise ValueError("V9 preview sequence is invalid")
    v9 = ShowcaseSource(
        "sequence", tuple(_pet_source(history, small, action_id) for action_id in sequence)
    )
    moon_184 = _pet_source(history, "02-full-circle-184", "rooftopChestnut")
    moon_232 = _pet_source(history, "03-cropped-disc-232", "rooftopChestnut")
    moon_full = _pet_source(history, "04-full-frame-moon-surface", "rooftopChestnut")

    blink = ShowcaseSource("blink", (blink_action,))
    action_sources = {
        "standing-chestnut": ShowcaseSource("action", (standing,)),
        "cinematic-36": ShowcaseSource("action", (cinematic,)),
        "anchored-48": ShowcaseSource("action", (anchored,)),
        "v9-small-moon": v9,
        "moon-184": ShowcaseSource("action", (moon_184,)),
        "moon-232": ShowcaseSource("action", (moon_232,)),
        "moon-full": ShowcaseSource("action", (moon_full,)),
    }
    _validate_source(blink)
    v9_frames, v9_duration = _validate_source(v9)
    if (
        preview.get("frameCount") != 166
        or preview.get("durationMs") != 30_680
        or (v9_frames, v9_duration) != (166, 30_680)
    ):
        raise ValueError("V9 source must contain 166 frames and 30680 ms")
    for source_name in ("moon-184", "moon-232", "moon-full"):
        if _validate_source(action_sources[source_name]) != (44, 8_990):
            raise ValueError("moon source must contain 44 frames and 8990 ms")
    for source_name in ("standing-chestnut", "cinematic-36", "anchored-48"):
        _validate_source(action_sources[source_name])

    segments = (
        ShowcaseSegment("blink-00", blink, 15),
        ShowcaseSegment("standing-chestnut", action_sources["standing-chestnut"], 62),
        ShowcaseSegment("blink-01", blink, 15),
        ShowcaseSegment("cinematic-36", action_sources["cinematic-36"], 273),
        ShowcaseSegment("blink-02", blink, 15),
        ShowcaseSegment("anchored-48", action_sources["anchored-48"], 288),
        ShowcaseSegment("blink-03", blink, 15),
        ShowcaseSegment("v9-small-moon", v9, 920),
        ShowcaseSegment("blink-04", blink, 15),
        ShowcaseSegment("moon-184", action_sources["moon-184"], 270),
        ShowcaseSegment("blink-05", blink, 15),
        ShowcaseSegment("moon-232", action_sources["moon-232"], 270),
        ShowcaseSegment("blink-06", blink, 15),
        ShowcaseSegment("moon-full", action_sources["moon-full"], 270),
        ShowcaseSegment("blink-07", blink, 15),
    )
    return ShowcasePlan(background_source, segments)
