# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks.qt import pyside6_library_info


repo_root = Path(SPECPATH).parent
source_root = repo_root / "src"
resource_root = source_root / "shiyi_desktop_pet" / "resources"

# A package's ``__main__.py`` cannot be executed as a plain script because its
# relative imports require package context. Generate a build-only launcher that
# imports the same public entry point used by ``python -m shiyi_desktop_pet``.
entry_script = repo_root / "build" / ".generated" / "ShiyiDesktopPet-entry.py"
entry_script.parent.mkdir(parents=True, exist_ok=True)
entry_script.write_text(
    "from shiyi_desktop_pet.app import main\n\nraise SystemExit(main())\n",
    encoding="utf-8",
)

required_plugin_names = {
    "qwindows.dll",
    "qico.dll",
    "qwebp.dll",
    "qmodernwindowsstyle.dll",
}
excluded_qt_library_prefixes = (
    "qt63d",
    "qt6charts",
    "qt6multimedia",
    "qt6opengl",
    "qt6pdf",
    "qt6qml",
    "qt6quick",
    "qt6sql",
    "qt6test",
    "qt6svg",
    "qt6virtualkeyboard",
    "qt6webengine",
)


def required_plugins(plugin_type):
    return [
        item
        for item in pyside6_library_info.collect_plugins(plugin_type)
        if Path(item[0]).name.lower() in required_plugin_names
    ]


qt_plugins = (
    required_plugins("platforms")
    + required_plugins("imageformats")
    + required_plugins("styles")
)

a = Analysis(
    [str(entry_script)],
    pathex=[str(source_root)],
    binaries=qt_plugins,
    datas=[
        (str(resource_root / "pet.json"), "resources"),
        (str(resource_root / "spritesheet.webp"), "resources"),
        (str(resource_root / "app.ico"), "resources"),
        (str(repo_root / "THIRD_PARTY_NOTICES.md"), "."),
    ],
    hiddenimports=["PySide6.QtNetwork"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickTest",
        "PySide6.QtQuickWidgets",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
    ],
    noarchive=False,
    optimize=0,
)

# The standard PySide6 hooks collect every plugin in a plugin category. Keep
# the runtime deliberately narrow after hook processing.
a.binaries = type(a.binaries)(
    item
    for item in a.binaries
    if (
        (
            "PySide6/plugins/" not in item[0].replace("\\", "/")
            or Path(item[0]).name.lower() in required_plugin_names
        )
        and not Path(item[0]).name.lower().startswith(excluded_qt_library_prefixes)
    )
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ShiyiDesktopPet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    uac_admin=False,
    icon=str(resource_root / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ShiyiDesktopPet",
)
