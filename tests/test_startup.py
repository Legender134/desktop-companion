from pathlib import Path

from shiyi_desktop_pet.startup import StartupManager, build_run_command


class FakeRunKey:
    value = None

    def read(self, name):
        return self.value

    def write(self, name, value):
        self.value = value

    def delete(self, name):
        self.value = None


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
