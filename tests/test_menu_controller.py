from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QHelpEvent, QIcon, QMouseEvent
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QToolTip

from shiyi_desktop_pet.menu_controller import MenuCommand, MenuController
from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.models import (
    ActionId,
    PetSequenceDefinition,
    PetSequenceStep,
    PetStateActionChoice,
    PetTransformationDefinition,
)
from shiyi_desktop_pet.settings import AppSettings
from shiyi_desktop_pet.tray_controller import TrayController


def _action(menu, label):
    for candidate in menu.actions():
        if candidate.text() == label:
            return candidate
        if candidate.menu() is not None:
            found = _action(candidate.menu(), label)
            if found is not None:
                return found
    return None


def _submenu(menu, label):
    action = next(candidate for candidate in menu.actions() if candidate.text() == label)
    return action.menu()


def _leaf_items(items):
    for item in items:
        if item.children:
            yield from _leaf_items(item.children)
        else:
            yield item


def _rendered_action(menu, label):
    for candidate in menu.actions():
        if candidate.property("_shiyi_label") == label:
            return candidate
        if candidate.menu() is not None:
            found = _rendered_action(candidate.menu(), label)
            if found is not None:
                return found
    return None


def _rendered_actions(menu):
    for action in menu.actions():
        yield action
        if action.menu() is not None:
            yield from _rendered_actions(action.menu())


def test_menu_contains_every_action_direction_and_toggle():
    menu_controller = MenuController(
        settings_supplier=AppSettings,
        startup_supplier=lambda: True,
        dispatch=lambda command: None,
        pet_choices_supplier=lambda: (
            ("shiyi", "十一"),
            ("ziling", "紫灵"),
            ("new_pet", "新宠物"),
        ),
        action_items_supplier=AnimationCatalog.load_default().action_menu_items,
    )
    labels = menu_controller.flattened_labels()
    for label in (
        "休息",
        "向右奔跑",
        "向左奔跑",
        "抬爪招呼",
        "开心扑跳",
        "撒娇翻肚",
        "乖乖等候",
        "四处巡视",
        "好奇观察",
        "随机动作",
        "动作展示",
    ):
        assert label in labels
    assert sum(label.startswith("观察 ") for label in labels) == 16
    for label in (
        "自动闲逛",
        "看向鼠标",
        "注视方式",
        "鼠标活动时（推荐）",
        "始终看向鼠标",
        "自主小动作",
        "悬停数字快捷键",
        "始终置顶",
        "开机启动",
        "显示详情",
    ):
        assert label in labels
    for label in (
        "切换宠物",
        "十一",
        "紫灵",
        "新宠物",
        "重新扫描宠物",
        "打开宠物目录",
        "75%",
        "100%",
        "125%",
        "150%",
        "慢速",
        "正常",
        "快速",
        "回到屏幕中央",
        "关于桌面灵伴",
        "退出",
    ):
        assert label in labels


def test_menu_dispatches_typed_values_from_one_command_model(qtbot):
    dispatched = []
    controller = MenuController(
        AppSettings,
        lambda: False,
        dispatched.append,
        pet_choices_supplier=lambda: (
            ("shiyi", "十一"),
            ("ziling", "紫灵"),
            ("new_pet", "新宠物"),
        ),
        action_items_supplier=AnimationCatalog.load_default().action_menu_items,
    )
    menu = controller.create_menu()

    _action(menu, "开心扑跳").trigger()
    _action(menu, "动作展示").trigger()
    _action(menu, "观察 067.5°").trigger()
    _action(menu, "125%").trigger()
    _action(menu, "新宠物").trigger()
    _action(menu, "重新扫描宠物").trigger()
    _action(menu, "打开宠物目录").trigger()
    _action(menu, "自动闲逛").trigger()
    _action(menu, "始终看向鼠标").trigger()

    assert dispatched == [
        MenuCommand("action", ActionId.JUMP),
        MenuCommand("showcase"),
        MenuCommand("look", 67.5),
        MenuCommand("scale", 125),
        MenuCommand("pet", "new_pet"),
        MenuCommand("refresh_pets"),
        MenuCommand("open_pets_directory"),
        MenuCommand("toggle", True, "wander_enabled"),
        MenuCommand("gaze_mode", "always"),
    ]


def test_checked_state_refreshes_each_time_menu_opens(qtbot):
    state = {"settings": AppSettings(), "startup": False}
    controller = MenuController(
        lambda: state["settings"],
        lambda: state["startup"],
        lambda command: None,
        pet_choices_supplier=lambda: (("shiyi", "十一"), ("ziling", "紫灵")),
    )
    menu = controller.create_menu()

    menu.aboutToShow.emit()
    assert not _action(menu, "自动闲逛").isChecked()
    assert _action(menu, "看向鼠标").isChecked()
    assert _action(_submenu(menu, "注视方式"), "鼠标活动时（推荐）").isChecked()
    assert _action(menu, "自主小动作").isChecked()
    assert _action(_submenu(menu, "闲逛强度"), "标准").isChecked()
    assert _action(menu, "100%").isChecked()
    assert _action(_submenu(menu, "动画速度"), "正常").isChecked()
    assert _action(_submenu(menu, "移动速度"), "正常").isChecked()
    assert not _action(menu, "开机启动").isChecked()

    state["settings"] = replace(
        state["settings"],
        wander_enabled=True,
        gaze_enabled=False,
        gaze_mode="always",
        scale_percent=150,
        animation_speed="fast",
        movement_speed="slow",
        wander_intensity="active",
        pet_id="ziling",
    )
    state["startup"] = True
    menu.aboutToShow.emit()
    assert _action(menu, "自动闲逛").isChecked()
    assert not _action(menu, "看向鼠标").isChecked()
    assert _action(_submenu(menu, "注视方式"), "始终看向鼠标").isChecked()
    assert _action(menu, "150%").isChecked()
    assert _action(_submenu(menu, "动画速度"), "快速").isChecked()
    assert _action(_submenu(menu, "移动速度"), "慢速").isChecked()
    assert _action(_submenu(menu, "闲逛强度"), "活跃").isChecked()
    assert _action(menu, "开机启动").isChecked()
    assert _action(_submenu(menu, "切换宠物"), "紫灵").isChecked()


def test_details_mode_marks_every_item_and_explains_only_question_area(
    qtbot, monkeypatch
):
    catalog = AnimationCatalog.load_pet("nangongwan")
    controller = MenuController(
        lambda: AppSettings(menu_details_enabled=True),
        lambda: False,
        lambda command: None,
        pet_choices_supplier=lambda: (("shiyi", "十一"), ("ziling", "紫灵")),
        action_items_supplier=catalog.action_menu_items,
        look_degrees_supplier=lambda: tuple(catalog.manual_look_degrees),
        action_details_supplier=catalog.action_menu_details,
        gaze_frame_count_supplier=lambda: len(catalog.look_degrees),
        shortcut_labels_supplier=catalog.digit_shortcut_labels,
    )
    menu = controller.create_menu()
    menu.aboutToShow.emit()

    actions = tuple(_rendered_actions(menu))
    assert actions
    assert all("?" not in action.text() for action in actions)
    assert all(action.toolTip() for action in actions)
    assert all(not item.toolTipsVisible() for item in (menu, *[a.menu() for a in actions if a.menu()]))
    def compact_tooltip(label):
        return _rendered_action(menu, label).toolTip().replace("\n", "")

    assert "WindowStaysOnTopHint" in compact_tooltip("始终置顶")
    assert "8–18" in compact_tooltip("安静")
    assert "64" in compact_tooltip("看向鼠标")
    assert "5.625°" in compact_tooltip("看向鼠标")
    assert "10" in compact_tooltip("遁光向右")
    assert "50%" in compact_tooltip("遁光向右")
    assert "45" in compact_tooltip("遁光向右")
    assert "1=静立凝神" in compact_tooltip("悬停数字快捷键")
    assert "菜单可见或允许自主触发" in compact_tooltip("动作展示")
    assert "休眠/彩蛋动作不会播放" in compact_tooltip("动作展示")
    assert _rendered_action(menu, "显示详情").isChecked()

    menu.ensurePolished()
    menu.resize(menu.sizeHint())
    action = _rendered_action(menu, "自动闲逛")
    geometry = menu.actionGeometry(action)
    circle = menu.detail_help_rect(action)
    assert circle.width() >= 16
    assert geometry.top() <= circle.center().y() <= geometry.bottom()
    assert circle.right() < menu.width()
    shown = []
    hidden = []
    monkeypatch.setattr(QToolTip, "showText", lambda *args: shown.append(args))
    monkeypatch.setattr(QToolTip, "hideText", lambda: hidden.append(True))
    monkeypatch.setattr(QToolTip, "isVisible", lambda: bool(shown) and not hidden)

    immediate_event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(circle.center()),
        QPointF(menu.mapToGlobal(circle.center())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(menu, immediate_event)
    assert shown

    shown.clear()
    hidden.clear()

    left_event = QHelpEvent(
        QEvent.Type.ToolTip,
        QPoint(geometry.left() + 8, geometry.center().y()),
        QPoint(10, 10),
    )
    QApplication.sendEvent(menu, left_event)
    assert not shown
    assert hidden

    question_event = QHelpEvent(
        QEvent.Type.ToolTip,
        circle.center(),
        QPoint(20, 20),
    )
    QApplication.sendEvent(menu, question_event)
    assert shown

    submenu_action = _rendered_action(menu, "闲逛强度")
    submenu_geometry = menu.actionGeometry(submenu_action)
    submenu_circle = menu.detail_help_rect(submenu_action)
    before_submenu = len(shown)
    submenu_question_event = QHelpEvent(
        QEvent.Type.ToolTip,
        submenu_circle.center(),
        QPoint(30, 30),
    )
    QApplication.sendEvent(menu, submenu_question_event)
    assert len(shown) == before_submenu + 1

    arrow_event = QHelpEvent(
        QEvent.Type.ToolTip,
        QPoint(submenu_geometry.right() - 4, submenu_geometry.center().y()),
        QPoint(40, 40),
    )
    QApplication.sendEvent(menu, arrow_event)
    assert len(shown) == before_submenu + 1


def test_details_mode_can_be_disabled_without_leaving_question_marks(qtbot):
    state = {"settings": AppSettings(menu_details_enabled=True)}
    controller = MenuController(
        lambda: state["settings"],
        lambda: False,
        lambda command: None,
        pet_choices_supplier=lambda: (("shiyi", "十一"),),
    )
    menu = controller.create_menu()
    menu.aboutToShow.emit()
    first_filter = menu._shiyi_detail_help_filter
    assert first_filter is not None

    state["settings"] = replace(state["settings"], menu_details_enabled=False)
    menu.aboutToShow.emit()

    assert getattr(menu, "_shiyi_detail_help_filter", None) is None
    assert menu._detail_help_enabled is False
    assert all("?" not in action.text() for action in _rendered_actions(menu))


def test_every_declarative_menu_item_has_a_detail_description():
    controller = MenuController(
        AppSettings,
        lambda: False,
        lambda command: None,
        pet_choices_supplier=lambda: (("shiyi", "十一"),),
    )

    def all_items(items):
        for item in items:
            yield item
            yield from all_items(item.children)

    assert all(item.description.strip() for item in all_items(controller.items))


def test_pet_choices_are_rebuilt_when_menu_opens(qtbot):
    choices = [[("shiyi", "十一"), ("ziling", "紫灵")]]
    controller = MenuController(
        AppSettings,
        lambda: False,
        lambda command: None,
        pet_choices_supplier=lambda: tuple(choices[0]),
    )
    menu = controller.create_menu()
    assert _action(menu, "新宠物") is None

    choices[0].append(("new_pet", "新宠物"))
    menu.aboutToShow.emit()

    assert _action(_submenu(menu, "切换宠物"), "新宠物") is not None


def test_action_names_are_rebuilt_from_the_current_pet(qtbot):
    current = [AnimationCatalog.load_default()]
    controller = MenuController(
        AppSettings,
        lambda: False,
        lambda command: None,
        action_items_supplier=lambda: current[0].action_menu_items(),
    )
    menu = controller.create_menu()
    assert _action(menu, "抬爪招呼") is not None
    assert _action(menu, "挥手问候") is None

    current[0] = AnimationCatalog.load_pet("ziling")
    menu.aboutToShow.emit()

    assert _action(menu, "抬爪招呼") is None
    assert _action(menu, "挥手问候") is not None


def test_v4_dynamic_forms_and_sequences_use_definition_order_visibility_and_kind(qtbot):
    transformations = [
        PetTransformationDefinition(
            "shared",
            "白狐形态",
            "human",
            "whiteFox",
            "foxEnter",
            (PetStateActionChoice("foxIdle", 1),),
            "foxExit",
            25_000,
            60_000,
            True,
        ),
        PetTransformationDefinition(
            "hiddenTransform",
            "隐藏变身",
            "human",
            "hidden",
            "hiddenEnter",
            (PetStateActionChoice("hiddenIdle", 1),),
            "hiddenExit",
            1_000,
            2_000,
            False,
        ),
        PetTransformationDefinition(
            "rabbit",
            "灵兔形态",
            "human",
            "rabbit",
            "rabbitEnter",
            (PetStateActionChoice("rabbitIdle", 1),),
            "rabbitExit",
            10_000,
            20_000,
            True,
        ),
    ]
    sequences = [
        PetSequenceDefinition(
            "shared",
            "月华术式",
            True,
            (PetSequenceStep("moonSpell", 2, 300, None, True),),
        ),
        PetSequenceDefinition(
            "hiddenSequence",
            "隐藏序列",
            False,
            (PetSequenceStep("hidden", 1, 0, None, True),),
        ),
    ]
    controller = MenuController(
        AppSettings,
        lambda: False,
        lambda command: None,
        transformation_items_supplier=lambda: tuple(transformations),
        sequence_items_supplier=lambda: tuple(sequences),
    )

    action_menu = next(item for item in controller.items if item.label == "动作")
    assert [item.label for item in action_menu.children[:2]] == ["变身", "月华术式"]
    transform_menu = action_menu.children[0]
    assert [item.label for item in transform_menu.children] == [
        "白狐形态",
        "灵兔形态",
        "恢复默认形态",
    ]
    assert [item.command for item in transform_menu.children] == [
        MenuCommand("transformation", "shared"),
        MenuCommand("transformation", "rabbit"),
        MenuCommand("restore_form"),
    ]
    assert action_menu.children[1].command == MenuCommand("sequence", "shared")
    assert "隐藏变身" not in controller.flattened_labels()
    assert "隐藏序列" not in controller.flattened_labels()
    assert "whiteFox" in transform_menu.children[0].description
    assert "moonSpell" in action_menu.children[1].description
    assert "银月" not in transform_menu.children[0].description

    transformations.clear()
    sequences.clear()
    menu = controller.create_menu()
    menu.aboutToShow.emit()
    assert _action(menu, "变身") is None
    assert _action(menu, "动作展示") is not None
    assert _action(menu, "特效质量") is None


def test_effects_quality_menu_dispatches_and_refreshes_radio_state(qtbot):
    state = {"settings": AppSettings(effects_quality="full")}
    dispatched = []
    transformation = PetTransformationDefinition(
        "fox",
        "白狐形态",
        "human",
        "fox",
        "foxEnter",
        (PetStateActionChoice("foxIdle", 1),),
        "foxExit",
        1_000,
        2_000,
        True,
    )
    controller = MenuController(
        lambda: state["settings"],
        lambda: False,
        dispatched.append,
        transformation_items_supplier=lambda: (transformation,),
    )
    menu = controller.create_menu()
    menu.aboutToShow.emit()

    assert _action(_submenu(menu, "特效质量"), "完整").isChecked()
    _action(_submenu(menu, "特效质量"), "简化").trigger()
    assert dispatched == [MenuCommand("effects_quality", "simplified")]

    state["settings"] = replace(state["settings"], effects_quality="simplified")
    menu.aboutToShow.emit()
    assert not _action(_submenu(menu, "特效质量"), "完整").isChecked()
    assert _action(_submenu(menu, "特效质量"), "简化").isChecked()


def test_dynamic_action_menu_accepts_variable_count_and_hides_unsupported_gaze(qtbot):
    controller = MenuController(
        AppSettings,
        lambda: False,
        lambda command: None,
        action_items_supplier=lambda: (
            ("安静陪伴", "rest"),
            ("向右移动", "moveRight"),
            ("向左移动", "moveLeft"),
            ("专属动作一", "specialOne"),
            ("专属动作二", "specialTwo"),
            ("遁光向右", "dashRight"),
        ),
        look_degrees_supplier=lambda: (),
    )
    menu = controller.create_menu()

    assert _action(menu, "专属动作一") is not None
    assert _action(menu, "专属动作二") is not None
    assert _action(menu, "遁光向右") is not None
    assert _action(menu, "观察方向") is None
    assert _action(menu, "看向鼠标") is None


def test_unavailable_tray_is_a_safe_disabled_object(monkeypatch, qtbot):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    menu_controller = MenuController(AppSettings, lambda: False, lambda command: None)
    pet = type(
        "PetStub",
        (),
        {"show": lambda self: None, "raise_": lambda self: None, "activateWindow": lambda self: None},
    )()

    tray = TrayController(pet, menu_controller, QIcon())

    assert not tray.available
    assert tray.tray_icon is None
    assert tray.show() is False
    tray.hide()
    tray.show_message("title", "body")
    assert tray.set_companion_icon(AnimationCatalog.load_default().icon_image(), "十一") is False


def test_available_tray_reuses_menu_and_double_click_recovers_pet(monkeypatch, qtbot):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    dispatched = []
    calls = []
    menu_controller = MenuController(AppSettings, lambda: False, dispatched.append)
    pet = type(
        "PetStub",
        (),
        {
            "show": lambda self: calls.append("show"),
            "raise_": lambda self: calls.append("raise"),
            "activateWindow": lambda self: calls.append("activate"),
        },
    )()
    tray = TrayController(pet, menu_controller)

    _action(tray.menu, "回到屏幕中央").trigger()
    tray.tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)

    assert dispatched == [MenuCommand("center")]
    assert calls == ["show", "raise", "activate"]
    assert tray.tray_icon.contextMenu() is tray.menu
    assert not tray.tray_icon.icon().isNull()
    assert tray.tray_icon.toolTip() == "桌面灵伴"
    original_key = tray.tray_icon.icon().cacheKey()
    assert tray.set_companion_icon(AnimationCatalog.load_pet("ziling").icon_image(), "紫灵")
    assert tray.tray_icon.icon().cacheKey() != original_key
    assert tray.tray_icon.toolTip() == "桌面灵伴 · 紫灵"
    tray.hide()


def test_supplier_failures_fall_back_report_and_do_not_escape_refresh(qtbot):
    reported = []

    def broken_settings():
        raise RuntimeError("private settings detail")

    def broken_startup():
        raise OSError("private registry detail")

    controller = MenuController(
        broken_settings,
        broken_startup,
        lambda command: None,
        error_reporter=lambda context, error_type: reported.append((context, error_type)),
    )
    menu = controller.create_menu()

    controller.refresh(menu)

    assert not _action(menu, "自动闲逛").isChecked()
    assert _action(menu, "看向鼠标").isChecked()
    assert _action(menu, "100%").isChecked()
    assert not _action(menu, "开机启动").isChecked()
    expected_reports = [
        ("settings supplier", "RuntimeError"),
        ("startup supplier", "OSError"),
    ]
    assert reported == expected_reports
    assert all("private" not in part for report in reported for part in report)

    reported.clear()
    menu.aboutToShow.emit()
    assert reported == expected_reports


def test_command_model_has_complete_exact_payload_table():
    controller = MenuController(
        AppSettings,
        lambda: False,
        lambda command: None,
        pet_choices_supplier=lambda: (
            ("shiyi", "十一"),
            ("ziling", "紫灵"),
            ("new_pet", "新宠物"),
        ),
    )
    commands = [item.command for item in _leaf_items(controller.items)]
    action_commands = [command for command in commands if command.kind == "action"]
    look_commands = [command for command in commands if command.kind == "look"]
    toggle_commands = [command for command in commands if command.kind == "toggle"]
    scale_commands = [command for command in commands if command.kind == "scale"]
    pet_commands = [command for command in commands if command.kind == "pet"]
    speed_commands = [
        command
        for command in commands
        if command.kind in {"animation_speed", "movement_speed"}
    ]
    terminal_commands = [
        command
        for command in commands
        if command.kind
        in {"refresh_pets", "open_pets_directory", "center", "about", "quit"}
    ]

    assert action_commands == [
        MenuCommand("action", ActionId.IDLE),
        MenuCommand("action", ActionId.RUN_RIGHT),
        MenuCommand("action", ActionId.RUN_LEFT),
        MenuCommand("action", ActionId.WAVE),
        MenuCommand("action", ActionId.JUMP),
        MenuCommand("action", ActionId.BELLY_FLOP),
        MenuCommand("action", ActionId.EXPECT),
        MenuCommand("action", ActionId.PATROL),
        MenuCommand("action", ActionId.CURIOUS),
        MenuCommand("action", ActionId.RANDOM),
    ]
    assert look_commands == [MenuCommand("look", index * 22.5) for index in range(16)]
    assert [command.target for command in toggle_commands] == [
        "wander_enabled",
        "gaze_enabled",
        "autonomous_actions_enabled",
        "hover_digits_enabled",
        "always_on_top",
        "startup_enabled",
        "menu_details_enabled",
    ]
    assert all(command.value is None for command in toggle_commands)
    assert scale_commands == [MenuCommand("scale", value) for value in (75, 100, 125, 150)]
    assert pet_commands == [
        MenuCommand("pet", "shiyi"),
        MenuCommand("pet", "ziling"),
        MenuCommand("pet", "new_pet"),
    ]
    wander_commands = [
        command for command in commands if command.kind == "wander_intensity"
    ]
    gaze_mode_commands = [
        command for command in commands if command.kind == "gaze_mode"
    ]
    assert speed_commands == [
        MenuCommand(kind, value)
        for kind in ("animation_speed", "movement_speed")
        for value in ("slow", "normal", "fast")
    ]
    assert wander_commands == [
        MenuCommand("wander_intensity", value)
        for value in ("quiet", "standard", "active")
    ]
    assert gaze_mode_commands == [
        MenuCommand("gaze_mode", "active"),
        MenuCommand("gaze_mode", "always"),
    ]
    assert terminal_commands == [
        MenuCommand("refresh_pets"),
        MenuCommand("open_pets_directory"),
        MenuCommand("center"),
        MenuCommand("about"),
        MenuCommand("quit"),
    ]
