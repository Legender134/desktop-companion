import math

from PIL import Image, ImageChops

from shiyi_desktop_pet.resource_locator import resource_path, resource_root


def test_icon_contains_required_windows_sizes():
    icon = Image.open(resource_path("app.ico"))
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.ico.sizes()


def test_static_product_icon_is_generated_from_shiyi_idle_frame():
    with Image.open(resource_root() / "pets" / "shiyi" / "spritesheet.webp") as atlas:
        idle_frame = atlas.convert("RGBA").crop((0, 0, 192, 208))
    trimmed = idle_frame.crop(idle_frame.getchannel("A").getbbox())
    square_size = math.ceil(max(trimmed.size) / 0.84)
    expected = Image.new("RGBA", (square_size, square_size), (0, 0, 0, 0))
    expected.alpha_composite(
        trimmed,
        ((square_size - trimmed.width) // 2, (square_size - trimmed.height) // 2),
    )
    expected = expected.resize((256, 256), resample=Image.Resampling.LANCZOS)

    with Image.open(resource_path("app.ico")) as icon:
        actual = icon.convert("RGBA")

    assert ImageChops.difference(actual, expected).getbbox() is None
