import json
from pathlib import Path
import re
import shutil

import pytest
from PySide6.QtGui import QColor, QImage

from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.models import (
    ActionId,
    ActionRole,
    PetActionDefinition,
    PetActionLayerDefinition,
    PetAtlasDefinition,
    PetAutoplayDefinition,
    PetCooldownGroupDefinition,
    PetFormDefinition,
    PetSequenceDefinition,
    PetSequenceStep,
    PetTransformationDefinition,
)
from shiyi_desktop_pet.pet_registry import PetRegistry
from shiyi_desktop_pet.resource_locator import resource_root


def _write_pack(
    root: Path,
    pet_id: str,
    *,
    manifest_id: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    sprite_version: int = 2,
    spritesheet_path: str = "spritesheet.webp",
    sprite_bytes: bytes = b"fake-webp",
    icon_frame: object | None = None,
    actions: object | None = None,
    states: object | None = None,
    atlases: object | None = None,
    forms: object | None = None,
    default_form: object | None = None,
    transformations: object | None = None,
    cooldown_groups: object | None = None,
    sequences: object | None = None,
) -> Path:
    directory = root / pet_id
    directory.mkdir(parents=True)
    manifest = {
        "id": manifest_id or pet_id,
        "displayName": display_name or pet_id.title(),
        "description": description if description is not None else f"{pet_id} test pet",
        "spriteVersionNumber": sprite_version,
    }
    if sprite_version != 4:
        manifest["spritesheetPath"] = spritesheet_path
    if icon_frame is not None:
        manifest["iconFrame"] = icon_frame
    if actions is not None:
        manifest["actions"] = actions
    if states is not None:
        manifest["states"] = states
    if atlases is not None:
        manifest["atlases"] = atlases
    if forms is not None:
        manifest["forms"] = forms
    if default_form is not None:
        manifest["defaultForm"] = default_form
    if transformations is not None:
        manifest["transformations"] = transformations
    if cooldown_groups is not None:
        manifest["cooldownGroups"] = cooldown_groups
    if sequences is not None:
        manifest["sequences"] = sequences
    (directory / "pet.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    if sprite_version == 4 and isinstance(atlases, dict):
        for atlas in atlases.values():
            if isinstance(atlas, dict) and isinstance(atlas.get("path"), str):
                path = atlas["path"]
                if Path(path).name == path:
                    (directory / path).write_bytes(sprite_bytes)
    elif spritesheet_path == "spritesheet.webp":
        (directory / spritesheet_path).write_bytes(sprite_bytes)
    return directory


def _valid_v4_manifest() -> dict[str, object]:
    def layer(
        atlas: str = "character",
        row: int = 0,
        *,
        hit_test: bool = True,
        frame_map: list[int | None] | None = None,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "atlas": atlas,
            "row": row,
            "startColumn": 0,
            "anchorX": 96,
            "anchorY": 200,
            "hitTest": hit_test,
        }
        if frame_map is not None:
            result["frameMap"] = frame_map
        return result

    def action(
        label: str,
        role: str,
        row: int,
        *,
        direction: str | None = None,
        frame_count: int = 4,
        layers: list[dict[str, object]] | None = None,
        loop: bool = False,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "label": label,
            "role": role,
            "frameCount": frame_count,
            "frameMs": 100,
            "loop": loop,
            "layers": layers or [layer(row=row)],
        }
        if direction is not None:
            result["direction"] = direction
        return result

    actions = {
        "idle": action("Idle", "idle", 0, loop=True),
        "moveRight": action("Move right", "move", 1, direction="right", loop=True),
        "moveLeft": action("Move left", "move", 2, direction="left", loop=True),
        "gaze": action("Gaze", "gaze", 3, frame_count=16, loop=True),
        "spell": action(
            "Spell",
            "interaction",
            4,
            layers=[
                layer("effects", 0, hit_test=False, frame_map=[0, 1, 2, 3]),
                layer("character", 4, hit_test=True),
            ],
        ),
        "transformEnter": action("Transform", "interaction", 5),
        "whiteFoxIdle": action("Fox idle", "idle", 6, loop=True),
        "whiteFoxMoveRight": action(
            "Fox move right", "move", 7, direction="right", loop=True
        ),
        "whiteFoxMoveLeft": action(
            "Fox move left", "move", 8, direction="left", loop=True
        ),
        "whiteFoxRest": action("Fox rest", "interaction", 9),
        "transformExit": action("Return", "interaction", 10),
    }
    autoplay = {
        "bucket": "commonTransform",
        "weight": 20,
        "minDelayMs": 1000,
        "maxDelayMs": 2000,
        "cooldownGroups": ["global"],
    }
    return {
        "id": "fixtureV4",
        "displayName": "Fixture v4",
        "description": "Valid two-atlas v4 fixture",
        "spriteVersionNumber": 4,
        "defaultForm": "foxEaredHuman",
        "iconFrame": {"atlas": "character", "row": 0, "column": 0},
        "atlases": {
            "character": {"path": "character.webp", "cellWidth": 192, "cellHeight": 208},
            "effects": {"path": "effects.webp", "cellWidth": 384, "cellHeight": 416},
        },
        "cooldownGroups": {"global": {"cooldownMs": 5000}},
        "actions": actions,
        "forms": {
            "foxEaredHuman": {
                "label": "Fox-eared human",
                "idleAction": "idle",
                "moveRightAction": "moveRight",
                "moveLeftAction": "moveLeft",
                "gazeAction": "gaze",
                "representativeAction": "idle",
                "interactionActions": ["spell", "transformEnter"],
            },
            "whiteFox": {
                "label": "White fox",
                "idleAction": "whiteFoxIdle",
                "moveRightAction": "whiteFoxMoveRight",
                "moveLeftAction": "whiteFoxMoveLeft",
                "representativeAction": "whiteFoxIdle",
                "interactionActions": ["whiteFoxRest"],
            },
        },
        "transformations": {
            "becomeWhiteFox": {
                "label": "Become a white fox",
                "fromForm": "foxEaredHuman",
                "toForm": "whiteFox",
                "enterAction": "transformEnter",
                "residentActions": [{"action": "whiteFoxRest", "weight": 100}],
                "exitAction": "transformExit",
                "minDurationMs": 1000,
                "maxDurationMs": 2000,
                "showInMenu": True,
                "autoplay": autoplay,
            }
        },
        "sequences": {
            "spellSequence": {
                "label": "Cast spell",
                "showInMenu": True,
                "steps": [
                    {
                        "action": "spell",
                        "repeatCount": 1,
                        "holdMs": 0,
                        "safeStopAfter": True,
                    }
                ],
            }
        },
    }


def _write_v4_manifest(root: Path, manifest: dict[str, object]) -> Path:
    pet_id = str(manifest["id"])
    return _write_pack(
        root,
        pet_id,
        sprite_version=4,
        atlases=manifest.get("atlases"),
        forms=manifest.get("forms"),
        default_form=manifest.get("defaultForm"),
        actions=manifest.get("actions"),
        transformations=manifest.get("transformations"),
        cooldown_groups=manifest.get("cooldownGroups"),
        sequences=manifest.get("sequences"),
        icon_frame=manifest.get("iconFrame"),
        display_name=manifest.get("displayName"),
        description=manifest.get("description"),
    )


def _write_valid_v4_pack(root: Path, pet_id: str) -> Path:
    manifest = _valid_v4_manifest()
    manifest["id"] = pet_id
    manifest["displayName"] = pet_id.title()
    return _write_v4_manifest(root, manifest)


def _write_and_refresh_v4(
    tmp_path: Path,
    manifest: dict[str, object],
    prepare_directory=None,
):
    root = tmp_path / "pets"
    directory = _write_v4_manifest(root, manifest)
    if prepare_directory is not None:
        prepare_directory(directory)
    return PetRegistry(root, None).refresh()


def test_v4_schema_declares_fixed_limits_and_required_sections():
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "pet-pack-v4.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["spriteVersionNumber"]["const"] == 4
    assert schema["properties"]["actions"]["maxProperties"] == 128
    assert schema["properties"]["forms"]["maxProperties"] == 16
    assert schema["properties"]["transformations"]["maxProperties"] == 32
    assert schema["properties"]["sequences"]["maxProperties"] == 16
    assert set(schema["required"]) >= {
        "id",
        "displayName",
        "spriteVersionNumber",
        "defaultForm",
        "atlases",
        "actions",
        "forms",
    }


def test_v4_schema_closes_id_maps_and_documents_frame_map_runtime_validation():
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "pet-pack-v4.schema.json").read_text(
            encoding="utf-8"
        )
    )
    definitions = schema["$defs"]
    id_pattern = definitions["id"]["pattern"]
    expected_values = {
        "atlases": "atlas",
        "cooldownGroups": "cooldownGroup",
        "actions": "action",
        "forms": "form",
        "transformations": "transformation",
        "sequences": "sequence",
    }

    for name, value_definition in expected_values.items():
        mapping = definitions[name]
        assert mapping["additionalProperties"] is False
        assert mapping["patternProperties"] == {
            id_pattern: {"$ref": f"#/$defs/{value_definition}"}
        }
        assert re.fullmatch(id_pattern, "validId")
        assert not re.fullmatch(id_pattern, "invalid-id")
        assert not re.fullmatch(id_pattern, "9invalid")

    frame_map = definitions["layer"]["properties"]["frameMap"]
    assert frame_map["minItems"] == 1
    assert frame_map["maxItems"] == 512
    assert frame_map["items"]["minimum"] == 0
    assert frame_map["items"]["maximum"] == 511
    assert "length == containing action.frameCount" in frame_map["$comment"]
    assert "available local layer frame" in frame_map["$comment"]
    assert "null skips drawing" in frame_map["$comment"]

    label_pattern = definitions["label"]["pattern"]
    assert re.fullmatch(label_pattern, "狐狸形态")
    assert not re.fullmatch(label_pattern, "bad\x00label")
    assert not re.fullmatch(label_pattern, "bad\x7flabel")
    assert not re.fullmatch(label_pattern, "bad\x80label")


def test_v4_domain_models_are_immutable_and_use_tuple_collections():
    layer = PetActionLayerDefinition("character", 0, 0, 96, 200, hit_test=True)
    action = PetActionDefinition("idle", "idle", "Idle", 0, layers=(layer,))
    atlas = PetAtlasDefinition("character", Path("character.webp"), 192, 208)
    form = PetFormDefinition(
        "defaultHuman", "Default", "idle", "moveRight", "moveLeft", None, "idle", ("idle",)
    )
    autoplay = PetAutoplayDefinition("common", 1, 1000, 2000, ("global",))
    transformation = PetTransformationDefinition(
        "change", "Change", "defaultHuman", "animal", "enter", (), "exit", 1000, 2000, True, autoplay
    )
    cooldown = PetCooldownGroupDefinition("global", 1000)
    step = PetSequenceStep("idle", 1, 0, "defaultHuman", True)
    sequence = PetSequenceDefinition("spell", "Spell", True, (step,), autoplay)

    assert action.layers == (layer,)
    assert atlas.path == Path("character.webp")
    assert form.interaction_actions == ("idle",)
    assert transformation.autoplay is autoplay
    assert cooldown.cooldown_ms == 1000
    assert sequence.steps == (step,)
    with pytest.raises(AttributeError):
        layer.hit_test = False


def test_registry_loads_v4_forms_layers_transformations_and_sequences(tmp_path: Path):
    directory = _write_valid_v4_pack(tmp_path / "pets", "fixtureV4")

    definition = PetRegistry(tmp_path / "pets", None).refresh().by_id("fixtureV4")

    assert definition.sprite_version == 4
    assert definition.default_form == "foxEaredHuman"
    assert tuple(item.key for item in definition.atlases) == ("character", "effects")
    assert definition.actions[0].layers[0].hit_test is True
    assert definition.transformations[0].autoplay.bucket == "commonTransform"
    assert definition.sequences[0].steps[0].safe_stop_after is True
    assert directory.joinpath("character.webp").is_file()


def test_registry_uses_v4_label_limits_for_display_name(tmp_path: Path):
    manifest = _valid_v4_manifest()
    manifest["displayName"] = "V" * 80

    definition = _write_and_refresh_v4(tmp_path, manifest).by_id("fixtureV4")

    assert definition.display_name == "V" * 80


def test_registry_accepts_schema_valid_v4_camel_case_pet_id(tmp_path: Path):
    manifest = _valid_v4_manifest()
    manifest["id"] = "foxPet"

    snapshot = _write_and_refresh_v4(tmp_path, manifest)

    assert snapshot.by_id("foxPet").pet_id == "foxPet"
    assert snapshot.issues == ()


@pytest.mark.parametrize("pet_id", ("fox_pet", "FoxPet"))
def test_registry_rejects_v4_pet_id_outside_schema_grammar(
    tmp_path: Path, pet_id: str
):
    manifest = _valid_v4_manifest()
    manifest["id"] = pet_id

    snapshot = _write_and_refresh_v4(tmp_path, manifest)

    assert snapshot.pets == ()
    assert "invalid v4 pet id" in snapshot.issues[0].message


def _remove_character_atlas(directory: Path) -> None:
    directory.joinpath("character.webp").unlink()


def _make_atlas_total_too_large(directory: Path) -> None:
    with directory.joinpath("character.webp").open("wb") as stream:
        stream.seek(32 * 1024 * 1024)
        stream.write(b"x")


def _add_mismatched_sequence_autoplay(pack: dict[str, object]) -> None:
    transformation = pack["transformations"]["becomeWhiteFox"]
    autoplay = dict(transformation["autoplay"])
    autoplay["maxDelayMs"] = 3000
    pack["sequences"]["spellSequence"]["autoplay"] = autoplay


@pytest.mark.parametrize(
    ("mutate", "prepare_directory", "message"),
    (
        (
            lambda pack: pack["atlases"]["character"].update(
                path="nested/character.webp"
            ),
            None,
            "bare WebP filename",
        ),
        (
            lambda pack: pack["atlases"]["character"].update(
                path="../character.webp"
            ),
            None,
            "bare WebP filename",
        ),
        (lambda pack: None, _remove_character_atlas, "atlas file is missing"),
        (
            lambda pack: pack["actions"]["idle"]["layers"][0].update(
                atlas="missing"
            ),
            None,
            "unknown atlas",
        ),
        (
            lambda pack: pack["actions"]["idle"]["layers"].append(
                dict(pack["actions"]["idle"]["layers"][0])
            ),
            None,
            "exactly one hitTest layer",
        ),
        (lambda pack: pack.update(defaultForm="missing"), None, "unknown defaultForm"),
        (
            lambda pack: pack["forms"]["foxEaredHuman"].update(
                representativeAction="missing"
            ),
            None,
            "unknown action",
        ),
        (
            lambda pack: pack["sequences"]["spellSequence"]["steps"][0].update(
                action="missing"
            ),
            None,
            "unknown action",
        ),
        (
            lambda pack: pack["transformations"]["becomeWhiteFox"].update(
                toForm="missing"
            ),
            None,
            "unknown form",
        ),
        (
            lambda pack: pack["transformations"]["becomeWhiteFox"][
                "autoplay"
            ].update(cooldownGroups=["missing"]),
            None,
            "unknown cooldown group",
        ),
        (
            lambda pack: pack["forms"]["foxEaredHuman"].update(
                moveRightAction="spell"
            ),
            None,
            "default form must define idle and both move directions",
        ),
        (
            lambda pack: pack["actions"]["gaze"].update(frameCount=15),
            None,
            "16, 32, or 64 frames",
        ),
        (
            lambda pack: pack["actions"]["spell"].update(
                role="burstMove",
                direction="right",
                travelDistanceRatio=10**400,
            ),
            None,
            "travelDistanceRatio must be 0.05 through 1",
        ),
        (
            lambda pack: pack["forms"]["whiteFox"].update(gazeAction="gaze"),
            None,
            "only the default form may define gazeAction",
        ),
        (
            lambda pack: pack["actions"]["spell"]["layers"][0].update(
                frameMap=[0, 1]
            ),
            None,
            "frameMap length must match frameCount",
        ),
        (
            lambda pack: pack["actions"]["spell"]["layers"][0].update(
                frameMap=[0, 1, 2, 4]
            ),
            None,
            "frameMap references an unavailable atlas cell",
        ),
        (_add_mismatched_sequence_autoplay, None, "autoplay bucket definitions must match"),
        (
            lambda pack: pack["sequences"]["spellSequence"]["steps"][0].update(
                action="spellSequence"
            ),
            None,
            "sequence steps may reference actions only",
        ),
        (
            lambda pack: pack["transformations"]["becomeWhiteFox"].update(
                fromForm="whiteFox"
            ),
            None,
            "transformations must originate from defaultForm",
        ),
        (
            lambda pack: pack["transformations"]["becomeWhiteFox"].update(
                minDurationMs=3000
            ),
            None,
            "minDurationMs cannot exceed maxDurationMs",
        ),
        (lambda pack: None, _make_atlas_total_too_large, "32 MiB"),
        (
            lambda pack: pack.update(description="unsafe\ndescription"),
            None,
            "description contains control characters",
        ),
    ),
)
def test_registry_rejects_incoherent_v4_references(
    tmp_path: Path, mutate, prepare_directory, message: str
):
    manifest = _valid_v4_manifest()
    mutate(manifest)

    snapshot = _write_and_refresh_v4(tmp_path, manifest, prepare_directory)

    assert snapshot.pets == ()
    assert message in snapshot.issues[0].message


def test_registry_defaults_v4_collections_for_legacy_packs(tmp_path: Path):
    root = tmp_path / "pets"
    _write_pack(root, "legacy")
    _write_pack(root, "dynamic", sprite_version=3, actions=_valid_v3_actions())

    snapshot = PetRegistry(root, None).refresh()

    for pet_id in ("legacy", "dynamic"):
        definition = snapshot.by_id(pet_id)
        assert definition.atlases == ()
        assert definition.forms == ()
        assert definition.default_form == ""
        assert definition.transformations == ()
        assert definition.cooldown_groups == ()
        assert definition.sequences == ()


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


@pytest.mark.parametrize("sprite_version", (2, 3))
def test_registry_preserves_canonical_lowercase_ids_for_v2_and_v3(
    tmp_path: Path, sprite_version: int
):
    root = tmp_path / "pets"
    actions = _valid_v3_actions() if sprite_version == 3 else None
    _write_pack(
        root,
        f"legacyv{sprite_version}good",
        sprite_version=sprite_version,
        actions=actions,
    )
    _write_pack(
        root,
        f"LegacyV{sprite_version}bad",
        sprite_version=sprite_version,
        actions=actions,
    )

    snapshot = PetRegistry(root, None).refresh()

    assert snapshot.choices == (
        (f"legacyv{sprite_version}good", f"Legacyv{sprite_version}Good"),
    )
    assert len(snapshot.issues) == 1
    assert "invalid pet id" in snapshot.issues[0].message


@pytest.mark.parametrize("sprite_version", (None, "4", [], {}, 5))
def test_registry_quarantines_malformed_or_unsupported_sprite_versions(
    tmp_path: Path, sprite_version
):
    root = tmp_path / "pets"
    _write_pack(root, "badversion", sprite_version=sprite_version)

    snapshot = PetRegistry(root, None).refresh()

    assert snapshot.pets == ()
    assert len(snapshot.issues) == 1


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


def _valid_v3_state_actions() -> dict[str, dict[str, object]]:
    actions = _valid_v3_actions()
    actions.update(
        {
            "rooftopEnter": {
                "label": "进入月下屋檐",
                "role": "interaction",
                "row": 4,
                "frameCount": 4,
                "frameMs": 140,
                "autoplayWeight": 5,
                "cooldownMs": 90000,
            },
            "rooftopIdle": {
                "label": "屋檐静坐",
                "role": "interaction",
                "row": 5,
                "frameCount": 4,
                "frameMs": 180,
                "showInMenu": False,
            },
            "rooftopMoon": {
                "label": "仰望月色",
                "role": "interaction",
                "row": 6,
                "frameCount": 4,
                "frameMs": 180,
                "showInMenu": False,
            },
            "rooftopExit": {
                "label": "离开月下屋檐",
                "role": "interaction",
                "row": 7,
                "frameCount": 4,
                "frameMs": 140,
                "showInMenu": False,
            },
        }
    )
    return actions


def _valid_v3_states() -> dict[str, dict[str, object]]:
    return {
        "moonlitRooftop": {
            "label": "月下屋檐",
            "enterAction": "rooftopEnter",
            "residentActions": [
                {"action": "rooftopIdle", "weight": 70},
                {"action": "rooftopMoon", "weight": 30},
            ],
            "exitAction": "rooftopExit",
            "minDurationMs": 30000,
            "rampDurationMs": 30000,
            "maxDurationMs": 90000,
            "exitChanceAfterMin": 5,
            "exitChanceAfterRamp": 25,
        }
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


def test_v3_allows_long_actions_and_parses_showcase_opt_out():
    actions = _valid_v3_actions()
    actions["longShowcase"] = {
        "label": "完整动作展示",
        "role": "interaction",
        "row": 4,
        "frameCount": 448,
        "frameDurations": [33] * 447 + [34],
        "repeatCount": 1,
        "autoplayWeight": 0,
        "showInMenu": True,
        "includeInShowcase": False,
    }

    parsed = {
        item.action_id: item for item in PetRegistry._parse_v3_actions(actions)
    }

    assert parsed["longShowcase"].spec.frame_count == 448
    assert parsed["longShowcase"].include_in_showcase is False
    assert parsed["hello"].include_in_showcase is True


def test_v3_rejects_more_than_512_frames_and_non_boolean_showcase_flag():
    too_long = _valid_v3_actions()
    too_long["hello"]["frameCount"] = 513
    too_long["hello"]["frameDurations"] = [33] * 513
    too_long["hello"].pop("frameMs")
    with pytest.raises(ValueError, match="frameCount must be 1 through 512"):
        PetRegistry._parse_v3_actions(too_long)

    invalid_flag = _valid_v3_actions()
    invalid_flag["hello"]["includeInShowcase"] = 0
    with pytest.raises(ValueError, match="includeInShowcase must be boolean"):
        PetRegistry._parse_v3_actions(invalid_flag)


def test_registry_loads_valid_persistent_state_with_weighted_resident_actions(
    tmp_path: Path,
):
    bundled = tmp_path / "bundled"
    _write_pack(
        bundled,
        "state_pet",
        sprite_version=3,
        actions=_valid_v3_state_actions(),
        states=_valid_v3_states(),
    )

    definition = PetRegistry(bundled, None).refresh().by_id("state_pet")

    assert len(definition.states) == 1
    state = definition.states[0]
    assert state.key == "moonlitRooftop"
    assert state.enter_action == "rooftopEnter"
    assert [(choice.action_id, choice.weight) for choice in state.resident_actions] == [
        ("rooftopIdle", 70),
        ("rooftopMoon", 30),
    ]
    assert state.exit_action == "rooftopExit"
    assert state.min_duration_ms == 30000
    assert state.ramp_duration_ms == 30000
    assert state.max_duration_ms == 90000


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda actions, states: states["moonlitRooftop"].update(
                {"enterAction": "missing"}
            ),
            "unknown action",
        ),
        (
            lambda actions, states: actions["rooftopIdle"].update(
                {"showInMenu": True}
            ),
            "hidden with autoplayWeight 0",
        ),
        (
            lambda actions, states: states["moonlitRooftop"].update(
                {"maxDurationMs": 50000}
            ),
            "at least minDurationMs plus rampDurationMs",
        ),
        (
            lambda actions, states: states["moonlitRooftop"].update(
                {"exitChanceAfterMin": 30, "exitChanceAfterRamp": 20}
            ),
            "exit chances must increase",
        ),
    ),
)
def test_registry_rejects_unsafe_or_incoherent_persistent_states(
    tmp_path: Path, mutate, message: str
):
    bundled = tmp_path / "bundled"
    actions = _valid_v3_state_actions()
    states = _valid_v3_states()
    mutate(actions, states)
    _write_pack(
        bundled,
        "bad_state",
        sprite_version=3,
        actions=actions,
        states=states,
    )

    snapshot = PetRegistry(bundled, None).refresh()

    assert snapshot.pets == ()
    assert message in snapshot.issues[0].message


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


def test_registry_keeps_gaze_limited_when_other_actions_allow_more_frames():
    actions = _valid_v3_actions()
    actions["gaze"] = {
        "label": "方向数量错误",
        "role": "gaze",
        "row": 5,
        "frameCount": 448,
        "frameDurations": [100] * 448,
        "showInMenu": False,
    }

    with pytest.raises(ValueError, match="16, 32, or 64 frames"):
        PetRegistry._parse_v3_actions(actions)


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
