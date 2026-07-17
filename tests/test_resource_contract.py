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


def test_packaged_resources_obey_multi_pet_v2_contract():
    expected = {
        "shiyi": {
            "id": "shiyi",
            "displayName": "十一",
            "description": "一只好奇亲人、略带呆萌气质的银黑经典虎斑猫。",
            "spriteVersionNumber": 2,
            "spritesheetPath": "spritesheet.webp",
        },
        "ziling": {
            "id": "ziling",
            "displayName": "紫灵",
            "description": "《凡人修仙传》动画中的成年紫灵，清冷温柔的精致Q版紫白仙裙人物宠物。",
            "spriteVersionNumber": 2,
            "spritesheetPath": "spritesheet.webp",
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
