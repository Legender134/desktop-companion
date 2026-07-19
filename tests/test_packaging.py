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


def test_product_and_installer_versions_are_2_3_1():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    installer = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")

    assert __version__ == "2.4.0"
    assert PRODUCT_VERSION == "2.4.0"
    assert project["project"]["version"] == "2.4.0"
    assert "AppVersion=2.4.0" in installer
    assert "VersionInfoVersion=2.4.0.0" in installer
