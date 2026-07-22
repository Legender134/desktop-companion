"""Plan the fixed sequence for the simple Nangong Wan action showcase."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from PIL import Image


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.nangongwan_action_showcase_v2 import (
    BACKGROUND_SHA256,
    FPS,
    FRAME_SIZE,
    SPRITE_ORIGIN,
    SPRITE_SIZE,
    ShowcasePlan,
    ShowcaseSegment,
    ShowcaseSource,
    _verified_background_pixels,
    add_silent_aac,
    build_segment_frames,
    concat_clips,
    copy_verified_background,
    extract_review_frames,
    probe_media,
    validate_showcase,
    write_silent_video,
)
from tools.nangongwan_rooftop_making_of import ActionSource


_FORBIDDEN_SOURCE_MARKERS = ("anime-reference", "do-not-publish")
_DEFAULT_BACKGROUND = Path(
    r"C:\Users\23644\AppData\Local\Temp\codex-clipboard-fa2f4101-2de0-4c4a-a1c9-01fc1c2a4412.png"
)
_OUTPUT_DIRECTORY = Path("work") / "nangongwan-action-showcase-v2"
_MASTER_NAME = "nangongwan-action-showcase-v2-1600x900.mp4"


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


def _action_metadata(source: ActionSource) -> tuple[int, tuple[int, ...]]:
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
    return frame_count, tuple(durations)


def _source_metadata(source: ShowcaseSource) -> tuple[int, tuple[int, ...]]:
    if not source.actions:
        raise ValueError("showcase source must contain actions")
    metadata = tuple(_action_metadata(action) for action in source.actions)
    return sum(frame_count for frame_count, _ in metadata), tuple(
        duration_ms
        for _, action_durations in metadata
        for duration_ms in action_durations
    )


def _validate_source(source: ShowcaseSource) -> tuple[int, int]:
    frame_count, durations = _source_metadata(source)
    return frame_count, sum(durations)


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
    moon_metadata = tuple(
        _source_metadata(action_sources[source_name])
        for source_name in ("moon-184", "moon-232", "moon-full")
    )
    for frame_count, durations in moon_metadata:
        if (frame_count, sum(durations)) != (44, 8_990):
            raise ValueError("moon source must contain 44 frames and 8990 ms")
    if any(durations != moon_metadata[0][1] for _, durations in moon_metadata[1:]):
        raise ValueError("moon sources must have identical per-frame durations")
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


def _timeline_document(plan: ShowcasePlan, background_hash: str) -> dict[str, Any]:
    """Describe the exact frame-exclusive segment boundaries without display text."""

    start_frame = 0
    entries: list[dict[str, object]] = []
    for segment in plan.segments:
        end_frame = start_frame + segment.output_frames
        entries.append(
            {
                "id": segment.id,
                "sourceActionIds": [action.action_id for action in segment.source.actions],
                "startFrame": start_frame,
                "endFrame": end_frame,
                "outputFrames": segment.output_frames,
                "sourceDurationMs": _validate_source(segment.source)[1],
            }
        )
        start_frame = end_frame
    if start_frame != plan.total_frames:
        raise ValueError("timeline boundaries do not match the showcase plan")
    return {
        "schemaVersion": 1,
        "backgroundSha256": background_hash,
        "frameSize": list(FRAME_SIZE),
        "spriteRectangle": {
            "x": SPRITE_ORIGIN[0],
            "y": SPRITE_ORIGIN[1],
            "width": SPRITE_SIZE[0],
            "height": SPRITE_SIZE[1],
        },
        "totalFrames": plan.total_frames,
        "segments": entries,
    }


def _write_timeline(plan: ShowcasePlan, background_hash: str, output: Path) -> None:
    document = _timeline_document(plan, background_hash)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def build_showcase(root: Path, background_source: Path) -> Path:
    """Build all fifteen silent clips, their timeline, and the silent-AAC master."""

    output = root / _OUTPUT_DIRECTORY
    clips_directory = output / "clips"
    clips_directory.mkdir(parents=True, exist_ok=True)
    background_copy = output / "background.png"
    background_hash = copy_verified_background(background_source, background_copy)
    plan = build_showcase_plan(root, background_copy)
    if len(plan.segments) != 15 or plan.total_frames != 2473:
        raise ValueError("showcase build requires the approved 15 segments and 2473 frames")

    with Image.open(background_copy) as source:
        background = source.copy()
    clip_paths: list[Path] = []
    for index, segment in enumerate(plan.segments, start=1):
        clip = clips_directory / f"{index:02d}-{segment.id}.mp4"
        write_silent_video(build_segment_frames(segment, background), clip)
        clip_paths.append(clip)

    _write_timeline(plan, background_hash, output / "timeline.json")
    video_only = output / "nangongwan-action-showcase-v2-video-only.mp4"
    master = output / _MASTER_NAME
    concat_clips(tuple(clip_paths), video_only)
    completed = False
    try:
        add_silent_aac(video_only, master, expected_frames=plan.total_frames)
        completed = True
    finally:
        if completed:
            video_only.unlink(missing_ok=True)
    return master


def _validate_existing(root: Path, background_source: Path) -> Path:
    """Check Task 3 file/timeline/media invariants without rebuilding artifacts."""

    output = root / _OUTPUT_DIRECTORY
    background_copy = output / "background.png"
    if not background_copy.is_file():
        raise ValueError(f"built background is missing: {background_copy}")
    background_hash, _ = _verified_background_pixels(background_copy)
    if background_hash != BACKGROUND_SHA256:
        raise ValueError("built background does not match the approved SHA-256")
    source_hash, _ = _verified_background_pixels(background_source)
    if source_hash != background_hash:
        raise ValueError("current approved background does not match the built copy")
    plan = build_showcase_plan(root, background_copy)
    timeline_path = output / "timeline.json"
    try:
        actual_timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"timeline is missing or invalid: {timeline_path}") from error
    if actual_timeline != _timeline_document(plan, background_hash):
        raise ValueError("timeline does not match the approved showcase plan")
    expected_clips = tuple(
        output / "clips" / f"{index:02d}-{segment.id}.mp4"
        for index, segment in enumerate(plan.segments, start=1)
    )
    actual_clips = {
        path.resolve()
        for path in (output / "clips").rglob("*")
        if path.is_file() and path.suffix.lower() == ".mp4"
    }
    if actual_clips != {clip.resolve() for clip in expected_clips}:
        raise ValueError("showcase clip filenames do not match the exact expected set")
    subtitle_sidecars = tuple(
        path
        for path in output.rglob("*")
        if path.is_file() and path.suffix.lower() in {".ass", ".srt", ".vtt"}
    )
    if subtitle_sidecars:
        raise ValueError("showcase output must not contain subtitle sidecars")
    for clip, segment in zip(expected_clips, plan.segments, strict=True):
        clip_probe = probe_media(clip, count_frames=True)
        if not (
            clip_probe.video.width == FRAME_SIZE[0]
            and clip_probe.video.height == FRAME_SIZE[1]
            and clip_probe.video.codec == "h264"
            and clip_probe.video.profile == "High"
            and clip_probe.video.pixel_format == "yuv420p"
            and clip_probe.video.sample_aspect_ratio == "1:1"
            and clip_probe.video.frame_rate == FPS
            and clip_probe.video.nb_read_frames == segment.output_frames
            and clip_probe.audio is None
            and clip_probe.subtitle_streams == 0
            and clip_probe.data_streams == 0
        ):
            raise ValueError(f"showcase clip does not satisfy its media contract: {clip}")
    master = output / _MASTER_NAME
    probe = probe_media(master, count_frames=True)
    if not (
        probe.video.width == FRAME_SIZE[0]
        and probe.video.height == FRAME_SIZE[1]
        and probe.video.codec == "h264"
        and probe.video.profile == "High"
        and probe.video.pixel_format == "yuv420p"
        and probe.video.sample_aspect_ratio == "1:1"
        and probe.video.frame_rate == FPS
        and probe.video.nb_read_frames == plan.total_frames
        and probe.audio is not None
        and probe.audio.codec == "aac"
        and probe.audio.sample_rate == 48_000
        and probe.audio.channels == 2
        and probe.subtitle_streams == 0
        and probe.data_streams == 0
    ):
        raise ValueError("existing master does not satisfy the Task 3 media contract")
    return master


def _validate_final_showcase(root: Path, background_source: Path) -> tuple[Path, Path]:
    """Run every Task 4 gate and write local review artifacts on success."""

    master = _validate_existing(root, background_source)
    output = root / _OUTPUT_DIRECTORY
    timeline = output / "timeline.json"
    plan = build_showcase_plan(root, output / "background.png")
    report = validate_showcase(master, plan, timeline)
    report_path = output / "validation-report.json"
    if report["allPassed"] is True:
        review = output / "review"
        frames = extract_review_frames(master, timeline, review)
        contact_sheet = review / "contact-sheet.jpg"
        report["review"] = {
            "frames": [str(path.resolve()) for path in frames],
            "contactSheet": str(contact_sheet.resolve()),
            "frameCount": len(frames),
            "contactSheetSha256": sha256(contact_sheet.read_bytes()).hexdigest(),
        }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["allPassed"] is not True:
        raise ValueError(f"final V2 validation failed; see {report_path}")
    return master, report_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", type=Path, default=_DEFAULT_BACKGROUND)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build-all", action="store_true")
    mode.add_argument("--validate-only", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.build_all:
        master = build_showcase(root, args.background)
        print(f"Built {master}")
    else:
        master, report = _validate_final_showcase(root, args.background)
        print(f"Validated {master}; allPassed=true; report={report}")


if __name__ == "__main__":
    main()
