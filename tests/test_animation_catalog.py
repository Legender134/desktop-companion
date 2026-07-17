import pytest

from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.models import ActionId


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


def test_unknown_direction_is_rejected():
    with pytest.raises(ValueError, match="22.5-degree"):
        AnimationCatalog.load_default().look_frame(13.0)
