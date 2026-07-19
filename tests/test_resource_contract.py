import json

from PySide6.QtGui import QImage

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
    assert len(manifest["actions"]) == 19
    assert manifest["actions"]["idle"]["role"] == "idle"
    assert manifest["actions"]["moveRight"]["role"] == "move"
    assert manifest["actions"]["moveLeft"]["role"] == "move"
    assert manifest["actions"]["burstRight"]["role"] == "burstMove"
    assert manifest["actions"]["burstLeft"]["role"] == "burstMove"

    atlas = QImage(str(resource_path(f"{root}/spritesheet.webp")))
    assert not atlas.isNull()
    assert (atlas.width(), atlas.height()) == (1920, 3952)
    assert atlas.hasAlphaChannel()

    columns = atlas.width() // 192
    for spec in manifest["actions"].values():
        start = spec["row"] * columns + spec.get("startColumn", 0)
        for offset in range(spec["frameCount"]):
            row, column = divmod(start + offset, columns)
            cell = atlas.copy(column * 192, row * 208, 192, 208)
            assert alpha_count(cell) > 0
