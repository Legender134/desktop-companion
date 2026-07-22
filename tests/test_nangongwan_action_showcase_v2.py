from io import BytesIO
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image, ImageChops, ImageStat

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
    write_silent_video(tiny_segments[0], first)
    write_silent_video(tiny_segments[1], second)
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


def test_timeline_has_exact_contiguous_segments_and_no_text_fields(showcase_plan):
    timeline = _timeline_document(showcase_plan, BACKGROUND_SHA256)

    assert timeline["schemaVersion"] == 1
    assert timeline["backgroundSha256"] == BACKGROUND_SHA256
    assert timeline["frameSize"] == [1600, 900]
    assert timeline["spriteRectangle"] == {
        "x": 704,
        "y": 346,
        "width": 192,
        "height": 208,
    }
    assert timeline["totalFrames"] == 2473
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


def test_build_showcase_writes_only_v2_background_clips_timeline_and_master(
    tmp_path, monkeypatch, showcase_plan
):
    encoded_clips = []

    monkeypatch.setattr(
        "tools.render_nangongwan_action_showcase_v2.build_showcase_plan",
        lambda root, background_source: showcase_plan,
    )
    monkeypatch.setattr(
        "tools.render_nangongwan_action_showcase_v2.build_segment_frames",
        lambda segment, background: SegmentFrames((background.copy(),) * segment.output_frames),
    )

    def fake_encode(frames, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"clip")
        encoded_clips.append((output.name, len(frames.frames)))

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

    master = build_showcase(tmp_path, BACKGROUND)

    output = tmp_path / "work" / "nangongwan-action-showcase-v2"
    assert master == output / "nangongwan-action-showcase-v2-1600x900.mp4"
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
    output = tmp_path / "work" / "nangongwan-action-showcase-v2"
    output.mkdir(parents=True)
    master = output / "nangongwan-action-showcase-v2-1600x900.mp4"
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
    def synthetic_frame(index):
        return Image.new(
            "RGB",
            showcase_module.SPRITE_SIZE,
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
                    changed.paste((255, 255, 255), (24, 80, 168, 112))
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
    output = tmp_path / "work" / "nangongwan-action-showcase-v2"
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
    master = output / "nangongwan-action-showcase-v2-1600x900.mp4"
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


def test_compose_frame_changes_only_the_centered_sprite_rectangle():
    background = Image.effect_noise((1600, 900), 80).convert("RGB")
    sprite = Image.new("RGBA", (192, 208), (200, 50, 80, 128))

    composed = showcase_module.compose_frame(background, sprite)

    changed_bounds = ImageChops.difference(background, composed).getbbox()
    assert changed_bounds is not None
    left, top, right, bottom = changed_bounds
    assert 704 <= left < right <= 896
    assert 346 <= top < bottom <= 554
    assert background.crop((704, 346, 896, 554)).tobytes() != composed.crop(
        (704, 346, 896, 554)
    ).tobytes()


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
            for frame in showcase_module.build_segment_frames(segment, background_image).frames
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
        segment.id: len(
            showcase_module.build_segment_frames(segment, background_image).frames
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


def test_showcase_plan_rejects_moon_actions_with_different_frame_durations(
    monkeypatch,
):
    original_read_text = Path.read_text

    def read_one_changed_moon_manifest(path: Path, *args, **kwargs) -> str:
        encoded = original_read_text(path, *args, **kwargs)
        if path.name == "pet.json" and "03-cropped-disc-232" in path.parts:
            document = json.loads(encoded)
            durations = document["actions"]["rooftopChestnut"]["frameDurations"]
            durations[0] += 10
            durations[1] -= 10
            return json.dumps(document)
        return encoded

    monkeypatch.setattr(Path, "read_text", read_one_changed_moon_manifest)

    with pytest.raises(ValueError, match="identical per-frame durations"):
        build_showcase_plan(ROOT, BACKGROUND)
