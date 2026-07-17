from PIL import Image

from shiyi_desktop_pet.resource_locator import resource_path


def test_icon_contains_required_windows_sizes():
    icon = Image.open(resource_path("app.ico"))
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.ico.sizes()
