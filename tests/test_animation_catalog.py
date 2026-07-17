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
    assert tuple(catalog.look_degrees) == tuple(index * 22.5 for index in range(16))
    assert all(not catalog.look_frame(degrees).image.isNull() for degrees in catalog.look_degrees)


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
