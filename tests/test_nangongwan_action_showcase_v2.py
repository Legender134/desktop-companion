from io import BytesIO
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageStat

import tools.nangongwan_action_showcase_v2 as showcase_module
import tools.render_nangongwan_action_showcase_v2 as render_module
from tools.render_nangongwan_action_showcase_v2 import (
    _timeline_document,
    build_showcase,
    build_showcase_plan,
)
from tools.nangongwan_action_showcase_v2 import (
    AudioProbe,
    BACKGROUND_SHA256,
    MediaProbe,
    SegmentFrames,
    ShowcasePlan,
    VideoProbe,
    add_silent_aac,
    concat_clips,
    copy_verified_background,
    extract_review_frames,
    probe_media,
    validate_showcase,
    write_silent_video,
)
from tools.nangongwan_rooftop_making_of import TimedFrames, read_action


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = Path(
    r"C:\Users\23644\AppData\Local\Temp\codex-clipboard-fa2f4101-2de0-4c4a-a1c9-01fc1c2a4412.png"
)
REAL_ENCODED_CENTER_SEQUENCE = showcase_module._encoded_center_sequence


@pytest.fixture
def showcase_plan():
    return build_showcase_plan(ROOT, BACKGROUND)


@pytest.fixture
def background_image():
    with Image.open(BACKGROUND) as source:
        return source.convert("RGB")


@pytest.fixture
def idle_frames(showcase_plan):
    return read_action(showcase_plan.segments[0].source.actions[0])


@pytest.fixture
def tiny_segments():
    return tuple(
        SegmentFrames(
            tuple(Image.new("RGB", (1600, 900), color) for _ in range(15))
        )
        for color in ((20, 40, 80), (80, 40, 20))
    )


def test_validation_requires_every_v2_gate(valid_showcase_fixture):
    report = validate_showcase(**valid_showcase_fixture)
    assert report["allPassed"] is True
    assert report["checks"] == {
        "backgroundHash": True,
        "segmentOrder": True,
        "segmentFrameCounts": True,
        "totalFrames": True,
        "videoGeometry": True,
        "videoEncoding": True,
        "silentAudio": True,
        "noTextSidecarsOrStreams": True,
        "sourcePrivacy": True,
        "sourceIntegrity": True,
        "renderGeometry": True,
        "centeredComposition": True,
        "moonFrameParity": True,
    }


def _decoded_frame_md5s(path: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-f",
            "framemd5",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return tuple(
        line.rsplit(",", 1)[-1].strip()
        for line in completed.stdout.splitlines()
        if line and not line.startswith("#")
    )


def test_two_segment_encode_has_exact_frames_and_no_subtitle_stream(
    tmp_path, tiny_segments
):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    joined = tmp_path / "joined.mp4"
    final = tmp_path / "final.mp4"
    write_silent_video(tiny_segments[0].frames, first, expected_frames=15)
    write_silent_video(tiny_segments[1].frames, second, expected_frames=15)
    concat_clips((first, second), joined)
    add_silent_aac(joined, final, expected_frames=30)

    probe = probe_media(final, count_frames=True)

    assert probe.video.nb_read_frames == 30
    assert probe.video.width == 1600 and probe.video.height == 900
    assert probe.video.codec == "h264" and probe.video.profile == "High"
    assert probe.video.pixel_format == "yuv420p"
    assert probe.video.sample_aspect_ratio == "1:1"
    assert probe.video.frame_rate == Fraction(30, 1)
    assert probe.audio is not None
    assert probe.audio.codec == "aac" and probe.audio.sample_rate == 48000
    assert probe.audio.channels == 2
    assert probe.subtitle_streams == 0
    assert probe.data_streams == 0
    assert _decoded_frame_md5s(final) == (
        *_decoded_frame_md5s(first),
        *_decoded_frame_md5s(second),
    )


def test_450px_timeline_records_source_and_render_geometry(showcase_plan):
    timeline = _timeline_document(showcase_plan, BACKGROUND_SHA256)

    assert timeline["schemaVersion"] == 2
    assert timeline["backgroundSha256"] == BACKGROUND_SHA256
    assert timeline["frameSize"] == [1600, 900]
    assert timeline["sourceSpriteSize"] == [192, 208]
    assert timeline["renderedSpriteRectangle"] == {
        "x": 575,
        "y": 206,
        "width": 450,
        "height": 488,
    }
    assert timeline["renderScale"] == {"numerator": 75, "denominator": 32}
    assert "spriteRectangle" not in timeline
    assert timeline["totalFrames"] == 2473
    assert len(timeline["sourceSha256"]) == 16
    assert all(
        set(asset) == {"id", "role", "sha256"}
        and not Path(asset["id"]).is_absolute()
        for asset in timeline["sourceSha256"]
    )
    assert len(timeline["segments"]) == 15
    assert [entry["startFrame"] for entry in timeline["segments"]] == [
        0,
        *[entry["endFrame"] for entry in timeline["segments"][:-1]],
    ]
    assert timeline["segments"][-1]["endFrame"] == 2473
    assert all(
        set(entry)
        == {
            "id",
            "sourceActionIds",
            "startFrame",
            "endFrame",
            "outputFrames",
            "sourceDurationMs",
        }
        for entry in timeline["segments"]
    )
    serialized = json.dumps(timeline).lower()
    assert all(field not in serialized for field in ("title", "caption", "text"))


def test_timeline_render_geometry_rejects_legacy_native_rectangle():
    document = {
        "schemaVersion": 2,
        "sourceSpriteSize": [192, 208],
        "renderedSpriteRectangle": {
            "x": 704,
            "y": 346,
            "width": 192,
            "height": 208,
        },
        "renderScale": {"numerator": 75, "denominator": 32},
    }

    detail = showcase_module._timeline_render_geometry(document)

    assert detail["passed"] is False


def test_450px_output_names_are_isolated_from_existing_v2():
    assert render_module._OUTPUT_DIRECTORY == (
        Path("work") / "nangongwan-action-showcase-450px"
    )
    assert render_module._MASTER_NAME == (
        "nangongwan-action-showcase-450px-1600x900.mp4"
    )
    assert "nangongwan-action-showcase-v2" not in str(
        render_module._OUTPUT_DIRECTORY
    )


def test_build_showcase_publishes_450px_without_touching_existing_v2(
    tmp_path, monkeypatch
):
    old_output = tmp_path / "work" / "nangongwan-action-showcase-v2"
    old_output.mkdir(parents=True)
    sentinel = old_output / "sentinel.bin"
    sentinel.write_bytes(b"keep-the-small-version")
    old_inventory = tuple(
        path.relative_to(old_output) for path in old_output.rglob("*")
    )

    def fake_build(root, background, staging):
        master = staging / render_module._MASTER_NAME
        master.write_bytes(b"staged")
        return master

    def fake_validate(root, background_source=None, **kwargs):
        output = kwargs["output_directory"]
        return output / render_module._MASTER_NAME, output / "validation-report.json"

    def fake_publish(staging, output):
        output.mkdir(parents=True)
        (output / render_module._MASTER_NAME).write_bytes(b"published")

    monkeypatch.setattr(render_module, "_build_showcase_directory", fake_build)
    monkeypatch.setattr(render_module, "_validate_final_showcase", fake_validate)
    monkeypatch.setattr(render_module, "_publish_staged_directory", fake_publish)

    result = render_module.build_showcase(tmp_path, tmp_path / "background.png")

    assert result == (
        tmp_path
        / "work"
        / "nangongwan-action-showcase-450px"
        / "nangongwan-action-showcase-450px-1600x900.mp4"
    )
    assert sentinel.read_bytes() == b"keep-the-small-version"
    assert tuple(
        path.relative_to(old_output) for path in old_output.rglob("*")
    ) == old_inventory


def test_build_showcase_directory_writes_only_background_clips_timeline_and_master(
    tmp_path, monkeypatch, showcase_plan
):
    encoded_clips = []

    monkeypatch.setattr(
        "tools.render_nangongwan_action_showcase_v2.build_showcase_plan",
        lambda root, background_source: showcase_plan,
    )
    monkeypatch.setattr(
        "tools.render_nangongwan_action_showcase_v2.iter_segment_frames",
        lambda segment, background: iter((background.copy(),) * segment.output_frames),
    )

    def fake_encode(frames, output, *, expected_frames):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"clip")
        encoded_clips.append((output.name, expected_frames))

    monkeypatch.setattr(
        "tools.render_nangongwan_action_showcase_v2.write_silent_video", fake_encode
    )
    monkeypatch.setattr(
        "tools.render_nangongwan_action_showcase_v2.concat_clips",
        lambda clips, output: output.write_bytes(b"joined"),
    )
    monkeypatch.setattr(
        "tools.render_nangongwan_action_showcase_v2.add_silent_aac",
        lambda video, output, expected_frames: output.write_bytes(b"final"),
    )

    output = tmp_path / "isolated-build"
    master = render_module._build_showcase_directory(tmp_path, BACKGROUND, output)
    assert master == output / render_module._MASTER_NAME
    assert len(encoded_clips) == 15
    assert [frame_count for _, frame_count in encoded_clips] == [
        segment.output_frames for segment in showcase_plan.segments
    ]
    assert (output / "background.png").read_bytes() == BACKGROUND.read_bytes()
    assert (output / "timeline.json").is_file()
    assert not tuple(output.rglob("*.ass"))
    assert not (output / "review").exists()


def test_render_cli_can_run_directly_from_the_repository_root():
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "render_nangongwan_action_showcase_v2.py"),
            "--help",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--build-all" in completed.stdout
    assert "--validate-only" in completed.stdout


def _test_video_probe(frame_count: int, *, pixel_format: str = "yuv420p") -> VideoProbe:
    return VideoProbe(
        width=1600,
        height=900,
        codec="h264",
        profile="High",
        pixel_format=pixel_format,
        sample_aspect_ratio="1:1",
        frame_rate=Fraction(30, 1),
        nb_read_frames=frame_count,
        average_frame_rate=Fraction(30, 1),
        time_base=Fraction(1, 15_360),
        duration=Fraction(frame_count, 30),
    )


def _valid_master_media_probe(
    *, audio_duration: Fraction = Fraction(2473, 30), other_streams: int = 0
) -> MediaProbe:
    return MediaProbe(
        _test_video_probe(2473),
        AudioProbe("aac", 48_000, 2, audio_duration),
        0,
        0,
        other_streams,
    )


@pytest.fixture
def valid_showcase_fixture(tmp_path, monkeypatch, showcase_plan):
    output = tmp_path / render_module._OUTPUT_DIRECTORY
    output.mkdir(parents=True)
    master = output / render_module._MASTER_NAME
    master.write_bytes(b"synthetic master")
    timeline = output / "timeline.json"
    timeline.write_text(
        json.dumps(_timeline_document(showcase_plan, BACKGROUND_SHA256)),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        showcase_module,
        "probe_media",
        lambda path, count_frames=False: _valid_master_media_probe(),
    )
    monkeypatch.setattr(
        showcase_module, "_read_mp4_atom_order", lambda path: True, raising=False
    )
    monkeypatch.setattr(
        showcase_module,
        "_probe_video_timestamps",
        lambda path, expected_frames: {
            "passed": True,
            "frameCount": expected_frames,
            "firstPts": 0,
            "lastPts": (expected_frames - 1) * 512,
            "step": 512,
            "firstMismatchFrame": None,
        },
        raising=False,
    )
    monkeypatch.setattr(
        showcase_module,
        "_measure_audio_silence",
        lambda path: {"passed": True, "maxVolumeDbfs": -91.0},
        raising=False,
    )
    monkeypatch.setattr(
        showcase_module,
        "_encoded_background_fidelity",
        lambda master, background, timeline_document: {
            "passed": True,
            "minimumSsim": 0.999,
            "threshold": 0.995,
        },
        raising=False,
    )
    monkeypatch.setattr(
        showcase_module,
        "_centered_composition",
        lambda plan, background: {"passed": True, "sampledFrames": 45},
        raising=False,
    )
    monkeypatch.setattr(
        showcase_module,
        "_iter_decoded_center_frames",
        lambda master: showcase_module._iter_expected_center_frames(
            showcase_plan, showcase_plan.background_source
        ),
        raising=False,
    )
    monkeypatch.setattr(
        showcase_module,
        "_encoded_center_sequence",
        lambda master, plan, background: {
            "passed": True,
            "framesCompared": 2473,
            "minimumPsnrDb": 40.0,
            "failedFrameCount": 0,
            "firstFailedFrame": None,
        },
    )
    return {"master": master, "plan": showcase_plan, "timeline": timeline}


def test_validation_fails_closed_when_encoded_background_check_errors(
    valid_showcase_fixture, monkeypatch
):
    def decode_failure(master, background, timeline_document):
        raise RuntimeError("decode failed")

    monkeypatch.setattr(
        showcase_module, "_encoded_background_fidelity", decode_failure
    )

    report = validate_showcase(**valid_showcase_fixture)

    assert report["allPassed"] is False
    assert report["checks"]["backgroundHash"] is False


def test_outside_sprite_ssim_is_one_for_identical_background(background_image):
    assert showcase_module._outside_sprite_ssim(background_image, background_image) == pytest.approx(
        1.0, abs=1e-12
    )


@pytest.mark.parametrize("alteration", ("overwrite", "repeat-earlier-action"))
def test_validation_rejects_altered_or_repeated_encoded_center_frame(
    valid_showcase_fixture, monkeypatch, alteration
):
    monkeypatch.setattr(showcase_module, "RENDERED_SPRITE_SIZE", (32, 24))

    def synthetic_frame(index):
        return Image.new(
            "RGB",
            showcase_module.RENDERED_SPRITE_SIZE,
            ((index * 37) % 256, (index * 73) % 256, (index * 109) % 256),
        )

    def expected_center_frames(plan, background):
        for index in range(2473):
            yield synthetic_frame(index)

    def altered_center_frames(master):
        for index in range(2473):
            frame = synthetic_frame(index)
            if index == 523:
                if alteration == "overwrite":
                    changed = frame.copy()
                    changed.paste((255, 255, 255), (4, 6, 28, 18))
                    yield changed
                else:
                    yield synthetic_frame(45)
            else:
                yield frame

    monkeypatch.setattr(
        showcase_module, "_iter_expected_center_frames", expected_center_frames
    )
    monkeypatch.setattr(
        showcase_module, "_iter_decoded_center_frames", altered_center_frames
    )
    monkeypatch.setattr(
        showcase_module, "_encoded_center_sequence", REAL_ENCODED_CENTER_SEQUENCE
    )

    report = validate_showcase(**valid_showcase_fixture)

    assert report["allPassed"] is False
    assert report["checks"]["centeredComposition"] is False
    encoded = report["details"]["centeredComposition"]["encodedSequence"]
    assert encoded["framesCompared"] == 2473
    assert encoded["failedFrameCount"] >= 1
    assert encoded["firstFailedFrame"] == 523


def test_validation_checks_privacy_before_reading_any_forbidden_source(
    tmp_path, monkeypatch, showcase_plan
):
    forbidden_background = tmp_path / "DO-NOT-PUBLISH" / "background.png"
    forbidden_sequence = tmp_path / "anime-reference" / "sequence.json"
    private_plan = ShowcasePlan(
        forbidden_background, showcase_plan.segments, (forbidden_sequence,)
    )
    timeline = tmp_path / "timeline.json"
    timeline.write_text(
        json.dumps(_timeline_document(showcase_plan, BACKGROUND_SHA256)),
        encoding="utf-8",
    )
    master = tmp_path / "master.mp4"
    master.write_bytes(b"not media")
    forbidden_reads = []
    source_operations = []
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def guarded_read_bytes(path, *args, **kwargs):
        if any(marker in str(path).lower() for marker in ("anime-reference", "do-not-publish")):
            forbidden_reads.append(path)
        return original_read_bytes(path, *args, **kwargs)

    def guarded_read_text(path, *args, **kwargs):
        if any(marker in str(path).lower() for marker in ("anime-reference", "do-not-publish")):
            forbidden_reads.append(path)
        return original_read_text(path, *args, **kwargs)

    def forbidden_read_action(source):
        source_operations.append(source)
        raise AssertionError("source-derived reads must be short-circuited")

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    monkeypatch.setattr(showcase_module, "read_action", forbidden_read_action)

    report = validate_showcase(master, private_plan, timeline)

    assert report["allPassed"] is False
    assert report["checks"]["sourcePrivacy"] is False
    assert report["checks"]["backgroundHash"] is False
    assert report["checks"]["centeredComposition"] is False
    assert forbidden_reads == []
    assert source_operations == []


@pytest.mark.parametrize("damage", ("gap", "malformed"))
def test_validation_rejects_noncontinuous_or_malformed_timeline_boundaries(
    valid_showcase_fixture, damage
):
    timeline = valid_showcase_fixture["timeline"]
    document = json.loads(timeline.read_text(encoding="utf-8"))
    if damage == "gap":
        document["segments"][4]["startFrame"] += 1
    else:
        document["segments"][4]["endFrame"] = "not-an-integer"
    timeline.write_text(json.dumps(document), encoding="utf-8")

    report = validate_showcase(**valid_showcase_fixture)

    assert report["allPassed"] is False
    assert report["checks"]["totalFrames"] is False


def test_validation_rejects_invalid_fast_start_atom_order(
    valid_showcase_fixture, monkeypatch
):
    monkeypatch.setattr(showcase_module, "_read_mp4_atom_order", lambda path: False)

    report = validate_showcase(**valid_showcase_fixture)

    assert report["allPassed"] is False
    assert report["checks"]["videoEncoding"] is False


def test_validation_rejects_audible_audio(valid_showcase_fixture, monkeypatch):
    monkeypatch.setattr(
        showcase_module,
        "_measure_audio_silence",
        lambda path: {"passed": False, "maxVolumeDbfs": -18.0},
    )

    report = validate_showcase(**valid_showcase_fixture)

    assert report["allPassed"] is False
    assert report["checks"]["silentAudio"] is False


def test_validation_rejects_a_one_second_silent_audio_track(
    valid_showcase_fixture, monkeypatch
):
    monkeypatch.setattr(
        showcase_module,
        "probe_media",
        lambda path, count_frames=False: _valid_master_media_probe(
            audio_duration=Fraction(1, 1)
        ),
    )

    report = validate_showcase(**valid_showcase_fixture)

    assert report["allPassed"] is False
    assert report["checks"]["silentAudio"] is False
    assert report["details"]["audio"]["durationAligned"] is False


def test_validation_rejects_attachment_or_unknown_streams(
    valid_showcase_fixture, monkeypatch
):
    monkeypatch.setattr(
        showcase_module,
        "probe_media",
        lambda path, count_frames=False: _valid_master_media_probe(other_streams=1),
    )

    report = validate_showcase(**valid_showcase_fixture)

    assert report["allPassed"] is False
    assert report["checks"]["noTextSidecarsOrStreams"] is False
    assert report["details"]["textStreamsAndSidecars"]["otherStreams"] == 1


def test_probe_media_reports_audio_duration_and_unknown_stream_count(
    tmp_path, monkeypatch
):
    document = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1600,
                "height": 900,
                "codec_name": "h264",
                "profile": "High",
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "time_base": "1/15360",
                "duration_ts": "1266176",
                "duration": "82.433333333333333333",
                "nb_read_frames": "2473",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "duration": "82.432000",
            },
            {"codec_type": "attachment", "codec_name": "ttf"},
        ]
    }
    monkeypatch.setattr(showcase_module, "_probe_document", lambda *args, **kwargs: document)

    probe = probe_media(tmp_path / "master.mp4", count_frames=True)

    assert probe.audio is not None
    assert probe.audio.duration == Fraction("82.432000")
    assert probe.other_streams == 1


def test_extract_review_frames_uses_every_segment_boundary_and_builds_15_by_3_sheet(
    tmp_path, monkeypatch, showcase_plan
):
    timeline = tmp_path / "timeline.json"
    timeline_document = _timeline_document(showcase_plan, BACKGROUND_SHA256)
    timeline.write_text(json.dumps(timeline_document), encoding="utf-8")
    extracted_indices = []

    def fake_extract(master, frame_indices, destinations):
        extracted_indices.extend(frame_indices)
        for index, destination in zip(frame_indices, destinations, strict=True):
            quotient = index // 256
            color = (
                (index * 37 + quotient * 17) % 256,
                (index * 73 + quotient * 79) % 256,
                (index * 109 + quotient * 131) % 256,
            )
            Image.new("RGB", (1600, 900), color).save(destination)

    monkeypatch.setattr(
        showcase_module, "_extract_selected_frames", fake_extract, raising=False
    )

    frames = extract_review_frames(
        tmp_path / "master.mp4", timeline, tmp_path / "review"
    )

    entries = timeline_document["segments"]
    expected_indices = tuple(
        index
        for position in ("first", "middle", "last")
        for entry in entries
        for index in (
            {
                "first": entry["startFrame"],
                "middle": (entry["startFrame"] + entry["endFrame"] - 1) // 2,
                "last": entry["endFrame"] - 1,
            }[position],
        )
    )
    assert tuple(extracted_indices) == tuple(sorted(expected_indices))
    assert len(frames) == 45
    assert frames[0].name == "01-blink-00-first.png"
    assert frames[15].name == "01-blink-00-middle.png"
    assert frames[-1].name == "15-blink-07-last.png"
    assert all(Image.open(frame).size == (1600, 900) for frame in frames)
    with Image.open(tmp_path / "review" / "contact-sheet.jpg") as sheet:
        assert sheet.size == (15 * 320, 3 * 180)
        for cell_index, frame_path in enumerate(frames):
            column = cell_index % 15
            row = cell_index // 15
            actual = sheet.crop(
                (column * 320, row * 180, (column + 1) * 320, (row + 1) * 180)
            )
            with Image.open(frame_path) as frame:
                expected = frame.convert("RGB").resize((320, 180), Image.Resampling.LANCZOS)
            difference = ImageStat.Stat(ImageChops.difference(actual, expected))
            assert max(difference.mean) < 3.0, frame_path.name


@pytest.fixture
def existing_validation_output(tmp_path, monkeypatch, showcase_plan):
    output = tmp_path / render_module._OUTPUT_DIRECTORY
    clips_directory = output / "clips"
    clips_directory.mkdir(parents=True)
    copy_verified_background(BACKGROUND, output / "background.png")
    (output / "timeline.json").write_text(
        json.dumps(_timeline_document(showcase_plan, BACKGROUND_SHA256)),
        encoding="utf-8",
    )
    clips = tuple(
        clips_directory / f"{index:02d}-{segment.id}.mp4"
        for index, segment in enumerate(showcase_plan.segments, start=1)
    )
    clip_probes = {}
    for clip, segment in zip(clips, showcase_plan.segments, strict=True):
        clip.write_bytes(b"clip")
        clip_probes[clip] = MediaProbe(
            _test_video_probe(segment.output_frames), None, 0, 0
        )
    master = output / render_module._MASTER_NAME
    master.write_bytes(b"master")
    master_probe = MediaProbe(
        _test_video_probe(showcase_plan.total_frames),
        AudioProbe("aac", 48_000, 2, Fraction(showcase_plan.total_frames, 30)),
        0,
        0,
    )

    monkeypatch.setattr(
        render_module,
        "build_showcase_plan",
        lambda root, background_source: showcase_plan,
    )
    monkeypatch.setattr(
        render_module,
        "probe_media",
        lambda path, count_frames=False: (
            master_probe if path == master else clip_probes[path]
        ),
    )
    return {
        "root": tmp_path,
        "output": output,
        "clips": clips,
        "clip_probes": clip_probes,
    }


@pytest.mark.parametrize("failure", ("frame-count", "stream"))
def test_validate_existing_rejects_a_clip_with_wrong_frames_or_stream(
    existing_validation_output, failure
):
    clip = existing_validation_output["clips"][3]
    if failure == "frame-count":
        video = _test_video_probe(274)
    else:
        video = _test_video_probe(273, pixel_format="yuv444p")
    existing_validation_output["clip_probes"][clip] = MediaProbe(video, None, 0, 0)

    with pytest.raises(ValueError, match="clip"):
        render_module._validate_existing(existing_validation_output["root"], BACKGROUND)


def test_validate_existing_rejects_an_extra_mp4_clip(existing_validation_output):
    (existing_validation_output["output"] / "clips" / "stale.mp4").write_bytes(b"stale")

    with pytest.raises(ValueError, match="clip"):
        render_module._validate_existing(existing_validation_output["root"], BACKGROUND)


def test_validate_existing_rejects_any_subtitle_sidecar(existing_validation_output):
    review = existing_validation_output["output"] / "review"
    review.mkdir()
    (review / "stale.srt").write_text("subtitle", encoding="utf-8")

    with pytest.raises(ValueError, match="subtitle"):
        render_module._validate_existing(existing_validation_output["root"], BACKGROUND)


def test_blink_is_exactly_fifteen_frames_and_returns_to_open_pose(idle_frames):
    blink = showcase_module.make_blink(idle_frames)

    assert len(blink.frames) == 15
    assert [frame.tobytes() for frame in blink.frames] == [
        idle_frames.frames[index].tobytes()
        for index in (0, 0, 0, 1, 2, 3, 2, 1, 0, 0, 0, 0, 0, 0, 0)
    ]


def test_450px_render_geometry_is_exactly_centered():
    assert showcase_module.SOURCE_SPRITE_SIZE == (192, 208)
    assert showcase_module.RENDERED_SPRITE_SIZE == (450, 488)
    assert showcase_module.RENDERED_SPRITE_ORIGIN == (575, 206)
    assert showcase_module.RENDERED_SPRITE_BOX == (575, 206, 1025, 694)
    assert showcase_module.RENDER_SCALE == Fraction(75, 32)
    x, y = showcase_module.RENDERED_SPRITE_ORIGIN
    width, height = showcase_module.RENDERED_SPRITE_SIZE
    assert (x + width / 2, y + height / 2) == (800, 450)


def test_scale_sprite_uses_fixed_premultiplied_lanczos_without_hidden_color_fringe():
    sprite = Image.new(
        "RGBA", showcase_module.SOURCE_SPRITE_SIZE, (255, 0, 0, 0)
    )
    ImageDraw.Draw(sprite).rectangle((48, 52, 143, 155), fill=(0, 255, 0, 255))
    original = sprite.tobytes()

    scaled = showcase_module.scale_sprite(sprite)

    assert scaled.mode == "RGBA"
    assert scaled.size == (450, 488)
    assert sprite.tobytes() == original
    antialiased = [
        pixel for pixel in scaled.get_flattened_data() if 0 < pixel[3] < 255
    ]
    assert antialiased
    assert all(red == 0 and blue == 0 for red, _, blue, _ in antialiased)


def test_compose_frame_changes_only_the_450px_center_rectangle():
    background = Image.effect_noise((1600, 900), 80).convert("RGB")
    sprite = Image.new("RGBA", (192, 208), (200, 50, 80, 128))

    composed = showcase_module.compose_frame(background, sprite)

    changed_bounds = ImageChops.difference(background, composed).getbbox()
    assert changed_bounds is not None
    assert changed_bounds == (575, 206, 1025, 694)
    assert background.crop((575, 206, 1025, 694)).tobytes() != composed.crop(
        (575, 206, 1025, 694)
    ).tobytes()


def test_decoded_center_crop_uses_450px_geometry():
    assert showcase_module._rendered_sprite_crop_filter() == (
        "crop=450:488:575:206:exact=1"
    )


def test_resample_action_uses_cumulative_duration_midpoints_and_endpoint_frames():
    frames = tuple(
        Image.new("RGBA", (192, 208), (value, 0, 0, 255))
        for value in (10, 20, 30)
    )
    timed = TimedFrames(frames, (10, 20, 70))

    resampled = showcase_module.resample_action(timed, 5)

    assert [frame.getpixel((0, 0))[0] for frame in resampled.frames] == [10, 30, 30, 30, 30]


@pytest.mark.parametrize(
    ("timed", "output_frames"),
    (
        (TimedFrames((Image.new("RGBA", (192, 208)),), (100,)), 0),
        (TimedFrames((Image.new("RGBA", (192, 208)),), (100,)), -1),
        (TimedFrames((), ()), 1),
        (TimedFrames((Image.new("RGBA", (192, 208)),), ()), 1),
        (TimedFrames((Image.new("RGBA", (191, 208)),), (100,)), 1),
    ),
)
def test_resample_action_rejects_invalid_output_and_native_frame_inputs(
    timed, output_frames
):
    with pytest.raises(ValueError):
        showcase_module.resample_action(timed, output_frames)


def test_moon_segments_use_one_identical_source_index_mapping(
    monkeypatch, showcase_plan, background_image
):
    durations = (200,) * 43 + (390,)
    synthetic = TimedFrames(
        tuple(
            Image.new("RGBA", (192, 208), (index, 0, 0, 255))
            for index in range(len(durations))
        ),
        durations,
    )
    monkeypatch.setattr(showcase_module, "read_action", lambda source: synthetic)
    monkeypatch.setattr(showcase_module, "compose_frame", lambda background, sprite: sprite)
    moon_segments = tuple(
        segment
        for segment in showcase_plan.segments
        if segment.id in {"moon-184", "moon-232", "moon-full"}
    )

    mappings = {
        segment.id: tuple(
            frame.getpixel((0, 0))[0]
            for frame in showcase_module.iter_segment_frames(segment, background_image)
        )
        for segment in moon_segments
    }
    expected = []
    cumulative = 0
    for index, duration in enumerate(durations):
        cumulative += duration
        expected.append(cumulative)
    expected_mapping = tuple(
        next(
            source_index
            for source_index, source_end in enumerate(expected)
            if source_end * 540 > (2 * output_index + 1) * 8_990
        )
        for output_index in range(270)
    )
    expected_mapping = (0, *expected_mapping[1:-1], len(durations) - 1)

    assert mappings["moon-184"] == expected_mapping
    assert mappings["moon-184"] == mappings["moon-232"] == mappings["moon-full"]


def test_all_segment_frame_counts_and_moon_mapping_are_exact(
    monkeypatch, showcase_plan, background_image
):
    monkeypatch.setattr(
        showcase_module, "compose_frame", lambda background, sprite: sprite.copy()
    )
    built_counts = {
        segment.id: sum(
            1
            for _ in showcase_module.iter_segment_frames(segment, background_image)
        )
        for segment in showcase_plan.segments
    }

    assert {key: built_counts[key] for key in ("moon-184", "moon-232", "moon-full")} == {
        "moon-184": 270,
        "moon-232": 270,
        "moon-full": 270,
    }
    assert all(
        built_counts[segment.id] == segment.output_frames
        for segment in showcase_plan.segments
    )


def test_showcase_plan_has_exact_fifteen_segments_and_output_frames():
    plan = build_showcase_plan(ROOT, BACKGROUND)

    assert [segment.id for segment in plan.segments] == [
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
    assert [segment.output_frames for segment in plan.segments] == [
        15,
        62,
        15,
        273,
        15,
        288,
        15,
        920,
        15,
        270,
        15,
        270,
        15,
        270,
        15,
    ]
    assert plan.total_frames == 2473


def test_copy_verified_background_rejects_wrong_pixels(tmp_path):
    wrong = tmp_path / "wrong.png"
    Image.new("RGB", (1600, 900), "black").save(wrong)

    with pytest.raises(ValueError, match="background SHA-256"):
        copy_verified_background(wrong, tmp_path / "background.png")


def test_copy_verified_background_uses_only_its_initial_source_byte_snapshot(
    tmp_path, monkeypatch
):
    original_read_bytes = Path.read_bytes
    original_open = showcase_module.Image.open
    source_reads = 0

    def read_bytes_once(path: Path) -> bytes:
        nonlocal source_reads
        if path == BACKGROUND:
            source_reads += 1
            if source_reads > 1:
                return b"replacement bytes"
        return original_read_bytes(path)

    def open_verified_bytes(source, *args, **kwargs):
        if source != output:
            assert isinstance(source, BytesIO)
        return original_open(source, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes_once)
    monkeypatch.setattr(showcase_module.Image, "open", open_verified_bytes)

    output = tmp_path / "background.png"
    assert copy_verified_background(BACKGROUND, output).lower() == (
        "1bca26d93bf3126b3c8be30e2b5f944b4912a4032ac55990b72cfb3d99ba745a"
    )
    assert output.read_bytes() == original_read_bytes(BACKGROUND)
    assert source_reads == 1


def test_showcase_plan_rejects_a_private_resolved_v9_preview_path(monkeypatch):
    original_resolve = Path.resolve
    original_verified_background_pixels = render_module._verified_background_pixels
    background_reads = []

    def resolve_preview_as_private(path: Path, *args, **kwargs) -> Path:
        if path.name == "preview-sequence-v9.json":
            return Path(r"C:\anime-reference\preview-sequence-v9.json")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_preview_as_private)

    def record_background_read(path):
        background_reads.append(path)
        return original_verified_background_pixels(path)

    monkeypatch.setattr(
        render_module,
        "_verified_background_pixels",
        record_background_read,
    )

    with pytest.raises(ValueError, match="showcase source is not public"):
        build_showcase_plan(ROOT, BACKGROUND)
    assert background_reads == []


def test_showcase_plan_rejects_changed_moon_manifest_hash(
    monkeypatch,
):
    original_read_bytes = Path.read_bytes

    def read_one_changed_moon_manifest(path: Path, *args, **kwargs) -> bytes:
        encoded = original_read_bytes(path, *args, **kwargs)
        if path.name == "pet.json" and "03-cropped-disc-232" in path.parts:
            document = json.loads(encoded)
            durations = document["actions"]["rooftopChestnut"]["frameDurations"]
            durations[0] += 10
            durations[1] -= 10
            return json.dumps(document).encode("utf-8")
        return encoded

    monkeypatch.setattr(Path, "read_bytes", read_one_changed_moon_manifest)

    with pytest.raises(ValueError, match="source SHA-256"):
        build_showcase_plan(ROOT, BACKGROUND)


def test_showcase_plan_binds_every_approved_input_to_fixed_sha256_inventory(
    showcase_plan,
):
    relative_inventory = {
        asset.path.relative_to(ROOT).as_posix(): asset.sha256
        for asset in showcase_plan.source_inventory
        if asset.path != BACKGROUND
    }

    assert relative_inventory == {
        "work/nangongwan-moonlit-rooftop-history/01-cinematic-36f-v2.4.1/pet.json": "a4397d9d4d0caeb338ecbfbae88d4c9ada457c5c50c507d2d77eb7d5fb922964",
        "work/nangongwan-moonlit-rooftop-history/01-cinematic-36f-v2.4.1/spritesheet.webp": "990d1ee9db3632102e9f07984301519606a9cc3591585e8ef892d0ba975a9d3e",
        "work/nangongwan-moonlit-rooftop-history/02-anchored-48f-v1/complete-archive/pet.json": "3edd549ff49be95758b531ff15dbdeabee1ce44f0dedb4065fcb8e23e7e10bf3",
        "work/nangongwan-moonlit-rooftop-history/02-anchored-48f-v1/complete-archive/spritesheet.webp": "d224d16c48beea73516a9eb02e4da4543dfbbd2af7bf96cf10efbf7ff11f0d52",
        "work/nangongwan-moonlit-rooftop-history/03-persistent-rooftop-revisions/render-history-v2-v9/preview-sequence-v9.json": "ce818923d127ba78facd81f8a2ff6afefcccd37319df3325774a0568154fe0fa",
        "work/nangongwan-moonlit-rooftop-history/04-moon-background-variants/01-small-moon-current/pet.json": "c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131",
        "work/nangongwan-moonlit-rooftop-history/04-moon-background-variants/01-small-moon-current/spritesheet.webp": "564793e6c2e090d8e882cc4a829ceccb9bde2ab98b54b9f6126c65cf41fac77e",
        "work/nangongwan-moonlit-rooftop-history/04-moon-background-variants/02-full-circle-184/pet.json": "c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131",
        "work/nangongwan-moonlit-rooftop-history/04-moon-background-variants/02-full-circle-184/spritesheet.webp": "117b5bcf84e9dbdc45b5ef13590fe3726667823178b5a603e0e83e527902fa5a",
        "work/nangongwan-moonlit-rooftop-history/04-moon-background-variants/03-cropped-disc-232/pet.json": "c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131",
        "work/nangongwan-moonlit-rooftop-history/04-moon-background-variants/03-cropped-disc-232/spritesheet.webp": "6f671f19463dd4f6bf293550ad05c24b6e18c851d98264dd3548b0dc5d5cbb92",
        "work/nangongwan-moonlit-rooftop-history/04-moon-background-variants/04-full-frame-moon-surface/pet.json": "c9622eb87d0f5cc3c5ec275e8ef4e017ed639b23e6ce8e31026d822e3f24d131",
        "work/nangongwan-moonlit-rooftop-history/04-moon-background-variants/04-full-frame-moon-surface/spritesheet.webp": "03393672e282e5bdcca3fea5f9d58928e0775fb42802e1c10b9a11d1d1e15abe",
        "work/nangongwan-moonlit-rooftop-history/06-standing-chestnut-easter-egg/action.json": "687da2a94210ac5d6907061b5ddd9d39e16d2f51719e311807179eaf01c70d9f",
        "work/nangongwan-moonlit-rooftop-history/06-standing-chestnut-easter-egg/standing-chestnut-10frames.webp": "9bb9c75b86b82e8903abc8b9099e1be51b5972d72243b6d6c5f10c74a41b275e",
    }
    assert next(
        asset.sha256
        for asset in showcase_plan.source_inventory
        if asset.path == BACKGROUND
    ) == BACKGROUND_SHA256


def test_showcase_plan_rejects_changed_source_hash_before_parsing_sources(monkeypatch):
    target = (
        ROOT
        / "work"
        / "nangongwan-moonlit-rooftop-history"
        / "04-moon-background-variants"
        / "01-small-moon-current"
        / "spritesheet.webp"
    )
    original_read_bytes = Path.read_bytes
    original_loads = render_module.json.loads
    parse_calls = []

    def changed_bytes(path: Path) -> bytes:
        encoded = original_read_bytes(path)
        return encoded + b"tampered" if path == target else encoded

    def record_parse(*args, **kwargs):
        parse_calls.append(args[0])
        return original_loads(*args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)
    monkeypatch.setattr(render_module.json, "loads", record_parse)

    with pytest.raises(ValueError, match="source SHA-256"):
        build_showcase_plan(ROOT, BACKGROUND)
    assert parse_calls == []


def test_validation_rejects_a_source_changed_after_plan_binding(
    valid_showcase_fixture, monkeypatch
):
    plan = valid_showcase_fixture["plan"]
    target = next(asset.path for asset in plan.source_inventory if asset.role == "atlas")
    original_read_bytes = Path.read_bytes

    def changed_bytes(path: Path) -> bytes:
        encoded = original_read_bytes(path)
        return encoded + b"tampered" if path == target else encoded

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)

    report = validate_showcase(**valid_showcase_fixture)

    assert report["allPassed"] is False
    assert report["checks"]["sourceIntegrity"] is False
    assert report["details"]["sourceIntegrity"]["mismatches"][0]["path"] == str(
        target.resolve()
    )


def test_encoded_background_fidelity_checks_every_frame_and_catches_one_frame_overlay(
    tmp_path,
):
    with Image.open(BACKGROUND) as source:
        background = source.convert("RGB")
    background_path = tmp_path / "background.png"
    background.save(background_path)
    clean = tmp_path / "clean.mp4"
    altered = tmp_path / "altered.mp4"
    write_silent_video(
        (background.copy() for _ in range(3)), clean, expected_frames=3
    )
    altered_frames = [background.copy() for _ in range(3)]
    altered_frames[1].paste((255, 0, 255), (40, 40, 300, 220))
    write_silent_video(iter(altered_frames), altered, expected_frames=3)

    clean_result = showcase_module._encoded_background_fidelity(
        clean, background_path, {"totalFrames": 3}
    )
    altered_result = showcase_module._encoded_background_fidelity(
        altered, background_path, {"totalFrames": 3}
    )

    assert clean_result["passed"] is True
    assert clean_result["framesChecked"] == 3
    assert clean_result["regionFrameCounts"] == {
        "top": 3,
        "bottom": 3,
        "left": 3,
        "right": 3,
    }
    assert altered_result["passed"] is False
    assert altered_result["framesChecked"] == 3
    assert altered_result["firstFailedFrame"] == 1


def test_center_validation_rejects_real_adjacent_frame_repetition(
    showcase_plan, monkeypatch
):
    previous = None
    repeated_frame = None
    repeated_index = None
    for index, current in enumerate(
        showcase_module._iter_expected_center_frames(
            showcase_plan, showcase_plan.background_source
        )
    ):
        if (
            previous is not None
            and current.tobytes() != previous.tobytes()
            and showcase_module._center_frame_psnr(current, previous) >= 29.0
            and showcase_module._frame_rms_difference(current, previous) > 3.0
        ):
            repeated_index = index
            repeated_frame = previous.copy()
            break
        previous = current
    assert repeated_index is not None and repeated_frame is not None

    def actual_frames(master):
        for index, frame in enumerate(
            showcase_module._iter_expected_center_frames(
                showcase_plan, showcase_plan.background_source
            )
        ):
            yield repeated_frame.copy() if index == repeated_index else frame

    monkeypatch.setattr(showcase_module, "_iter_decoded_center_frames", actual_frames)

    result = REAL_ENCODED_CENTER_SEQUENCE(
        Path("synthetic.mp4"), showcase_plan, showcase_plan.background_source
    )

    assert result["passed"] is False
    assert result["firstFailedFrame"] == repeated_index
    assert result["contentMismatchFrameCount"] >= 1


def test_center_validation_accepts_lossy_subpixel_motion_when_current_frame_wins(
    monkeypatch,
):
    monkeypatch.setattr(showcase_module, "RENDERED_SPRITE_SIZE", (40, 40))
    expected_previous = Image.new("RGB", (40, 40), (100, 100, 100))
    expected_current = expected_previous.copy()
    ImageDraw.Draw(expected_current).rectangle(
        (0, 0, 19, 19), fill=(101, 101, 101)
    )
    actual_previous = expected_previous.copy()
    ImageDraw.Draw(actual_previous).rectangle(
        (0, 0, 11, 19), fill=(101, 101, 101)
    )
    ImageDraw.Draw(actual_previous).rectangle(
        (12, 0, 12, 9), fill=(101, 101, 101)
    )
    actual_current = actual_previous.copy()
    actual_current.putpixel((12, 10), (101, 101, 101))
    actual_current.putpixel((12, 11), (101, 101, 101))

    result = showcase_module._compare_center_sequences(
        iter((expected_previous, expected_current)),
        iter((actual_previous, actual_current)),
        expected_frames=2,
    )

    assert showcase_module._frame_rms_difference(
        expected_current, expected_previous
    ) < 1.0
    assert result["observedMinimumTemporalRatio"] < 0.1
    assert result["passed"] is True
    assert result["toleratedSubthresholdTemporalFrames"] == [1]


def test_center_validation_rejects_h264_encoded_adjacent_frame_repetition(
    tmp_path, showcase_plan
):
    expected_pair = None
    previous = None
    for current in showcase_module._iter_expected_center_frames(
        showcase_plan, showcase_plan.background_source
    ):
        if (
            previous is not None
            and current.tobytes() != previous.tobytes()
            and showcase_module._center_frame_psnr(current, previous) >= 29.0
            and showcase_module._frame_rms_difference(current, previous) > 3.0
        ):
            expected_pair = (previous.copy(), current.copy())
            break
        previous = current
    assert expected_pair is not None
    with Image.open(showcase_plan.background_source) as source:
        background = source.convert("RGB")

    def full_frame(center):
        frame = background.copy()
        frame.paste(center, showcase_module.RENDERED_SPRITE_ORIGIN)
        return frame

    clean = tmp_path / "clean-center.mp4"
    repeated = tmp_path / "repeated-center.mp4"
    write_silent_video(
        (full_frame(center) for center in expected_pair),
        clean,
        expected_frames=2,
    )
    write_silent_video(
        (full_frame(expected_pair[0]) for _ in range(2)),
        repeated,
        expected_frames=2,
    )

    clean_result = showcase_module._compare_center_sequences(
        iter(expected_pair),
        showcase_module._iter_decoded_center_frames(clean),
        expected_frames=2,
    )
    repeated_result = showcase_module._compare_center_sequences(
        iter(expected_pair),
        showcase_module._iter_decoded_center_frames(repeated),
        expected_frames=2,
    )

    assert clean_result["passed"] is True
    assert repeated_result["passed"] is False
    assert repeated_result["firstFailedFrame"] == 1
    assert repeated_result["contentMismatchFrameCount"] == 1


class _SinglePassFrames:
    def __init__(self, frames, *, failure: Exception | None = None):
        self._frames = iter(frames)
        self._failure = failure
        self.iterated = False
        self.closed = False

    def __iter__(self):
        if self.iterated:
            raise AssertionError("frame source was iterated more than once")
        self.iterated = True
        return self

    def __next__(self):
        try:
            return next(self._frames)
        except StopIteration:
            if self._failure is not None:
                failure, self._failure = self._failure, None
                raise failure
            raise

    def close(self):
        self.closed = True


def test_write_silent_video_accepts_a_single_pass_iterator_with_explicit_count(
    tmp_path,
):
    source = _SinglePassFrames(
        (
            Image.new("RGB", (1600, 900), (20, 40, 80)),
            Image.new("RGB", (1600, 900), (80, 40, 20)),
        )
    )
    output = tmp_path / "single-pass.mp4"

    write_silent_video(source, output, expected_frames=2)

    assert source.iterated is True
    assert source.closed is True
    assert probe_media(output, count_frames=True).video.nb_read_frames == 2


@pytest.mark.parametrize("damage", ("short", "long", "failure"))
def test_write_silent_video_enforces_count_and_cleans_failed_stream(
    tmp_path, damage
):
    frame = Image.new("RGB", (1600, 900), (20, 40, 80))
    if damage == "short":
        source = _SinglePassFrames((frame,))
    elif damage == "long":
        source = _SinglePassFrames((frame, frame, frame))
    else:
        source = _SinglePassFrames((frame,), failure=RuntimeError("producer failed"))
    output = tmp_path / f"{damage}.mp4"
    output.write_bytes(b"stale")

    with pytest.raises((ValueError, RuntimeError)):
        write_silent_video(source, output, expected_frames=2)

    assert source.closed is True
    assert not output.exists()


def test_failed_rebuild_invalidates_acceptance_but_preserves_previous_publication(
    tmp_path, monkeypatch
):
    output = tmp_path / render_module._OUTPUT_DIRECTORY
    review = output / "review"
    review.mkdir(parents=True)
    (output / render_module._MASTER_NAME).write_bytes(b"old master")
    (output / "timeline.json").write_text("old timeline", encoding="utf-8")
    (output / "validation-report.json").write_text(
        json.dumps({"allPassed": True}), encoding="utf-8"
    )
    (review / "contact-sheet.jpg").write_bytes(b"old review")

    def fail_build(root, background, staging):
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "mixed-new-file").write_bytes(b"partial")
        raise RuntimeError("interrupted build")

    monkeypatch.setattr(render_module, "_build_showcase_directory", fail_build, raising=False)

    with pytest.raises(RuntimeError, match="interrupted"):
        build_showcase(tmp_path, BACKGROUND)

    assert (output / render_module._MASTER_NAME).read_bytes() == b"old master"
    assert (output / "timeline.json").read_text(encoding="utf-8") == "old timeline"
    assert not (output / "validation-report.json").exists()
    assert not review.exists()
    assert not tuple(
        (tmp_path / "work").glob(
            f".{render_module._OUTPUT_DIRECTORY.name}-staging-*"
        )
    )


def test_failed_staging_validation_never_publishes_mixed_outputs(
    tmp_path, monkeypatch
):
    output = tmp_path / render_module._OUTPUT_DIRECTORY
    output.mkdir(parents=True)
    (output / render_module._MASTER_NAME).write_bytes(b"old master")
    (output / "validation-report.json").write_text(
        json.dumps({"allPassed": True}), encoding="utf-8"
    )

    def staged_build(root, background, staging):
        (staging / render_module._MASTER_NAME).write_bytes(b"new unapproved master")
        return staging / render_module._MASTER_NAME

    def failed_validation(*args, **kwargs):
        staging = kwargs["output_directory"]
        (staging / "validation-report.json").write_text(
            json.dumps({"allPassed": False}), encoding="utf-8"
        )
        raise ValueError("staging validation failed")

    monkeypatch.setattr(render_module, "_build_showcase_directory", staged_build)
    monkeypatch.setattr(render_module, "_validate_final_showcase", failed_validation)

    with pytest.raises(ValueError, match="staging validation failed"):
        build_showcase(tmp_path, BACKGROUND)

    assert (output / render_module._MASTER_NAME).read_bytes() == b"old master"
    assert not (output / "validation-report.json").exists()
    assert b"new unapproved" not in b"".join(
        path.read_bytes() for path in output.rglob("*") if path.is_file()
    )


def _write_synthetic_publishable_staging(staging: Path) -> None:
    master = staging / render_module._MASTER_NAME
    background = staging / "background.png"
    timeline = staging / "timeline.json"
    clips = staging / "clips"
    review = staging / "review"
    clips.mkdir()
    review.mkdir()
    master.write_bytes(b"new")
    background.write_bytes(b"background")
    segments = [{"id": f"segment-{index:02d}"} for index in range(1, 16)]
    timeline.write_text(json.dumps({"segments": segments}), encoding="utf-8")
    for index, segment in enumerate(segments, start=1):
        (clips / f"{index:02d}-{segment['id']}.mp4").write_bytes(b"clip")
    for index in range(45):
        (review / f"frame-{index:02d}.png").write_bytes(b"frame")
    contact_sheet = review / "contact-sheet.jpg"
    contact_sheet.write_bytes(b"sheet")
    report = {
        "allPassed": True,
        "artifactSha256": {
            "master": sha256(master.read_bytes()).hexdigest(),
            "background": sha256(background.read_bytes()).hexdigest(),
            "timeline": sha256(timeline.read_bytes()).hexdigest(),
        },
        "review": {
            "frameCount": 45,
            "contactSheetSha256": sha256(contact_sheet.read_bytes()).hexdigest(),
        },
    }
    (staging / "validation-report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )


def test_atomic_directory_publication_restores_previous_output_on_rename_failure(
    tmp_path, monkeypatch
):
    output = tmp_path / "published"
    staging = tmp_path / "staging"
    output.mkdir()
    staging.mkdir()
    (output / "master.mp4").write_bytes(b"old")
    _write_synthetic_publishable_staging(staging)
    original_replace = Path.replace

    def fail_staging_publish(path: Path, target: Path):
        if path == staging and target == output:
            raise OSError("simulated publish failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_staging_publish)

    with pytest.raises(OSError, match="publish failure"):
        render_module._publish_staged_directory(staging, output)

    assert (output / "master.mp4").read_bytes() == b"old"
    assert not (output / "validation-report.json").exists()
    assert not tuple(tmp_path.glob(".published-backup-*"))


def test_atomic_directory_publication_replaces_the_complete_output_set(tmp_path):
    output = tmp_path / "published"
    staging = tmp_path / "staging"
    output.mkdir()
    staging.mkdir()
    (output / "old-only").write_bytes(b"old")
    _write_synthetic_publishable_staging(staging)

    render_module._publish_staged_directory(staging, output)

    assert not (output / "old-only").exists()
    assert (output / render_module._MASTER_NAME).read_bytes() == b"new"
    assert json.loads((output / "validation-report.json").read_text(encoding="utf-8"))[
        "allPassed"
    ] is True
    assert not tuple(tmp_path.glob(".published-backup-*"))


def test_successful_publication_is_not_reversed_by_backup_cleanup_failure(
    tmp_path, monkeypatch
):
    output = tmp_path / "published"
    staging = tmp_path / "staging"
    output.mkdir()
    staging.mkdir()
    (output / "old-only").write_bytes(b"old")
    _write_synthetic_publishable_staging(staging)
    original_rmtree = render_module.shutil.rmtree

    def fail_only_backup_cleanup(path: Path, *args, **kwargs):
        if path.name.startswith(".published-backup-"):
            raise PermissionError("simulated locked old publication")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(render_module.shutil, "rmtree", fail_only_backup_cleanup)

    render_module._publish_staged_directory(staging, output)

    assert not (output / "old-only").exists()
    assert (output / render_module._MASTER_NAME).read_bytes() == b"new"


def test_validate_only_uses_built_background_without_external_temp_source(
    existing_validation_output,
):
    master = render_module._validate_existing(
        existing_validation_output["root"], background_source=None
    )

    assert master == existing_validation_output["output"] / render_module._MASTER_NAME
    assert render_module._parser().parse_args(["--validate-only"]).background is None


def test_validation_rejects_nonuniform_decoded_video_pts(
    valid_showcase_fixture, monkeypatch
):
    monkeypatch.setattr(
        showcase_module,
        "_probe_video_timestamps",
        lambda path, expected_frames: {
            "passed": False,
            "frameCount": expected_frames,
            "firstPts": 0,
            "step": 512,
            "firstMismatchFrame": 200,
        },
        raising=False,
    )

    report = validate_showcase(**valid_showcase_fixture)

    assert report["allPassed"] is False
    assert report["checks"]["videoEncoding"] is False
    assert report["details"]["video"]["timestamps"]["firstMismatchFrame"] == 200


def test_probe_media_reports_exact_video_time_base_and_duration(tmp_path, monkeypatch):
    document = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1600,
                "height": 900,
                "codec_name": "h264",
                "profile": "High",
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "time_base": "1/15360",
                "duration_ts": "1266176",
                "duration": "82.433333333333333333",
                "nb_read_frames": "2473",
            }
        ]
    }
    monkeypatch.setattr(showcase_module, "_probe_document", lambda *args, **kwargs: document)

    probe = probe_media(tmp_path / "master.mp4", count_frames=True)

    assert probe.video.time_base == Fraction(1, 15_360)
    assert probe.video.duration == Fraction(2473, 30)
    assert probe.video.average_frame_rate == Fraction(30, 1)


def test_retained_moonlit_clis_default_to_archive_and_never_write_it():
    import tools.build_nangongwan_moonlit_chestnut as builder
    import tools.preview_nangongwan_moonlit_chestnut as previewer

    archive = ROOT / "tools" / "archives" / "nangongwan-moonlit-chestnut-anchored-v1"
    assert previewer.ATLAS_PATH == archive / "spritesheet.webp"
    assert previewer.MANIFEST_PATH == archive / "pet.json"
    assert builder.ATLAS_PATH == archive / "spritesheet.webp"
    assert builder.MANIFEST_PATH == archive / "pet.json"
    assert builder.OUTPUT_ATLAS_PATH.is_relative_to(ROOT / "work")
    assert builder.OUTPUT_ATLAS_PATH != builder.ATLAS_PATH
    assert "archived 48-frame" in previewer._parser().format_help().lower()
    assert "archived 48-frame" in builder._parser().format_help().lower()


@pytest.mark.parametrize(
    "script",
    (
        "tools/build_nangongwan_moonlit_chestnut.py",
        "tools/preview_nangongwan_moonlit_chestnut.py",
    ),
)
def test_retained_moonlit_clis_run_directly_from_the_repository_root(script):
    completed = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "archived 48-frame" in completed.stdout.lower()


@pytest.mark.parametrize("protected_kind", ("archive", "live"))
def test_retained_moonlit_clis_reject_any_output_inside_protected_trees(
    tmp_path, protected_kind
):
    import tools.build_nangongwan_moonlit_chestnut as builder
    import tools.preview_nangongwan_moonlit_chestnut as previewer

    protected_root = (
        builder.ARCHIVE_ROOT
        if protected_kind == "archive"
        else builder.LIVE_PET_ROOT
    )
    output_file = protected_root / "nested" / "candidate.webp"
    output_directory = protected_root / "nested" / "preview"

    with pytest.raises(ValueError, match="protected archive or live pet tree"):
        builder._validate_output_location(output_file)
    with pytest.raises(ValueError, match="protected archive or live pet tree"):
        previewer._validate_output_location(output_directory)

    safe_file = tmp_path / "candidate.webp"
    safe_directory = tmp_path / "preview"
    builder._validate_output_location(safe_file)
    previewer._validate_output_location(safe_directory)


@pytest.mark.parametrize("input_kind", ("atlas", "manifest"))
def test_retained_preview_rejects_transition_report_input_collision_before_writes(
    tmp_path, monkeypatch, input_kind
):
    import tools.preview_nangongwan_moonlit_chestnut as previewer

    output = tmp_path / "preview"
    output.mkdir()
    collision = output / "transition-metrics.json"
    collision.write_bytes(b"approved input bytes")
    other_input = tmp_path / "other-input"
    other_input.write_bytes(b"other approved input bytes")
    atlas = collision if input_kind == "atlas" else other_input
    manifest = collision if input_kind == "manifest" else other_input
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preview_nangongwan_moonlit_chestnut.py",
            "--atlas",
            str(atlas),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output),
        ],
    )

    with pytest.raises(ValueError, match="planned output collides with input"):
        previewer.main()

    assert collision.read_bytes() == b"approved input bytes"
    assert tuple(path.relative_to(output) for path in output.rglob("*") if path.is_file()) == (
        Path("transition-metrics.json"),
    )


@pytest.mark.parametrize("input_kind", ("atlas", "manifest"))
@pytest.mark.parametrize(
    "collision_relative", (Path("audit-48.png"), Path("frames/frame-01.png"))
)
def test_retained_builder_rejects_secondary_output_input_collision_before_writes(
    tmp_path, monkeypatch, input_kind, collision_relative
):
    import tools.build_nangongwan_moonlit_chestnut as builder

    output_directory = tmp_path / "builder"
    collision = output_directory / collision_relative
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"approved input bytes")
    other_input = tmp_path / "other-input"
    other_input.write_bytes(b"other approved input bytes")
    atlas = collision if input_kind == "atlas" else other_input
    manifest = collision if input_kind == "manifest" else other_input
    output_atlas = output_directory / "candidate.webp"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_nangongwan_moonlit_chestnut.py",
            "--archive-atlas",
            str(atlas),
            "--archive-manifest",
            str(manifest),
            "--output-atlas",
            str(output_atlas),
        ],
    )

    with pytest.raises(ValueError, match="planned output collides with input"):
        builder.main()

    assert collision.read_bytes() == b"approved input bytes"
    assert not output_atlas.exists()
    assert tuple(
        path.relative_to(output_directory)
        for path in output_directory.rglob("*")
        if path.is_file()
    ) == (collision_relative,)


def test_live_rooftop_user_text_matches_final_duration_and_resident_count():
    manifest = json.loads(
        (
            ROOT
            / "src"
            / "shiyi_desktop_pet"
            / "resources"
            / "pets"
            / "nangongwan"
            / "pet.json"
        ).read_text(encoding="utf-8")
    )
    menu_source = (ROOT / "src" / "shiyi_desktop_pet" / "menu_controller.py").read_text(
        encoding="utf-8"
    )

    assert "二十五至六十秒" in manifest["description"]
    assert "九种坐姿小动作" in manifest["description"]
    assert "25–60 秒的常驻状态" in menu_source


def test_making_of_concat_handles_an_apostrophe_in_the_output_path(tmp_path):
    import tools.nangongwan_rooftop_making_of as making_of

    directory = tmp_path / "reviewer's-cut"
    first = directory / "first.mp4"
    second = directory / "second.mp4"
    joined = directory / "joined.mp4"
    write_silent_video(
        iter((Image.new("RGB", (1600, 900), (20, 40, 80)),)),
        first,
        expected_frames=1,
    )
    write_silent_video(
        iter((Image.new("RGB", (1600, 900), (80, 40, 20)),)),
        second,
        expected_frames=1,
    )

    making_of.concat_shots((first, second), joined)

    assert probe_media(joined, count_frames=True).video.nb_read_frames == 2
    assert not joined.with_suffix(".concat.txt").exists()


def test_making_of_render_shot_directly_covers_an_action_source(
    tmp_path, monkeypatch
):
    import tools.nangongwan_rooftop_making_of as making_of
    from tools.nangongwan_rooftop_making_of import ActionSource, ShotSpec

    source = ActionSource(
        tmp_path / "atlas.webp", tmp_path / "pet.json", "directAction"
    )
    shot = ShotSpec("direct", "action", 1_000, source)
    output = tmp_path / "direct.mp4"
    calls = []

    monkeypatch.setattr(
        making_of,
        "read_action",
        lambda action: TimedFrames(
            (Image.new("RGBA", (192, 208), (20, 40, 80, 255)),), (1_000,)
        ),
    )

    def fake_action_video(frames, path):
        calls.append((frames.duration_ms, path))
        path.write_bytes(b"action")

    def fake_ffmpeg(command):
        Path(command[-1]).write_bytes(b"rendered")

    monkeypatch.setattr(making_of, "write_action_mp4", fake_action_video)
    monkeypatch.setattr(making_of, "run_ffmpeg", fake_ffmpeg)

    making_of.render_shot(shot, output, frame_count=30)

    generated = output.with_suffix(".action-source.mp4")
    assert calls == [(1_000, generated)]
    assert output.read_bytes() == b"rendered"
    assert not generated.exists()
    assert not output.with_suffix(".background.png").exists()
