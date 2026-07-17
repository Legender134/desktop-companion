"""Versioned, per-user persistence for desktop-pet settings."""

from __future__ import annotations

import configparser
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .product import PET_IDS


CURRENT_SCHEMA_VERSION = 2
VALID_SCALES = frozenset({75, 100, 125, 150})
VALID_SPEEDS = frozenset({"slow", "normal", "fast"})


class Logger(Protocol):
    def warning(self, message: str, *args: object) -> None: ...


@dataclass(frozen=True)
class AppSettings:
    schema_version: int = CURRENT_SCHEMA_VERSION
    pet_id: str = "shiyi"
    wander_enabled: bool = False
    gaze_enabled: bool = True
    hover_digits_enabled: bool = True
    always_on_top: bool = True
    scale_percent: int = 100
    animation_speed: str = "normal"
    movement_speed: str = "normal"
    screen_name: str = ""
    relative_x: float = 0.85
    relative_y: float = 0.75


class SettingsStore:
    """Load and atomically save settings at a caller-selected user path."""

    def __init__(self, path: Path, logger: Logger | None = None) -> None:
        self.path = Path(path)
        self._logger = logger or logging.getLogger(__name__)

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()

        parser = configparser.ConfigParser(interpolation=None)
        try:
            with self.path.open("r", encoding="utf-8") as settings_file:
                parser.read_file(settings_file)
            if "settings" not in parser:
                raise ValueError("missing [settings] section")
            schema_version = self._read_schema_version(parser["settings"])
            if schema_version > CURRENT_SCHEMA_VERSION:
                raise ValueError(f"unsupported schema version {schema_version}")
            if schema_version < 0:
                raise ValueError(f"invalid schema version {schema_version}")
            return self._load_known_schema(parser)
        except (OSError, UnicodeError, configparser.Error, ValueError) as error:
            self._logger.warning("Could not load settings from %s: %s", self.path, error)
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        normalized = self._normalize(settings)
        parser = configparser.ConfigParser(interpolation=None)
        parser["settings"] = {key: str(value) for key, value in asdict(normalized).items()}

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as settings_file:
                parser.write(settings_file)
            temporary_path.replace(self.path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def _load_known_schema(self, parser: configparser.ConfigParser) -> AppSettings:
        """Overlay schema 0/1's known values on current defaults."""
        defaults = AppSettings()
        section = parser["settings"]
        values = asdict(defaults)
        pet_id = section.get("pet_id", defaults.pet_id).lower()
        values["pet_id"] = pet_id if pet_id in PET_IDS else defaults.pet_id
        values["wander_enabled"] = self._read_bool(section, "wander_enabled", defaults.wander_enabled)
        values["gaze_enabled"] = self._read_bool(section, "gaze_enabled", defaults.gaze_enabled)
        values["hover_digits_enabled"] = self._read_bool(
            section, "hover_digits_enabled", defaults.hover_digits_enabled
        )
        values["always_on_top"] = self._read_bool(section, "always_on_top", defaults.always_on_top)
        scale = self._read_int(section, "scale_percent", defaults.scale_percent)
        values["scale_percent"] = scale if scale in VALID_SCALES else defaults.scale_percent
        animation_speed = section.get("animation_speed", defaults.animation_speed).lower()
        values["animation_speed"] = (
            animation_speed if animation_speed in VALID_SPEEDS else defaults.animation_speed
        )
        movement_speed = section.get("movement_speed", defaults.movement_speed).lower()
        values["movement_speed"] = (
            movement_speed if movement_speed in VALID_SPEEDS else defaults.movement_speed
        )
        values["screen_name"] = section.get("screen_name", defaults.screen_name)
        values["relative_x"] = self._clamp(
            self._read_float(section, "relative_x", defaults.relative_x), defaults.relative_x
        )
        values["relative_y"] = self._clamp(
            self._read_float(section, "relative_y", defaults.relative_y), defaults.relative_y
        )
        return AppSettings(**values)

    @staticmethod
    def _read_schema_version(section: configparser.SectionProxy) -> int:
        """Read a present schema marker strictly; absent markers predate versioning."""
        if "schema_version" not in section:
            return CURRENT_SCHEMA_VERSION
        try:
            return int(section["schema_version"])
        except ValueError as error:
            raise ValueError("malformed schema version") from error

    @staticmethod
    def _read_bool(section: configparser.SectionProxy, name: str, default: bool) -> bool:
        try:
            return section.getboolean(name, fallback=default)
        except ValueError:
            return default

    @staticmethod
    def _read_int(
        section: configparser.SectionProxy, name: str, default: int
    ) -> int:
        try:
            return section.getint(name, fallback=default)
        except ValueError:
            return default

    @staticmethod
    def _read_float(section: configparser.SectionProxy, name: str, default: float) -> float:
        try:
            return section.getfloat(name, fallback=default)
        except ValueError:
            return default

    @staticmethod
    def _clamp(value: float, default: float = 0.0) -> float:
        if not math.isfinite(value):
            return default
        return min(1.0, max(0.0, value))

    @staticmethod
    def _normalize(settings: AppSettings) -> AppSettings:
        """Ensure programmatic callers persist only supported current settings."""
        return AppSettings(
            schema_version=CURRENT_SCHEMA_VERSION,
            pet_id=settings.pet_id.lower() if settings.pet_id.lower() in PET_IDS else AppSettings.pet_id,
            wander_enabled=bool(settings.wander_enabled),
            gaze_enabled=bool(settings.gaze_enabled),
            hover_digits_enabled=bool(settings.hover_digits_enabled),
            always_on_top=bool(settings.always_on_top),
            scale_percent=(
                settings.scale_percent if settings.scale_percent in VALID_SCALES else AppSettings.scale_percent
            ),
            animation_speed=(
                settings.animation_speed.lower()
                if settings.animation_speed.lower() in VALID_SPEEDS
                else AppSettings.animation_speed
            ),
            movement_speed=(
                settings.movement_speed.lower()
                if settings.movement_speed.lower() in VALID_SPEEDS
                else AppSettings.movement_speed
            ),
            screen_name=str(settings.screen_name),
            relative_x=SettingsStore._clamp(float(settings.relative_x), AppSettings.relative_x),
            relative_y=SettingsStore._clamp(float(settings.relative_y), AppSettings.relative_y),
        )
