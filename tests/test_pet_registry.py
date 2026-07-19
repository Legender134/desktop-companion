import json
from pathlib import Path
import shutil

from PySide6.QtGui import QColor, QImage

from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.models import ActionId, ActionRole
from shiyi_desktop_pet.pet_registry import PetRegistry
from shiyi_desktop_pet.resource_locator import resource_root


def _write_pack(
    root: Path,
    pet_id: str,
    *,
    manifest_id: str | None = None,
    sprite_version: int = 2,
    spritesheet_path: str = "spritesheet.webp",
    sprite_bytes: bytes = b"fake-webp",
    icon_frame: object | None = None,
    actions: object | None = None,
) -> Path:
    directory = root / pet_id
    directory.mkdir(parents=True)
    manifest = {
        "id": manifest_id or pet_id,
        "displayName": pet_id.title(),
        "description": f"{pet_id} test pet",
        "spriteVersionNumber": sprite_version,
        "spritesheetPath": spritesheet_path,
    }
    if icon_frame is not None:
        manifest["iconFrame"] = icon_frame
    if actions is not None:
        manifest["actions"] = actions
    (directory / "pet.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    if spritesheet_path == "spritesheet.webp":
        (directory / spritesheet_path).write_bytes(sprite_bytes)
    return directory


def test_registry_discovers_bundled_and_user_pets_and_creates_user_root(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user-pets"
    _write_pack(bundled, "shiyi")
    _write_pack(bundled, "ziling")
    _write_pack(user, "new_pet")

    snapshot = PetRegistry(bundled, user).refresh()

    assert user.is_dir()
    assert snapshot.choices == (
        ("shiyi", "Shiyi"),
        ("ziling", "Ziling"),
        ("new_pet", "New_Pet"),
    )
    assert snapshot.by_id("new_pet").is_bundled is False
    assert snapshot.by_id("new_pet").icon_frame == (0, 0)
    assert dict(
        (definition.action_id, definition.label)
        for definition in snapshot.by_id("new_pet").actions
    )[ActionId.BELLY_FLOP] == "特别动作"
    assert snapshot.by_id("shiyi").is_bundled is True
    assert snapshot.issues == ()


def test_registry_keeps_bundled_pets_when_user_root_cannot_be_created(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user-pets"
    _write_pack(bundled, "shiyi")
    user.write_text("not a directory", encoding="utf-8")

    snapshot = PetRegistry(bundled, user).refresh()

    assert snapshot.choices == (("shiyi", "Shiyi"),)
    assert len(snapshot.issues) == 1
    assert snapshot.issues[0].pet_directory == user


def test_registry_rejects_duplicate_unsafe_and_unsupported_user_packs(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user-pets"
    _write_pack(bundled, "shiyi")
    _write_pack(user, "shiyi")
    _write_pack(user, "bad_id", manifest_id="Bad Pet")
    _write_pack(user, "old_format", sprite_version=1)
    escaped = _write_pack(user, "escaped", spritesheet_path="../outside.webp")
    (escaped.parent / "outside.webp").write_bytes(b"outside")

    snapshot = PetRegistry(bundled, user).refresh()

    assert snapshot.choices == (("shiyi", "Shiyi"),)
    messages = "\n".join(issue.message for issue in snapshot.issues)
    assert "duplicate pet id" in messages
    assert "invalid pet id" in messages
    assert "unsupported sprite version" in messages
    assert "spritesheetPath must be spritesheet.webp" in messages


def test_registry_requires_canonical_lowercase_id_and_directory(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user-pets"
    _write_pack(bundled, "shiyi")
    _write_pack(user, "Upper", manifest_id="Upper")

    snapshot = PetRegistry(bundled, user).refresh()

    assert snapshot.choices == (("shiyi", "Shiyi"),)
    assert "invalid pet id" in snapshot.issues[0].message


def test_registry_accepts_valid_icon_frame_and_rejects_invalid_values(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user-pets"
    _write_pack(bundled, "shiyi", icon_frame={"row": 3, "column": 1})
    _write_pack(user, "bad_bool", icon_frame={"row": True, "column": 0})
    _write_pack(user, "bad_column", icon_frame={"row": 0, "column": 8})
    _write_pack(user, "bad_shape", icon_frame=[0, 0])

    snapshot = PetRegistry(bundled, user).refresh()

    assert snapshot.by_id("shiyi").icon_frame == (3, 1)
    assert snapshot.choices == (("shiyi", "Shiyi"),)
    assert len(snapshot.issues) == 3
    assert all("iconFrame" in issue.message for issue in snapshot.issues)


def _valid_actions() -> dict[str, dict[str, object]]:
    return {
        "idle": {"label": "安静站立", "autoplayWeight": 0},
        "moveRight": {"label": "向右轻行", "autoplayWeight": 0},
        "moveLeft": {"label": "向左轻行", "autoplayWeight": 0},
        "greet": {"label": "挥手问候", "autoplayWeight": 3},
        "jump": {"label": "翩然旋舞", "autoplayWeight": 1},
        "special": {"label": "舒展衣袖", "autoplayWeight": 2},
        "wait": {"label": "安静等候", "autoplayWeight": 3},
        "observe": {"label": "凝神静气", "autoplayWeight": 2},
        "curious": {"label": "若有所思", "autoplayWeight": 3},
    }


def _valid_v3_actions() -> dict[str, dict[str, object]]:
    return {
        "rest": {
            "label": "静静陪伴",
            "role": "idle",
            "row": 0,
            "frameCount": 3,
            "frameMs": 180,
            "loop": True,
        },
        "walkRight": {
            "label": "向右轻行",
            "role": "move",
            "direction": "right",
            "row": 1,
            "frameCount": 5,
            "frameDurations": [80, 90, 100, 90, 80],
            "loop": True,
            "autoplayWeight": 9,
        },
        "walkLeft": {
            "label": "向左轻行",
            "role": "move",
            "direction": "left",
            "mirrorOf": "walkRight",
            "autoplayWeight": 9,
        },
        "hello": {
            "label": "点头回应",
            "role": "interaction",
            "row": 2,
            "frameCount": 4,
            "frameMs": 140,
            "repeatCount": 2,
            "autoplayWeight": 3,
            "autoplayGroup": "quiet",
        },
        "dashRight": {
            "label": "遁光向右",
            "role": "burstMove",
            "direction": "right",
            "row": 3,
            "frameCount": 8,
            "frameMs": 90,
            "travelStartFrame": 3,
            "travelEndFrame": 6,
            "autoplayWeight": 1,
            "cooldownMs": 45000,
            "minDistance": 280,
            "travelDistanceRatio": 0.5,
            "maxVerticalRatio": 0.1,
        },
        "dashLeft": {
            "label": "遁光向左",
            "role": "burstMove",
            "direction": "left",
            "mirrorOf": "dashRight",
            "autoplayWeight": 1,
            "cooldownMs": 45000,
            "minDistance": 280,
        },
    }


def test_registry_loads_complete_pet_specific_action_names_and_weights(tmp_path: Path):
    bundled = tmp_path / "bundled"
    _write_pack(bundled, "shiyi", actions=_valid_actions())

    definition = PetRegistry(bundled, None).refresh().by_id("shiyi")
    actions = {item.action_id: item for item in definition.actions}

    assert actions[ActionId.WAVE].label == "挥手问候"
    assert actions[ActionId.WAVE].autoplay_weight == 3
    assert actions[ActionId.RUN_RIGHT].autoplay_weight == 0


def test_registry_rejects_incomplete_or_unsafe_action_metadata(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user-pets"
    _write_pack(bundled, "shiyi", actions=_valid_actions())

    missing = _valid_actions()
    del missing["curious"]
    _write_pack(user, "missing_action", actions=missing)

    moving = _valid_actions()
    moving["moveRight"]["autoplayWeight"] = 1
    _write_pack(user, "moving_action", actions=moving)

    boolean = _valid_actions()
    boolean["greet"]["autoplayWeight"] = True
    _write_pack(user, "boolean_weight", actions=boolean)

    control_character = _valid_actions()
    control_character["greet"]["label"] = "挥手\n问候"
    _write_pack(user, "control_label", actions=control_character)

    disabled = _valid_actions()
    for entry in disabled.values():
        entry["autoplayWeight"] = 0
    _write_pack(user, "no_autoplay", actions=disabled)

    snapshot = PetRegistry(bundled, user).refresh()

    assert snapshot.choices == (("shiyi", "Shiyi"),)
    messages = "\n".join(issue.message for issue in snapshot.issues)
    assert "every documented v2 action key" in messages
    assert "moving or idle action" in messages
    assert "integer from 0 through 10" in messages
    assert "printable characters" in messages
    assert "at least one in-place autoplay action" in messages


def test_registry_loads_dynamic_v3_actions_timing_mirroring_and_burst_metadata(
    tmp_path: Path,
):
    bundled = tmp_path / "bundled"
    _write_pack(
        bundled,
        "dynamic_pet",
        sprite_version=3,
        actions=_valid_v3_actions(),
    )

    definition = PetRegistry(bundled, None).refresh().by_id("dynamic_pet")
    actions = {item.action_id: item for item in definition.actions}

    assert definition.sprite_version == 3
    assert actions["rest"].role is ActionRole.IDLE
    assert actions["walkRight"].spec.frame_count == 5
    assert actions["walkRight"].spec.frame_durations == (80, 90, 100, 90, 80)
    assert actions["walkLeft"].mirror_of == "walkRight"
    assert actions["dashRight"].role is ActionRole.BURST_MOVE
    assert actions["dashRight"].travel_start_frame == 3
    assert actions["dashRight"].travel_end_frame == 6
    assert actions["dashRight"].cooldown_ms == 45000
    assert actions["dashRight"].min_distance == 280
    assert actions["dashRight"].travel_distance_ratio == 0.5
    assert actions["dashRight"].max_vertical_ratio == 0.1
    assert actions["dashLeft"].travel_distance_ratio == 0.5
    assert actions["dashLeft"].max_vertical_ratio == 0.1
    assert actions["hello"].autoplay_group == "quiet"


def test_registry_accepts_supported_gaze_density_and_rejects_other_counts(
    tmp_path: Path,
):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    for count in (16, 32, 64):
        actions = _valid_v3_actions()
        actions["gaze"] = {
            "label": "随眸相望",
            "role": "gaze",
            "row": 5,
            "frameCount": count,
            "frameMs": 100,
            "showInMenu": False,
        }
        _write_pack(
            bundled,
            f"gaze_{count}",
            sprite_version=3,
            actions=actions,
        )

    invalid = _valid_v3_actions()
    invalid["gaze"] = {
        "label": "方向数量错误",
        "role": "gaze",
        "row": 5,
        "frameCount": 24,
        "frameMs": 100,
        "showInMenu": False,
    }
    _write_pack(user, "gaze_24", sprite_version=3, actions=invalid)

    snapshot = PetRegistry(bundled, user).refresh()

    assert snapshot.choices == (
        ("gaze_16", "Gaze_16"),
        ("gaze_32", "Gaze_32"),
        ("gaze_64", "Gaze_64"),
    )
    assert len(snapshot.issues) == 1
    assert "16, 32, or 64 frames" in snapshot.issues[0].message


def test_registry_rejects_v3_without_required_capabilities_or_valid_timing(
    tmp_path: Path,
):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _write_pack(bundled, "good", sprite_version=3, actions=_valid_v3_actions())

    missing_interaction = _valid_v3_actions()
    del missing_interaction["hello"]
    _write_pack(
        user,
        "missing_interaction",
        sprite_version=3,
        actions=missing_interaction,
    )
    bad_durations = _valid_v3_actions()
    bad_durations["walkRight"]["frameDurations"] = [80, 90]
    _write_pack(
        user,
        "bad_durations",
        sprite_version=3,
        actions=bad_durations,
    )
    bad_group = _valid_v3_actions()
    bad_group["hello"]["autoplayGroup"] = "unsafe group"
    _write_pack(user, "bad_group", sprite_version=3, actions=bad_group)
    movement_group = _valid_v3_actions()
    movement_group["walkRight"]["autoplayGroup"] = "movement"
    _write_pack(
        user,
        "movement_group",
        sprite_version=3,
        actions=movement_group,
    )

    snapshot = PetRegistry(bundled, user).refresh()

    assert snapshot.choices == (("good", "Good"),)
    messages = "\n".join(issue.message for issue in snapshot.issues)
    assert "at least one interaction" in messages
    assert "frameDurations must match frameCount" in messages
    assert "autoplayGroup must be empty or a safe" in messages
    assert "autoplayGroup is only valid for interaction" in messages


def test_registry_validator_quarantines_bad_pack_without_hiding_good_pets(tmp_path: Path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user-pets"
    _write_pack(bundled, "shiyi", sprite_bytes=b"good")
    _write_pack(user, "broken", sprite_bytes=b"bad")

    def validate(definition):
        if definition.spritesheet_path.read_bytes() == b"bad":
            raise ValueError("spritesheet could not be decoded")

    snapshot = PetRegistry(bundled, user, validator=validate).refresh()

    assert snapshot.choices == (("shiyi", "Shiyi"),)
    assert len(snapshot.issues) == 1
    assert snapshot.issues[0].pet_directory == user / "broken"
    assert "spritesheet could not be decoded" in snapshot.issues[0].message


def test_real_v2_pack_can_be_added_without_changing_product_code(tmp_path: Path):
    user = tmp_path / "pets"
    custom = _write_pack(user, "copycat")
    shutil.copyfile(
        resource_root() / "pets" / "shiyi" / "spritesheet.webp",
        custom / "spritesheet.webp",
    )

    registry = PetRegistry(
        resource_root() / "pets",
        user,
        validator=AnimationCatalog.load_definition,
    )
    snapshot = registry.refresh()
    definition = snapshot.by_id("copycat")
    catalog = AnimationCatalog.load_definition(definition)

    assert {pet_id for pet_id, _ in snapshot.choices} == {
        "nangongwan",
        "shiyi",
        "ziling",
        "copycat",
    }
    assert catalog.pet_id == "copycat"
    assert catalog.display_name == "Copycat"
    assert snapshot.issues == ()


def test_real_dynamic_v3_webp_is_discovered_validated_and_loaded(tmp_path: Path):
    user = tmp_path / "pets"
    directory = _write_pack(
        user,
        "dynamic_pet",
        sprite_version=3,
        actions=_valid_v3_actions(),
    )
    atlas = QImage(8 * 192, 4 * 208, QImage.Format.Format_RGBA8888)
    atlas.fill(QColor(0, 0, 0, 0))
    for row, used in enumerate((3, 5, 4, 8)):
        for column in range(used):
            atlas.setPixelColor(
                column * 192 + 5, row * 208 + 5, QColor(255, 255, 255, 255)
            )
    assert atlas.save(str(directory / "spritesheet.webp"), "WEBP")

    bundled = tmp_path / "bundled"
    bundled.mkdir()
    registry = PetRegistry(
        bundled,
        user,
        validator=AnimationCatalog.load_definition,
    )
    snapshot = registry.refresh()
    catalog = AnimationCatalog.load_definition(snapshot.by_id("dynamic_pet"))

    assert snapshot.issues == ()
    assert catalog.sprite_version == 3
    assert catalog.atlas_size == (1536, 832)
    assert len(catalog.frames("walkRight")) == 5
    assert len(catalog.frames("dashLeft")) == 8
