from dataclasses import replace
from pathlib import Path

import pytest

from shiyi_desktop_pet.settings import AppSettings, SettingsStore


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append((message, args))


def test_first_launch_defaults_match_approved_design(tmp_path: Path):
    settings = SettingsStore(tmp_path / "settings.ini").load()
    assert settings == AppSettings(
        schema_version=7, pet_id="shiyi", wander_enabled=False,
        wander_intensity="standard", gaze_enabled=True, gaze_mode="active",
        autonomous_actions_enabled=True,
        hover_digits_enabled=True, always_on_top=True, menu_details_enabled=False,
        scale_percent=100, animation_speed="normal", movement_speed="normal",
        effects_quality="full",
        screen_name="", relative_x=0.85, relative_y=0.75,
    )


def test_round_trip_and_corrupt_file_fallback(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.ini")
    changed = AppSettings(
        pet_id="ziling",
        wander_enabled=True,
        wander_intensity="quiet",
        menu_details_enabled=True,
        scale_percent=125,
    )
    store.save(changed)
    assert store.load().wander_enabled
    assert store.load().pet_id == "ziling"
    assert store.load().wander_intensity == "quiet"
    assert store.load().menu_details_enabled is True
    store.path.write_text("not-an-ini", encoding="utf-8")
    assert store.load().scale_percent == 100


def test_older_schema_is_migrated_with_new_defaults(tmp_path: Path):
    path = tmp_path / "settings.ini"
    path.write_text("[settings]\nschema_version=0\nwander_enabled=true\n", encoding="utf-8")
    loaded = SettingsStore(path).load()
    assert loaded.schema_version == 7
    assert loaded.autonomous_actions_enabled is True
    assert loaded.pet_id == "shiyi"
    assert loaded.wander_enabled is True
    assert loaded.wander_intensity == "standard"
    assert loaded.gaze_enabled is True
    assert loaded.gaze_mode == "active"
    assert loaded.menu_details_enabled is False


def test_unknown_but_valid_pet_id_is_preserved_for_dynamic_registry(tmp_path: Path):
    path = tmp_path / "settings.ini"
    path.write_text("[settings]\nschema_version=2\npet_id=new_pet\n", encoding="utf-8")

    assert SettingsStore(path).load().pet_id == "new_pet"


def test_invalid_values_are_normalized_and_future_schema_falls_back(tmp_path: Path):
    path = tmp_path / "settings.ini"
    path.write_text(
        "[settings]\nschema_version=2\npet_id=../unsafe\nscale_percent=98\n"
        "animation_speed=turbo\nwander_intensity=chaotic\n"
        "relative_x=2\nrelative_y=-1\n",
        encoding="utf-8",
    )
    settings = SettingsStore(path).load()
    assert settings.scale_percent == 100
    assert settings.pet_id == "shiyi"
    assert settings.animation_speed == "normal"
    assert settings.wander_intensity == "standard"
    assert (settings.relative_x, settings.relative_y) == (1.0, 0.0)

    path.write_text("[settings]\nschema_version=8\n", encoding="utf-8")
    assert SettingsStore(path).load() == AppSettings()


def test_gaze_mode_round_trips_and_invalid_values_use_active_default(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.ini")
    store.save(AppSettings(gaze_mode="always"))
    assert store.load().gaze_mode == "always"

    store.path.write_text(
        "[settings]\nschema_version=5\ngaze_mode=unknown\n",
        encoding="utf-8",
    )
    assert store.load().gaze_mode == "active"


@pytest.mark.parametrize("quality", ("full", "simplified"))
def test_effects_quality_round_trips(tmp_path: Path, quality: str):
    store = SettingsStore(tmp_path / "settings.ini")

    store.save(replace(AppSettings(), effects_quality=quality))

    assert store.load().effects_quality == quality


def test_invalid_effects_quality_falls_back_to_full(tmp_path: Path):
    path = tmp_path / "settings.ini"
    path.write_text(
        "[settings]\nschema_version=7\neffects_quality=cinematic\n",
        encoding="utf-8",
    )

    assert SettingsStore(path).load().effects_quality == "full"


def test_non_finite_relative_positions_fall_back_to_defaults(tmp_path: Path):
    path = tmp_path / "settings.ini"
    path.write_text("[settings]\nrelative_x=nan\nrelative_y=inf\n", encoding="utf-8")
    settings = SettingsStore(path).load()
    assert (settings.relative_x, settings.relative_y) == (0.85, 0.75)


def test_malformed_schema_version_warns_and_returns_all_defaults(tmp_path: Path):
    path = tmp_path / "settings.ini"
    logger = FakeLogger()
    path.write_text("[settings]\nschema_version=not-a-number\nwander_enabled=true\n", encoding="utf-8")

    assert SettingsStore(path, logger).load() == AppSettings()
    assert len(logger.warnings) == 1
    assert path in logger.warnings[0][1]
    assert "schema version" in str(logger.warnings[0][1]).lower()


def test_blank_schema_version_warns_and_returns_all_defaults(tmp_path: Path):
    path = tmp_path / "settings.ini"
    logger = FakeLogger()
    path.write_text("[settings]\nschema_version=\nwander_enabled=true\n", encoding="utf-8")

    assert SettingsStore(path, logger).load() == AppSettings()
    assert len(logger.warnings) == 1


def test_missing_schema_is_compatible_but_invalid_boolean_and_unknown_keys_default(tmp_path: Path):
    path = tmp_path / "settings.ini"
    path.write_text("[settings]\nwander_enabled=maybe\nunknown=value\n", encoding="utf-8")

    assert SettingsStore(path).load() == AppSettings()


def test_missing_settings_section_warns_and_returns_defaults(tmp_path: Path):
    path = tmp_path / "settings.ini"
    logger = FakeLogger()
    path.write_text("[other]\nwander_enabled=true\n", encoding="utf-8")

    assert SettingsStore(path, logger).load() == AppSettings()
    assert len(logger.warnings) == 1
    assert path in logger.warnings[0][1]
