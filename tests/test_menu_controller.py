from dataclasses import replace

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon

from shiyi_desktop_pet.menu_controller import MenuCommand, MenuController
from shiyi_desktop_pet.models import ActionId
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


def test_menu_contains_every_action_direction_and_toggle():
    menu_controller = MenuController(
        settings_supplier=AppSettings,
        startup_supplier=lambda: True,
        dispatch=lambda command: None,
    )
    labels = menu_controller.flattened_labels()
    for label in (
        "休息",
        "向右奔跑",
        "向左奔跑",
        "招手",
        "跳跃",
        "撒娇翻肚",
        "期待",
        "原地巡视",
        "好奇观察",
        "随机动作",
    ):
        assert label in labels
    assert sum(label.startswith("观察 ") for label in labels) == 16
    for label in ("自动闲逛", "看向鼠标", "悬停数字快捷键", "始终置顶", "开机启动"):
        assert label in labels
    for label in (
        "75%",
        "100%",
        "125%",
        "150%",
        "慢速",
        "正常",
        "快速",
        "回到屏幕中央",
        "关于十一",
        "退出",
    ):
        assert label in labels


def test_menu_dispatches_typed_values_from_one_command_model(qtbot):
    dispatched = []
    controller = MenuController(AppSettings, lambda: False, dispatched.append)
    menu = controller.create_menu()

    _action(menu, "跳跃").trigger()
    _action(menu, "观察 067.5°").trigger()
    _action(menu, "125%").trigger()
    _action(menu, "自动闲逛").trigger()

    assert dispatched == [
        MenuCommand("action", ActionId.JUMP),
        MenuCommand("look", 67.5),
        MenuCommand("scale", 125),
        MenuCommand("toggle", True, "wander_enabled"),
    ]


def test_checked_state_refreshes_each_time_menu_opens(qtbot):
    state = {"settings": AppSettings(), "startup": False}
    controller = MenuController(
        lambda: state["settings"], lambda: state["startup"], lambda command: None
    )
    menu = controller.create_menu()

    menu.aboutToShow.emit()
    assert not _action(menu, "自动闲逛").isChecked()
    assert _action(menu, "看向鼠标").isChecked()
    assert _action(menu, "100%").isChecked()
    assert _action(_submenu(menu, "动画速度"), "正常").isChecked()
    assert _action(_submenu(menu, "移动速度"), "正常").isChecked()
    assert not _action(menu, "开机启动").isChecked()

    state["settings"] = replace(
        state["settings"],
        wander_enabled=True,
        gaze_enabled=False,
        scale_percent=150,
        animation_speed="fast",
        movement_speed="slow",
    )
    state["startup"] = True
    menu.aboutToShow.emit()
    assert _action(menu, "自动闲逛").isChecked()
    assert not _action(menu, "看向鼠标").isChecked()
    assert _action(menu, "150%").isChecked()
    assert _action(_submenu(menu, "动画速度"), "快速").isChecked()
    assert _action(_submenu(menu, "移动速度"), "慢速").isChecked()
    assert _action(menu, "开机启动").isChecked()


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
    tray = TrayController(pet, menu_controller, QIcon())

    _action(tray.menu, "回到屏幕中央").trigger()
    tray.tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)

    assert dispatched == [MenuCommand("center")]
    assert calls == ["show", "raise", "activate"]
    assert tray.tray_icon.contextMenu() is tray.menu
    tray.hide()
