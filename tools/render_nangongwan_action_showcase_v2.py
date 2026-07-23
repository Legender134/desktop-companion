"""Plan the fixed sequence for the simple Nangong Wan action showcase."""

from __future__ import annotations

import argparse
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
from uuid import uuid4

from PIL import Image


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.nangongwan_action_showcase_v2 import (
    BACKGROUND_SHA256,
    FPS,
    FRAME_SIZE,
    RENDER_SCALE,
    RENDERED_SPRITE_ORIGIN,
    RENDERED_SPRITE_SIZE,
    SOURCE_SPRITE_SIZE,
    SourceAsset,
    ShowcasePlan,
    ShowcaseSegment,
    ShowcaseSource,
    _verified_background_pixels,
    _verified_source_snapshots,
    _EXPECTED_VIDEO_TIME_BASE,
    add_silent_aac,
    concat_clips,
    copy_verified_background,
    extract_review_frames,
    probe_media,
    iter_segment_frames,
    validate_showcase,
    write_silent_video,
)
from tools.nangongwan_rooftop_making_of import ActionSource


_FORBIDDEN_SOURCE_MARKERS = ("anime-reference", "do-not-publish")
_OUTPUT_DIRECTORY = Path("work") / "nangongwan-action-showcase-450px"
_MASTER_NAME = "nangongwan-action-showcase-450px-1600x900.mp4"
_VIDEO_ONLY_NAME = "nangongwan-action-showcase-450px-video-only.mp4"
_SOURCE_HASHES = (
    ("01-cinematic-36f-v2.4.1/pet.json", "a4397d9d4d0caeb338ecbfbae88d4c9ada457c5c50c507d2d77eb7d5fb922964", "manifest"),
    ("01-cinematic-36f-v2.4.1/spritesheet.webp", "990d1ee9db3632102e9f07984301519606a9cc3591585e8ef892d0ba975a9d3e", "atlas"),
    ("02-anchored-48f-v1/complete-archive/pet.json", "3edd549ff49be95758b531ff15dbdeabee1ce44f0dedb4065fcb8e23e7e10bf3", "manifest"),
    ("02-anchored-48f-v1/complete-archive/spritesheet.webp", "d224d16c48beea73516a9eb02e4da4543dfbbd2af7bf96cf10efbf7ff11f0d52", "atlas"),
    ("03-persistent-rooftop-revisions/render-history-v2-v9/preview-sequence-v9.json", "ce818923d127ba78facd81f8a2ff6afefcccd37319df3325774a0568154fe0fa", "sequence"),
    ("04-moon-background-variants/01-small-moon-current/pet.json", "c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131", "manifest"),
    ("04-moon-background-variants/01-small-moon-current/spritesheet.webp", "564793e6c2e090d8e882cc4a829ceccb9bde2ab98b54b9f6126c65cf41fac77e", "atlas"),
    ("04-moon-background-variants/02-full-circle-184/pet.json", "c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131", "manifest"),
    ("04-moon-background-variants/02-full-circle-184/spritesheet.webp", "117b5bcf84e9dbdc45b5ef13590fe3726667823178b5a603e0e83e527902fa5a", "atlas"),
    ("04-moon-background-variants/03-cropped-disc-232/pet.json", "c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131", "manifest"),
    ("04-moon-background-variants/03-cropped-disc-232/spritesheet.webp", "6f671f19463dd4f6bf293550ad05c24b6e18c851d98264dd3548b0dc5d5cbb92", "atlas"),
    ("04-moon-background-variants/04-full-frame-moon-surface/pet.json", "c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131", "manifest"),
    ("04-moon-background-variants/04-full-frame-moon-surface/spritesheet.webp", "03393672e282e5bdcca3fea5f9d58928e0775fb42802e1c10b9a11d1d1e15abe", "atlas"),
    ("06-standing-chestnut-easter-egg/action.json", "687da2a94210ac5d6907061b5ddd9d39e16d2f51719e311807179eaf01c70d9f", "manifest"),
    ("06-standing-chestnut-easter-egg/standing-chestnut-10frames.webp", "9bb9c75b86b82e8903abc8b9099e1be51b5972d72243b6d6c5f10c74a41b275e", "atlas"),
)


def _history(root: Path) -> Path:
    return root / "work" / "nangongwan-moonlit-rooftop-history"


def _approved_source_assets(root: Path, background: Path) -> tuple[SourceAsset, ...]:
    history = _history(root)
    assets = [
        SourceAsset(background, BACKGROUND_SHA256, "background", "background.png")
    ]
    assets.extend(
        SourceAsset(
            history / relative,
            expected_hash,
            role,  # type: ignore[arg-type]
            relative,
        )
        for relative, expected_hash, role in _SOURCE_HASHES
    )
    return tuple(assets)


def _source_assets_for_actions(
    actions: tuple[ActionSource, ...], inventory: tuple[SourceAsset, ...]
) -> tuple[SourceAsset, ...]:
    paths = {
        path.resolve()
        for action in actions
        for path in (action.atlas, action.manifest)
    }
    return tuple(asset for asset in inventory if asset.path.resolve() in paths)


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


def _action_metadata(
    source: ActionSource, snapshots: dict[Path, bytes]
) -> tuple[int, tuple[int, ...]]:
    document = json.loads(snapshots[source.manifest.resolve()])
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


def _source_metadata(
    source: ShowcaseSource, snapshots: dict[Path, bytes] | None = None
) -> tuple[int, tuple[int, ...]]:
    if not source.actions:
        raise ValueError("showcase source must contain actions")
    snapshots = (
        _verified_source_snapshots(source.assets) if snapshots is None else snapshots
    )
    metadata = tuple(_action_metadata(action, snapshots) for action in source.actions)
    return sum(frame_count for frame_count, _ in metadata), tuple(
        duration_ms
        for _, action_durations in metadata
        for duration_ms in action_durations
    )


def _validate_source(
    source: ShowcaseSource, snapshots: dict[Path, bytes] | None = None
) -> tuple[int, int]:
    frame_count, durations = _source_metadata(source, snapshots)
    return frame_count, sum(durations)


def _pet_source(history: Path, variant: str, action_id: str) -> ActionSource:
    directory = history / "04-moon-background-variants" / variant
    return _source(directory / "spritesheet.webp", directory / "pet.json", action_id)


def build_showcase_plan(root: Path, background_source: Path) -> ShowcasePlan:
    """Build and validate the approved fifteen-segment action sequence."""

    history = _history(root)
    inventory = _approved_source_assets(root, background_source)
    snapshots = _verified_source_snapshots(inventory)
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
    moon_184 = _pet_source(history, "02-full-circle-184", "rooftopChestnut")
    moon_232 = _pet_source(history, "03-cropped-disc-232", "rooftopChestnut")
    moon_full = _pet_source(history, "04-full-frame-moon-surface", "rooftopChestnut")

    background_hash, _ = _verified_background_pixels(background_source)
    if background_hash != BACKGROUND_SHA256:
        raise ValueError("background SHA-256 does not match the approved source")

    preview = json.loads(snapshots[preview_path.resolve()])
    sequence = preview.get("sequence")
    if not isinstance(sequence, list) or not all(isinstance(action_id, str) for action_id in sequence):
        raise ValueError("V9 preview sequence is invalid")
    v9_actions = tuple(_pet_source(history, small, action_id) for action_id in sequence)
    v9 = ShowcaseSource(
        "sequence", v9_actions, _source_assets_for_actions(v9_actions, inventory)
    )

    blink_actions = (blink_action,)
    blink = ShowcaseSource(
        "blink", blink_actions, _source_assets_for_actions(blink_actions, inventory)
    )

    def action_source(action: ActionSource) -> ShowcaseSource:
        actions = (action,)
        return ShowcaseSource(
            "action", actions, _source_assets_for_actions(actions, inventory)
        )

    action_sources = {
        "standing-chestnut": action_source(standing),
        "cinematic-36": action_source(cinematic),
        "anchored-48": action_source(anchored),
        "v9-small-moon": v9,
        "moon-184": action_source(moon_184),
        "moon-232": action_source(moon_232),
        "moon-full": action_source(moon_full),
    }
    _validate_source(blink, snapshots)
    v9_frames, v9_duration = _validate_source(v9, snapshots)
    if (
        preview.get("frameCount") != 166
        or preview.get("durationMs") != 30_680
        or (v9_frames, v9_duration) != (166, 30_680)
    ):
        raise ValueError("V9 source must contain 166 frames and 30680 ms")
    moon_metadata = tuple(
        _source_metadata(action_sources[source_name], snapshots)
        for source_name in ("moon-184", "moon-232", "moon-full")
    )
    for frame_count, durations in moon_metadata:
        if (frame_count, sum(durations)) != (44, 8_990):
            raise ValueError("moon source must contain 44 frames and 8990 ms")
    if any(durations != moon_metadata[0][1] for _, durations in moon_metadata[1:]):
        raise ValueError("moon sources must have identical per-frame durations")
    for source_name in ("standing-chestnut", "cinematic-36", "anchored-48"):
        _validate_source(action_sources[source_name], snapshots)

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
    return ShowcasePlan(background_source, segments, (preview_path,), inventory)


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
        "schemaVersion": 2,
        "backgroundSha256": background_hash,
        "frameSize": list(FRAME_SIZE),
        "sourceSpriteSize": list(SOURCE_SPRITE_SIZE),
        "renderedSpriteRectangle": {
            "x": RENDERED_SPRITE_ORIGIN[0],
            "y": RENDERED_SPRITE_ORIGIN[1],
            "width": RENDERED_SPRITE_SIZE[0],
            "height": RENDERED_SPRITE_SIZE[1],
        },
        "renderScale": {
            "numerator": RENDER_SCALE.numerator,
            "denominator": RENDER_SCALE.denominator,
        },
        "sourceSha256": [
            {
                "id": asset.id,
                "role": asset.role,
                "sha256": asset.sha256,
            }
            for asset in plan.source_inventory
        ],
        "totalFrames": plan.total_frames,
        "segments": entries,
    }


def _write_timeline(plan: ShowcasePlan, background_hash: str, output: Path) -> None:
    document = _timeline_document(plan, background_hash)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _plan_with_background(plan: ShowcasePlan, background: Path) -> ShowcasePlan:
    inventory = tuple(
        SourceAsset(background, asset.sha256, asset.role, asset.id)
        if asset.role == "background"
        else asset
        for asset in plan.source_inventory
    )
    return ShowcasePlan(
        background, plan.segments, plan.sequence_sources, inventory
    )


def _build_showcase_directory(
    root: Path, background_source: Path, output: Path
) -> Path:
    """Build into one unpublished directory without touching accepted output."""

    source_plan = build_showcase_plan(root, background_source)
    clips_directory = output / "clips"
    clips_directory.mkdir(parents=True, exist_ok=True)
    background_copy = output / "background.png"
    background_hash = copy_verified_background(background_source, background_copy)
    plan = _plan_with_background(source_plan, background_copy)
    if len(plan.segments) != 15 or plan.total_frames != 2473:
        raise ValueError("showcase build requires the approved 15 segments and 2473 frames")

    with Image.open(background_copy) as source:
        background = source.copy()
    clip_paths: list[Path] = []
    for index, segment in enumerate(plan.segments, start=1):
        clip = clips_directory / f"{index:02d}-{segment.id}.mp4"
        write_silent_video(
            iter_segment_frames(segment, background),
            clip,
            expected_frames=segment.output_frames,
        )
        clip_paths.append(clip)

    _write_timeline(plan, background_hash, output / "timeline.json")
    video_only = output / _VIDEO_ONLY_NAME
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


def _invalidate_acceptance(output: Path) -> None:
    (output / "validation-report.json").unlink(missing_ok=True)
    review = output / "review"
    if review.exists():
        shutil.rmtree(review)


def _publish_staged_directory(staging: Path, output: Path) -> None:
    """Replace an output directory as one rename transaction with rollback."""

    report_path = staging / "validation-report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("staging directory has no valid validation report") from error
    if not isinstance(report, dict) or report.get("allPassed") is not True:
        raise ValueError("staging directory is not approved for publication")
    master = staging / _MASTER_NAME
    background = staging / "background.png"
    timeline = staging / "timeline.json"
    contact_sheet = staging / "review" / "contact-sheet.jpg"
    required = (master, background, timeline, contact_sheet)
    if not all(path.is_file() for path in required):
        raise ValueError("staging directory is missing required approved artifacts")
    try:
        timeline_document = json.loads(timeline.read_text(encoding="utf-8"))
        segments = timeline_document["segments"]
        expected_clips = {
            f"{index:02d}-{segment['id']}.mp4"
            for index, segment in enumerate(segments, start=1)
        }
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("staging timeline cannot define the published clip set") from error
    actual_clips = {
        path.name for path in (staging / "clips").glob("*.mp4") if path.is_file()
    }
    review_frames = tuple((staging / "review").glob("*.png"))
    review = report.get("review")
    artifact_hashes = report.get("artifactSha256")
    expected_hashes = {
        "master": sha256(master.read_bytes()).hexdigest(),
        "background": sha256(background.read_bytes()).hexdigest(),
        "timeline": sha256(timeline.read_bytes()).hexdigest(),
    }
    if not (
        isinstance(segments, list)
        and len(segments) == 15
        and actual_clips == expected_clips
        and len(review_frames) == 45
        and isinstance(review, dict)
        and review.get("frameCount") == 45
        and review.get("contactSheetSha256")
        == sha256(contact_sheet.read_bytes()).hexdigest()
        and artifact_hashes == expected_hashes
    ):
        raise ValueError("staging directory is not a complete approved output set")
    output.parent.mkdir(parents=True, exist_ok=True)
    backup = output.parent / f".{output.name}-backup-{uuid4().hex}"
    moved_previous = False
    try:
        if output.exists():
            output.replace(backup)
            moved_previous = True
        try:
            staging.replace(output)
        except BaseException:
            if moved_previous and backup.exists() and not output.exists():
                backup.replace(output)
            raise
    finally:
        if output.exists() and backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError:
                # Publication already committed; a locked old backup must not
                # turn that successful directory swap into a reported failure.
                pass


def build_showcase(root: Path, background_source: Path) -> Path:
    """Build, validate, then publish the complete 450px output set."""

    output = root / _OUTPUT_DIRECTORY
    output.parent.mkdir(parents=True, exist_ok=True)
    _invalidate_acceptance(output)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}-staging-", dir=output.parent
        )
    )
    try:
        _build_showcase_directory(root, background_source, staging)
        _validate_final_showcase(
            root,
            background_source=None,
            output_directory=staging,
            published_output=output,
        )
        _publish_staged_directory(staging, output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return output / _MASTER_NAME


def _validate_existing(
    root: Path,
    background_source: Path | None = None,
    *,
    output_directory: Path | None = None,
) -> Path:
    """Check Task 3 file/timeline/media invariants without rebuilding artifacts."""

    output = root / _OUTPUT_DIRECTORY if output_directory is None else output_directory
    background_copy = output / "background.png"
    if not background_copy.is_file():
        raise ValueError(f"built background is missing: {background_copy}")
    plan = build_showcase_plan(root, background_copy)
    background_hash, _ = _verified_background_pixels(background_copy)
    if background_hash != BACKGROUND_SHA256:
        raise ValueError("built background does not match the approved SHA-256")
    if background_source is not None:
        _validate_public_path(background_source)
        source_hash, _ = _verified_background_pixels(background_source)
        if source_hash != background_hash:
            raise ValueError("current approved background does not match the built copy")
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
            and clip_probe.video.average_frame_rate == FPS
            and clip_probe.video.time_base == _EXPECTED_VIDEO_TIME_BASE
            and clip_probe.video.duration == Fraction(segment.output_frames, FPS)
            and clip_probe.video.nb_read_frames == segment.output_frames
            and clip_probe.audio is None
            and clip_probe.subtitle_streams == 0
            and clip_probe.data_streams == 0
            and clip_probe.other_streams == 0
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
        and probe.video.average_frame_rate == FPS
        and probe.video.time_base == _EXPECTED_VIDEO_TIME_BASE
        and probe.video.duration == Fraction(plan.total_frames, FPS)
        and probe.video.nb_read_frames == plan.total_frames
        and probe.audio is not None
        and probe.audio.codec == "aac"
        and probe.audio.sample_rate == 48_000
        and probe.audio.channels == 2
        and abs(probe.audio.duration - Fraction(plan.total_frames, FPS))
        <= Fraction(1024, 48_000)
        and probe.subtitle_streams == 0
        and probe.data_streams == 0
        and probe.other_streams == 0
    ):
        raise ValueError("existing master does not satisfy the Task 3 media contract")
    return master


def _remap_output_paths(value: object, source: Path, destination: Path) -> object:
    if isinstance(value, dict):
        return {
            key: _remap_output_paths(item, source, destination)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _remap_output_paths(item, source, destination) for item in value
        ]
    if isinstance(value, str):
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                relative = candidate.relative_to(source.resolve())
            except ValueError:
                pass
            else:
                return str((destination / relative).resolve())
    return value


def _validate_final_showcase(
    root: Path,
    background_source: Path | None = None,
    *,
    output_directory: Path | None = None,
    published_output: Path | None = None,
) -> tuple[Path, Path]:
    """Run every Task 4 gate and write local review artifacts on success."""

    output = root / _OUTPUT_DIRECTORY if output_directory is None else output_directory
    _invalidate_acceptance(output)
    master = _validate_existing(
        root, background_source, output_directory=output
    )
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
    if published_output is not None:
        report = _remap_output_paths(report, output, published_output)
        assert isinstance(report, dict)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["allPassed"] is not True:
        raise ValueError(f"final 450px validation failed; see {report_path}")
    return master, report_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--background",
        type=Path,
        default=None,
        help=(
            "approved background PNG (required for --build-all; optional explicit "
            "comparison for --validate-only)"
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build-all", action="store_true")
    mode.add_argument("--validate-only", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.build_all:
        if args.background is None:
            _parser().error("--build-all requires --background")
        master = build_showcase(root, args.background)
        print(f"Built, validated, and published {master}")
    else:
        master, report = _validate_final_showcase(root, args.background)
        print(f"Validated {master}; allPassed=true; report={report}")


if __name__ == "__main__":
    main()
