import json
from hashlib import sha256
from pathlib import Path

from PySide6.QtGui import QImage

from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.resource_locator import resource_path


FRAME_COUNTS = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)


def alpha_count(image: QImage) -> int:
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 0
    )


def test_packaged_legacy_resources_obey_multi_pet_v2_contract():
    expected = {
        "shiyi": {
            "id": "shiyi",
            "displayName": "十一",
            "description": "一只好奇亲人、略带呆萌气质的银黑经典虎斑猫。",
            "spriteVersionNumber": 2,
            "spritesheetPath": "spritesheet.webp",
            "iconFrame": {"row": 0, "column": 0},
            "actions": {
                "idle": {"label": "休息", "autoplayWeight": 0},
                "moveRight": {"label": "向右奔跑", "autoplayWeight": 0},
                "moveLeft": {"label": "向左奔跑", "autoplayWeight": 0},
                "greet": {"label": "抬爪招呼", "autoplayWeight": 3},
                "jump": {"label": "开心扑跳", "autoplayWeight": 1},
                "special": {"label": "撒娇翻肚", "autoplayWeight": 2},
                "wait": {"label": "乖乖等候", "autoplayWeight": 3},
                "observe": {"label": "四处巡视", "autoplayWeight": 2},
                "curious": {"label": "好奇观察", "autoplayWeight": 3},
            },
        },
        "ziling": {
            "id": "ziling",
            "displayName": "紫灵",
            "description": "《凡人修仙传》动画中的成年紫灵，清冷温柔的精致Q版紫白仙裙人物宠物。",
            "spriteVersionNumber": 2,
            "spritesheetPath": "spritesheet.webp",
            "iconFrame": {"row": 0, "column": 0},
            "actions": {
                "idle": {"label": "静静相伴", "autoplayWeight": 0},
                "moveRight": {"label": "向右轻行", "autoplayWeight": 0},
                "moveLeft": {"label": "向左轻行", "autoplayWeight": 0},
                "greet": {"label": "挥手问候", "autoplayWeight": 3},
                "jump": {"label": "翩然旋舞", "autoplayWeight": 1},
                "special": {"label": "舒展衣袖", "autoplayWeight": 2},
                "wait": {"label": "安静等候", "autoplayWeight": 3},
                "observe": {"label": "凝神静气", "autoplayWeight": 2},
                "curious": {"label": "若有所思", "autoplayWeight": 3},
            },
        },
    }

    for pet_id, expected_manifest in expected.items():
        root = f"pets/{pet_id}"
        manifest = json.loads(resource_path(f"{root}/pet.json").read_text(encoding="utf-8"))
        assert manifest == expected_manifest
        atlas = QImage(str(resource_path(f"{root}/spritesheet.webp")))
        assert not atlas.isNull()
        assert (atlas.width(), atlas.height()) == (1536, 2288)
        assert atlas.hasAlphaChannel()
        for row, used in enumerate(FRAME_COUNTS):
            for column in range(8):
                cell = atlas.copy(column * 192, row * 208, 192, 208)
                assert (alpha_count(cell) > 0) is (column < used)


def test_packaged_nangongwan_resource_obeys_dynamic_v3_contract():
    root = "pets/nangongwan"
    manifest = json.loads(resource_path(f"{root}/pet.json").read_text(encoding="utf-8"))

    assert manifest["id"] == "nangongwan"
    assert manifest["displayName"] == "南宫婉"
    assert manifest["spriteVersionNumber"] == 3
    assert manifest["spritesheetPath"] == "spritesheet.webp"
    assert len(manifest["actions"]) == 32
    assert sum(spec["frameCount"] for spec in manifest["actions"].values()) == 852
    assert manifest["actions"]["idle"]["role"] == "idle"
    assert manifest["actions"]["moveRight"]["role"] == "move"
    assert manifest["actions"]["moveLeft"]["role"] == "move"
    assert manifest["actions"]["burstRight"]["role"] == "burstMove"
    assert manifest["actions"]["burstLeft"]["role"] == "burstMove"
    assert manifest["actions"]["gaze"] == {
        "label": "随眸相望",
        "role": "gaze",
        "row": 19,
        "frameCount": 64,
        "frameMs": 100,
        "showInMenu": False,
    }
    moonlit = manifest["actions"]["moonlitChestnut"]
    assert moonlit == {
        "label": "月下屋檐",
        "role": "interaction",
        "row": 23,
        "frameCount": 18,
        "frameDurations": [
            90, 90, 100, 90, 100, 90, 100, 90, 110,
            110, 110, 110, 120, 120, 130, 140, 160, 220,
        ],
        "repeatCount": 1,
        "autoplayWeight": 5,
        "cooldownMs": 90000,
        "showInMenu": True,
    }
    assert sum(moonlit["frameDurations"]) == 2080

    rooftop_chestnut = manifest["actions"]["rooftopChestnut"]
    assert rooftop_chestnut["frameCount"] == 44
    assert len(rooftop_chestnut["frameDurations"]) == 44
    assert sum(rooftop_chestnut["frameDurations"]) == 8990

    assert manifest["states"]["moonlitRooftop"] == {
        "label": "月下屋檐",
        "enterAction": "moonlitChestnut",
        "residentActions": [
            {"action": "rooftopIdle", "weight": 18},
            {"action": "rooftopMoonGaze", "weight": 12},
            {"action": "rooftopChestnut", "weight": 20},
            {"action": "rooftopRest", "weight": 10},
            {"action": "rooftopBreeze", "weight": 10},
            {"action": "rooftopGlance", "weight": 8},
            {"action": "rooftopHair", "weight": 8},
            {"action": "rooftopBracelet", "weight": 7},
            {"action": "rooftopCranes", "weight": 7},
        ],
        "exitAction": "rooftopExit",
        "minDurationMs": 25000,
        "rampDurationMs": 20000,
        "maxDurationMs": 60000,
        "exitChanceAfterMin": 12,
        "exitChanceAfterRamp": 30,
    }

    standing_cake = manifest["actions"]["tasteCake"]
    assert standing_cake["label"] == "栗糕轻尝"
    assert standing_cake["frameCount"] == 10
    assert standing_cake["autoplayWeight"] == 2
    assert standing_cake["cooldownMs"] == 35000
    assert standing_cake["showInMenu"] is True

    complete = manifest["actions"]["completeShowcase"]
    assert complete["label"] == "完整动作展示"
    assert complete["row"] == 34
    assert complete["startColumn"] == 0
    assert complete["frameCount"] == 448
    assert len(complete["frameDurations"]) == 448
    assert sum(complete["frameDurations"]) == 82_433
    assert (min(complete["frameDurations"]), max(complete["frameDurations"])) == (
        33,
        666,
    )
    assert complete["repeatCount"] == 1
    assert complete["autoplayWeight"] == 0
    assert complete["showInMenu"] is True
    assert complete["includeInShowcase"] is False

    atlas_path = resource_path(f"{root}/spritesheet.webp")
    atlas = QImage(str(atlas_path))
    assert not atlas.isNull()
    assert (atlas.width(), atlas.height()) == (3072, 12896)
    assert atlas.hasAlphaChannel()
    assert sha256(atlas_path.read_bytes()).hexdigest() == (
        "6c1df790c2807c6b0293cada191fbf47be644b56a77894a3feb9407f8581c728"
    )

    columns = atlas.width() // 192
    for spec in manifest["actions"].values():
        start = spec["row"] * columns + spec.get("startColumn", 0)
        for offset in range(spec["frameCount"]):
            row, column = divmod(start + offset, columns)
            cell = atlas.copy(column * 192, row * 208, 192, 208)
            assert alpha_count(cell) > 0

    final_rooftop = atlas.copy(5 * 192, 33 * 208, 192, 208)
    assert alpha_count(final_rooftop) > 0

    catalog = AnimationCatalog.load_pet("nangongwan")
    assert catalog.supports_gaze
    assert len(catalog.look_degrees) == 64
    assert len(
        {
            catalog.look_frame(degrees).image.constBits().tobytes()
            for degrees in catalog.look_degrees
        }
    ) == 64
    assert (catalog.look_frame(0.0).row, catalog.look_frame(0.0).column) == (19, 0)
    assert (catalog.look_frame(337.5).row, catalog.look_frame(337.5).column) == (
        22,
        12,
    )
    assert (catalog.look_frame(354.375).row, catalog.look_frame(354.375).column) == (
        22,
        15,
    )


def test_nangongwan_legacy_moonlit_atlas_is_preserved_byte_for_byte():
    root = resource_path("pets/nangongwan/pet.json").parent
    manifest = json.loads((root / "pet.json").read_text(encoding="utf-8"))
    legacy = root / "spritesheet-moonlit-chestnut-v2.4.1-legacy.webp"

    assert manifest["spritesheetPath"] == "spritesheet.webp"
    assert legacy.is_file()
    payload = legacy.read_bytes()
    assert len(payload) == 8_634_008
    assert sha256(payload).hexdigest().upper() == (
        "990D1EE9DB3632102E9F07984301519606A9CC3591585E8EF892D0BA975A9D3E"
    )


def test_nangongwan_v246_active_atlas_is_archived_outside_packaged_resources():
    root = Path(__file__).resolve().parents[1]
    archive = (
        root
        / "tools"
        / "archives"
        / "nangongwan-complete-showcase-v2.4.6"
    )
    atlas = archive / "spritesheet.webp"
    manifest = archive / "pet.json"

    assert atlas.is_file()
    assert manifest.is_file()
    payload = atlas.read_bytes()
    assert len(payload) == 9_838_046
    assert sha256(payload).hexdigest() == (
        "564793e6c2e090d8e882cc4a829ceccb9bde2ab98b54b9f6126c65cf41fac77e"
    )
    assert json.loads(manifest.read_text(encoding="utf-8"))["actions"].get(
        "completeShowcase"
    ) is None
