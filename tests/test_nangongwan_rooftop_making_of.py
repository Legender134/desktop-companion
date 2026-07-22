import json
import subprocess
from functools import lru_cache
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

from tools.nangongwan_rooftop_making_of import (
    ActionSource,
    TimedFrames,
    compose_desktop,
    read_action,
    write_action_mp4,
)
from tools.render_nangongwan_rooftop_making_of import build_video_plan


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
