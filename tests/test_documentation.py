import json
from pathlib import Path
import re

from shiyi_desktop_pet.models import ActionRole
from shiyi_desktop_pet.pet_registry import PetRegistry


_MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def test_beginner_readme_names_the_installer_and_routes_each_audience(repo_root: Path):
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "DesktopCompanion-2.4.7-setup.exe" in readme
    assert "普通用户只需要下载" in readme
    assert "docs/新手使用指南.md" in readme
    assert "docs/添加新宠物指南.md" in readme
    assert "docs/pet-pack-format-v3.md" in readme
    assert "docs/pet-pack-format-v2.md" in readme


def test_documentation_local_links_point_to_existing_files(repo_root: Path):
    documents = (
        repo_root / "README.md",
        repo_root / "docs" / "新手使用指南.md",
        repo_root / "docs" / "添加新宠物指南.md",
        repo_root / "docs" / "pet-pack-format-v3.md",
        repo_root / "docs" / "pet-pack-format-v2.md",
        repo_root / "examples" / "pet-pack-template" / "README.md",
    )

    missing: list[str] = []
    for document in documents:
        for target in _MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            path_text = target.split("#", 1)[0]
            if not path_text or "://" in path_text:
                continue
            if not (document.parent / path_text).resolve().exists():
                missing.append(f"{document.relative_to(repo_root)} -> {target}")

    assert missing == []


def test_pet_pack_template_matches_runtime_manifest_contract(
    repo_root: Path, tmp_path: Path
):
    template_path = repo_root / "examples" / "pet-pack-template" / "pet.json"
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    pet_directory = tmp_path / "pets" / manifest["id"]
    pet_directory.mkdir(parents=True)
    (pet_directory / "pet.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    (pet_directory / "spritesheet.webp").write_bytes(b"documented-template")
    bundled_root = tmp_path / "bundled"
    bundled_root.mkdir()

    snapshot = PetRegistry(bundled_root, tmp_path / "pets").refresh()
    definition = snapshot.by_id("my_pet")
    actions = {item.action_id: item for item in definition.actions}

    assert snapshot.issues == ()
    assert definition.display_name == "我的宠物"
    assert definition.sprite_version == 3
    assert actions["greet"].label == "打个招呼"
    assert actions["greet"].autoplay_weight == 3
    assert actions["greet"].role is ActionRole.INTERACTION
    assert actions["moveRight"].autoplay_weight == 19
    assert actions["moveLeft"].mirror_of == "moveRight"
    assert actions["dashRight"].role is ActionRole.BURST_MOVE


def test_pet_pack_v3_schema_and_template_describe_dynamic_actions(repo_root: Path):
    schema = json.loads(
        (repo_root / "schemas" / "pet-pack-v3.schema.json").read_text(
            encoding="utf-8"
        )
    )
    template = json.loads(
        (repo_root / "examples" / "pet-pack-template" / "pet.json").read_text(
            encoding="utf-8"
        )
    )
    format_guide = (repo_root / "docs" / "pet-pack-format-v3.md").read_text(
        encoding="utf-8"
    )

    action_schema = schema["properties"]["actions"]
    common = schema["$defs"]["common"]["properties"]
    direct = schema["$defs"]["direct"]["allOf"][1]["properties"]
    assert action_schema["minProperties"] == 3
    assert action_schema["maxProperties"] == 64
    assert schema["properties"]["spriteVersionNumber"]["const"] == 3
    assert schema["properties"]["spritesheetPath"]["const"] == "spritesheet.webp"
    assert "autoplayGroup" in schema["$defs"]["common"]["properties"]
    assert common["includeInShowcase"] == {"type": "boolean"}
    assert direct["frameCount"]["maximum"] == 512
    assert direct["frameDurations"]["maxItems"] == 512
    assert direct["travelStartFrame"]["maximum"] == 511
    assert direct["travelEndFrame"]["maximum"] == 511
    assert schema["$defs"]["direct"]["allOf"][2]["then"]["properties"][
        "frameCount"
    ]["enum"] == [16, 32, 64]
    assert "includeInShowcase" in format_guide
    assert "1–512" in format_guide
    assert "16、32 或 64" in format_guide
    assert template["spriteVersionNumber"] == 3
    assert {entry["role"] for entry in template["actions"].values()} >= {
        "idle",
        "move",
        "interaction",
        "burstMove",
    }


def test_legacy_v2_schema_remains_available(repo_root: Path):
    schema = json.loads(
        (repo_root / "schemas" / "pet-pack-v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["spriteVersionNumber"]["const"] == 2


def test_v246_rooftop_timing_documentation_matches_resource_contract(repo_root: Path):
    expected = "最短 25 秒、渐变 20 秒、最长 60 秒"
    manual_qa = (repo_root / "docs" / "manual-qa-v2.4.6.md").read_text(
        encoding="utf-8"
    )
    changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    format_guide = (repo_root / "docs" / "pet-pack-format-v3.md").read_text(
        encoding="utf-8"
    )

    assert expected in manual_qa
    assert "最短驻留由 20 秒提高到 25 秒" in changelog
    assert '"minDurationMs": 25000' in format_guide
    assert '"rampDurationMs": 20000' in format_guide
    assert '"maxDurationMs": 60000' in format_guide
    assert "30–90 秒" not in format_guide
