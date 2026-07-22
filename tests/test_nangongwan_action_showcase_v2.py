from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image, ImageChops

import tools.nangongwan_action_showcase_v2 as showcase_module
from tools.render_nangongwan_action_showcase_v2 import (
    _timeline_document,
    build_showcase,
    build_showcase_plan,
)
from tools.nangongwan_action_showcase_v2 import (
    BACKGROUND_SHA256,
    SegmentFrames,
    add_silent_aac,
    concat_clips,
    copy_verified_background,
    probe_media,
    write_silent_video,
)
from tools.nangongwan_rooftop_making_of import TimedFrames, read_action


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = Path(
    r"C:\Users\23644\AppData\Local\Temp\codex-clipboard-fa2f4101-2de0-4c4a-a1c9-01fc1c2a4412.png"
)


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
    assert probe.audio is not None
    assert probe.audio.codec == "aac" and probe.audio.sample_rate == 48000
    assert probe.subtitle_streams == 0


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
    showcase_plan, background_image
):
    built = {
        segment.id: showcase_module.build_segment_frames(segment, background_image)
        for segment in showcase_plan.segments
    }

    assert {key: len(built[key].frames) for key in ("moon-184", "moon-232", "moon-full")} == {
        "moon-184": 270,
        "moon-232": 270,
        "moon-full": 270,
    }
    assert all(len(built[segment.id].frames) == segment.output_frames for segment in showcase_plan.segments)


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

    def resolve_preview_as_private(path: Path, *args, **kwargs) -> Path:
        if path.name == "preview-sequence-v9.json":
            return Path(r"C:\anime-reference\preview-sequence-v9.json")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_preview_as_private)

    with pytest.raises(ValueError, match="showcase source is not public"):
        build_showcase_plan(ROOT, BACKGROUND)
