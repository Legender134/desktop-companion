from pathlib import Path


def test_installer_always_creates_desktop_shortcut():
    installer = (
        Path(__file__).resolve().parents[1] / "packaging" / "installer.iss"
    ).read_text(encoding="utf-8")

    assert (
        "Name: {autodesktop}\\桌面灵伴; "
        "Filename: {app}\\DesktopCompanion.exe"
    ) in installer
