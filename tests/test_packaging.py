from pathlib import Path
import tomllib

from shiyi_desktop_pet import __version__
from shiyi_desktop_pet.product import PRODUCT_VERSION


def test_installer_always_creates_desktop_shortcut():
    installer = (
        Path(__file__).resolve().parents[1] / "packaging" / "installer.iss"
    ).read_text(encoding="utf-8")

    assert (
        "Name: {autodesktop}\\桌面灵伴; "
        "Filename: {app}\\DesktopCompanion.exe"
    ) in installer


def test_product_and_installer_versions_are_2_4_2():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    installer = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")

    assert __version__ == "2.4.2"
    assert PRODUCT_VERSION == "2.4.2"
    assert project["project"]["version"] == "2.4.2"
    assert "AppVersion=2.4.2" in installer
    assert "VersionInfoVersion=2.4.2.0" in installer


def test_pyinstaller_collects_the_legacy_moonlit_atlas_with_pet_resources():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging" / "DesktopCompanion.spec").read_text(
        encoding="utf-8"
    )
    legacy = (
        root
        / "src"
        / "shiyi_desktop_pet"
        / "resources"
        / "pets"
        / "nangongwan"
        / "spritesheet-moonlit-chestnut-v2.4.1-legacy.webp"
    )

    assert '(str(resource_root), "resources")' in spec
    assert legacy.is_file()
    assert legacy.is_relative_to(root / "src" / "shiyi_desktop_pet" / "resources")
