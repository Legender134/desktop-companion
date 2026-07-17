import json
from pathlib import Path
import shutil

from shiyi_desktop_pet.animation_catalog import AnimationCatalog
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
) -> Path:
    directory = root / pet_id
    directory.mkdir(parents=True)
    (directory / "pet.json").write_text(
        json.dumps(
            {
                "id": manifest_id or pet_id,
                "displayName": pet_id.title(),
                "description": f"{pet_id} test pet",
                "spriteVersionNumber": sprite_version,
                "spritesheetPath": spritesheet_path,
            }
        ),
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

    assert {pet_id for pet_id, _ in snapshot.choices} == {"shiyi", "ziling", "copycat"}
    assert catalog.pet_id == "copycat"
    assert catalog.display_name == "Copycat"
    assert snapshot.issues == ()
