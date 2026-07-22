import pytest
from PySide6.QtGui import QColor, QImage

from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.animation_player import AnimationTimeline
from shiyi_desktop_pet.models import ActionId, ActionRole, FrameAsset
from shiyi_desktop_pet.pet_registry import PetRegistry


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


def _dynamic_actions():
    return PetRegistry._parse_v3_actions(
        {
            "rest": {
                "label": "待机",
                "role": "idle",
                "row": 0,
                "frameCount": 3,
                "frameMs": 180,
                "loop": True,
            },
            "moveRight": {
                "label": "向右",
                "role": "move",
                "direction": "right",
                "row": 1,
                "frameCount": 5,
                "frameMs": 80,
                "loop": True,
                "autoplayWeight": 9,
            },
            "moveLeft": {
                "label": "向左",
                "role": "move",
                "direction": "left",
                "mirrorOf": "moveRight",
                "autoplayWeight": 9,
            },
            "hello": {
                "label": "问候",
                "role": "interaction",
                "row": 2,
                "frameCount": 4,
                "frameMs": 140,
                "autoplayWeight": 3,
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
            },
            "dashLeft": {
                "label": "遁光向左",
                "role": "burstMove",
                "direction": "left",
                "mirrorOf": "dashRight",
                "autoplayWeight": 1,
            },
        }
    )


def _valid_dynamic_atlas() -> QImage:
    atlas = QImage(8 * 192, 4 * 208, QImage.Format.Format_RGBA8888)
    atlas.fill(QColor(0, 0, 0, 0))
    for row, used in enumerate((3, 5, 4, 8)):
        for column in range(used):
            atlas.setPixelColor(
                column * 192 + 5, row * 208 + 5, QColor(255, 255, 255, 255)
            )
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


def test_catalog_builds_precise_action_help_and_current_digit_mapping():
    catalog = AnimationCatalog.load_pet("nangongwan")
    details = catalog.action_menu_details()

    burst = details["burstRight"]
    assert "10 帧" in burst
    assert "90–160 毫秒" in burst
    assert "总时长约 1.2 秒" in burst
    assert "第 4–8 帧" in burst
    assert "50%" in burst
    assert "至少 280 像素" in burst
    assert "1/20" in burst
    assert "45 秒" in burst

    spell = details["reincarnationLight"]
    assert "180 秒" in spell
    assert "spell" in spell
    assert "慢速时长乘 1.25" in spell

    shortcuts = dict(catalog.digit_shortcut_labels())
    assert shortcuts[1] == "静立凝神"
    assert shortcuts[2] == "御风向右"
    assert shortcuts[4] == "遗帕相赠"
    assert shortcuts[0] == "按权重随机"


def test_nangongwan_exposes_persistent_rooftop_state_and_standing_cake_action():
    catalog = AnimationCatalog.load_pet("nangongwan")
    menu = dict(catalog.action_menu_items())
    autoplay = dict(catalog.autoplay_actions())

    assert menu["月下屋檐"] == "moonlitChestnut"
    assert menu["栗糕轻尝"] == "tasteCake"
    assert autoplay["moonlitChestnut"] == 5
    assert autoplay["tasteCake"] == 2
    assert "moonlitChestnut" not in catalog.showcase_actions()
    assert "tasteCake" in catalog.showcase_actions()
    assert len(catalog.frames("tasteCake")) == 10
    assert autoplay["moonlitChestnut"] / sum(autoplay.values()) == pytest.approx(
        5 / 103
    )
    state = catalog.state_for_enter_action("moonlitChestnut")
    assert state.key == "moonlitRooftop"
    assert state.label == "月下屋檐"
    assert state.exit_action == "rooftopExit"
    assert [(choice.action_id, choice.weight) for choice in state.resident_actions] == [
        ("rooftopIdle", 25),
        ("rooftopMoonGaze", 18),
        ("rooftopChestnut", 20),
        ("rooftopRest", 10),
        ("rooftopBreeze", 17),
        ("rooftopGlance", 10),
    ]


def test_moonlit_rooftop_clips_share_exact_resident_boundaries():
    catalog = AnimationCatalog.load_pet("nangongwan")
    action = "moonlitChestnut"
    spec = catalog.spec(action)
    frames = catalog.frames(action)

    assert [(frame.row, frame.column) for frame in frames] == [
        divmod(23 * 16 + offset, 16) for offset in range(18)
    ]
    assert spec.cycle_ms == 2080
    assert spec.loops == 1

    boundary = frames[-1].image.constBits().tobytes()
    for resident_action in (
        "rooftopIdle",
        "rooftopMoonGaze",
        "rooftopChestnut",
        "rooftopRest",
        "rooftopBreeze",
        "rooftopGlance",
    ):
        resident = catalog.frames(resident_action)
        assert resident[0].image.constBits().tobytes() == boundary
        assert resident[-1].image.constBits().tobytes() == boundary
    assert catalog.frames("rooftopExit")[0].image.constBits().tobytes() == boundary

    timeline = AnimationTimeline()
    timeline.start(action, 0)
    assert timeline.advance(2079, spec).frame_index == 17
    assert not timeline.advance(2079, spec).finished
    assert timeline.advance(2080, spec).frame_index == 17
    assert timeline.advance(2080, spec).finished


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
    with pytest.raises(ValueError, match="supported gaze step"):
        AnimationCatalog.load_default().look_frame(13.0)


def test_nearest_gaze_accepts_continuous_angles_and_wraps_at_zero():
    catalog = AnimationCatalog.load_default()

    exact = catalog.nearest_look_frame(22.5)
    below_boundary = catalog.nearest_look_frame(11.2)
    above_boundary = catalog.nearest_look_frame(11.3)
    wrapped = catalog.nearest_look_frame(358.7)

    assert exact is catalog.look_frame(22.5)
    assert below_boundary is catalog.look_frame(0.0)
    assert above_boundary is catalog.look_frame(22.5)
    assert wrapped is catalog.look_frame(0.0)

    with pytest.raises(ValueError, match="between 0 and 360"):
        catalog.nearest_look_frame(360.0)


def test_sixty_four_direction_gaze_uses_fine_runtime_steps_and_compact_manual_menu():
    catalog = AnimationCatalog.load_pet("nangongwan")

    assert len(catalog.look_degrees) == 64
    assert catalog.look_degrees[:3] == (0.0, 5.625, 11.25)
    assert len(catalog.manual_look_degrees) == 16
    assert catalog.manual_look_degrees[:3] == (0.0, 22.5, 45.0)
    assert catalog.nearest_look_frame(2.8) is catalog.look_frame(0.0)
    assert catalog.nearest_look_frame(2.9) is catalog.look_frame(5.625)
    assert catalog.nearest_look_frame(357.5) is catalog.look_frame(0.0)


def test_v3_catalog_supports_dynamic_frame_counts_roles_and_mirrored_actions():
    catalog = AnimationCatalog(
        _valid_dynamic_atlas(),
        actions=_dynamic_actions(),
        sprite_version=3,
    )

    assert catalog.idle_action == "rest"
    assert len(catalog.frames("rest")) == 3
    assert len(catalog.frames("moveRight")) == 5
    assert len(catalog.frames("dashRight")) == 8
    assert catalog.spec("moveRight").frame_ms == 80
    assert catalog.definition("dashRight").role is ActionRole.BURST_MOVE
    assert [item.action_id for item in catalog.movement_actions(1)] == [
        "moveRight",
        "dashRight",
    ]
    assert catalog.interaction_actions() == ("hello",)
    assert not catalog.supports_gaze
    assert catalog.look_degrees == ()
    assert catalog.frames("moveRight")[0].image.pixelColor(5, 5).alpha() == 255
    assert catalog.frames("moveLeft")[0].image.pixelColor(186, 5).alpha() == 255
