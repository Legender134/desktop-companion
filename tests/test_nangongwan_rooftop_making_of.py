import json
import struct
import subprocess
import sys
from dataclasses import replace
from functools import lru_cache
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw


_marker_config = getattr(pytest.mark, "_config", None)
if _marker_config is not None:
    _marker_config.addinivalue_line("markers", "integration: exercises the FFmpeg render pipeline")

from tools import nangongwan_rooftop_making_of as making_of
from tools import render_nangongwan_rooftop_making_of as renderer
from tools.nangongwan_rooftop_making_of import (
    ActionSource,
    ShotSpec,
    TimedFrames,
    burn_ass_and_add_silence,
    concat_shots,
    compose_desktop,
    extract_dense_review_proxy,
    extract_review_frames,
    read_action,
    render_shot,
    review_proxy_timestamps,
    run_ffmpeg,
    validate_master,
    write_ass,
    write_action_mp4,
)
from tools.render_nangongwan_rooftop_making_of import (
    build_frame_schedule,
    build_video_plan,
    quantize_subtitle_events,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def synthetic_timed_frames():
    return TimedFrames(
        frames=(
            Image.new("RGBA", (192, 208), (70, 110, 170, 255)),
            Image.new("RGBA", (192, 208), (110, 150, 210, 255)),
        ),
        durations_ms=(200, 300),
    )


def test_run_ffmpeg_raises_with_command_and_stderr(monkeypatch):
    def fail(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, b"", b"bad filter")

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(RuntimeError, match="bad filter") as error:
        run_ffmpeg(["ffmpeg", "-version"])

    assert "['ffmpeg', '-version']" in str(error.value)


def test_renderer_cli_is_directly_runnable_from_the_checkout():
    command = [sys.executable, "tools/render_nangongwan_rooftop_making_of.py", "--help"]

    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    assert completed.returncode == 0, completed.stderr
    assert "--build-all" in completed.stdout
    assert "--validate-only" in completed.stdout


def _valid_master_probe():
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "profile": "High",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
                "avg_frame_rate": "30/1",
                "nb_read_frames": "8400",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
            },
        ],
        "format": {"duration": "280.000"},
    }


def test_probe_injection_cannot_certify_a_nonexistent_master(tmp_path):
    approved_plan = build_video_plan(ROOT)

    report = validate_master(tmp_path / "master.mp4", approved_plan, probe=_valid_master_probe())

    assert report["checks"]["masterExists"] is False
    assert report["checks"]["audioSamplesEffectivelySilent"] is False
    assert report["checks"]["faststart"] is False
    assert report["allPassed"] is False


@pytest.mark.parametrize(
    ("mutate", "failed_gate"),
    (
        (lambda probe: probe["streams"].append(dict(probe["streams"][0])), "streamCount"),
        (lambda probe: probe["streams"][0].update(profile="Main"), "videoProfile"),
        (lambda probe: probe["streams"][0].update(sample_aspect_ratio="4:3"), "sampleAspectRatio"),
        (lambda probe: probe["streams"][0].update(nb_read_frames="8399"), "videoFrameCount"),
        (lambda probe: probe["streams"][0].pop("profile"), "videoProfile"),
        (lambda probe: probe["streams"][0].pop("sample_aspect_ratio"), "sampleAspectRatio"),
        (lambda probe: probe["streams"][0].pop("nb_read_frames"), "videoFrameCount"),
        (lambda probe: probe["streams"][0].update(avg_frame_rate="30/0"), "videoFrameRate"),
    ),
)
def test_validation_rejects_non_delivery_media_properties(tmp_path, mutate, failed_gate):
    probe = _valid_master_probe()
    mutate(probe)

    report = validate_master(tmp_path / "master.mp4", build_video_plan(ROOT), probe=probe)

    assert report["allPassed"] is False
    assert report["checks"][failed_gate] is False


def test_validation_fails_closed_on_malformed_stream_records(tmp_path):
    probe = _valid_master_probe()
    probe["streams"][0] = "not-a-stream-object"

    report = validate_master(tmp_path / "master.mp4", build_video_plan(ROOT), probe=probe)

    assert report["checks"]["streamCount"] is False
    assert report["allPassed"] is False


@pytest.mark.parametrize(
    "forbidden_source",
    (
        "anime-reference/clip.mp4",
        "DO-NOT-PUBLISH/still.png",
        "local-install-backup/pet.json",
        "private-reference/frame.webp",
        "setup.exe",
        "pet.reg",
        "setup.exe.backup/readme.txt",
        "pet.reg.txt",
    ),
)
def test_validation_rejects_forbidden_private_or_install_sources(
    tmp_path, forbidden_source
):
    plan = build_video_plan(ROOT)
    first_chapter = plan.chapters[0]
    unsafe_source = tmp_path / forbidden_source
    unsafe_source.parent.mkdir(parents=True, exist_ok=True)
    unsafe_source.write_bytes(b"test fixture")
    first_shot = replace(first_chapter.shots[0], source=unsafe_source)
    unsafe_plan = replace(
        plan,
        chapters=(
            replace(first_chapter, shots=(first_shot, *first_chapter.shots[1:])),
            *plan.chapters[1:],
        ),
    )

    report = validate_master(tmp_path / "master.mp4", unsafe_plan, probe=_valid_master_probe())

    assert report["privateAnimeUsed"] is ("anime-reference" in forbidden_source)
    assert report["checks"]["sourceProvenance"] is False
    assert report["allPassed"] is False


@pytest.mark.parametrize(
    "leaked_text",
    (
        r"C:\Users\alice\secret.txt",
        r"D:\workspace\release",
        "https://github.com/alice/project",
        "token=super-secret-value",
        "0123456789abcdef0123456789abcdef",
        "gitee.com/alice/project",
        "username: alice",
    ),
)
def test_validation_scans_public_text_but_not_internal_source_paths(tmp_path, leaked_text):
    plan = build_video_plan(ROOT)
    first_chapter = plan.chapters[0]
    unsafe_shot = replace(first_chapter.shots[0], caption=leaked_text)
    unsafe_plan = replace(
        plan,
        chapters=(
            replace(first_chapter, shots=(unsafe_shot, *first_chapter.shots[1:])),
            *plan.chapters[1:],
        ),
    )

    report = validate_master(tmp_path / "master.mp4", unsafe_plan, probe=_valid_master_probe())

    assert report["privacyScanPassed"] is False
    assert report["checks"]["publicTextPrivacy"] is False
    assert report["allPassed"] is False


@pytest.mark.parametrize("sidecar", ("timeline", "ass"))
def test_validation_scans_public_strings_exported_to_rendered_sidecars(tmp_path, sidecar):
    master = tmp_path / "master.mp4"
    timeline = tmp_path / "master-v1-timeline.json"
    timeline.write_text(
        json.dumps(
            {
                "chapters": [],
                "subtitleEvents": [{"text": "safe caption"}],
                "voiceStatus": "pending",
            }
        ),
        encoding="utf-8",
    )
    ass = tmp_path / "master-v1.ass"
    ass.write_text(
        "Dialogue: 0,0:00:00.00,0:00:01.00,Caption,,0,0,0,,safe caption\n",
        encoding="utf-8",
    )
    leak = r"C:\Users\alice\secret.txt"
    if sidecar == "timeline":
        payload = json.loads(timeline.read_text(encoding="utf-8"))
        payload["subtitleEvents"][0]["text"] = leak
        timeline.write_text(json.dumps(payload), encoding="utf-8")
    else:
        ass.write_text(
            f"Dialogue: 0,0:00:00.00,0:00:01.00,Caption,,0,0,0,,{leak}\n",
            encoding="utf-8",
        )

    report = validate_master(master, build_video_plan(ROOT), probe=_valid_master_probe())

    assert report["privacyScanPassed"] is False
    assert report["checks"]["publicTextPrivacy"] is False


def test_validation_resolves_timeline_sources_as_internal_provenance_not_public_text(tmp_path):
    master = tmp_path / "master.mp4"
    unsafe = tmp_path / "private-reference" / "frame.webp"
    (tmp_path / "master-v1-timeline.json").write_text(
        json.dumps(
            {
                "chapters": [
                    {"title": "safe", "shots": [{"title": "safe", "caption": "safe", "source": str(unsafe)}]}
                ],
                "subtitleEvents": [],
            }
        ),
        encoding="utf-8",
    )

    report = validate_master(master, build_video_plan(ROOT), probe=_valid_master_probe())

    assert report["privacyScanPassed"] is True
    assert report["checks"]["sourceProvenance"] is False


def test_extract_review_frames_uses_required_offsets_and_builds_a_7_by_2_sheet(
    tmp_path, monkeypatch
):
    generated_offsets = []

    def fake_ffmpeg(command):
        offset = command[command.index("-ss") + 1]
        generated_offsets.append(offset)
        Image.new("RGB", (1920, 1080), (30, 60, 90)).save(Path(command[-1]))

    monkeypatch.setattr(making_of, "run_ffmpeg", fake_ffmpeg)

    frames, sheet = extract_review_frames(tmp_path / "master.mp4", tmp_path / "review")

    assert [path.name for path in frames] == [
        f"frame-{milliseconds:06d}.jpg" for milliseconds in making_of.REVIEW_FRAME_MILLISECONDS
    ]
    assert generated_offsets == [
        f"{milliseconds / 1000:.3f}" for milliseconds in making_of.REVIEW_FRAME_MILLISECONDS
    ]
    with Image.open(sheet) as contact_sheet:
        assert contact_sheet.size == (7 * 480, 2 * 300)


def test_review_extractors_remove_obsolete_frames_and_pages(tmp_path, monkeypatch):
    review = tmp_path / "review"
    dense = tmp_path / "dense"
    review.mkdir()
    dense.mkdir()
    (review / "frame-obsolete.jpg").write_bytes(b"stale")
    (review / "contact-sheet-old.jpg").write_bytes(b"stale")
    (dense / "proxy-obsolete.jpg").write_bytes(b"stale")
    (dense / "contact-sheet-99.jpg").write_bytes(b"stale")
    timeline = tmp_path / "timeline.json"
    timeline.write_text(
        json.dumps({"durationMs": 1_000, "chapters": [], "subtitleEvents": []}),
        encoding="utf-8",
    )

    def fake_ffmpeg(command):
        Image.new("RGB", (1920, 1080), (40, 70, 100)).save(Path(command[-1]))

    monkeypatch.setattr(making_of, "run_ffmpeg", fake_ffmpeg)
    extract_review_frames(tmp_path / "master.mp4", review, timestamps_ms=(0,))
    extract_dense_review_proxy(tmp_path / "master.mp4", timeline, dense)

    assert not (review / "frame-obsolete.jpg").exists()
    assert not (review / "contact-sheet-old.jpg").exists()
    assert not (dense / "proxy-obsolete.jpg").exists()
    assert not (dense / "contact-sheet-99.jpg").exists()


def _atom(kind, payload=b"", *, extended=False, to_eof=False):
    if to_eof:
        return struct.pack(">I4s", 0, kind) + payload
    if extended:
        return struct.pack(">I4sQ", 1, kind, 16 + len(payload)) + payload
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def test_faststart_parser_reads_only_top_level_atoms_and_supports_extended_sizes(tmp_path):
    misleading = tmp_path / "misleading.mp4"
    misleading.write_bytes(_atom(b"free", b"contains moov text") + _atom(b"mdat") + _atom(b"moov"))
    extended = tmp_path / "extended.mp4"
    extended.write_bytes(_atom(b"ftyp") + _atom(b"moov", extended=True) + _atom(b"mdat", to_eof=True))

    assert making_of._read_mp4_atom_order(misleading) is False
    assert making_of._read_mp4_atom_order(extended) is True


@pytest.mark.parametrize(
    "leak",
    (r"\\server\share\secret", r"\\?\C:\Users\alice\secret", r"\\.\pipe\private"),
)
def test_public_privacy_rejects_unc_and_windows_device_paths(leak):
    assert making_of._public_text_is_safe((leak,)) is False


def test_validation_scans_ffprobe_metadata_for_private_text(tmp_path):
    probe = _valid_master_probe()
    probe["format"]["tags"] = {
        "comment": r"\\server\share\private",
        "homepage": "private.example.net/person",
        "username": "alice",
    }

    report = validate_master(tmp_path / "master.mp4", build_video_plan(ROOT), probe=probe)

    assert report["checks"]["publicMetadataPrivacy"] is False
    assert report["privacyScanPassed"] is False


def test_dense_review_proxy_includes_every_second_and_every_shot_action_transition(tmp_path):
    plan = build_video_plan(ROOT)
    schedule = build_frame_schedule(plan)
    rendered_events = quantize_subtitle_events(
        plan.subtitle_events, plan=plan, frame_schedule=schedule
    )
    timeline_path = tmp_path / "master-v1-timeline.json"
    making_of.write_timeline_json(
        plan,
        timeline_path,
        frame_schedule=schedule,
        subtitle_events=rendered_events,
    )
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))

    timestamps = review_proxy_timestamps(timeline)

    assert set(range(0, 280_000, 1_000)).issubset(timestamps)
    assert all(
        round(shot[boundary]) in timestamps
        for chapter in timeline["chapters"]
        for shot in chapter["shots"]
        for boundary in ("renderedStartMs", "renderedEndMs")
        if shot[boundary] < 280_000
    )
    assert all(
        round(event[boundary]) in timestamps
        for event in timeline["subtitleEvents"]
        if event["style"] == "Action"
        for boundary in ("renderedStartMs", "renderedEndMs")
        if event[boundary] < 280_000
    )


def test_dense_review_proxy_writes_auditable_contact_sheet_pages(tmp_path, monkeypatch):
    timeline = {
        "durationMs": 3_000,
        "chapters": [
            {
                "shots": [
                    {
                        "renderedStartMs": 0,
                        "renderedEndMs": 1_500,
                    },
                    {
                        "renderedStartMs": 1_500,
                        "renderedEndMs": 3_000,
                    },
                ]
            }
        ],
        "subtitleEvents": [
            {
                "style": "Action",
                "renderedStartMs": 750,
                "renderedEndMs": 1_250,
            }
        ],
    }
    timeline_path = tmp_path / "timeline.json"
    timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

    def fake_ffmpeg(command):
        Image.new("RGB", (1920, 1080), (40, 70, 100)).save(Path(command[-1]))

    monkeypatch.setattr(making_of, "run_ffmpeg", fake_ffmpeg)

    frames, pages = extract_dense_review_proxy(
        tmp_path / "master.mp4", timeline_path, tmp_path / "dense"
    )

    assert len(frames) == len(review_proxy_timestamps(timeline)) == 6
    assert pages == (tmp_path / "dense" / "contact-sheet-01.jpg",)
    with Image.open(pages[0]) as page:
        assert page.size == (7 * 384, 4 * 240)


def test_manual_review_is_bound_transitively_to_exact_artifacts(tmp_path):
    master = tmp_path / "master.mp4"
    timeline = tmp_path / "master-v1-timeline.json"
    ass = tmp_path / "master-v1.ass"
    master.write_bytes(b"master")
    timeline.write_text("{}", encoding="utf-8")
    ass.write_text("ass", encoding="utf-8")
    required_dir = tmp_path / "review-frames"
    dense_dir = tmp_path / "dense-review-proxy"
    required_dir.mkdir()
    dense_dir.mkdir()
    required_artifact = required_dir / "frame-000000.jpg"
    dense_artifact = dense_dir / "proxy-000000.jpg"
    required_artifact.write_bytes(b"required")
    dense_artifact.write_bytes(b"dense")
    required_manifest = required_dir / "manifest.json"
    dense_manifest = dense_dir / "manifest.json"
    making_of.write_review_manifest(
        required_manifest,
        kind="required-frames",
        master=master,
        timeline=timeline,
        ass=ass,
        artifacts=(required_artifact,),
    )
    making_of.write_review_manifest(
        dense_manifest,
        kind="dense-proxy",
        master=master,
        timeline=timeline,
        ass=ass,
        artifacts=(dense_artifact,),
    )
    manual = {
        "passed": True,
        "method": "inspected exact required frames and every dense proxy page",
        "findings": [],
        "artifactBinding": making_of.build_review_binding(
            master, timeline, ass, required_manifest, dense_manifest
        ),
    }

    assert making_of.verify_manual_review_binding(
        manual, master, timeline, ass, required_manifest, dense_manifest
    )
    dense_artifact.write_bytes(b"changed after approval")
    assert not making_of.verify_manual_review_binding(
        manual, master, timeline, ass, required_manifest, dense_manifest
    )
    making_of.write_review_manifest(
        dense_manifest,
        kind="dense-proxy",
        master=master,
        timeline=timeline,
        ass=ass,
        artifacts=(dense_artifact,),
    )
    assert not making_of.verify_manual_review_binding(
        manual, master, timeline, ass, required_manifest, dense_manifest
    )


def test_validation_report_is_overwritten_as_in_progress_before_validation(tmp_path):
    output = tmp_path / "validation-report.json"
    output.write_text('{"allPassed": true}', encoding="utf-8")

    pending = making_of.write_in_progress_validation_report(output)

    assert pending["allPassed"] is False
    assert pending["status"] == "in-progress"
    assert json.loads(output.read_text(encoding="utf-8"))["allPassed"] is False


def _expected_timeline(tmp_path):
    plan = build_video_plan(ROOT)
    schedule = build_frame_schedule(plan)
    events = quantize_subtitle_events(plan.subtitle_events, plan=plan, frame_schedule=schedule)
    path = tmp_path / "expected.json"
    making_of.write_timeline_json(plan, path, frame_schedule=schedule, subtitle_events=events)
    return plan, events, json.loads(path.read_text(encoding="utf-8"))


def test_timeline_and_ass_must_match_independently_regenerated_expectations(tmp_path):
    _, events, expected = _expected_timeline(tmp_path)
    master = tmp_path / "master.mp4"
    actual_timeline = tmp_path / "master-v1-timeline.json"
    actual_ass = tmp_path / "master-v1.ass"
    actual_timeline.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
    write_ass(events, actual_ass)

    assert making_of._timeline_and_ass_checks(master, expected) == {
        "timelineMatchesPlan": True,
        "assMatchesTimeline": True,
    }

    actual_ass.write_text(
        actual_ass.read_text(encoding="utf-8-sig").replace("Style: Caption", "Style: Invalid"),
        encoding="utf-8-sig",
    )
    assert making_of._timeline_and_ass_checks(master, expected)["assMatchesTimeline"] is False
    write_ass(events, actual_ass)

    tampered = json.loads(json.dumps(expected))
    tampered["chapters"][0]["shots"][0]["durationMs"] += 1
    tampered["subtitleEvents"][0]["text"] = "coordinated stale edit"
    actual_timeline.write_text(json.dumps(tampered), encoding="utf-8")
    stale_events = list(events)
    stale_events[0] = replace(stale_events[0], text="coordinated stale edit")
    write_ass(tuple(stale_events), actual_ass)

    checks = making_of._timeline_and_ass_checks(master, expected)
    assert checks["timelineMatchesPlan"] is False
    assert checks["assMatchesTimeline"] is False


@pytest.mark.integration
def test_synthetic_shots_concatenate_with_chinese_ass_and_silent_aac(tmp_path):
    first_source = tmp_path / "first-action.mp4"
    second_source = tmp_path / "second-action.mp4"
    first_shot = tmp_path / "01-first.mp4"
    second_shot = tmp_path / "02-second.mp4"
    master_base = tmp_path / "master-base.mp4"
    ass = tmp_path / "master-v1.ass"
    master = tmp_path / "master.mp4"

    write_action_mp4(
        TimedFrames((Image.new("RGBA", (192, 208), (70, 110, 170, 255)),), (500,)),
        first_source,
    )
    write_action_mp4(
        TimedFrames((Image.new("RGBA", (192, 208), (110, 150, 210, 255)),), (500,)),
        second_source,
    )
    render_shot(ShotSpec("first", "video", 500, first_source), first_shot)
    render_shot(ShotSpec("second", "video", 500, second_source), second_shot)
    concat_shots((first_shot, second_shot), master_base)
    write_ass((making_of.SubtitleEvent(0, 1_000, "中文字幕", "Caption"),), ass)
    burn_ass_and_add_silence(master_base, ass, master)

    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(master)]
        )
    )
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    assert (video["width"], video["height"], video["codec_name"], video["pix_fmt"]) == (
        1920,
        1080,
        "h264",
        "yuv420p",
    )
    assert (audio["codec_name"], audio["sample_rate"], audio["channels"]) == ("aac", "48000", 2)
    assert float(probe["format"]["duration"]) == pytest.approx(1.0, abs=0.05)


def test_read_action_supports_cross_row_frames_and_exact_durations(tmp_path):
    atlas = Image.new("RGBA", (192 * 16, 208 * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(atlas)
    for linear, color in zip(
        (15, 16, 17), ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))
    ):
        row, column = divmod(linear, 16)
        draw.rectangle(
            (column * 192, row * 208, column * 192 + 191, row * 208 + 207),
            fill=color,
        )
    atlas_path = tmp_path / "atlas.webp"
    atlas.save(atlas_path, "WEBP", lossless=True)
    manifest_path = tmp_path / "pet.json"
    manifest_path.write_text(
        json.dumps(
            {
                "actions": {
                    "demo": {
                        "row": 0,
                        "startColumn": 15,
                        "frameCount": 3,
                        "frameDurations": [100, 200, 300],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    timed = read_action(ActionSource(atlas_path, manifest_path, "demo"))

    assert timed.durations_ms == (100, 200, 300)
    assert timed.duration_ms == 600
    assert [frame.getpixel((96, 104))[:3] for frame in timed.frames] == [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
    ]


def test_read_action_supports_a_cropped_strip_wider_than_a_full_atlas_row(tmp_path):
    atlas = Image.new("RGBA", (192 * 17, 208), (0, 0, 0, 0))
    ImageDraw.Draw(atlas).rectangle((192 * 16, 0, 192 * 17 - 1, 207), fill=(91, 45, 173, 255))
    atlas_path = tmp_path / "strip.webp"
    atlas.save(atlas_path, "WEBP", lossless=True)
    manifest_path = tmp_path / "action.json"
    manifest_path.write_text(
        json.dumps({"frameCount": 17, "frameMs": 100}), encoding="utf-8"
    )

    timed = read_action(
        ActionSource(
            atlas_path,
            manifest_path,
            "long-strip",
            manifest_kind="action",
            atlas_start_frame=0,
        )
    )

    assert len(timed.frames) == 17
    assert timed.frames[-1].getpixel((96, 104)) == (91, 45, 173, 255)


def test_compose_desktop_places_a_pet_on_the_960x540_taskbar_desktop():
    desktop = compose_desktop(Image.new("RGBA", (192, 208), (255, 0, 0, 255)))

    assert (desktop.mode, desktop.size) == ("RGB", (960, 540))
    assert desktop.getpixel((480, 255)) == (255, 0, 0)
    assert desktop.getpixel((398, 514)) != desktop.getpixel((20, 514))


def test_write_action_mp4_produces_960x540_h264_with_exact_length(
    tmp_path, synthetic_timed_frames
):
    output = tmp_path / "clip.mp4"

    write_action_mp4(synthetic_timed_frames, output)

    probe = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(output),
            ]
        )
    )
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"], video["codec_name"]) == (960, 540, "h264")
    assert abs(float(probe["format"]["duration"]) - synthetic_timed_frames.duration_ms / 1000) < 0.03


def _archived_transparent_rooftop_chestnut_frames() -> tuple[Image.Image, ...]:
    """Rebuild the immutable archive's character-and-roof layer without a moon."""

    from tools import build_nangongwan_moonlit_rooftop_state as rooftop
    from tools.preview_nangongwan_rooftop_moon_vote import _build_clips

    original_moon_builder = rooftop._prepared_local_moon
    rooftop._prepared_local_moon = lambda source, *, variant="current": Image.new(
        "RGBA", (192, 208), (0, 0, 0, 0)
    )
    try:
        manifest = json.loads(rooftop.MANIFEST_PATH.read_text(encoding="utf-8"))
        return _build_clips(manifest, "current")["rooftopChestnut"]
    finally:
        rooftop._prepared_local_moon = original_moon_builder


def _rgba_hash_under_mask(frame: Image.Image, mask: Image.Image) -> str:
    rgba = frame.convert("RGBA").tobytes()
    included = mask.tobytes()
    return sha256(
        b"".join(
            rgba[offset : offset + 4]
            for offset, value in zip(range(0, len(rgba), 4), included, strict=True)
            if value
        )
    ).hexdigest()


@lru_cache
def _rebuild_archived_moon_variant(action_name: str) -> tuple[Image.Image, ...]:
    """Build a variant from immutable source layers, never from its atlas."""

    from tools import build_nangongwan_moonlit_rooftop_state as rooftop
    from tools.preview_nangongwan_rooftop_moon_vote import _build_clips

    manifest = json.loads(rooftop.MANIFEST_PATH.read_text(encoding="utf-8"))
    if action_name == "moon_full":
        clips = _build_clips(manifest, "anime")
    else:
        history_path = (
            ROOT
            / "work"
            / "nangongwan-moonlit-rooftop-history"
            / "04-moon-background-variants"
            / "rebuild_moon_variants.py"
        )
        spec = spec_from_file_location("moon_variant_history", history_path)
        assert spec is not None and spec.loader is not None
        history = module_from_spec(spec)
        spec.loader.exec_module(history)
        moon_builder = {
            "moon_184": history._full_circle_184,
            "moon_232": history._cropped_disc_232,
        }[action_name]
        original_moon_builder = rooftop._prepared_local_moon

        def build_requested_moon(source: Image.Image, *, variant: str = "current") -> Image.Image:
            if variant == "anime":
                return moon_builder(source)
            return original_moon_builder(source, variant=variant)

        rooftop._prepared_local_moon = build_requested_moon
        try:
            clips = _build_clips(manifest, "anime")
        finally:
            rooftop._prepared_local_moon = original_moon_builder

    with Image.open(rooftop.ATLAS_PATH) as source:
        rebuilt = rooftop.extend_atlas(source.convert("RGBA"), clips)
    action = manifest["actions"]["rooftopChestnut"]
    start = action["row"] * 16 + action["startColumn"]
    return tuple(
        rebuilt.crop(
            (
                column * 192,
                row * 208,
                (column + 1) * 192,
                (row + 1) * 208,
            )
        )
        for row, column in (divmod(start + offset, 16) for offset in range(action["frameCount"]))
    )


def _assert_rebuild_matches_actual(
    actual: tuple[Image.Image, ...], expected: tuple[Image.Image, ...], mask: Image.Image
) -> None:
    assert len(actual) == len(expected) == 44
    assert tuple(_rgba_hash_under_mask(frame, mask) for frame in actual) == tuple(
        _rgba_hash_under_mask(frame, mask) for frame in expected
    )
    assert tuple(frame.tobytes() for frame in actual) == tuple(
        frame.tobytes() for frame in expected
    )


def _opaque_character_mask(frame: Image.Image, roof_alpha: Image.Image) -> Image.Image:
    foreground_alpha = frame.getchannel("A").tobytes()
    roof = roof_alpha.tobytes()
    return Image.frombytes(
        "L",
        frame.size,
        bytes(255 if alpha == 255 and not roof_alpha else 0 for alpha, roof_alpha in zip(foreground_alpha, roof, strict=True)),
    )


def test_three_moon_variants_share_character_motion_and_timing():
    plan = build_video_plan(ROOT)
    variants = [plan.action_sources[name] for name in ("moon_184", "moon_232", "moon_full")]
    timed = [read_action(source) for source in variants]

    assert {item.durations_ms for item in timed} == {timed[0].durations_ms}
    assert all(item.duration_ms == 8990 and len(item.frames) == 44 for item in timed)

    # This transparent layer is the common archived foreground used beneath all
    # three moon backgrounds. Its alpha union is calculated once and is used to
    # compare each actual atlas against its independently rebuilt source recipe.
    foregrounds = _archived_transparent_rooftop_chestnut_frames()
    foreground_mask = Image.new("L", (192, 208), 0)
    for frame in foregrounds:
        foreground_mask = ImageChops.lighter(foreground_mask, frame.getchannel("A"))
    expected = [_rebuild_archived_moon_variant(name) for name in ("moon_184", "moon_232", "moon_full")]
    for actual, rebuilt in zip((item.frames for item in timed), expected, strict=True):
        _assert_rebuild_matches_actual(actual, rebuilt, foreground_mask)

    from tools import build_nangongwan_moonlit_rooftop_state as rooftop

    with Image.open(rooftop.ROOF_PATH) as source:
        roof_alpha = rooftop._prepared_local_roof(source).getchannel("A")
    body_masks = tuple(_opaque_character_mask(frame, roof_alpha) for frame in foregrounds)
    assert all(mask.getbbox() is not None for mask in body_masks)
    body_hashes = [
        tuple(_rgba_hash_under_mask(frame, mask) for frame, mask in zip(item.frames, body_masks, strict=True))
        for item in timed
    ]
    assert body_hashes[0] == body_hashes[1] == body_hashes[2]


def test_moon_variant_rebuild_check_rejects_an_opaque_character_mutation():
    plan = build_video_plan(ROOT)
    actual = read_action(plan.action_sources["moon_184"]).frames
    mutated = list(actual)
    foreground = _archived_transparent_rooftop_chestnut_frames()[0]

    from tools import build_nangongwan_moonlit_rooftop_state as rooftop

    with Image.open(rooftop.ROOF_PATH) as source:
        body_mask = _opaque_character_mask(
            foreground, rooftop._prepared_local_roof(source).getchannel("A")
        )
    pixel = next(index for index, value in enumerate(body_mask.tobytes()) if value)
    y, x = divmod(pixel, 192)
    mutated[0] = actual[0].copy()
    red, green, blue, alpha = mutated[0].getpixel((x, y))
    mutated[0].putpixel((x, y), ((red + 1) % 256, green, blue, alpha))

    foreground_mask = Image.new("L", (192, 208), 0)
    for frame in _archived_transparent_rooftop_chestnut_frames():
        foreground_mask = ImageChops.lighter(foreground_mask, frame.getchannel("A"))
    with pytest.raises(AssertionError):
        _assert_rebuild_matches_actual(
            tuple(mutated), _rebuild_archived_moon_variant("moon_184"), foreground_mask
        )


def test_video_plan_has_the_approved_six_chapters_and_exact_duration():
    plan = build_video_plan(ROOT)
    assert [chapter.id for chapter in plan.chapters] == [
        "standing_chestnut",
        "cinematic_36",
        "anchored_48",
        "persistent_v1",
        "v9_small_moon",
        "moon_variants",
    ]
    assert [chapter.duration_ms for chapter in plan.chapters] == [
        18_000, 40_000, 40_000, 40_000, 87_000, 55_000
    ]
    assert plan.duration_ms == 280_000


def test_video_plan_never_reads_private_anime_or_rejected_failure_media():
    plan = build_video_plan(ROOT)
    source_text = "\n".join(str(path).lower() for path in plan.source_paths)
    assert "07-private-anime-reference-do-not-publish" not in source_text
    assert "anime-reference" not in source_text
    assert "rejected-transition" not in source_text
    assert "seat-anchor-diagnostic" not in source_text


def test_every_chapter_shot_sum_matches_approved_duration():
    plan = build_video_plan(ROOT)

    assert renderer.build_shots(ROOT) == tuple(
        shot for chapter in plan.chapters for shot in chapter.shots
    )
    for chapter in plan.chapters:
        assert sum(shot.duration_ms for shot in chapter.shots) == chapter.duration_ms


def test_chapter_frame_schedule_keeps_each_editorial_chapter_on_its_exact_30fps_boundary():
    schedule = build_frame_schedule(build_video_plan(ROOT))

    assert [chapter.frame_count for chapter in schedule] == [540, 1200, 1200, 1200, 2610, 1650]
    assert sum(chapter.frame_count for chapter in schedule) == 8400
    assert all(
        sum(shot.frame_count for shot in chapter.shots) == chapter.frame_count
        and all(shot.frame_count > 0 for shot in chapter.shots)
        for chapter in schedule
    )
    v9, moon = schedule[4:6]
    assert (v9.end_frame, moon.start_frame) == (6750, 6750)
    assert (v9.end_ms, moon.start_ms) == (225_000, 225_000)
    moon_actions = [
        shot for shot in moon.shots if shot.shot.id in {"moon-184", "moon-232", "moon-full"}
    ]
    assert [shot.frame_count for shot in moon_actions] == [270, 270, 270]
    assert next(shot for shot in moon.shots if shot.shot.id == "moon-compare").frame_count == 450


def test_rendered_timeline_and_subtitles_use_the_frame_schedule_without_title_action_collisions(tmp_path):
    plan = build_video_plan(ROOT)
    schedule = build_frame_schedule(plan)
    rendered_events = quantize_subtitle_events(
        plan.subtitle_events, plan=plan, frame_schedule=schedule
    )
    output = tmp_path / "master-v1-timeline.json"

    making_of.write_timeline_json(
        plan,
        output,
        frame_schedule=schedule,
        subtitle_events=rendered_events,
    )

    timeline = json.loads(output.read_text(encoding="utf-8"))
    v9, moon = timeline["chapters"][4:6]
    assert (v9["endFrame"], moon["startFrame"]) == (6750, 6750)
    assert (v9["renderedEndMs"], moon["renderedStartMs"]) == (225_000, 225_000)
    assert all(
        "startFrame" in shot and "endFrame" in shot
        for chapter in timeline["chapters"]
        for shot in chapter["shots"]
    )
    titles = [event for event in rendered_events if event.style == "Title"]
    actions = [event for event in rendered_events if event.style == "Action"]
    assert all(
        title.end_frame <= action.start_frame or action.end_frame <= title.start_frame
        for title in titles
        for action in actions
    )


def test_shot_scoped_subtitles_follow_every_allocated_shot_boundary_after_parity_adjustment(tmp_path):
    plan = build_video_plan(ROOT)
    schedule = build_frame_schedule(plan)
    rendered_events = quantize_subtitle_events(
        plan.subtitle_events, plan=plan, frame_schedule=schedule
    )
    allocated = {
        scheduled.shot.id: scheduled
        for chapter in schedule
        for scheduled in chapter.shots
    }
    output = tmp_path / "master-v1-timeline.json"
    making_of.write_timeline_json(
        plan,
        output,
        frame_schedule=schedule,
        subtitle_events=rendered_events,
    )

    scoped = [event for event in rendered_events if event.style in {"Title", "Caption", "Note"}]
    assert scoped
    for event in scoped:
        shot = allocated[event.shot_id]
        assert event.start_frame == shot.start_frame
        assert shot.start_frame < event.end_frame <= shot.end_frame
        if event.style in {"Caption", "Note"}:
            assert event.end_frame == shot.end_frame

    declared_shot_starts = {}
    cursor = 0
    for chapter in plan.chapters:
        for shot in chapter.shots:
            declared_shot_starts[shot.id] = cursor
            cursor += shot.duration_ms
    actions = [event for event in rendered_events if event.style == "Action"]
    assert actions
    for event in actions:
        shot = allocated[event.shot_id]
        declared = next(
            source
            for source in plan.subtitle_events
            if source.style == "Action" and source.shot_id == event.shot_id and source.text == event.text
        )
        relative_start = declared.start_ms - declared_shot_starts[event.shot_id]
        relative_end = declared.end_ms - declared_shot_starts[event.shot_id]
        assert (event.start_frame, event.end_frame) == (
            shot.start_frame + (relative_start * 30 + 500) // 1_000,
            shot.start_frame + (relative_end * 30 + 500) // 1_000,
        )
        assert shot.start_frame <= event.start_frame < event.end_frame <= shot.end_frame

    moon_cases = {
        "moon-232": (7110, 7380),
        "moon-full": (7380, 7650),
        "moon-compare": (7650, 8100),
    }
    for shot_id, expected in moon_cases.items():
        events = [event for event in scoped if event.shot_id == shot_id]
        assert events
        assert all((event.start_frame, event.end_frame) == expected for event in events if event.style == "Caption")
        assert all(event.start_frame == expected[0] for event in events if event.style == "Title")

    timeline = json.loads(output.read_text(encoding="utf-8"))
    timeline_scoped = [event for event in timeline["subtitleEvents"] if event.get("shotId")]
    assert all("startFrame" in event and "endFrame" in event for event in timeline_scoped)
    assert {
        (event["shotId"], event["startFrame"], event["endFrame"])
        for event in timeline_scoped
        if event["shotId"] in moon_cases and event["style"] == "Caption"
    } == {(shot_id, *frames) for shot_id, frames in moon_cases.items()}

    ass = tmp_path / "master-v1.ass"
    making_of.write_ass(rendered_events, ass)
    ass_text = ass.read_text(encoding="utf-8-sig")
    assert "Dialogue: 0,0:03:57.00,0:04:06.00,Caption" in ass_text
    assert "Dialogue: 0,0:04:06.00,0:04:15.00,Caption" in ass_text
    assert "Dialogue: 0,0:04:15.00,0:04:30.00,Caption" in ass_text


@pytest.mark.integration
def test_built_shots_match_the_exact_frame_schedule_and_v9_moon_boundary():
    master = renderer.build_master(ROOT)
    schedule = build_frame_schedule(build_video_plan(ROOT))
    output = ROOT / "work" / "nangongwan-rooftop-making-of-video"
    allocated_shots = tuple(shot for chapter in schedule for shot in chapter.shots)

    for allocated in allocated_shots:
        probe = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-count_frames",
                    "-show_entries",
                    "stream=nb_read_frames",
                    "-of",
                    "json",
                    str(output / "intermediates" / "shots" / f"{allocated.index:02d}-{allocated.shot.id}.mp4"),
                ]
            )
        )
        assert int(probe["streams"][0]["nb_read_frames"]) == allocated.frame_count

    master_probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(master)]
        )
    )
    video = next(stream for stream in master_probe["streams"] if stream["codec_type"] == "video")
    assert int(video["nb_frames"]) == 8400
    timeline = json.loads((output / "master-v1-timeline.json").read_text(encoding="utf-8"))
    assert timeline["chapters"][4]["endFrame"] == timeline["chapters"][5]["startFrame"] == 6750


def test_v9_caption_explains_sequential_demo_vs_random_runtime():
    plan = build_video_plan(ROOT)
    chapter = next(item for item in plan.chapters if item.id == "v9_small_moon")
    captions = "\n".join(shot.caption for shot in chapter.shots)

    assert "九种动作会按权重随机出现" in captions
    assert "演示视频为方便观看而依次播放" in captions


def test_v9_overview_uses_clean_desktop_qa_instead_of_a_checkerboard_audit():
    shot = next(shot for shot in renderer.build_shots(ROOT) if shot.id == "v9-grid")

    assert isinstance(shot.source, Path)
    assert shot.source.name == "desktop-background-qa-v5.png"
    assert shot.title == "桌面背景适配抽查"
    assert "Windows、浅色与深色桌面" in shot.caption


def test_public_text_is_privacy_safe():
    plan = build_video_plan(ROOT)
    text = "\n".join(
        shot.title + "\n" + shot.caption
        for chapter in plan.chapters
        for shot in chapter.shots
    )
    forbidden = ("c:\\users", "d:\\workspace", "gitee", "github token", "私人令牌")

    assert not any(value in text.lower() for value in forbidden)


def test_ass_writer_uses_editable_styles_and_escapes_dialogue_text(tmp_path):
    output = tmp_path / "master-v1.ass"

    making_of.write_ass(
        (
            making_of.SubtitleEvent(0, 1_250, "标题", "Title"),
            making_of.SubtitleEvent(1_250, 2_500, "换行\n{保留为文字}", "Action"),
        ),
        output,
    )

    content = output.read_text(encoding="utf-8-sig")
    assert "PlayResX: 1920" in content
    assert "PlayResY: 1080" in content
    assert "Microsoft YaHei UI" in content
    assert "Style: Caption,Microsoft YaHei UI" in content
    assert ",76,76,76," in content
    assert "Style: Action,Microsoft YaHei UI" in content
    assert ",58,58,58," in content
    assert "Dialogue: 0,0:00:00.00,0:00:01.25,Title" in content
    assert "换行\\N\\{保留为文字\\}" in content
    assert making_of.ass_time(3_661_239) == "1:01:01.23"


def test_timeline_json_records_shots_subtitles_and_public_disclosures(tmp_path):
    plan = build_video_plan(ROOT)
    output = tmp_path / "master-v1-timeline.json"

    making_of.write_timeline_json(plan, output)

    timeline = json.loads(output.read_text(encoding="utf-8"))
    assert timeline["schemaVersion"] == 1
    assert timeline["durationMs"] == 280_000
    assert len(timeline["chapters"]) == 6
    assert timeline["voiceStatus"] == "pending-openai-api-key"
    assert timeline["aiVoiceDisclosureRequired"] is True
    assert timeline["privateAnimeUsed"] is False
    assert all("startMs" in shot and "endMs" in shot and "source" in shot
               for chapter in timeline["chapters"] for shot in chapter["shots"])
    assert any(event["style"] == "Action" for event in timeline["subtitleEvents"])


def test_v9_action_labels_follow_manifest_frame_durations_not_even_slices(tmp_path):
    plan = build_video_plan(ROOT)
    output = tmp_path / "master-v1-timeline.json"
    making_of.write_timeline_json(plan, output)
    timeline = json.loads(output.read_text(encoding="utf-8"))
    labels = [
        event
        for event in timeline["subtitleEvents"]
        if event["style"] == "Action" and event["text"] == "月下含栗"
    ]

    assert [(item["startMs"], item["endMs"]) for item in labels] == [
        (146_080, 155_070),
        (176_760, 185_750),
    ]


def test_cinematic_contact_sheet_uses_all_and_only_the_36_approved_action_frames():
    plan = build_video_plan(ROOT)
    source = plan.action_sources["cinematic"]
    source_frames = read_action(source).frames

    renderer.build_review_stills(ROOT)

    sheet_path = next(
        shot.source
        for chapter in plan.chapters
        for shot in chapter.shots
        if shot.id == "cinematic-sheet"
    )
    assert isinstance(sheet_path, Path)
    with Image.open(sheet_path) as source_sheet:
        sheet = source_sheet.convert("RGBA")
    assert len(source_frames) == 36
    assert sheet.size == (6 * 192, 6 * 208)
    assert sheet.crop((0, 0, 192, 208)).tobytes() == source_frames[0].tobytes()
    assert sheet.crop((5 * 192, 5 * 208, 6 * 192, 6 * 208)).tobytes() == source_frames[-1].tobytes()


def test_moon_comparison_uses_three_approved_rooftop_chestnut_frames_at_one_index():
    plan = build_video_plan(ROOT)
    renderer.build_review_stills(ROOT)
    comparison_path = next(
        shot.source
        for chapter in plan.chapters
        for shot in chapter.shots
        if shot.id == "moon-compare"
    )
    assert isinstance(comparison_path, Path)
    with Image.open(comparison_path) as source_comparison:
        comparison = source_comparison.convert("RGBA")

    assert comparison.size == (3 * 192, 208 + 36)
    frame_index = renderer.MOON_COMPARISON_FRAME_INDEX
    expected = [
        read_action(plan.action_sources[name]).frames[frame_index]
        for name in ("moon_184", "moon_232", "moon_full")
    ]
    actual = [
        comparison.crop((column * 192, 36, (column + 1) * 192, 36 + 208))
        for column in range(3)
    ]
    assert [frame.tobytes() for frame in actual] == [frame.tobytes() for frame in expected]


def test_v9_top_titles_never_overlap_top_action_labels():
    events = build_video_plan(ROOT).subtitle_events
    titles = [event for event in events if event.style == "Title"]
    actions = [event for event in events if event.style == "Action"]

    assert all(
        title.end_ms <= action.start_ms or action.end_ms <= title.start_ms
        for title in titles
        for action in actions
    )
