from hashlib import sha256
import json
from pathlib import Path
import shutil

from PIL import Image
import pytest

from tools import build_nangongwan_complete_showcase_action as builder
from tools.render_nangongwan_action_showcase_v2 import build_showcase_plan


def test_collapse_indices_preserves_order_and_exact_global_30fps_boundaries():
    runs = builder.collapse_indices(
        (0, 0, 1, 1, 1, 0),
        global_output_start=0,
    )

    assert [(run.source_index, run.output_frames) for run in runs] == [
        (0, 2),
        (1, 3),
        (0, 1),
    ]
    assert [run.duration_ms for run in runs] == [67, 100, 33]
    assert sum(run.duration_ms for run in runs) == 200


def test_append_frames_copies_rgba_bytes_without_alpha_recompositing():
    cell_size = (2, 2)
    atlas = Image.new("RGBA", (4, 2), (0, 0, 0, 0))
    atlas.putpixel((0, 0), (1, 2, 3, 4))
    semitransparent = Image.new("RGBA", cell_size, (120, 80, 40, 128))

    result = builder.append_frames(
        atlas,
        (semitransparent,),
        columns=2,
        original_rows=1,
        cell_size=cell_size,
    )

    assert result.size == (4, 4)
    assert result.getpixel((0, 0)) == (1, 2, 3, 4)
    assert result.getpixel((0, 2)) == (120, 80, 40, 128)
    assert result.getpixel((2, 2)) == (0, 0, 0, 0)


def test_manifest_action_is_manual_only_and_uses_compiled_durations():
    manifest = {"actions": {"idle": {"label": "待机"}}}
    durations = tuple([33] * 447 + [34])

    updated = builder.with_complete_showcase_action(manifest, durations)
    action = updated["actions"]["completeShowcase"]

    assert "completeShowcase" not in manifest["actions"]
    assert action == {
        "label": "完整动作展示",
        "role": "interaction",
        "row": 34,
        "startColumn": 0,
        "frameCount": 448,
        "frameDurations": [*durations],
        "repeatCount": 1,
        "autoplayWeight": 0,
        "showInMenu": True,
        "includeInShowcase": False,
    }


def test_real_showcase_plan_compiles_to_448_frames_and_82433_ms(repo_root: Path):
    background = (
        repo_root
        / "work"
        / "nangongwan-action-showcase-450px"
        / "background.png"
    )
    plan = build_showcase_plan(repo_root, background)

    compiled = builder.compile_showcase_action(plan)

    assert [segment.frame_count for segment in compiled.segments] == [
        7,
        10,
        7,
        36,
        7,
        48,
        7,
        166,
        7,
        44,
        7,
        44,
        7,
        44,
        7,
    ]
    assert [segment.id for segment in compiled.segments] == [
        "blink-00",
        "standing-chestnut",
        "blink-01",
        "cinematic-36",
        "blink-02",
        "anchored-48",
        "blink-03",
        "v9-small-moon",
        "blink-04",
        "moon-184",
        "blink-05",
        "moon-232",
        "blink-06",
        "moon-full",
        "blink-07",
    ]
    assert len(compiled.frames) == 448
    assert len(compiled.durations_ms) == 448
    assert sum(compiled.durations_ms) == 82_433
    assert min(compiled.durations_ms) == 33
    assert max(compiled.durations_ms) == 666
    assert all(frame.mode == "RGBA" and frame.size == (192, 208) for frame in compiled.frames)

    digest = sha256()
    for frame in compiled.frames:
        digest.update(frame.tobytes())
    assert digest.hexdigest() == "594b0e6da45fb084638a868373308414bb558a1c15c3420ea1fb562942496f73"


def test_publish_pair_rolls_back_both_files_when_second_replace_fails(tmp_path: Path):
    atlas = tmp_path / "spritesheet.webp"
    manifest = tmp_path / "pet.json"
    staged_atlas = tmp_path / "staged.webp"
    staged_manifest = tmp_path / "staged.json"
    atlas.write_bytes(b"old-atlas")
    manifest.write_bytes(b"old-manifest")
    staged_atlas.write_bytes(b"new-atlas")
    staged_manifest.write_bytes(b"new-manifest")
    calls = 0

    def fail_second_replace(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected manifest publish failure")
        source.replace(destination)

    with pytest.raises(OSError, match="injected manifest publish failure"):
        builder.publish_pair(
            staged_atlas,
            staged_manifest,
            atlas,
            manifest,
            replace_file=fail_second_replace,
        )

    assert atlas.read_bytes() == b"old-atlas"
    assert manifest.read_bytes() == b"old-manifest"
    assert not tuple(tmp_path.glob("*.rollback-*"))


def test_build_rejects_unapproved_active_atlas_before_writing(
    tmp_path: Path,
    repo_root: Path,
):
    pet_directory = tmp_path / "nangongwan"
    pet_directory.mkdir()
    (pet_directory / "spritesheet.webp").write_bytes(b"not-the-approved-atlas")
    shutil.copy2(
        repo_root / "src/shiyi_desktop_pet/resources/pets/nangongwan/pet.json",
        pet_directory / "pet.json",
    )

    with pytest.raises(ValueError, match="active atlas SHA-256"):
        builder.build_complete_showcase(
            root=repo_root,
            background=repo_root
            / "work/nangongwan-action-showcase-450px/background.png",
            pet_directory=pet_directory,
            archive_directory=tmp_path / "archive",
            review_directory=tmp_path / "review",
        )

    assert (pet_directory / "spritesheet.webp").read_bytes() == b"not-the-approved-atlas"
    assert not (tmp_path / "archive").exists()
    assert not (tmp_path / "review").exists()


def test_archive_write_failure_leaves_no_partial_directory(
    tmp_path: Path,
    monkeypatch,
):
    archive = tmp_path / "archive"
    original_write_bytes = Path.write_bytes
    calls = 0

    def fail_second_write(path: Path, payload: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected archive write failure")
        return original_write_bytes(path, payload)

    monkeypatch.setattr(Path, "write_bytes", fail_second_write)

    with pytest.raises(OSError, match="injected archive write failure"):
        builder._validate_archive(
            archive,
            b"approved-atlas",
            b"approved-manifest",
            allow_create=True,
        )

    assert not archive.exists()


@pytest.fixture(scope="module")
def built_complete_showcase_pack(tmp_path_factory):
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path_factory.mktemp("complete-showcase-pack")
    pet_directory = output_root / "nangongwan"
    pet_directory.mkdir()
    source_pet = (
        repo_root
        / "tools"
        / "archives"
        / "nangongwan-complete-showcase-v2.4.6"
    )
    if not source_pet.is_dir():
        source_pet = repo_root / "src/shiyi_desktop_pet/resources/pets/nangongwan"
    shutil.copy2(source_pet / "spritesheet.webp", pet_directory / "spritesheet.webp")
    shutil.copy2(source_pet / "pet.json", pet_directory / "pet.json")
    archive_directory = output_root / "archive"
    review_directory = output_root / "review"

    result = builder.build_complete_showcase(
        root=repo_root,
        background=repo_root
        / "work/nangongwan-action-showcase-450px/background.png",
        pet_directory=pet_directory,
        archive_directory=archive_directory,
        review_directory=review_directory,
    )
    return result, pet_directory, archive_directory, review_directory


def test_build_publishes_expected_atlas_manifest_archive_and_review(
    built_complete_showcase_pack,
):
    result, pet_directory, archive_directory, review_directory = (
        built_complete_showcase_pack
    )
    atlas_path = pet_directory / "spritesheet.webp"
    manifest_path = pet_directory / "pet.json"

    assert result.already_current is False
    assert result.atlas_sha256 == (
        "6c1df790c2807c6b0293cada191fbf47be644b56a77894a3feb9407f8581c728"
    )
    assert result.atlas_bytes == 19_435_428
    with Image.open(atlas_path) as atlas:
        assert atlas.mode == "RGBA"
        assert atlas.size == (3072, 12896)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    action = manifest["actions"]["completeShowcase"]
    assert action["frameCount"] == 448
    assert len(action["frameDurations"]) == 448
    assert sum(action["frameDurations"]) == 82_433
    assert action["includeInShowcase"] is False

    archived = archive_directory / "spritesheet.webp"
    assert sha256(archived.read_bytes()).hexdigest() == (
        "564793e6c2e090d8e882cc4a829ceccb9bde2ab98b54b9f6126c65cf41fac77e"
    )
    assert (archive_directory / "pet.json").is_file()
    report = json.loads((review_directory / "build-report.json").read_text("utf-8"))
    assert report["allPassed"] is True
    assert report["totalFrames"] == 448
    assert report["durationMs"] == 82_433
    assert len(report["segments"]) == 15
    with Image.open(review_directory / "contact-sheet-15x3.png") as sheet:
        assert sheet.size == (15 * 192, 3 * 208)
    assert len(tuple((review_directory / "segment-boundaries").glob("*.png"))) == 30


def test_build_is_idempotent_and_validate_only_does_not_rewrite(
    built_complete_showcase_pack,
):
    repo_root = Path(__file__).resolve().parents[1]
    _, pet_directory, archive_directory, review_directory = built_complete_showcase_pack
    atlas = pet_directory / "spritesheet.webp"
    manifest = pet_directory / "pet.json"
    before = (
        atlas.read_bytes(),
        manifest.read_bytes(),
        atlas.stat().st_mtime_ns,
        manifest.stat().st_mtime_ns,
    )

    result = builder.build_complete_showcase(
        root=repo_root,
        background=repo_root
        / "work/nangongwan-action-showcase-450px/background.png",
        pet_directory=pet_directory,
        archive_directory=archive_directory,
        review_directory=review_directory,
        validate_only=True,
    )

    after = (
        atlas.read_bytes(),
        manifest.read_bytes(),
        atlas.stat().st_mtime_ns,
        manifest.stat().st_mtime_ns,
    )
    assert result.already_current is True
    assert after == before


def test_review_failure_cannot_publish_the_active_pair(
    tmp_path: Path,
    monkeypatch,
    built_complete_showcase_pack,
):
    repo_root = Path(__file__).resolve().parents[1]
    _, built_pet, built_archive, _ = built_complete_showcase_pack
    pet_directory = tmp_path / "nangongwan"
    pet_directory.mkdir()
    shutil.copy2(
        built_archive / "spritesheet.webp",
        pet_directory / "spritesheet.webp",
    )
    shutil.copy2(built_archive / "pet.json", pet_directory / "pet.json")
    old_atlas = (pet_directory / "spritesheet.webp").read_bytes()
    old_manifest = (pet_directory / "pet.json").read_bytes()

    def reuse_verified_output(_image: Image.Image, destination: Path) -> None:
        shutil.copy2(built_pet / "spritesheet.webp", destination)

    def fail_review(*_args, **_kwargs) -> None:
        raise OSError("injected review failure")

    monkeypatch.setattr(builder, "_save_lossless_webp", reuse_verified_output)
    monkeypatch.setattr(builder, "_write_review", fail_review)

    with pytest.raises(OSError, match="injected review failure"):
        builder.build_complete_showcase(
            root=repo_root,
            background=repo_root
            / "work/nangongwan-action-showcase-450px/background.png",
            pet_directory=pet_directory,
            archive_directory=tmp_path / "archive",
            review_directory=tmp_path / "review",
        )

    assert (pet_directory / "spritesheet.webp").read_bytes() == old_atlas
    assert (pet_directory / "pet.json").read_bytes() == old_manifest
    assert not (tmp_path / "archive").exists()
    assert not (tmp_path / "review").exists()
