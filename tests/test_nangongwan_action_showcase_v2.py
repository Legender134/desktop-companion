from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import tools.nangongwan_action_showcase_v2 as showcase_module
from tools.render_nangongwan_action_showcase_v2 import build_showcase_plan
from tools.nangongwan_action_showcase_v2 import copy_verified_background


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = Path(
    r"C:\Users\23644\AppData\Local\Temp\codex-clipboard-fa2f4101-2de0-4c4a-a1c9-01fc1c2a4412.png"
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

    def resolve_preview_as_private(path: Path, *args, **kwargs) -> Path:
        if path.name == "preview-sequence-v9.json":
            return Path(r"C:\anime-reference\preview-sequence-v9.json")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_preview_as_private)

    with pytest.raises(ValueError, match="showcase source is not public"):
        build_showcase_plan(ROOT, BACKGROUND)
