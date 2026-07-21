from dataclasses import replace
from io import StringIO
import json
import logging
from pathlib import Path
from random import Random
import shutil
import sys

import pytest
from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QImage

from shiyi_desktop_pet.app import (
    DesktopPetApplication,
    HoverSnapshot,
    main,
    parse_args,
    resolve_digit_action,
    restore_window_position,
    run_self_test,
    _write_stdout,
)
from shiyi_desktop_pet.behavior import BehaviorMode
from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.geometry import Point, Rect, Size
from shiyi_desktop_pet.logging_setup import configure_logging, install_exception_hook
from shiyi_desktop_pet.menu_controller import MenuCommand
from shiyi_desktop_pet.models import ActionId
from shiyi_desktop_pet.pet_registry import PetRegistry
from shiyi_desktop_pet.pet_window import PetWindow
from shiyi_desktop_pet.resource_locator import resource_root
from shiyi_desktop_pet.settings import AppSettings
from shiyi_desktop_pet.wander import WanderTarget


class MemorySettingsStore:
    def __init__(self, settings=AppSettings()):
        self.loaded = settings
        self.saved = []

    def load(self):
        return self.loaded

    def save(self, settings):
        self.saved.append(settings)


class FakeHook(QObject):
    digit_pressed = Signal(int)
    hook_failed = Signal(str)

    def __init__(self, hover_hit_test, *, enabled=True, start_error=None):
        super().__init__()
        self.hover_hit_test = hover_hit_test
        self.enabled = enabled
        self.start_error = start_error
        self.started = False
        self.stopped = False
        self.last_error = None

    def start(self):
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def stop(self):
        self.stopped = True

    def set_enabled(self, enabled):
        self.enabled = enabled


class FakeTray:
    def __init__(self, window, menu_controller, available=True):
        self.window = window
        self.menu_controller = menu_controller
        self.available = available
        self.shown = False
        self.hidden = False
        self.messages = []
        self.companion_icons = []

    def show(self):
        self.shown = True
        return self.available

    def hide(self):
        self.hidden = True

    def show_message(self, title, message, milliseconds=10_000):
        self.messages.append((title, message, milliseconds))
        return self.available

    def set_companion_icon(self, image, display_name):
        self.companion_icons.append((image.copy(), display_name))
        return self.available


class SpyPetWindow(PetWindow):
    def __init__(self, catalog):
        super().__init__(catalog)
        self.show_without_activation = []
        self.raise_calls = 0
        self.activate_calls = 0

    def show(self):
        self.show_without_activation.append(
            self.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        )
        super().show()

    def raise_(self):
        self.raise_calls += 1
        super().raise_()

    def activateWindow(self):
        self.activate_calls += 1
        super().activateWindow()


class FakeStartup:
    def __init__(self):
        self.enabled = False

    def is_enabled(self):
        return self.enabled

    def set_enabled(self, enabled):
        self.enabled = enabled


class GuardSpy:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.commands = []
        self.closed = False
        self.close_calls = 0
        self._signals = _SignalBox()
        self.command_received = self._signals.command_received

    def acquire(self, command="activate"):
        self.commands.append(command)
        return self.acquired

    def close(self):
        self.close_calls += 1
        self.closed = True


class _SignalBox(QObject):
    command_received = Signal(str)


def _catalog():
    return AnimationCatalog.load_default()


def _dynamic_catalog():
    actions = PetRegistry._parse_v3_actions(
        {
            "rest": {
                "label": "待机", "role": "idle", "row": 0,
                "frameCount": 3, "frameMs": 180, "loop": True,
            },
            "moveRight": {
                "label": "向右", "role": "move", "direction": "right",
                "row": 1, "frameCount": 5, "frameMs": 80, "loop": True,
                "autoplayWeight": 19,
            },
            "moveLeft": {
                "label": "向左", "role": "move", "direction": "left",
                "mirrorOf": "moveRight", "autoplayWeight": 19,
            },
            "hello": {
                "label": "问候", "role": "interaction", "row": 2,
                "frameCount": 4, "frameMs": 140, "autoplayWeight": 3,
            },
            "dashRight": {
                "label": "遁光向右", "role": "burstMove", "direction": "right",
                "row": 3, "frameCount": 8, "frameMs": 90,
                "travelStartFrame": 3, "travelEndFrame": 6,
                "autoplayWeight": 1, "cooldownMs": 45000,
                "minDistance": 280, "travelDistanceRatio": 0.5,
                "maxVerticalRatio": 0.1,
            },
            "dashLeft": {
                "label": "遁光向左", "role": "burstMove", "direction": "left",
                "mirrorOf": "dashRight", "autoplayWeight": 1,
                "cooldownMs": 45000, "minDistance": 280,
            },
        }
    )
    atlas = QImage(8 * 192, 4 * 208, QImage.Format.Format_RGBA8888)
    atlas.fill(QColor(0, 0, 0, 0))
    for row, used in enumerate((3, 5, 4, 8)):
        for column in range(used):
            atlas.setPixelColor(
                column * 192 + 5, row * 208 + 5, QColor(255, 255, 255, 255)
            )
    return AnimationCatalog(atlas, actions=actions, sprite_version=3)


def _grouped_catalog():
    actions = PetRegistry._parse_v3_actions(
        {
            "rest": {
                "label": "待机", "role": "idle", "row": 0,
                "frameCount": 3, "frameMs": 180, "loop": True,
            },
            "moveRight": {
                "label": "向右", "role": "move", "direction": "right",
                "row": 1, "frameCount": 5, "frameMs": 80, "loop": True,
                "autoplayWeight": 19,
            },
            "moveLeft": {
                "label": "向左", "role": "move", "direction": "left",
                "mirrorOf": "moveRight", "autoplayWeight": 19,
            },
            "daily": {
                "label": "日常", "role": "interaction", "row": 2,
                "frameCount": 4, "frameMs": 140, "autoplayWeight": 1,
            },
            "spellA": {
                "label": "术法甲", "role": "interaction", "row": 3,
                "frameCount": 4, "frameMs": 140, "autoplayWeight": 100,
                "autoplayGroup": "spell",
            },
            "spellB": {
                "label": "术法乙", "role": "interaction", "row": 4,
                "frameCount": 4, "frameMs": 140, "autoplayWeight": 100,
                "autoplayGroup": "spell",
            },
        }
    )
    atlas = QImage(5 * 192, 5 * 208, QImage.Format.Format_RGBA8888)
    atlas.fill(QColor(0, 0, 0, 0))
    for row, used in enumerate((3, 5, 4, 4, 4)):
        for column in range(used):
            atlas.setPixelColor(
                column * 192 + 5, row * 208 + 5, QColor(255, 255, 255, 255)
            )
    return AnimationCatalog(atlas, actions=actions, sprite_version=3)


def _state_catalog():
    actions = PetRegistry._parse_v3_actions(
        {
            "rest": {
                "label": "待机", "role": "idle", "row": 0,
                "frameCount": 3, "frameMs": 180, "loop": True,
            },
            "moveRight": {
                "label": "向右", "role": "move", "direction": "right",
                "row": 1, "frameCount": 5, "frameMs": 80, "loop": True,
                "autoplayWeight": 19,
            },
            "moveLeft": {
                "label": "向左", "role": "move", "direction": "left",
                "mirrorOf": "moveRight", "autoplayWeight": 19,
            },
            "hello": {
                "label": "问候", "role": "interaction", "row": 2,
                "frameCount": 3, "frameMs": 100, "autoplayWeight": 10,
            },
            "rooftopEnter": {
                "label": "月下屋檐", "role": "interaction", "row": 3,
                "frameCount": 3, "frameMs": 100, "autoplayWeight": 5,
                "cooldownMs": 90000,
            },
            "rooftopIdle": {
                "label": "屋檐静坐", "role": "interaction", "row": 4,
                "frameCount": 3, "frameMs": 100, "showInMenu": False,
            },
            "rooftopMoon": {
                "label": "仰望月色", "role": "interaction", "row": 5,
                "frameCount": 3, "frameMs": 100, "showInMenu": False,
            },
            "rooftopExit": {
                "label": "离开屋檐", "role": "interaction", "row": 6,
                "frameCount": 3, "frameMs": 100, "showInMenu": False,
            },
        }
    )
    states = PetRegistry._parse_v3_states(
        {
            "moonlitRooftop": {
                "label": "月下屋檐",
                "enterAction": "rooftopEnter",
                "residentActions": [
                    {"action": "rooftopIdle", "weight": 70},
                    {"action": "rooftopMoon", "weight": 30},
                ],
                "exitAction": "rooftopExit",
                "minDurationMs": 30000,
                "rampDurationMs": 30000,
                "maxDurationMs": 90000,
                "exitChanceAfterMin": 5,
                "exitChanceAfterRamp": 25,
            }
        },
        actions,
    )
    atlas = QImage(8 * 192, 7 * 208, QImage.Format.Format_RGBA8888)
    atlas.fill(QColor(0, 0, 0, 0))
    for row, used in enumerate((3, 5, 3, 3, 3, 3, 3)):
        for column in range(used):
            atlas.setPixelColor(
                column * 192 + 5, row * 208 + 5, QColor(255, 255, 255, 255)
            )
    return AnimationCatalog(
        atlas, actions=actions, states=states, sprite_version=3
    )


def _install_test_pet(user_root: Path, pet_id: str, display_name: str) -> Path:
    directory = user_root / pet_id
    directory.mkdir(parents=True)
    manifest = json.loads(
        (resource_root() / "pets" / "shiyi" / "pet.json").read_text(encoding="utf-8")
    )
    manifest.update({"id": pet_id, "displayName": display_name})
    (directory / "pet.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    shutil.copyfile(
        resource_root() / "pets" / "shiyi" / "spritesheet.webp",
        directory / "spritesheet.webp",
    )
    return directory


def _controller(
    qapp,
    *,
    settings=AppSettings(),
    hook_factory=None,
    tray_factory=None,
    window_factory=PetWindow,
    qa_window=False,
    pet_registry=None,
    open_pet_directory=None,
    catalog_factory=_catalog,
):
    store = MemorySettingsStore(settings)
    startup = FakeStartup()
    hooks = []
    trays = []
    pet_registry = pet_registry or PetRegistry(resource_root() / "pets", None)

    if hook_factory is None:
        def hook_factory(hit_test, *, enabled=True):
            hook = FakeHook(hit_test, enabled=enabled)
            hooks.append(hook)
            return hook

    if tray_factory is None:
        def tray_factory(window, menu):
            tray = FakeTray(window, menu)
            trays.append(tray)
            return tray

    controller = DesktopPetApplication(
        qapp,
        settings_store=store,
        startup_manager=startup,
        catalog_factory=catalog_factory,
        hook_factory=hook_factory,
        tray_factory=tray_factory,
        random=Random(0),
        window_factory=window_factory,
        qa_window=qa_window,
        pet_registry=pet_registry,
        open_pet_directory=open_pet_directory or (lambda path: True),
    )
    return controller, store, startup, hooks, trays


def test_digit_and_random_action_mapping():
    assert resolve_digit_action(4, Random(0)) is ActionId.WAVE
    assert resolve_digit_action(0, Random(0)) in {
        ActionId.WAVE,
        ActionId.JUMP,
        ActionId.BELLY_FLOP,
        ActionId.EXPECT,
        ActionId.PATROL,
        ActionId.CURIOUS,
    }
    with pytest.raises(ValueError):
        resolve_digit_action(10, Random(0))


def test_self_test_reports_resources_qt_and_webp():
    report = run_self_test()
    assert report["ok"] is True
    assert report["atlas"] == {"width": 1536, "height": 2288, "frames": 74}
    assert report["pets"] == ["nangongwan", "shiyi", "ziling"]
    assert report["webp_plugin"] is True
    assert report["qt"]


def test_first_launch_and_missing_screen_are_recoverable():
    screens = {"primary": Rect(0, 0, 1920, 1040)}
    selected, first = restore_window_position(
        AppSettings(), screens, "primary", Size(192, 208)
    )
    assert selected == "primary"
    assert first == Point(1696, 808)

    missing = replace(
        AppSettings(), screen_name="disconnected", relative_x=2.0, relative_y=-1.0
    )
    selected, restored = restore_window_position(
        missing, screens, "primary", Size(192, 208)
    )
    assert selected == "primary"
    assert 0 <= restored.x <= 1728 and 0 <= restored.y <= 832


def test_restore_uses_saved_monitor_center_ratios_and_negative_coordinates():
    screens = {
        "primary": Rect(0, 0, 1920, 1040),
        "left": Rect(-1280, -100, 1280, 984),
    }
    settings = replace(
        AppSettings(), screen_name="left", relative_x=0.25, relative_y=0.75
    )
    selected, restored = restore_window_position(
        settings, screens, "primary", Size(192, 208)
    )
    assert selected == "left"
    assert restored == Point(-1056, 534)


def test_restore_rejects_missing_screen_data():
    with pytest.raises(ValueError):
        restore_window_position(AppSettings(), {}, "primary", Size(192, 208))


def test_cli_modes_are_mutually_exclusive():
    assert parse_args(["--startup"]).startup
    assert parse_args(["--self-test"]).self_test
    assert parse_args(["--quit-existing"]).quit_existing
    with pytest.raises(SystemExit):
        parse_args(["--self-test", "--quit-existing"])


def test_internal_qa_window_cli_mode_is_hidden_and_exclusive(capsys):
    args = parse_args(["--qa-window"])

    assert args.qa_window is True
    assert not args.startup
    with pytest.raises(SystemExit):
        parse_args(["--qa-window", "--startup"])
    with pytest.raises(SystemExit):
        parse_args(["--help"])
    assert "--qa-window" not in capsys.readouterr().out


def test_qa_window_is_enumerable_without_changing_default_window_type(qapp):
    qa_controller, *_ = _controller(qapp, qa_window=True)
    default_controller, *_ = _controller(qapp)
    try:
        assert (
            qa_controller.window.windowFlags() & Qt.WindowType.WindowType_Mask
        ) == Qt.WindowType.Window
        assert qa_controller.window.windowTitle() == "DesktopCompanion QA"
        assert (
            default_controller.window.windowFlags() & Qt.WindowType.WindowType_Mask
        ) == Qt.WindowType.Tool
        assert default_controller.window.windowTitle() != "DesktopCompanion QA"
    finally:
        qa_controller.shutdown()
        default_controller.shutdown()


def test_hover_snapshot_is_immutable_and_alpha_aware():
    snapshot = HoverSnapshot(
        alpha=bytes([0, 255, 0, 0]),
        width=2,
        height=2,
        bytes_per_line=2,
        scale=2.0,
        window_x=10,
        window_y=20,
        visible=True,
        cursor_x=12,
        cursor_y=20,
    )
    assert snapshot.hit_test()
    assert not replace(snapshot, cursor_x=10).hit_test()
    assert not replace(snapshot, visible=False).hit_test()
    assert not replace(snapshot, scale=0).hit_test()
    assert not replace(snapshot, cursor_x=100).hit_test()
    with pytest.raises(Exception):
        snapshot.visible = False


def test_hook_start_failure_keeps_pet_running_and_disables_session_shortcut(qapp):
    hooks = []
    trays = []

    def hook_factory(hit_test, *, enabled=True):
        hook = FakeHook(
            hit_test, enabled=enabled, start_error=RuntimeError("installation failed")
        )
        hooks.append(hook)
        return hook

    def tray_factory(window, menu):
        tray = FakeTray(window, menu)
        trays.append(tray)
        return tray

    controller, store, _, _, _ = _controller(
        qapp, hook_factory=hook_factory, tray_factory=tray_factory
    )
    controller.start(startup=False)

    assert controller.window.isVisible()
    assert controller.settings.hover_digits_enabled is False
    assert hooks[0].enabled is False
    assert len(trays[0].messages) == 1
    controller.shutdown()
    assert hooks[0].stopped
    assert trays[0].hidden
    assert store.saved[-1].hover_digits_enabled is True


def test_startup_show_suppresses_activation_but_later_activation_is_explicit(qapp):
    startup, _, _, _, _ = _controller(qapp, window_factory=SpyPetWindow)
    try:
        startup.start(startup=True)

        assert startup.window.show_without_activation == [True]
        assert not startup.window.testAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating
        )
        assert startup.window.raise_calls == 0

        startup.activate()
        assert startup.window.show_without_activation[-1] is False
        assert startup.window.raise_calls == 1
        assert startup.window.activate_calls == 1
    finally:
        startup.shutdown()

    normal, _, _, _, _ = _controller(qapp, window_factory=SpyPetWindow)
    try:
        normal.start(startup=False)
        assert normal.window.show_without_activation == [False]
        assert normal.window.raise_calls == 1
    finally:
        normal.shutdown()


def test_runtime_hook_failure_uses_last_error_and_notifies_only_once(qapp):
    controller, _, _, hooks, trays = _controller(qapp)
    controller.start(startup=True)
    hooks[0].last_error = RuntimeError("sanitized runtime failure")
    hooks[0].hook_failed.emit("keyboard hook failed")
    hooks[0].hook_failed.emit("keyboard hook failed again")

    assert controller.settings.hover_digits_enabled is False
    assert len(trays[0].messages) == 1
    controller.shutdown()


def test_direction_zero_does_not_start_wander_running_action(qapp, monkeypatch):
    settings = replace(AppSettings(), wander_enabled=True)
    controller, _, _, _, _ = _controller(qapp, settings=settings)
    controller.start(startup=True)

    current = Point(controller.window.x(), controller.window.y())
    monkeypatch.setattr(
        controller.wander_planner,
        "choose_target",
        lambda *args, **kwargs: __import__("shiyi_desktop_pet.wander", fromlist=["WanderTarget"]).WanderTarget(
            current, 0
        ),
    )
    controller.begin_wander()

    assert controller.wander_target is None
    assert controller.current_action is ActionId.IDLE
    controller.shutdown()


def test_menu_dispatch_updates_runtime_settings_and_shutdown_saves(qapp):
    controller, store, startup, hooks, _ = _controller(qapp)
    controller.start(startup=True)
    controller.dispatch_menu(MenuCommand("toggle", True, "wander_enabled"))
    controller.dispatch_menu(MenuCommand("toggle", False, "gaze_enabled"))
    controller.dispatch_menu(MenuCommand("toggle", True, "menu_details_enabled"))
    controller.dispatch_menu(MenuCommand("toggle", True, "startup_enabled"))
    controller.dispatch_menu(MenuCommand("scale", 125))
    controller.dispatch_menu(MenuCommand("animation_speed", "fast"))
    controller.dispatch_menu(MenuCommand("movement_speed", "slow"))
    controller.dispatch_menu(MenuCommand("wander_intensity", "quiet"))
    controller.dispatch_menu(MenuCommand("action", ActionId.WAVE))

    assert controller.settings.wander_enabled
    assert not controller.settings.gaze_enabled
    assert controller.settings.menu_details_enabled
    assert startup.enabled
    assert controller.settings.scale_percent == 125
    assert controller.settings.wander_intensity == "quiet"
    assert controller.current_action is ActionId.WAVE
    assert hooks[0].started
    controller.shutdown()
    assert store.saved


def test_wander_intensity_controls_schedule_delay(qapp):
    settings = replace(
        AppSettings(),
        wander_enabled=True,
        wander_intensity="quiet",
    )
    controller, _, _, _, _ = _controller(qapp, settings=settings)
    controller.start(startup=True)
    controller.wander_timer.stop()

    controller._schedule_wander()
    assert 8_000 <= controller.wander_timer.interval() <= 18_000

    controller.dispatch_menu(MenuCommand("wander_intensity", "active"))
    assert controller.settings.wander_intensity == "active"
    assert 1_000 <= controller.wander_timer.interval() <= 3_000
    controller.shutdown()


def test_controller_advances_manual_run_wander_gaze_and_drag(qapp, monkeypatch):
    settings = replace(AppSettings(), wander_enabled=True)
    controller, _, _, _, _ = _controller(qapp, settings=settings)
    controller.start(startup=True)
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    controller.wander_timer.stop()

    starting_x = controller.window.x()
    controller.trigger_action(ActionId.RUN_RIGHT)
    controller.timeline.started_ms = 0
    controller._advance_manual(100)
    assert controller.window.x() >= starting_x
    controller._advance_manual(10_000)
    assert controller.behavior.mode is BehaviorMode.WANDER

    current = Point(float(controller.window.x()), float(controller.window.y()))
    target = Point(current.x + 40, current.y)
    monkeypatch.setattr(
        controller.wander_planner,
        "choose_target",
        lambda *args, **kwargs: WanderTarget(target, 1),
    )
    controller.begin_wander()
    assert controller.current_action is ActionId.RUN_RIGHT
    before = controller.window.x()
    controller._advance_wander(controller._now_ms() + 100, 0.1)
    assert controller.window.x() > before

    controller._wander_target = Point(
        float(controller.window.x()), float(controller.window.y())
    )
    controller._advance_wander(controller._now_ms() + 200, 0.1)
    assert controller.wander_target is None

    controller.behavior.set_wander_enabled(False)
    controller._gaze_tick()
    controller._render_base(controller._now_ms())

    controller._begin_drag()
    assert controller.behavior.mode is BehaviorMode.DRAGGING
    controller._animation_tick()
    controller._drag_to(QPoint(controller.window.x() + 5, controller.window.y() + 5))
    controller._finish_drag(QPoint(10_000, 10_000))
    assert controller.behavior.mode is not BehaviorMode.DRAGGING

    controller.window.move(10_000, 10_000)
    controller._recover_window_visibility()
    assert controller.window.x() < 10_000
    assert isinstance(controller.hover_snapshot.hit_test(), bool)
    controller.shutdown()
    controller.shutdown()


def test_screen_recovery_cancels_stale_negative_monitor_wander(qapp):
    settings = replace(AppSettings(), wander_enabled=True)
    controller, _, _, _, _ = _controller(qapp, settings=settings)
    controller.start(startup=True)
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    controller.wander_timer.stop()

    def seed_stale_wander():
        controller._wander_target = Point(-1_100, -50)
        controller._wander_direction = -1
        controller._wander_area = Rect(-1_280, -100, 1_280, 984)
        controller.timeline.start(ActionId.RUN_LEFT, controller._now_ms())

    seed_stale_wander()
    controller._recover_window_visibility()
    assert controller.wander_target is None
    assert controller._wander_direction == 0
    assert controller._wander_area is None

    seed_stale_wander()
    controller._screen_removed(object())
    qapp.processEvents()
    assert controller.wander_target is None
    before = QPoint(controller.window.pos())
    controller._animation_tick()
    assert controller.window.pos() == before

    area = controller._current_screen_area()
    assert area.x <= controller.window.x() <= area.x + area.width - controller.window.width()
    assert area.y <= controller.window.y() <= area.y + area.height - controller.window.height()
    controller.shutdown()


def test_each_menu_operation_interrupts_active_wander_before_dispatch(qapp):
    settings = replace(AppSettings(), wander_enabled=True)
    controller, _, _, _, _ = _controller(qapp, settings=settings)
    controller.start(startup=True)
    controller.animation_timer.stop()
    controller.gaze_timer.stop()

    def assert_interrupts(command):
        controller.wander_timer.stop()
        controller._wander_target = Point(-1_100, -50)
        controller._wander_direction = -1
        controller._wander_area = Rect(-1_280, -100, 1_280, 984)
        controller.timeline.start(ActionId.RUN_LEFT, controller._now_ms())
        controller.dispatch_menu(command)
        assert controller.wander_target is None
        assert controller._wander_direction == 0
        assert controller._wander_area is None
        after_command = QPoint(controller.window.pos())
        controller._animation_tick()
        assert controller.window.pos() == after_command

    assert_interrupts(MenuCommand("center"))
    assert_interrupts(MenuCommand("scale", 125))
    assert_interrupts(MenuCommand("toggle", False, "gaze_enabled"))
    assert controller.settings.wander_enabled is True
    assert controller.wander_timer.isActive()
    controller.shutdown()


def test_remaining_menu_commands_hook_digit_and_activation(qapp):
    about = []
    controller, _, _, hooks, _ = _controller(qapp)
    controller._about_dialog = lambda parent, title, message: about.append((title, message))
    controller.start(startup=True)

    controller.dispatch_menu(MenuCommand("look", 90.0))
    assert controller.window.current_frame.row == 9
    controller.dispatch_menu(MenuCommand("toggle", False, "hover_digits_enabled"))
    assert not hooks[0].enabled
    controller.dispatch_menu(MenuCommand("toggle", False, "always_on_top"))
    controller.dispatch_menu(MenuCommand("toggle", False, "wander_enabled"))
    controller.dispatch_menu(MenuCommand("center"))
    controller.dispatch_menu(MenuCommand("about"))
    assert about == [
        ("关于桌面灵伴", "桌面灵伴 2.4.3\n可用宠物：3（南宫婉、十一、紫灵）")
    ]

    hooks[0].digit_pressed.emit(4)
    assert controller.current_action is ActionId.WAVE
    controller.trigger_action(ActionId.RANDOM)
    controller.trigger_action(ActionId.IDLE)
    controller.handle_ipc_command("activate")
    assert controller.window.isVisible()

    with pytest.raises(ValueError):
        controller.dispatch_menu(MenuCommand("unknown"))
    with pytest.raises(ValueError):
        controller.dispatch_menu(MenuCommand("toggle", True, "unknown"))
    with pytest.raises(ValueError):
        controller.trigger_action("broken")
    controller.shutdown()


def test_dynamic_burst_move_is_rare_distance_gated_cooled_down_and_interpolated(qapp):
    class PickLast:
        @staticmethod
        def randint(lower, upper):
            del lower
            return upper

        @staticmethod
        def random():
            return 1.0

    settings = replace(AppSettings(), wander_enabled=True)
    controller, _, _, _, _ = _controller(
        qapp, settings=settings, catalog_factory=_dynamic_catalog
    )
    try:
        controller._rng = PickLast()
        controller._now_ms = lambda: 100_000

        assert controller._choose_wander_action(-1, 200) == "moveLeft"
        assert controller._choose_wander_action(-1, 400) == "dashLeft"
        controller._last_action_played_ms["dashLeft"] = 99_999
        assert controller._choose_wander_action(-1, 400) == "moveLeft"

        controller._last_action_played_ms.clear()
        start = Point(float(controller.window.x()), float(controller.window.y()))
        target = Point(start.x - 300, start.y)
        area = controller._current_screen_area()
        controller._wander_target = target
        controller._wander_direction = -1
        controller._wander_area = area
        controller._wander_action = "dashLeft"
        controller._wander_start = start
        controller.timeline.start("dashLeft", 0)

        controller._advance_wander(100, 0.1)
        assert controller.wander_target == target
        assert controller.window.x() == round(start.x)

        controller._advance_wander(405, 0.1)
        assert target.x < controller.window.x() < start.x

        controller._advance_wander(540, 0.1)
        assert controller.window.x() == round(target.x)
        assert controller.wander_target == target

        controller._advance_wander(720, 0.1)
        assert controller.wander_target is None
        assert controller.window.x() == round(target.x)
        assert controller.current_action == "rest"
    finally:
        controller.shutdown()


def test_ratio_burst_moves_half_screen_inward_and_manual_edge_action_reverses(qapp):
    class PickBurst:
        @staticmethod
        def randint(lower, upper):
            del lower
            return upper

    settings = replace(AppSettings(), wander_enabled=True)
    controller, _, _, _, _ = _controller(
        qapp, settings=settings, catalog_factory=_dynamic_catalog
    )
    try:
        controller._rng = PickBurst()
        controller._now_ms = lambda: 100_000
        area = controller._current_screen_area()
        pet = controller._pet_size()
        max_x = area.x + area.width - pet.width
        max_y = area.y + area.height - pet.height
        controller.window.move(round(max_x), round((area.y + max_y) / 2))
        current = Point(float(controller.window.x()), float(controller.window.y()))
        normal_target = Point(max_x, max_y)

        plan = controller._choose_ratio_wander_plan(
            current, normal_target, 1, area
        )

        assert plan is not None
        action, target, direction = plan
        assert action == "dashLeft"
        assert direction == -1
        usable_width = area.width - pet.width
        assert target.x == pytest.approx(current.x - usable_width * 0.5)
        assert abs(target.y - current.y) <= (area.height - pet.height) * 0.1
        assert area.x <= target.x <= max_x
        assert area.y <= target.y <= max_y

        controller.trigger_action("dashRight")
        assert controller.current_action == "dashLeft"
        assert controller._manual_burst_target is not None
        assert controller._manual_burst_target.x == pytest.approx(
            current.x - usable_width * 0.5
        )
    finally:
        controller.shutdown()


def test_pet_switch_is_immediate_and_persisted(qapp):
    controller, store, _, _, trays = _controller(qapp)
    original = controller.window.current_frame.image
    initial_icon, initial_name = trays[0].companion_icons[-1]
    assert initial_name == "十一"
    assert initial_icon == controller.catalog.icon_image()
    assert "抬爪招呼" in controller.menu_controller.flattened_labels()
    assert "挥手问候" not in controller.menu_controller.flattened_labels()

    controller.dispatch_menu(MenuCommand("pet", "ziling"))

    assert controller.settings.pet_id == "ziling"
    assert controller.catalog.pet_id == "ziling"
    assert controller.window.current_frame.image != original
    assert store.saved[-1].pet_id == "ziling"
    ziling_icon, ziling_name = trays[0].companion_icons[-1]
    assert ziling_name == "紫灵"
    assert ziling_icon == controller.catalog.icon_image()
    assert ziling_icon != initial_icon
    assert "抬爪招呼" not in controller.menu_controller.flattened_labels()
    assert "挥手问候" in controller.menu_controller.flattened_labels()

    controller.dispatch_menu(MenuCommand("pet", "shiyi"))
    assert controller.settings.pet_id == "shiyi"
    assert controller.catalog.pet_id == "shiyi"
    controller.shutdown()


def test_weighted_random_actions_never_move_or_repeat_immediately(qapp):
    controller, _, _, _, _ = _controller(qapp)
    try:
        chosen = [controller._choose_random_action() for _ in range(30)]

        assert all(action not in {ActionId.RUN_LEFT, ActionId.RUN_RIGHT} for action in chosen)
        assert all(left is not right for left, right in zip(chosen, chosen[1:]))
    finally:
        controller.shutdown()


def test_weighted_random_actions_do_not_repeat_a_nonempty_autoplay_group(qapp):
    class PickLast:
        @staticmethod
        def randint(lower, upper):
            del lower
            return upper

    controller, _, _, _, _ = _controller(qapp, catalog_factory=_grouped_catalog)
    try:
        controller._rng = PickLast()
        controller._last_random_group = "spell"

        assert controller._choose_random_action() == "daily"
        assert controller._last_random_group is None
        assert controller._choose_random_action() == "spellB"
        assert controller._last_random_group == "spell"
        assert controller._choose_random_action() == "daily"
    finally:
        controller.shutdown()


def test_cursor_stillness_triggers_autonomous_action_after_eight_seconds(qapp):
    controller, _, _, _, _ = _controller(qapp)
    controller.start(startup=True)
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    controller.autonomous_timer.stop()
    now = [0]
    controller._now_ms = lambda: now[0]
    controller._last_cursor_move_ms = 0
    controller._autonomous_not_before_ms = 0

    now[0] = 7_999
    controller._autonomous_timeout()
    assert controller.current_action is ActionId.IDLE

    controller.autonomous_timer.stop()
    now[0] = 8_000
    controller._autonomous_timeout()
    assert controller.current_action in {
        ActionId.WAVE,
        ActionId.JUMP,
        ActionId.BELLY_FLOP,
        ActionId.EXPECT,
        ActionId.PATROL,
        ActionId.CURIOUS,
    }
    controller.shutdown()


def test_active_gaze_releases_to_wander_and_mouse_motion_takes_control_again(
    qapp, monkeypatch
):
    cursor = [QPoint(900, 300)]

    class ControlledCursor:
        @staticmethod
        def pos():
            return QPoint(cursor[0])

    monkeypatch.setattr("shiyi_desktop_pet.app.QCursor", ControlledCursor)
    settings = replace(
        AppSettings(), wander_enabled=True, gaze_mode="active"
    )
    controller, _, _, _, _ = _controller(qapp, settings=settings)
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    now = [100]
    controller._now_ms = lambda: now[0]
    controller._last_cursor_move_ms = 0
    controller._last_cursor_position = QPoint(cursor[0])

    controller._gaze_tick()
    assert controller.behavior.mode is BehaviorMode.GAZE
    assert not controller.wander_timer.isActive()

    now[0] = 8_000
    controller._gaze_tick()
    assert controller.behavior.mode is BehaviorMode.WANDER
    assert controller.behavior.gaze_degrees is None
    assert controller.wander_timer.isActive()

    cursor[0] = QPoint(950, 320)
    now[0] = 8_050
    controller._gaze_tick()
    assert controller.behavior.mode is BehaviorMode.GAZE
    assert controller.behavior.gaze_degrees is not None
    assert not controller.wander_timer.isActive()
    controller.shutdown()


def test_always_gaze_suppresses_wander_and_autonomous_actions(qapp, monkeypatch):
    class ControlledCursor:
        @staticmethod
        def pos():
            return QPoint(900, 300)

    monkeypatch.setattr("shiyi_desktop_pet.app.QCursor", ControlledCursor)
    settings = replace(
        AppSettings(), wander_enabled=True, gaze_mode="always"
    )
    controller, _, _, _, _ = _controller(qapp, settings=settings)
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    controller._now_ms = lambda: 60_000
    controller._last_cursor_move_ms = 0

    controller._gaze_tick()
    controller._schedule_wander()
    controller._schedule_autonomous()

    assert controller.behavior.mode is BehaviorMode.GAZE
    assert not controller.wander_timer.isActive()
    assert not controller.autonomous_timer.isActive()
    controller.shutdown()


def test_gaze_mode_menu_command_is_persisted_in_runtime_settings(qapp):
    controller, _, _, _, _ = _controller(qapp)

    controller.dispatch_menu(MenuCommand("gaze_mode", "always"))

    assert controller.settings.gaze_mode == "always"
    with pytest.raises(ValueError, match="unsupported gaze mode"):
        controller.dispatch_menu(MenuCommand("gaze_mode", "sometimes"))
    controller.shutdown()


def test_pet_without_gaze_frames_does_not_wait_for_cursor_stillness(qapp):
    controller, _, _, _, _ = _controller(qapp, catalog_factory=_dynamic_catalog)
    controller.start(startup=True)
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    controller.autonomous_timer.stop()
    now = [1_000]
    controller._now_ms = lambda: now[0]
    controller._last_cursor_move_ms = now[0]
    controller._autonomous_not_before_ms = 0

    controller._schedule_autonomous()
    assert 16_000 <= controller._autonomous_not_before_ms <= 36_000
    now[0] = controller._autonomous_not_before_ms
    controller._last_cursor_move_ms = now[0]
    controller._autonomous_timeout()

    assert controller.current_action == "hello"
    controller.shutdown()


def test_autonomous_actions_wait_randomly_without_gaze_and_respect_toggle(qapp):
    settings = replace(AppSettings(), gaze_enabled=False)
    controller, _, _, _, _ = _controller(qapp, settings=settings)
    controller.start(startup=True)
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    controller.autonomous_timer.stop()
    controller._now_ms = lambda: 0
    controller._autonomous_not_before_ms = 0

    controller._schedule_autonomous()
    assert 15_000 <= controller._autonomous_not_before_ms <= 35_000
    assert controller.autonomous_timer.isActive()

    controller.dispatch_menu(
        MenuCommand("toggle", False, "autonomous_actions_enabled")
    )
    assert not controller.settings.autonomous_actions_enabled
    assert not controller.autonomous_timer.isActive()
    controller._autonomous_timeout()
    assert controller.current_action is ActionId.IDLE
    controller.shutdown()


def test_action_showcase_plays_every_in_place_action_once(qapp):
    controller, _, _, _, _ = _controller(qapp)
    controller.start(startup=True)
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    controller.autonomous_timer.stop()
    expected = controller.catalog.showcase_actions()

    controller.dispatch_menu(MenuCommand("showcase"))
    for action in expected:
        assert controller.current_action is action
        controller.timeline.started_ms = 0
        controller._advance_manual(100_000)

    assert controller.current_action is ActionId.IDLE
    assert not controller._showcase_active
    controller.shutdown()


def test_persistent_state_enters_cycles_without_repeating_and_forces_exit(qapp):
    settings = replace(AppSettings(), gaze_enabled=False)
    controller, _, _, _, _ = _controller(
        qapp, settings=settings, catalog_factory=_state_catalog
    )
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    controller.autonomous_timer.stop()
    now = [0]
    controller._now_ms = lambda: now[0]

    controller.trigger_action("rooftopEnter")
    assert controller.active_state.key == "moonlitRooftop"
    assert controller._state_phase == "enter"
    assert controller.current_action == "rooftopEnter"

    now[0] = 300
    controller._advance_manual(now[0])
    first_resident = controller.current_action
    assert controller._state_phase == "resident"
    assert first_resident in {"rooftopIdle", "rooftopMoon"}

    now[0] = 600
    controller._advance_manual(now[0])
    assert controller.current_action in {"rooftopIdle", "rooftopMoon"}
    assert controller.current_action != first_resident
    assert controller._state_phase == "resident"

    controller.timeline.started_ms = 90000
    now[0] = 90300
    controller._advance_manual(now[0])
    assert controller._state_phase == "exit"
    assert controller.current_action == "rooftopExit"

    now[0] = 90600
    controller._advance_manual(now[0])
    assert controller.active_state is None
    assert controller.current_action == controller.catalog.idle_action
    controller.shutdown()


def test_persistent_state_menu_requests_natural_exit_after_current_clip(qapp):
    controller, _, _, _, _ = _controller(
        qapp,
        settings=replace(AppSettings(), gaze_enabled=False),
        catalog_factory=_state_catalog,
    )
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    now = [0]
    controller._now_ms = lambda: now[0]

    controller.dispatch_menu(MenuCommand("action", "rooftopEnter"))
    now[0] = 300
    controller._advance_manual(now[0])
    resident = controller.current_action

    assert ("结束月下屋檐", "rooftopEnter") in controller._action_menu_items()
    controller.dispatch_menu(MenuCommand("action", "rooftopEnter"))
    assert controller._state_exit_requested
    assert controller.current_action == resident
    assert ("正在结束月下屋檐", "rooftopEnter") in controller._action_menu_items()

    now[0] = 600
    controller._advance_manual(now[0])
    assert controller._state_phase == "exit"
    assert controller.current_action == "rooftopExit"
    now[0] = 900
    controller._advance_manual(now[0])
    assert controller.active_state is None
    controller.shutdown()


def test_drag_and_pet_switch_cancel_persistent_state_without_scene_residue(qapp):
    controller, _, _, _, _ = _controller(
        qapp,
        settings=replace(AppSettings(), gaze_enabled=False),
        catalog_factory=_state_catalog,
    )
    controller.animation_timer.stop()
    controller.gaze_timer.stop()

    controller.trigger_action("rooftopEnter")
    controller._begin_drag()
    assert controller.active_state is None
    assert controller.behavior.mode is BehaviorMode.DRAGGING
    assert controller.behavior.current_action is None
    controller._finish_drag(QPoint(controller.window.x(), controller.window.y()))

    controller.trigger_action("rooftopEnter")
    controller._switch_pet("shiyi", force=True)
    assert controller.active_state is None
    assert controller.catalog.pet_id == "shiyi"
    assert controller.current_action == controller.catalog.idle_action
    controller.shutdown()


def test_moonlit_rooftop_manual_start_ignores_cooldown_and_can_exit(qapp):
    class PickLast:
        @staticmethod
        def randint(lower, upper):
            del lower
            return upper

    settings = replace(AppSettings(), pet_id="nangongwan", gaze_enabled=False)
    controller, _, _, _, _ = _controller(
        qapp,
        settings=settings,
        catalog_factory=lambda: AnimationCatalog.load_pet("nangongwan"),
    )
    controller.animation_timer.stop()
    controller.gaze_timer.stop()
    controller.autonomous_timer.stop()
    now = [200_000]
    controller._now_ms = lambda: now[0]
    controller._rng = PickLast()

    controller._last_action_played_ms.clear()
    assert controller._choose_random_action() == "moonlitChestnut"
    controller._last_action_played_ms["moonlitChestnut"] = now[0]
    assert controller._choose_random_action() != "moonlitChestnut"

    controller.dispatch_menu(MenuCommand("action", "moonlitChestnut"))
    assert controller.current_action == "moonlitChestnut"
    assert controller.active_state.key == "moonlitRooftop"
    assert controller._last_action_played_ms["moonlitChestnut"] == now[0]

    now[0] += 2460
    controller._advance_manual(now[0])
    assert controller.current_action == "rooftopGlance"

    controller.dispatch_menu(MenuCommand("action", "moonlitChestnut"))
    assert controller._state_exit_requested
    now[0] += 2100
    controller._advance_manual(now[0])
    assert controller.current_action == "rooftopExit"
    now[0] += 2460
    controller._advance_manual(now[0])
    assert controller.current_action == controller.catalog.idle_action
    assert controller.active_state is None
    controller.shutdown()


def test_dynamic_pet_pack_refresh_switch_and_open_directory(tmp_path, qapp):
    user_root = tmp_path / "pets"
    opened = []
    registry = PetRegistry(
        resource_root() / "pets",
        user_root,
        validator=AnimationCatalog.load_definition,
    )
    controller, store, _, _, trays = _controller(
        qapp,
        pet_registry=registry,
        open_pet_directory=lambda path: opened.append(path) or True,
    )
    assert controller.pet_choices == (
        ("nangongwan", "南宫婉"),
        ("shiyi", "十一"),
        ("ziling", "紫灵"),
    )

    _install_test_pet(user_root, "new_pet", "新宠物")
    controller.dispatch_menu(MenuCommand("refresh_pets"))

    assert controller.pet_choices == (
        ("nangongwan", "南宫婉"),
        ("shiyi", "十一"),
        ("ziling", "紫灵"),
        ("new_pet", "新宠物"),
    )
    assert trays[0].messages[-1][0] == "桌面灵伴"
    controller.dispatch_menu(MenuCommand("pet", "new_pet"))
    assert controller.catalog.pet_id == "new_pet"
    assert controller.settings.pet_id == "new_pet"
    assert store.saved[-1].pet_id == "new_pet"

    controller.dispatch_menu(MenuCommand("open_pets_directory"))
    assert opened == [user_root]

    shutil.rmtree(user_root / "new_pet")
    controller.dispatch_menu(MenuCommand("refresh_pets"))
    assert controller.settings.pet_id == "shiyi"
    assert controller.catalog.pet_id == "shiyi"
    assert store.saved[-1].pet_id == "shiyi"
    controller.shutdown()


def test_missing_saved_pet_falls_back_to_default_and_is_persisted(qapp):
    controller, store, _, _, _ = _controller(
        qapp, settings=AppSettings(pet_id="missing_pet")
    )

    assert controller.settings.pet_id == "shiyi"
    assert controller.catalog.pet_id == "shiyi"
    assert store.saved[-1].pet_id == "shiyi"
    controller.shutdown()


def test_rotating_logging_and_exception_cleanup(tmp_path, qapp, monkeypatch):
    logger = configure_logging(tmp_path)
    assert configure_logging(tmp_path) is logger
    handler = next(
        item
        for item in logger.handlers
        if getattr(item, "baseFilename", "") == str((tmp_path / "DesktopCompanion.log").resolve())
    )
    assert handler.maxBytes == 1_048_576
    assert handler.backupCount == 3

    events = []

    class CleanupTarget:
        def stop(self):
            events.append("stop")

        def hide(self):
            events.append("hide")

    previous = sys.excepthook
    try:
        installed = install_exception_hook(
            logger,
            hook_supplier=CleanupTarget,
            tray_supplier=CleanupTarget,
        )
        error = RuntimeError("boom")
        installed(RuntimeError, error, error.__traceback__)
        qapp.processEvents()
    finally:
        sys.excepthook = previous
    assert events == ["stop", "hide"]
    handler.flush()
    assert "Unhandled application exception" in (tmp_path / "DesktopCompanion.log").read_text(
        encoding="utf-8"
    )


def test_main_successful_composition_cleans_runtime(qapp, tmp_path, monkeypatch):
    guard = GuardSpy()
    store = MemorySettingsStore()
    hooks = []
    trays = []

    def hook_factory(hit_test, *, enabled=True):
        hook = FakeHook(hit_test, enabled=enabled)
        hooks.append(hook)
        return hook

    def tray_factory(window, menu):
        tray = FakeTray(window, menu)
        trays.append(tray)
        return tray

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    previous = sys.excepthook
    try:
        result = main(
            ["--startup"],
            qapp=qapp,
            guard_factory=lambda: guard,
            catalog_factory=_catalog,
            settings_store_factory=lambda: store,
            startup_manager_factory=FakeStartup,
            hook_factory=hook_factory,
            tray_factory=tray_factory,
            run_event_loop=False,
        )
    finally:
        sys.excepthook = previous

    assert result == 0
    assert guard.closed
    assert hooks[0].started and hooks[0].stopped
    assert trays[0].shown and trays[0].hidden
    assert store.saved


@pytest.mark.parametrize(
    ("argv", "expected_qa_window"),
    [([], False), (["--qa-window"], True)],
)
def test_main_passes_only_explicit_qa_window_mode_to_controller(
    qapp, tmp_path, monkeypatch, argv, expected_qa_window
):
    captured = []

    class CapturingController:
        def __init__(self, *args, qa_window, **kwargs):
            captured.append(qa_window)
            self.hook = FakeHook(lambda: False)
            self.tray = FakeTray(None, None)

        def handle_ipc_command(self, command):
            pass

        def start(self, *, startup=False):
            pass

        def shutdown(self):
            pass

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(
        "shiyi_desktop_pet.app.DesktopPetApplication", CapturingController
    )
    previous = sys.excepthook
    try:
        result = main(
            argv,
            qapp=qapp,
            guard_factory=GuardSpy,
            settings_store_factory=MemorySettingsStore,
            startup_manager_factory=FakeStartup,
            critical_error=lambda title, message: None,
            run_event_loop=False,
        )
    finally:
        sys.excepthook = previous

    assert result == 0
    assert captured == [expected_qa_window]


def test_main_closes_guard_even_when_controller_shutdown_raises(
    qapp, tmp_path, monkeypatch
):
    guard = GuardSpy()

    class FailingController:
        def __init__(self, *args, **kwargs):
            self.hook = FakeHook(lambda: False)
            self.tray = FakeTray(None, None)
            self.shutdown_calls = 0

        def handle_ipc_command(self, command):
            pass

        def start(self, *, startup=False):
            pass

        def shutdown(self):
            self.shutdown_calls += 1
            raise RuntimeError("shutdown failed")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(
        "shiyi_desktop_pet.app.DesktopPetApplication", FailingController
    )
    previous = sys.excepthook
    try:
        with pytest.raises(RuntimeError, match="shutdown failed"):
            main(
                [],
                qapp=qapp,
                guard_factory=lambda: guard,
                settings_store_factory=MemorySettingsStore,
                startup_manager_factory=FakeStartup,
                run_event_loop=False,
            )
    finally:
        sys.excepthook = previous

    assert guard.close_calls == 1


def test_self_test_failure_and_owner_quit_cli_paths(qapp):
    chunks = []
    assert main(
        ["--self-test"],
        qapp=qapp,
        catalog_factory=lambda: (_ for _ in ()).throw(ValueError("missing")),
        stdout_writer=chunks.append,
        run_event_loop=False,
    ) == 1
    assert json.loads("".join(chunks))["ok"] is False

    guard = GuardSpy(acquired=True)
    assert main(
        ["--quit-existing"],
        qapp=qapp,
        guard_factory=lambda: guard,
        run_event_loop=False,
    ) == 0
    assert guard.closed


def test_stdout_writer_uses_python_stream(monkeypatch):
    stream = StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    _write_stdout("{\"ok\":true}\n")
    assert stream.getvalue() == "{\"ok\":true}\n"


def test_stdout_writer_does_not_crash_a_windowed_process_with_a_broken_stream(monkeypatch):
    class BrokenStream:
        def write(self, text):
            del text
            raise OSError(22, "Invalid argument")

        def flush(self):
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(sys, "stdout", BrokenStream())
    _write_stdout("{\"ok\":true}\n")


def test_atlas_failure_releases_instance_guard_and_returns_nonzero(
    qapp, tmp_path, monkeypatch
):
    guard = GuardSpy()
    dialogs = []
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    result = main(
        [],
        qapp=qapp,
        guard_factory=lambda: guard,
        catalog_factory=lambda: (_ for _ in ()).throw(ValueError("bad atlas")),
        settings_store_factory=lambda: MemorySettingsStore(),
        startup_manager_factory=FakeStartup,
        critical_error=lambda title, message: dialogs.append((title, message)),
        run_event_loop=False,
    )

    assert result != 0
    assert guard.closed
    assert dialogs and "bad atlas" in dialogs[0][1]
    assert not any(widget.isVisible() for widget in qapp.topLevelWidgets())


def test_atlas_failure_still_releases_guard_when_dialog_fails(
    qapp, tmp_path, monkeypatch
):
    guard = GuardSpy()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    result = main(
        [],
        qapp=qapp,
        guard_factory=lambda: guard,
        catalog_factory=lambda: (_ for _ in ()).throw(ValueError("bad atlas")),
        settings_store_factory=lambda: MemorySettingsStore(),
        startup_manager_factory=FakeStartup,
        critical_error=lambda title, message: (_ for _ in ()).throw(
            RuntimeError("dialog unavailable")
        ),
        run_event_loop=False,
    )

    assert result == 1
    assert guard.closed


def test_duplicate_and_quit_existing_exit_without_building_runtime(qapp):
    duplicate = GuardSpy(acquired=False)
    assert main(
        [], qapp=qapp, guard_factory=lambda: duplicate, run_event_loop=False
    ) == 0
    assert duplicate.commands == ["activate"]

    quitter = GuardSpy(acquired=False)
    assert main(
        ["--quit-existing"],
        qapp=qapp,
        guard_factory=lambda: quitter,
        run_event_loop=False,
    ) == 0
    assert quitter.commands == ["quit"]


def test_self_test_cli_writes_one_json_object(qapp):
    chunks = []
    result = main(
        ["--self-test"], qapp=qapp, stdout_writer=chunks.append, run_event_loop=False
    )
    assert result == 0
    assert json.loads("".join(chunks))["ok"] is True
