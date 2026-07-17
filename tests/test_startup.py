from pathlib import Path

from shiyi_desktop_pet.startup import RUN_KEY_PATH, VALUE_NAME, StartupManager, WinRegRunKey, build_run_command


class FakeRunKey:
    value = None

    def read(self, name):
        return self.value

    def write(self, name, value):
        self.value = value

    def delete(self, name):
        self.value = None


class FakeHandle:
    def __init__(self):
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.exited = True


class FakeRegistry:
    HKEY_CURRENT_USER = "hkcu"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 3

    def __init__(self):
        self.values = {}
        self.open_handles = []
        self.create_handles = []

    def OpenKey(self, hive, path, reserved, access):
        assert (hive, path, reserved) == (self.HKEY_CURRENT_USER, RUN_KEY_PATH, 0)
        handle = FakeHandle()
        self.open_handles.append(handle)
        return handle

    def CreateKeyEx(self, hive, path, reserved, access):
        assert (hive, path, reserved, access) == (
            self.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, self.KEY_SET_VALUE
        )
        handle = FakeHandle()
        self.create_handles.append(handle)
        return handle

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, value_type, value):
        assert (reserved, value_type) == (0, self.REG_SZ)
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError
        del self.values[name]


def test_startup_command_quotes_path_and_round_trips():
    backend = FakeRunKey()
    manager = StartupManager(backend, Path(r"C:\Program Files\Shiyi\ShiyiDesktopPet.exe"))
    manager.set_enabled(True)
    assert backend.value == r'"C:\Program Files\Shiyi\ShiyiDesktopPet.exe" --startup'
    assert manager.is_enabled()
    manager.set_enabled(False)
    assert not manager.is_enabled()


def test_startup_requires_exact_normalized_command():
    backend = FakeRunKey()
    manager = StartupManager(backend, Path(r"C:\Shiyi\ShiyiDesktopPet.exe"))
    backend.value = r' "C:\Shiyi\ShiyiDesktopPet.exe" --startup '
    assert manager.is_enabled()
    backend.value = r'"C:\Shiyi\ShiyiDesktopPet.exe" --startup --extra'
    assert not manager.is_enabled()


def test_startup_rejects_malformed_stored_commands():
    backend = FakeRunKey()
    manager = StartupManager(backend, Path(r"C:\Shiyi\ShiyiDesktopPet.exe"))
    for malformed in ("C:\\Shiyi\\ShiyiDesktopPet.exe --startup", '"C:\\Shiyi\\ShiyiDesktopPet.exe"', None):
        backend.value = malformed
        assert not manager.is_enabled()


def test_winreg_adapter_uses_hkcu_and_context_managed_handles():
    registry = FakeRegistry()
    backend = WinRegRunKey(registry)

    assert backend.read(VALUE_NAME) is None
    assert registry.open_handles[-1].entered and registry.open_handles[-1].exited
    backend.write(VALUE_NAME, "command")
    assert backend.read(VALUE_NAME) == "command"
    assert registry.create_handles[-1].entered and registry.create_handles[-1].exited
    backend.delete(VALUE_NAME)
    assert backend.read(VALUE_NAME) is None
