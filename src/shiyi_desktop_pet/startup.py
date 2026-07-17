"""Per-user Windows startup integration with an injectable registry adapter."""

from __future__ import annotations

import ntpath
import re
from pathlib import Path
from typing import Protocol

from .product import APP_IDENTIFIER


RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = APP_IDENTIFIER


class RunKey(Protocol):
    def read(self, name: str) -> str | None: ...

    def write(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class WinRegRunKey:
    """Adapter for HKCU's Run key; the registry module is injected for tests."""

    def __init__(self, registry: object | None = None) -> None:
        if registry is None:
            import winreg

            registry = winreg
        self._registry = registry

    def read(self, name: str) -> str | None:
        registry = self._registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, registry.KEY_READ) as key:
                value, _ = registry.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None

    def write(self, name: str, value: str) -> None:
        registry = self._registry
        with registry.CreateKeyEx(
            registry.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, registry.KEY_SET_VALUE
        ) as key:
            registry.SetValueEx(key, name, 0, registry.REG_SZ, value)

    def delete(self, name: str) -> None:
        registry = self._registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, registry.KEY_SET_VALUE) as key:
                registry.DeleteValue(key, name)
        except FileNotFoundError:
            return


def build_run_command(executable: Path) -> str:
    """Build the canonical Run value for launching the packaged executable."""
    return f'"{executable}" --startup'


class StartupManager:
    def __init__(self, backend: RunKey, executable: Path, value_name: str = VALUE_NAME) -> None:
        self._backend = backend
        self._executable = Path(executable)
        self._value_name = value_name

    def is_enabled(self) -> bool:
        stored_command = self._backend.read(self._value_name)
        return self._normalize_command(stored_command) == self._normalize_command(
            build_run_command(self._executable)
        )

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._backend.write(self._value_name, build_run_command(self._executable))
        else:
            self._backend.delete(self._value_name)

    @staticmethod
    def _normalize_command(command: str | None) -> tuple[str, str] | None:
        if not isinstance(command, str):
            return None
        match = re.fullmatch(r'\s*"([^"]+)"\s+([^\s]+)\s*', command)
        if match is None:
            return None
        executable, argument = match.groups()
        return ntpath.normcase(ntpath.normpath(executable)), argument.lower()
