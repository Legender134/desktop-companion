from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

from jsonschema import Draft202012Validator, ValidationError
from PIL import Image
from PySide6.QtCore import QPoint, QRect, QSize
import pytest

from shiyi_desktop_pet.app import DesktopPetApplication
from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.autoplay import AutoplayBucketScheduler
from shiyi_desktop_pet.multiform import MultiformController, RuntimeCommandKind
from shiyi_desktop_pet.pet_registry import PetRegistry
from shiyi_desktop_pet.settings import AppSettings, SettingsStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "pets"


def _load_fixture():
    snapshot = PetRegistry(
        FIXTURE_ROOT,
        None,
        validator=AnimationCatalog.load_definition,
    ).refresh()
    assert snapshot.issues == ()
    definition = snapshot.by_id("multiformV4")
    assert definition is not None
    return definition, AnimationCatalog.load_definition(definition)


def test_real_v4_fixture_loads_through_registry_and_catalog():
    definition, catalog = _load_fixture()

    assert definition.manifest_path.parent.name == "multiformV4"
    assert catalog.sprite_version == 4
    assert catalog.form_keys == ("defaultHuman", "smallAnimal")
    frame = catalog.rendered_frames("wideSpell", "full")[0]
    assert frame.image.size() == QSize(384, 208)
    assert frame.body_image.size() == QSize(192, 208)


def test_real_v4_fixture_resolves_after_settings_restart(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.ini")
    store.save(AppSettings(pet_id="multiformV4"))

    restarted_settings = SettingsStore(store.path).load()
    restarted_snapshot = PetRegistry(FIXTURE_ROOT, None).refresh()
    restarted_definition = restarted_snapshot.by_id(restarted_settings.pet_id)

    assert restarted_definition is not None
    assert AnimationCatalog.load_definition(restarted_definition).pet_id == "multiformV4"


def test_fixture_manifest_validates_against_the_published_schema(repo_root: Path):
    schema = json.loads(
        (repo_root / "schemas" / "pet-pack-v4.schema.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads(
        (FIXTURE_ROOT / "multiformV4" / "pet.json").read_text(encoding="utf-8")
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)


@pytest.mark.parametrize(
    "invalid_change",
    (
        lambda manifest: manifest.__setitem__("unknownRootField", True),
        lambda manifest: manifest.__setitem__("id", "multiform_v4"),
        lambda manifest: manifest["actions"]["humanIdle"].__setitem__(
            "frameCount", "2"
        ),
    ),
    ids=("unknown-root-field", "underscore-id", "wrong-field-type"),
)
def test_published_schema_independently_rejects_invalid_fixture_mutations(
    repo_root: Path, invalid_change
):
    schema = json.loads(
        (repo_root / "schemas" / "pet-pack-v4.schema.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads(
        (FIXTURE_ROOT / "multiformV4" / "pet.json").read_text(encoding="utf-8")
    )
    invalid_manifest = deepcopy(manifest)
    invalid_change(invalid_manifest)

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid_manifest)


def test_lossless_geometric_atlases_have_stable_sizes_and_alpha():
    expected = {
        "character.webp": (
            (768, 2496),
            9_670,
            "0a9bdfdb8eab232aca063f8d28fbd35ac8749f5182d9b36ab4f07a6d632c29b9",
        ),
        "effects.webp": (
            (1152, 208),
            1_644,
            "72a8f337557aaa4e47f9cbcf761b0a329e704d1ff9130c3008969168e869b3a1",
        ),
    }

    for name, (size, encoded_bytes, sha256) in expected.items():
        path = FIXTURE_ROOT / "multiformV4" / name
        with Image.open(path) as atlas:
            assert atlas.format == "WEBP"
            assert atlas.mode == "RGBA"
            assert atlas.size == size
        assert path.read_bytes()[12:16] == b"VP8L"
        assert path.stat().st_size == encoded_bytes
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha256


def test_full_and_simplified_composition_preserve_body_world_anchor():
    _, catalog = _load_fixture()

    full = catalog.rendered_frames("wideSpell", "full")
    simplified = catalog.rendered_frames("wideSpell", "simplified")

    assert full[0].image.size() == QSize(384, 208)
    assert full[0].body_rect == QRect(96, 0, 192, 208)
    assert full[0].anchor == QPoint(192, 208)
    assert full[0].image.pixelColor(20, 104).alpha() > 0
    assert not full[0].body_rect.contains(QPoint(20, 104))
    assert full[0].body_image.size() == QSize(192, 208)

    assert simplified[0].image.size() == QSize(192, 208)
    assert simplified[0].body_rect == QRect(0, 0, 192, 208)
    assert simplified[0].anchor == QPoint(96, 208)
    assert (
        full[0].body_rect.topLeft() - full[0].anchor
        == simplified[0].body_rect.topLeft() - simplified[0].anchor
        == QPoint(-96, -208)
    )
    assert full[1].image.size() == QSize(192, 208)
    assert full[1].identity[-1] == (("character", 1),)


def test_mirror_and_form_apis_use_rendered_fixture_pixels():
    _, catalog = _load_fixture()

    right = catalog.rendered_frames("humanMoveRight")[0]
    left = catalog.rendered_frames("humanMoveLeft")[0]

    assert right.body_image.pixelColor(66, 83).red() > 200
    assert left.body_image.pixelColor(125, 83).red() > 200
    assert left.anchor == QPoint(right.image.width() - right.anchor.x(), right.anchor.y())
    assert catalog.idle_action_for("defaultHuman") == "humanIdle"
    assert catalog.idle_action_for("smallAnimal") == "animalIdle"
    assert catalog.supports_gaze_for("defaultHuman")
    assert not catalog.supports_gaze_for("smallAnimal")
    assert catalog.look_frame_for("defaultHuman", 22.5).image.size() == QSize(192, 208)
    assert tuple(
        item.action_id for item in catalog.movement_actions_for("smallAnimal", -1)
    ) == ("animalMoveLeft",)
    assert catalog.interaction_actions_for("smallAnimal") == ("animalResident",)


def test_fixture_transformation_sequence_and_hard_cleanup_are_runtime_driven():
    definition, _ = _load_fixture()
    controller = MultiformController(
        default_form=definition.default_form,
        forms=definition.forms,
        transformations=definition.transformations,
        sequences=definition.sequences,
        rng=random.Random(7),
    )

    command = controller.request_transformation("becomeAnimal", manual=True, now_ms=0)
    assert command.kind is RuntimeCommandKind.PLAY
    assert (command.action, command.started_kind, command.started_key) == (
        "transformEnter",
        "transformation",
        "becomeAnimal",
    )
    command = controller.action_finished(50)
    assert (command.kind, command.form, command.action) == (
        RuntimeCommandKind.SET_FORM,
        "smallAnimal",
        "animalResident",
    )
    controller.request_stop()
    assert controller.action_finished(100).action == "transformExit"
    command = controller.action_finished(150)
    assert (command.kind, command.form, controller.current_form) == (
        RuntimeCommandKind.SET_FORM,
        "defaultHuman",
        "defaultHuman",
    )

    command = controller.request_sequence("shapeBurst", manual=True, now_ms=200)
    assert (command.action, command.repeat_count, command.hold_ms) == (
        "wideSpell",
        2,
        125,
    )
    controller.request_stop()
    command = controller.action_finished(300)
    assert (command.kind, command.form, command.action) == (
        RuntimeCommandKind.SET_FORM,
        "smallAnimal",
        "animalResident",
    )
    command = controller.action_finished(400)
    assert (command.kind, command.form, controller.busy) == (
        RuntimeCommandKind.CLEANUP,
        "defaultHuman",
        False,
    )

    controller.request_transformation("becomeAnimal", manual=True, now_ms=500)
    first_cleanup = controller.hard_cancel()
    second_cleanup = controller.hard_cancel()
    assert first_cleanup == second_cleanup
    assert first_cleanup[0].kind is RuntimeCommandKind.CLEANUP
    assert controller.current_form == "defaultHuman"
    assert not controller.busy


def test_real_application_cleanup_strips_wide_effect_without_a_qt_event_loop():
    definition, catalog = _load_fixture()
    controller = MultiformController(
        default_form=definition.default_form,
        forms=definition.forms,
        transformations=definition.transformations,
        sequences=definition.sequences,
        rng=random.Random(7),
    )
    controller.request_sequence("shapeBurst", manual=True, now_ms=0)

    class MinimalBehavior:
        def __init__(self):
            self.scripted_finished_count = 0

        def scripted_finished(self):
            self.scripted_finished_count += 1

    application = object.__new__(DesktopPetApplication)
    application.catalog = catalog
    application.multiform = controller
    application.v4_autoplay = None
    application.behavior = MinimalBehavior()
    application._runtime_repeat_remaining = 9
    application._runtime_step_hold_ms = 875
    application._runtime_hold_until_ms = 1_234
    application._displayed_frame = ("wide-effect",)
    shown_frames = []
    application._show_frame = shown_frames.append

    assert DesktopPetApplication._hard_cancel_v4(application)

    assert not controller.busy
    assert controller.current_form == "defaultHuman"
    assert not controller._sequence_steps
    assert application._runtime_repeat_remaining == 0
    assert application._runtime_step_hold_ms == 0
    assert application._runtime_hold_until_ms is None
    assert application.behavior.scripted_finished_count == 1
    assert len(shown_frames) == 1
    cleanup_frame = shown_frames[0]
    assert cleanup_frame.image == cleanup_frame.body_image
    assert cleanup_frame.body_rect == QRect(
        0, 0, cleanup_frame.body_image.width(), cleanup_frame.body_image.height()
    )
    assert cleanup_frame.image.size() == QSize(192, 208)


def test_fixture_autoplay_uses_one_bucket_deadline_and_shared_cooldown():
    definition, _ = _load_fixture()
    scheduler = AutoplayBucketScheduler(
        definition.transformations,
        definition.sequences,
        definition.cooldown_groups,
        default_form=definition.default_form,
        rng=random.Random(5),
    )

    scheduler.reset(0)
    assert scheduler.deadlines == {"shapeEvents": 100}
    assert scheduler.choose_due(99, "defaultHuman", random.Random(0)) is None
    candidate = scheduler.choose_due(100, "defaultHuman", random.Random(0))
    assert (candidate.kind, candidate.key) == ("sequence", "shapeBurst")
    alternate = scheduler.choose_due(100, "defaultHuman", random.Random(1))
    assert (alternate.kind, alternate.key) == ("transformation", "becomeAnimal")

    scheduler.record_started(candidate, 100, automatic=False)
    assert scheduler.deadlines == {"shapeEvents": 100}
    assert scheduler.cooldown_deadlines == {"sharedShape": 600}
    assert scheduler.choose_due(100, "defaultHuman", random.Random(1)) is None
    scheduler.defer(100)
    assert scheduler.deadlines == {"shapeEvents": 1_100}

    scheduler.record_started(candidate, 600, automatic=True)
    assert scheduler.deadlines == {"shapeEvents": 700}
    assert scheduler.cooldown_deadlines == {"sharedShape": 1_100}
    assert scheduler.choose_due(700, "defaultHuman", random.Random(1)) is None
    scheduler.defer(700)
    assert scheduler.deadlines == {"shapeEvents": 1_700}
