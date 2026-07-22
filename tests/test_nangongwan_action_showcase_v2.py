from pathlib import Path

import pytest
from PIL import Image

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
