"""Build a complete Nangong Wan atlas with the anime-framed giant moon."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from PIL import Image

try:
    from tools import build_nangongwan_moonlit_rooftop_state as rooftop
    from tools.preview_nangongwan_rooftop_moon_vote import _build_clips
except ModuleNotFoundError:  # Direct ``python tools/<script>.py`` execution.
    import build_nangongwan_moonlit_rooftop_state as rooftop
    from preview_nangongwan_rooftop_moon_vote import _build_clips


ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = ROOT / "work" / "moonlit-rooftop-giant-moon-webp"
OUTPUT_PATH = WORK_DIR / "nangongwan-spritesheet-giant-moon.webp"
AUDIT_PATH = WORK_DIR / "giant-moon-rooftop-frames.png"
REPORT_PATH = WORK_DIR / "giant-moon-webp-report.json"


def main() -> None:
    manifest = json.loads(rooftop.MANIFEST_PATH.read_text(encoding="utf-8"))
    original_bytes = rooftop.ATLAS_PATH.read_bytes()
    original_file_hash = sha256(original_bytes).hexdigest()
    clips = _build_clips(manifest, "anime")

    with Image.open(rooftop.ATLAS_PATH) as source:
        source_rgba = source.convert("RGBA")
        prefix_hash = sha256(
            source_rgba.crop(
                (0, 0, rooftop.ATLAS_WIDTH, rooftop.SOURCE_ATLAS_HEIGHT)
            ).tobytes()
        ).hexdigest()
        variant = rooftop.extend_atlas(source_rgba, clips)
        expected_size = source_rgba.size

    if variant.size != expected_size:
        raise AssertionError(
            f"variant atlas size changed: {variant.size} != {expected_size}"
        )
    variant_prefix_hash = sha256(
        variant.crop(
            (0, 0, rooftop.ATLAS_WIDTH, rooftop.SOURCE_ATLAS_HEIGHT)
        ).tobytes()
    ).hexdigest()
    if variant_prefix_hash != prefix_hash:
        raise AssertionError("giant-moon variant changed non-rooftop atlas rows")
    if sha256(rooftop.ATLAS_PATH.read_bytes()).hexdigest() != original_file_hash:
        raise AssertionError("builder modified the current installed-source atlas")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    variant.save(
        OUTPUT_PATH,
        "WEBP",
        lossless=True,
        quality=100,
        method=6,
        exact=True,
    )
    rooftop._write_audit(clips, AUDIT_PATH)

    with Image.open(OUTPUT_PATH) as written:
        if written.size != expected_size:
            raise AssertionError("written WebP dimensions differ from the source atlas")
        if written.mode != "RGBA":
            raise AssertionError("written WebP lost its alpha channel")

    report = {
        "output": str(OUTPUT_PATH),
        "sha256": sha256(OUTPUT_PATH.read_bytes()).hexdigest().upper(),
        "width": expected_size[0],
        "height": expected_size[1],
        "format": "WEBP lossless RGBA",
        "rooftopFrameCount": sum(len(frames) for frames in clips.values()),
        "unchangedPrefixRows": 23,
        "sourceAtlasUnchanged": True,
        "moonDiameterPixels": 184,
        "cellSize": list(rooftop.CELL_SIZE),
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT_PATH)
    print(AUDIT_PATH)
    print(REPORT_PATH)
    print(report["sha256"])


if __name__ == "__main__":
    main()
