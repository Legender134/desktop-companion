"""Build the approved fifteen-segment Nangong Wan showcase as one pet action."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import groupby
import json
from math import ceil
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Callable
from uuid import uuid4

from PIL import Image


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.nangongwan_action_showcase_v2 import (
    FPS,
    ShowcasePlan,
    _concatenate_actions,
    _segment_source_indices,
)
from tools.render_nangongwan_action_showcase_v2 import build_showcase_plan


ACTION_ID = "completeShowcase"
ACTION_LABEL = "完整动作展示"
ATLAS_COLUMNS = 16
CELL_SIZE = (192, 208)
ORIGINAL_ROWS = 34
EXPECTED_FRAME_COUNT = 448
EXPECTED_DURATION_MS = 82_433
EXPECTED_OUTPUT_FRAMES = 2_473
APPROVED_ATLAS_SHA256 = (
    "564793e6c2e090d8e882cc4a829ceccb9bde2ab98b54b9f6126c65cf41fac77e"
)
APPROVED_ATLAS_BYTES = 9_838_046
OUTPUT_ATLAS_SHA256 = (
    "6c1df790c2807c6b0293cada191fbf47be644b56a77894a3feb9407f8581c728"
)
OUTPUT_ATLAS_BYTES = 19_435_428
OUTPUT_ATLAS_SIZE = (3_072, 12_896)
MAX_ATLAS_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024


@dataclass(frozen=True)
class CollapsedRun:
    source_index: int
    output_frames: int
    duration_ms: int


@dataclass(frozen=True)
class CompiledSegment:
    id: str
    start_frame: int
    end_frame: int
    output_frames: int

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame


@dataclass(frozen=True)
class CompiledShowcaseAction:
    frames: tuple[Image.Image, ...]
    durations_ms: tuple[int, ...]
    segments: tuple[CompiledSegment, ...]


@dataclass(frozen=True)
class BuildResult:
    atlas_path: Path
    manifest_path: Path
    archive_directory: Path
    review_directory: Path
    atlas_sha256: str
    atlas_bytes: int
    already_current: bool


def frame_boundary_ms(frame_index: int) -> int:
    """Return the nearest integer millisecond at one global 30 fps boundary."""

    if frame_index < 0:
        raise ValueError("frame index must be non-negative")
    return round(Fraction(frame_index * 1000, FPS))


def collapse_indices(
    indices: tuple[int, ...],
    *,
    global_output_start: int,
) -> tuple[CollapsedRun, ...]:
    """Collapse adjacent identical source indices while preserving exact CFR time."""

    if not indices:
        raise ValueError("source indices must not be empty")
    if global_output_start < 0 or any(
        not isinstance(index, int) or isinstance(index, bool) or index < 0
        for index in indices
    ):
        raise ValueError("source indices and global start must be non-negative integers")

    cursor = global_output_start
    runs: list[CollapsedRun] = []
    for source_index, grouped in groupby(indices):
        output_frames = sum(1 for _ in grouped)
        end = cursor + output_frames
        runs.append(
            CollapsedRun(
                source_index=source_index,
                output_frames=output_frames,
                duration_ms=frame_boundary_ms(end) - frame_boundary_ms(cursor),
            )
        )
        cursor = end
    return tuple(runs)


def compile_showcase_action(plan: ShowcasePlan) -> CompiledShowcaseAction:
    """Compile a showcase plan into unique adjacent frames and exact durations."""

    frames: list[Image.Image] = []
    durations: list[int] = []
    segments: list[CompiledSegment] = []
    output_cursor = 0

    for segment in plan.segments:
        timed = _concatenate_actions(segment.source)
        indices = _segment_source_indices(segment, timed)
        if len(indices) != segment.output_frames:
            raise ValueError(f"segment {segment.id} source mapping has the wrong length")
        runs = collapse_indices(indices, global_output_start=output_cursor)
        start_frame = len(frames)
        for run in runs:
            frames.append(timed.frames[run.source_index].copy().convert("RGBA"))
            durations.append(run.duration_ms)
        segments.append(
            CompiledSegment(
                id=segment.id,
                start_frame=start_frame,
                end_frame=len(frames),
                output_frames=segment.output_frames,
            )
        )
        output_cursor += segment.output_frames

    if not frames or any(frame.size != CELL_SIZE for frame in frames):
        raise ValueError("compiled frames must be non-empty 192 by 208 RGBA images")
    if any(duration < 33 or duration > 2_000 for duration in durations):
        raise ValueError("compiled frame durations must be 33 through 2000 ms")
    return CompiledShowcaseAction(tuple(frames), tuple(durations), tuple(segments))


def append_frames(
    atlas: Image.Image,
    frames: tuple[Image.Image, ...],
    *,
    columns: int = ATLAS_COLUMNS,
    original_rows: int = ORIGINAL_ROWS,
    cell_size: tuple[int, int] = CELL_SIZE,
) -> Image.Image:
    """Append RGBA cells without recompositing their semi-transparent pixels."""

    if columns <= 0 or original_rows <= 0 or min(cell_size) <= 0:
        raise ValueError("atlas geometry must be positive")
    expected_size = (columns * cell_size[0], original_rows * cell_size[1])
    if atlas.size != expected_size:
        raise ValueError(f"source atlas must be {expected_size[0]}x{expected_size[1]}")
    if not frames or any(
        frame.mode != "RGBA" or frame.size != cell_size for frame in frames
    ):
        raise ValueError("appended frames must be non-empty matching RGBA cells")

    added_rows = ceil(len(frames) / columns)
    result = Image.new(
        "RGBA",
        (expected_size[0], (original_rows + added_rows) * cell_size[1]),
        (0, 0, 0, 0),
    )
    result.paste(atlas.convert("RGBA"), (0, 0))
    first_cell = original_rows * columns
    for offset, frame in enumerate(frames):
        row, column = divmod(first_cell + offset, columns)
        result.paste(frame, (column * cell_size[0], row * cell_size[1]))
    return result


def with_complete_showcase_action(
    manifest: dict[str, object],
    durations_ms: tuple[int, ...],
) -> dict[str, object]:
    """Return a copied manifest with the approved manual-only action appended."""

    if len(durations_ms) != EXPECTED_FRAME_COUNT or any(
        not isinstance(duration, int)
        or isinstance(duration, bool)
        or not 33 <= duration <= 2_000
        for duration in durations_ms
    ):
        raise ValueError("complete showcase requires 448 valid frame durations")
    result = deepcopy(manifest)
    actions = result.get("actions")
    if not isinstance(actions, dict):
        raise ValueError("pet manifest must contain an actions object")
    actions[ACTION_ID] = {
        "label": ACTION_LABEL,
        "role": "interaction",
        "row": ORIGINAL_ROWS,
        "startColumn": 0,
        "frameCount": EXPECTED_FRAME_COUNT,
        "frameDurations": list(durations_ms),
        "repeatCount": 1,
        "autoplayWeight": 0,
        "showInMenu": True,
        "includeInShowcase": False,
    }
    return result


def _sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _replace_file(source: Path, destination: Path) -> None:
    source.replace(destination)


def publish_pair(
    staged_atlas: Path,
    staged_manifest: Path,
    atlas_path: Path,
    manifest_path: Path,
    *,
    replace_file: Callable[[Path, Path], None] = _replace_file,
) -> None:
    """Publish two staged files and restore both originals on any failure."""

    paths = (staged_atlas, staged_manifest, atlas_path, manifest_path)
    if any(not path.is_file() for path in paths):
        raise ValueError("publish inputs and destinations must all be files")
    token = uuid4().hex
    atlas_backup = atlas_path.with_name(f"{atlas_path.name}.rollback-{token}")
    manifest_backup = manifest_path.with_name(f"{manifest_path.name}.rollback-{token}")
    shutil.copy2(atlas_path, atlas_backup)
    shutil.copy2(manifest_path, manifest_backup)
    try:
        replace_file(staged_atlas, atlas_path)
        replace_file(staged_manifest, manifest_path)
    except BaseException:
        shutil.copy2(atlas_backup, atlas_path)
        shutil.copy2(manifest_backup, manifest_path)
        staged_atlas.unlink(missing_ok=True)
        staged_manifest.unlink(missing_ok=True)
        raise
    finally:
        atlas_backup.unlink(missing_ok=True)
        manifest_backup.unlink(missing_ok=True)


def _read_manifest(path: Path) -> tuple[dict[str, object], bytes]:
    payload = path.read_bytes()
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("pet.json must contain UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ValueError("pet.json root must be an object")
    return document, payload


def _validate_compiled(compiled: CompiledShowcaseAction, plan: ShowcasePlan) -> None:
    if plan.total_frames != EXPECTED_OUTPUT_FRAMES:
        raise ValueError("showcase plan must contain 2473 video frames")
    if len(compiled.frames) != EXPECTED_FRAME_COUNT:
        raise ValueError("compiled showcase must contain 448 frames")
    if len(compiled.durations_ms) != EXPECTED_FRAME_COUNT:
        raise ValueError("compiled showcase duration count must match its frames")
    if sum(compiled.durations_ms) != EXPECTED_DURATION_MS:
        raise ValueError("compiled showcase must last 82433 ms")
    if len(compiled.segments) != 15:
        raise ValueError("compiled showcase must contain fifteen segments")


def _validate_archive(
    archive_directory: Path,
    atlas_payload: bytes,
    manifest_payload: bytes,
    *,
    allow_create: bool,
) -> None:
    atlas_path = archive_directory / "spritesheet.webp"
    manifest_path = archive_directory / "pet.json"
    if archive_directory.exists():
        if not atlas_path.is_file() or not manifest_path.is_file():
            raise ValueError("complete showcase archive is incomplete")
        if atlas_path.read_bytes() != atlas_payload:
            raise ValueError("complete showcase archive atlas does not match v2.4.6")
        if manifest_path.read_bytes() != manifest_payload:
            raise ValueError("complete showcase archive manifest does not match v2.4.6")
        return
    if not allow_create:
        raise ValueError("complete showcase archive is missing")
    archive_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{archive_directory.name}-",
            dir=archive_directory.parent,
        )
    )
    try:
        (staging / "spritesheet.webp").write_bytes(atlas_payload)
        (staging / "pet.json").write_bytes(manifest_payload)
        staging.replace(archive_directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _save_lossless_webp(image: Image.Image, destination: Path) -> None:
    image.save(destination, "WEBP", lossless=True, method=6, exact=True)


def _validate_output_atlas(
    atlas_path: Path,
    *,
    compiled: CompiledShowcaseAction,
    archived_atlas: Path,
) -> tuple[str, int]:
    payload = atlas_path.read_bytes()
    digest = _sha256_bytes(payload)
    if len(payload) > MAX_ATLAS_BYTES:
        raise ValueError("output atlas exceeds 32 MiB")
    if (len(payload), digest) != (OUTPUT_ATLAS_BYTES, OUTPUT_ATLAS_SHA256):
        raise ValueError(
            "output atlas bytes or SHA-256 do not match the approved deterministic build"
        )
    with Image.open(atlas_path) as output_source:
        output = output_source.convert("RGBA")
    with Image.open(archived_atlas) as archived_source:
        old = archived_source.convert("RGBA")
    if output.size != OUTPUT_ATLAS_SIZE:
        raise ValueError("output atlas must be 3072x12896")
    if output.crop((0, 0, old.width, old.height)).tobytes() != old.tobytes():
        raise ValueError("output atlas changed a pre-existing v2.4.6 cell")
    for offset, expected in enumerate(compiled.frames):
        row, column = divmod(ORIGINAL_ROWS * ATLAS_COLUMNS + offset, ATLAS_COLUMNS)
        box = (
            column * CELL_SIZE[0],
            row * CELL_SIZE[1],
            (column + 1) * CELL_SIZE[0],
            (row + 1) * CELL_SIZE[1],
        )
        if output.crop(box).tobytes() != expected.tobytes():
            raise ValueError(f"output atlas frame {offset} does not match its source")
    return digest, len(payload)


def _manifest_payload(document: dict[str, object]) -> bytes:
    payload = (
        json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("output pet.json exceeds 64 KiB")
    return payload


def _segment_samples(
    compiled: CompiledShowcaseAction,
) -> tuple[tuple[Image.Image, Image.Image, Image.Image], ...]:
    samples = []
    for segment in compiled.segments:
        middle = segment.start_frame + segment.frame_count // 2
        samples.append(
            (
                compiled.frames[segment.start_frame],
                compiled.frames[middle],
                compiled.frames[segment.end_frame - 1],
            )
        )
    return tuple(samples)


def _write_review(
    review_directory: Path,
    *,
    compiled: CompiledShowcaseAction,
    input_atlas_sha256: str,
    output_atlas_sha256: str,
    output_atlas_bytes: int,
) -> None:
    parent = review_directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{review_directory.name}-", dir=parent)
    )
    try:
        boundaries = staging / "segment-boundaries"
        boundaries.mkdir()
        samples = _segment_samples(compiled)
        sheet = Image.new(
            "RGBA",
            (len(samples) * CELL_SIZE[0], 3 * CELL_SIZE[1]),
            (0, 0, 0, 0),
        )
        for segment_index, (segment, sample_set) in enumerate(
            zip(compiled.segments, samples, strict=True),
            start=1,
        ):
            for sample_index, (label, frame) in enumerate(
                zip(("first", "middle", "last"), sample_set, strict=True)
            ):
                sheet.paste(
                    frame,
                    ((segment_index - 1) * CELL_SIZE[0], sample_index * CELL_SIZE[1]),
                )
                if label != "middle":
                    frame.save(
                        boundaries
                        / f"{segment_index:02d}-{segment.id}-{label}.png"
                    )
        sheet.save(staging / "contact-sheet-15x3.png")
        report = {
            "schemaVersion": 1,
            "allPassed": True,
            "actionId": ACTION_ID,
            "totalFrames": len(compiled.frames),
            "durationMs": sum(compiled.durations_ms),
            "minimumFrameMs": min(compiled.durations_ms),
            "maximumFrameMs": max(compiled.durations_ms),
            "inputAtlasSha256": input_atlas_sha256,
            "outputAtlasSha256": output_atlas_sha256,
            "outputAtlasBytes": output_atlas_bytes,
            "segments": [
                {
                    "id": segment.id,
                    "startFrame": segment.start_frame,
                    "endFrame": segment.end_frame,
                    "frameCount": segment.frame_count,
                    "outputFrames": segment.output_frames,
                }
                for segment in compiled.segments
            ],
        }
        (staging / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if review_directory.exists():
            shutil.rmtree(review_directory)
        staging.replace(review_directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _is_current_manifest(
    manifest: dict[str, object],
    compiled: CompiledShowcaseAction,
) -> bool:
    expected = with_complete_showcase_action(
        {"actions": {}}, compiled.durations_ms
    )["actions"][ACTION_ID]
    actions = manifest.get("actions")
    return isinstance(actions, dict) and actions.get(ACTION_ID) == expected


def build_complete_showcase(
    *,
    root: Path,
    background: Path,
    pet_directory: Path | None = None,
    archive_directory: Path | None = None,
    review_directory: Path | None = None,
    validate_only: bool = False,
) -> BuildResult:
    """Build or validate the packaged complete-showcase action."""

    root = root.resolve()
    pet_directory = (
        root / "src/shiyi_desktop_pet/resources/pets/nangongwan"
        if pet_directory is None
        else pet_directory
    )
    archive_directory = (
        root / "tools/archives/nangongwan-complete-showcase-v2.4.6"
        if archive_directory is None
        else archive_directory
    )
    review_directory = (
        root / "work/nangongwan-complete-showcase-action"
        if review_directory is None
        else review_directory
    )
    atlas_path = pet_directory / "spritesheet.webp"
    manifest_path = pet_directory / "pet.json"
    if not atlas_path.is_file() or not manifest_path.is_file():
        raise ValueError("active Nangong Wan atlas and manifest must exist")

    active_atlas_payload = atlas_path.read_bytes()
    active_digest = _sha256_bytes(active_atlas_payload)
    manifest, active_manifest_payload = _read_manifest(manifest_path)
    is_old = (
        len(active_atlas_payload) == APPROVED_ATLAS_BYTES
        and active_digest == APPROVED_ATLAS_SHA256
        and ACTION_ID not in manifest.get("actions", {})
    )
    is_new = (
        len(active_atlas_payload) == OUTPUT_ATLAS_BYTES
        and active_digest == OUTPUT_ATLAS_SHA256
        and ACTION_ID in manifest.get("actions", {})
    )
    if not is_old and not is_new:
        raise ValueError("active atlas SHA-256 or manifest state is not approved")

    plan = build_showcase_plan(root, background)
    compiled = compile_showcase_action(plan)
    _validate_compiled(compiled, plan)

    if is_new:
        archived_atlas = archive_directory / "spritesheet.webp"
        archived_manifest = archive_directory / "pet.json"
        if not archived_atlas.is_file() or not archived_manifest.is_file():
            raise ValueError("complete showcase archive is missing")
        if _sha256_bytes(archived_atlas.read_bytes()) != APPROVED_ATLAS_SHA256:
            raise ValueError("complete showcase archive atlas does not match v2.4.6")
        if _is_current_manifest(manifest, compiled) is False:
            raise ValueError("current complete showcase action metadata is invalid")
        digest, byte_count = _validate_output_atlas(
            atlas_path,
            compiled=compiled,
            archived_atlas=archived_atlas,
        )
        report_path = review_directory / "build-report.json"
        if not report_path.is_file():
            raise ValueError("complete showcase review report is missing")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (
            not isinstance(report, dict)
            or report.get("allPassed") is not True
            or report.get("outputAtlasSha256") != OUTPUT_ATLAS_SHA256
        ):
            raise ValueError("complete showcase review report is invalid")
        return BuildResult(
            atlas_path,
            manifest_path,
            archive_directory,
            review_directory,
            digest,
            byte_count,
            True,
        )

    if validate_only:
        raise ValueError("complete showcase has not been built")

    with Image.open(atlas_path) as atlas_source:
        atlas = atlas_source.convert("RGBA")
    if atlas.size != (ATLAS_COLUMNS * CELL_SIZE[0], ORIGINAL_ROWS * CELL_SIZE[1]):
        raise ValueError("approved active atlas must be 3072x7072")
    updated_manifest = with_complete_showcase_action(
        manifest, compiled.durations_ms
    )
    manifest_payload = _manifest_payload(updated_manifest)

    pet_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".complete-showcase-", dir=pet_directory) as raw:
        staging = Path(raw)
        staged_atlas = staging / "spritesheet.webp"
        staged_manifest = staging / "pet.json"
        output = append_frames(atlas, compiled.frames)
        _save_lossless_webp(output, staged_atlas)
        staged_manifest.write_bytes(manifest_payload)

        archive_existed = archive_directory.exists()
        _validate_archive(
            archive_directory,
            active_atlas_payload,
            active_manifest_payload,
            allow_create=True,
        )
        review_backup = review_directory.with_name(
            f"{review_directory.name}.rollback-{uuid4().hex}"
        )
        if review_directory.exists():
            review_directory.replace(review_backup)
        try:
            digest, byte_count = _validate_output_atlas(
                staged_atlas,
                compiled=compiled,
                archived_atlas=archive_directory / "spritesheet.webp",
            )
            _write_review(
                review_directory,
                compiled=compiled,
                input_atlas_sha256=APPROVED_ATLAS_SHA256,
                output_atlas_sha256=digest,
                output_atlas_bytes=byte_count,
            )
            publish_pair(
                staged_atlas,
                staged_manifest,
                atlas_path,
                manifest_path,
            )
        except BaseException:
            if review_directory.exists():
                shutil.rmtree(review_directory, ignore_errors=True)
            if review_backup.exists():
                review_backup.replace(review_directory)
            if not archive_existed:
                shutil.rmtree(archive_directory, ignore_errors=True)
            raise
        else:
            if review_backup.exists():
                shutil.rmtree(review_backup)

    return BuildResult(
        atlas_path,
        manifest_path,
        archive_directory,
        review_directory,
        digest,
        byte_count,
        False,
    )


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Build the approved Nangong Wan complete showcase pet action."
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument(
        "--background",
        type=Path,
        default=root
        / "work/nangongwan-action-showcase-450px/background.png",
        help="approved background used only to verify the immutable video plan",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    result = build_complete_showcase(
        root=args.root,
        background=args.background,
        validate_only=args.validate_only,
    )
    verb = "Validated" if result.already_current else "Built"
    print(
        f"{verb} {result.atlas_path} "
        f"({result.atlas_bytes} bytes, SHA256 {result.atlas_sha256})"
    )


if __name__ == "__main__":
    main()
