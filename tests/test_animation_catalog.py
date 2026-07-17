import pytest
from PySide6.QtGui import QColor, QImage

from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.models import ActionId, FrameAsset


USED_COUNTS = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)


def _valid_synthetic_atlas() -> QImage:
    atlas = QImage(1536, 2288, QImage.Format.Format_RGBA8888)
    atlas.fill(QColor(0, 0, 0, 0))
    for row, used in enumerate(USED_COUNTS):
        for column in range(used):
            atlas.setPixelColor(column * 192, row * 208, QColor(255, 255, 255, 255))
    return atlas


def _atlas_with_empty_used_cell() -> QImage:
    atlas = _valid_synthetic_atlas()
    atlas.setPixelColor(0, 0, QColor(0, 0, 0, 0))
    return atlas


def _atlas_with_non_empty_unused_cell() -> QImage:
    atlas = _valid_synthetic_atlas()
    atlas.setPixelColor(7 * 192, 0, QColor(255, 255, 255, 255))
    return atlas


def test_catalog_exposes_all_actions_and_look_directions():
    catalog = AnimationCatalog.load_default()
    expected = {
        ActionId.IDLE: 7,
        ActionId.RUN_RIGHT: 8,
        ActionId.RUN_LEFT: 8,
        ActionId.WAVE: 4,
        ActionId.JUMP: 5,
        ActionId.BELLY_FLOP: 8,
        ActionId.EXPECT: 6,
        ActionId.PATROL: 6,
        ActionId.CURIOUS: 6,
    }
    assert {action: len(catalog.frames(action)) for action in expected} == expected


def test_catalog_exposes_pet_specific_menu_names_and_safe_autoplay_pool():
    shiyi = AnimationCatalog.load_pet("shiyi")
    ziling = AnimationCatalog.load_pet("ziling")

    assert dict(shiyi.action_menu_items())["抬爪招呼"] is ActionId.WAVE
    assert dict(ziling.action_menu_items())["挥手问候"] is ActionId.WAVE
    assert "撒娇翻肚" not in dict(ziling.action_menu_items())
    autoplay = dict(ziling.autoplay_actions())
    assert autoplay[ActionId.WAVE] == 3
    assert ActionId.IDLE not in autoplay
    assert ActionId.RUN_RIGHT not in autoplay
    assert ziling.showcase_actions() == (
        ActionId.WAVE,
        ActionId.JUMP,
        ActionId.BELLY_FLOP,
        ActionId.EXPECT,
        ActionId.PATROL,
        ActionId.CURIOUS,
    )
    assert tuple(shiyi.look_degrees) == tuple(index * 22.5 for index in range(16))
    assert all(not shiyi.look_frame(degrees).image.isNull() for degrees in shiyi.look_degrees)


def test_catalog_loads_each_bundled_pet_and_rejects_unknown_id():
    shiyi = AnimationCatalog.load_pet("shiyi")
    ziling = AnimationCatalog.load_pet("ziling")

    assert shiyi.pet_id == "shiyi"
    assert shiyi.display_name == "十一"
    assert ziling.pet_id == "ziling"
    assert ziling.display_name == "紫灵"
    assert shiyi.frames(ActionId.IDLE)[0].image != ziling.frames(ActionId.IDLE)[0].image

    with pytest.raises(ValueError, match="unknown pet"):
        AnimationCatalog.load_pet("missing")


def test_catalog_exposes_configured_visible_icon_frame():
    catalog = AnimationCatalog(_valid_synthetic_atlas(), icon_frame=(3, 1))

    icon_image = catalog.icon_image()

    assert icon_image == catalog.frames(ActionId.WAVE)[1].image
    assert catalog.icon_frame == (3, 1)


@pytest.mark.parametrize("icon_frame", [(-1, 0), (11, 0), (0, 8), (0, 7)])
def test_catalog_rejects_invalid_or_empty_icon_frame(icon_frame):
    with pytest.raises(ValueError, match="iconFrame"):
        AnimationCatalog(_valid_synthetic_atlas(), icon_frame=icon_frame)


def test_alpha_hit_test_uses_scaled_visible_pixel():
    catalog = AnimationCatalog.load_default()
    frame = catalog.frames(ActionId.IDLE)[0]
    assert catalog.hit_test(frame, 96, 150, 1.0)
    assert not catalog.hit_test(frame, 0, 0, 1.0)
    assert catalog.hit_test(frame, 192, 300, 2.0)


def test_alpha_hit_test_rejects_negative_fractional_window_coordinates():
    image = QImage(192, 208, QImage.Format.Format_RGBA8888)
    image.fill(QColor(0, 0, 0, 0))
    image.setPixelColor(0, 0, QColor(255, 255, 255, 255))
    frame = FrameAsset(image, 0, 0)
    catalog = AnimationCatalog.__new__(AnimationCatalog)

    assert not catalog.hit_test(frame, -0.1, 0, 1.0)
    assert not catalog.hit_test(frame, 0, -0.1, 1.0)


@pytest.mark.parametrize(
    ("atlas_factory", "message"),
    [
        (QImage, "could not be decoded"),
        (lambda: QImage(1535, 2288, QImage.Format.Format_RGBA8888), "1536x2288"),
        (lambda: QImage(1536, 2288, QImage.Format.Format_RGB888), "must have alpha"),
        (_atlas_with_empty_used_cell, "row 0 column 0"),
        (_atlas_with_non_empty_unused_cell, "row 0 column 7"),
    ],
)
def test_constructor_rejects_invalid_synthetic_atlases(atlas_factory, message):
    with pytest.raises(ValueError, match=message):
        AnimationCatalog(atlas_factory())


def test_alpha_hit_test_rejects_invalid_scale_and_upper_bounds():
    image = QImage(192, 208, QImage.Format.Format_RGBA8888)
    image.fill(QColor(255, 255, 255, 255))
    frame = FrameAsset(image, 0, 0)
    catalog = AnimationCatalog.__new__(AnimationCatalog)

    assert not catalog.hit_test(frame, 0, 0, 0)
    assert not catalog.hit_test(frame, 0, 0, -1)
    assert not catalog.hit_test(frame, 192, 0, 1.0)
    assert not catalog.hit_test(frame, 0, 208, 1.0)


def test_unknown_direction_is_rejected():
    with pytest.raises(ValueError, match="22.5-degree"):
        AnimationCatalog.load_default().look_frame(13.0)
