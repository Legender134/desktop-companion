"""Render exact-timing previews and transition diagnostics for moonlitChestnut."""

from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

if __package__ in {None, ""}:
    from nangongwan_output_preflight import validate_planned_outputs
else:
    from tools.nangongwan_output_preflight import validate_planned_outputs


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = (
    ROOT / "tools" / "archives" / "nangongwan-moonlit-chestnut-anchored-v1"
)
LIVE_PET_ROOT = (
    ROOT / "src" / "shiyi_desktop_pet" / "resources" / "pets" / "nangongwan"
)
ATLAS_PATH = ARCHIVE_ROOT / "spritesheet.webp"
MANIFEST_PATH = ARCHIVE_ROOT / "pet.json"
WORK_DIR = ROOT / "work" / "moonlit-chestnut-redesign"
CELL = (192, 208)
ATLAS_COLUMNS = 16


def _runtime_frames(atlas: Image.Image, action: dict) -> tuple[Image.Image, ...]:
    start = action["row"] * ATLAS_COLUMNS + action.get("startColumn", 0)
    frames: list[Image.Image] = []
    for offset in range(action["frameCount"]):
        row, column = divmod(start + offset, ATLAS_COLUMNS)
        frames.append(
            atlas.crop(
                (
                    column * CELL[0],
                    row * CELL[1],
                    (column + 1) * CELL[0],
                    (row + 1) * CELL[1],
                )
            ).convert("RGBA")
        )
    return tuple(frames)


def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    result = Image.new("RGB", size)
    draw = ImageDraw.Draw(result)
    height = max(1, size[1] - 1)
    for y in range(size[1]):
        ratio = y / height
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(top, bottom))
        draw.line((0, y, size[0], y), fill=color)
    return result


def _desktop_preview(frame: Image.Image) -> Image.Image:
    panel_size = (432, 480)
    dark = _gradient(panel_size, (13, 20, 35), (35, 47, 70))
    light = _gradient(panel_size, (226, 235, 246), (187, 208, 229))
    scaled = frame.resize((384, 416), Image.Resampling.LANCZOS)
    position = ((panel_size[0] - scaled.width) // 2, panel_size[1] - scaled.height - 18)
    dark.paste(scaled, position, scaled)
    light.paste(scaled, position, scaled)
    combined = Image.new("RGB", (panel_size[0] * 2, panel_size[1]), (0, 0, 0))
    combined.paste(dark, (0, 0))
    combined.paste(light, (panel_size[0], 0))
    return combined


def _transition_metric(left: Image.Image, right: Image.Image) -> dict[str, float]:
    background = Image.new("RGBA", CELL, (127, 127, 127, 255))
    left_composite = background.copy()
    right_composite = background.copy()
    left_composite.alpha_composite(left)
    right_composite.alpha_composite(right)
    left_rgb = left_composite.convert("RGB")
    right_rgb = right_composite.convert("RGB")
    difference = ImageChops.difference(left_rgb, right_rgb)
    union_alpha = ImageChops.lighter(left.getchannel("A"), right.getchannel("A"))
    alpha_values = list(union_alpha.get_flattened_data())
    difference_values = list(difference.get_flattened_data())
    active = [index for index, alpha in enumerate(alpha_values) if alpha > 8]
    if not active:
        return {"meanRgbDelta": 0.0, "changedPixelRatio": 0.0, "activePixels": 0}
    channel_delta = [sum(difference_values[index]) / 3 for index in active]
    changed = [
        index
        for index in active
        if max(difference_values[index]) > 20
    ]
    return {
        "meanRgbDelta": round(sum(channel_delta) / len(channel_delta), 3),
        "changedPixelRatio": round(len(changed) / len(active), 5),
        "activePixels": len(active),
    }


def _difference_panel(left: Image.Image, right: Image.Image) -> Image.Image:
    background = Image.new("RGBA", CELL, (127, 127, 127, 255))
    left_composite = background.copy()
    right_composite = background.copy()
    left_composite.alpha_composite(left)
    right_composite.alpha_composite(right)
    difference = ImageChops.difference(
        left_composite.convert("RGB"), right_composite.convert("RGB")
    )
    return difference.point(lambda value: min(255, value * 3))


def _hardest_seams(
    frames: tuple[Image.Image, ...], metrics: list[dict], path: Path
) -> None:
    hardest = sorted(metrics, key=lambda item: item["meanRgbDelta"], reverse=True)[:6]
    label_height = 32
    block_width = CELL[0] * 3
    block_height = CELL[1] + label_height
    sheet = Image.new("RGB", (block_width * 2, block_height * 3), (240, 243, 248))
    draw = ImageDraw.Draw(sheet)
    checker = Image.new("RGBA", CELL, (223, 228, 236, 255))
    checker_draw = ImageDraw.Draw(checker)
    for y in range(0, CELL[1], 16):
        for x in range(0, CELL[0], 16):
            if (x // 16 + y // 16) % 2:
                checker_draw.rectangle((x, y, x + 15, y + 15), fill=(184, 194, 207, 255))

    for rank, metric in enumerate(hardest):
        row, column = divmod(rank, 2)
        index = metric["fromFrame"] - 1
        x = column * block_width
        y = row * block_height
        left = checker.copy()
        left.alpha_composite(frames[index])
        right = checker.copy()
        right.alpha_composite(frames[index + 1])
        sheet.paste(left.convert("RGB"), (x, y))
        sheet.paste(right.convert("RGB"), (x + CELL[0], y))
        sheet.paste(_difference_panel(frames[index], frames[index + 1]), (x + CELL[0] * 2, y))
        draw.text(
            (x + 5, y + CELL[1] + 5),
            f"{metric['fromFrame']:02d}->{metric['toFrame']:02d}  mean={metric['meanRgbDelta']:.2f}  changed={metric['changedPixelRatio']:.1%}",
            fill=(20, 28, 38),
        )
    sheet.save(path)


def _write_gif(
    preview_frames: tuple[Image.Image, ...], durations: list[int], path: Path
) -> None:
    preview_frames[0].save(
        path,
        save_all=True,
        append_images=list(preview_frames[1:]),
        duration=durations,
        loop=0,
        disposal=2,
        optimize=False,
    )


def _write_mp4(
    preview_frames: tuple[Image.Image, ...], durations: list[int], path: Path
) -> None:
    if any(duration % 10 for duration in durations):
        raise ValueError("100 fps preview requires durations divisible by 10 ms")
    width, height = preview_frames[0].size
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            "100",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-r",
            "100",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ],
        stdin=subprocess.PIPE,
    )
    if process.stdin is None:
        raise RuntimeError("failed to open the ffmpeg input pipe")
    try:
        for frame, duration in zip(preview_frames, durations):
            data = frame.convert("RGB").tobytes()
            for _ in range(duration // 10):
                process.stdin.write(data)
    finally:
        process.stdin.close()
    if process.wait() != 0:
        raise subprocess.CalledProcessError(process.returncode, process.args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview the archived 48-frame moonlit-chestnut candidate safely."
    )
    parser.add_argument("--atlas", type=Path, default=ATLAS_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--output-dir", type=Path, default=WORK_DIR)
    return parser


def _validate_output_location(path: Path) -> None:
    validate_planned_outputs(
        inputs=(),
        outputs=(path,),
        protected_roots=(ARCHIVE_ROOT, LIVE_PET_ROOT),
    )


def _planned_output_paths(output_directory: Path) -> tuple[Path, ...]:
    return (
        output_directory,
        output_directory / "moonlit-chestnut-9600ms.gif",
        output_directory / "moonlit-chestnut-75pct.gif",
        output_directory / "moonlit-chestnut-125pct.gif",
        output_directory / "moonlit-chestnut-9600ms.mp4",
        output_directory / "transition-metrics.json",
        output_directory / "hardest-seams.png",
    )


def _preflight_paths(atlas: Path, manifest: Path, output_directory: Path) -> None:
    validate_planned_outputs(
        inputs=(atlas, manifest),
        outputs=_planned_output_paths(output_directory),
        protected_roots=(ARCHIVE_ROOT, LIVE_PET_ROOT),
    )


def main() -> None:
    args = _parser().parse_args()
    _preflight_paths(args.atlas, args.manifest, args.output_dir)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    action = manifest["actions"]["moonlitChestnut"]
    durations = action["frameDurations"]
    if len(durations) != 48 or sum(durations) != 9600:
        raise ValueError("moonlitChestnut must contain 48 durations totalling 9600 ms")
    with Image.open(args.atlas) as atlas:
        frames = _runtime_frames(atlas.convert("RGBA"), action)
        idle = _runtime_frames(
            atlas.convert("RGBA"),
            {**manifest["actions"]["idle"], "frameCount": 1},
        )[0]

    if frames[0].tobytes() != idle.tobytes() or frames[-1].tobytes() != idle.tobytes():
        raise AssertionError("runtime action does not share exact idle endpoints")

    preview_frames = tuple(_desktop_preview(frame) for frame in frames)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_gif(preview_frames, durations, args.output_dir / "moonlit-chestnut-9600ms.gif")
    _write_gif(
        preview_frames,
        [max(10, round(duration / 0.75)) for duration in durations],
        args.output_dir / "moonlit-chestnut-75pct.gif",
    )
    _write_gif(
        preview_frames,
        [max(10, round(duration / 1.25)) for duration in durations],
        args.output_dir / "moonlit-chestnut-125pct.gif",
    )
    _write_mp4(preview_frames, durations, args.output_dir / "moonlit-chestnut-9600ms.mp4")

    metrics: list[dict] = []
    for index, (left, right) in enumerate(zip(frames, frames[1:]), start=1):
        metric = _transition_metric(left, right)
        metric.update({"fromFrame": index, "toFrame": index + 1})
        metrics.append(metric)
    hardest = sorted(metrics, key=lambda item: item["meanRgbDelta"], reverse=True)
    report = {
        "frameCount": len(frames),
        "durationMs": sum(durations),
        "firstFrameSha256": sha256(frames[0].tobytes()).hexdigest(),
        "lastFrameSha256": sha256(frames[-1].tobytes()).hexdigest(),
        "idleBoundaryExact": frames[0].tobytes() == frames[-1].tobytes() == idle.tobytes(),
        "transitions": metrics,
        "hardestTransitions": hardest[:10],
    }
    (args.output_dir / "transition-metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _hardest_seams(frames, metrics, args.output_dir / "hardest-seams.png")
    print(args.output_dir / "moonlit-chestnut-9600ms.gif")
    print(args.output_dir / "moonlit-chestnut-9600ms.mp4")
    print(args.output_dir / "transition-metrics.json")


if __name__ == "__main__":
    main()
