"""Executable composition root for the standalone Shiyi desktop pet."""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass, replace
import json
import logging
import math
import os
from pathlib import Path
from random import Random
import sys
from collections.abc import Callable, Mapping

from PySide6.QtCore import QElapsedTimer, QPoint, QTimer, Qt, qVersion
from PySide6.QtGui import QCursor, QGuiApplication, QImage, QImageReader
from PySide6.QtWidgets import QApplication, QMessageBox

from .animation_catalog import AnimationCatalog
from .animation_player import AnimationTimeline
from .behavior import BehaviorEngine, BehaviorMode
from .constants import ACTION_SPECS, CELL_HEIGHT, CELL_WIDTH, KEY_TO_ACTION
from .gaze import GazeStabilizer, quantize_gaze
from .geometry import Point, Rect, Size, clamp_position
from .keyboard_hook import LowLevelKeyboardHook
from .logging_setup import configure_logging, install_exception_hook
from .menu_controller import MenuCommand, MenuController
from .models import ActionId, FrameAsset
from .pet_window import PetWindow
from .settings import AppSettings, SettingsStore
from .single_instance import SingleInstanceGuard
from .startup import StartupManager, WinRegRunKey
from .tray_controller import TrayController
from .wander import WanderPlanner


_LOGGER = logging.getLogger(__name__)
_RANDOM_ACTIONS = (
    ActionId.WAVE,
    ActionId.JUMP,
    ActionId.BELLY_FLOP,
    ActionId.EXPECT,
    ActionId.PATROL,
    ActionId.CURIOUS,
)
_ANIMATION_SPEED = {"slow": 1.25, "normal": 1.0, "fast": 0.75}
_MOVEMENT_SPEED = {"slow": 75.0, "normal": 120.0, "fast": 180.0}


@dataclass(frozen=True, slots=True)
class HoverSnapshot:
    """Complete UI-thread snapshot consumed atomically by the hook thread."""

    alpha: bytes
    width: int
    height: int
    bytes_per_line: int
    scale: float
    window_x: float
    window_y: float
    visible: bool
    cursor_x: float
    cursor_y: float

    def hit_test(self) -> bool:
        if not self.visible or self.scale <= 0:
            return False
        source_x = int((self.cursor_x - self.window_x) / self.scale)
        source_y = int((self.cursor_y - self.window_y) / self.scale)
        if not (0 <= source_x < self.width and 0 <= source_y < self.height):
            return False
        offset = source_y * self.bytes_per_line + source_x
        return offset < len(self.alpha) and self.alpha[offset] > 0


_EMPTY_HOVER_SNAPSHOT = HoverSnapshot(
    alpha=b"",
    width=0,
    height=0,
    bytes_per_line=0,
    scale=1.0,
    window_x=0.0,
    window_y=0.0,
    visible=False,
    cursor_x=0.0,
    cursor_y=0.0,
)


def resolve_digit_action(digit: int, rng: Random) -> ActionId:
    """Resolve a top-row or keypad digit, including the random action key."""
    if digit not in KEY_TO_ACTION:
        raise ValueError(f"unsupported digit: {digit}")
    action = KEY_TO_ACTION[digit]
    return rng.choice(_RANDOM_ACTIONS) if action is ActionId.RANDOM else action


def restore_window_position(
    settings: AppSettings,
    screens: Mapping[str, Rect],
    primary_name: str,
    pet_size: Size,
) -> tuple[str, Point]:
    """Restore a center-relative position and clamp it to an available screen."""
    if not screens:
        raise ValueError("at least one screen is required")
    selected_name = settings.screen_name if settings.screen_name in screens else primary_name
    if selected_name not in screens:
        selected_name = next(iter(screens))
    area = screens[selected_name]

    if settings.screen_name == "":
        position = Point(
            area.x + area.width - pet_size.width - 32,
            area.y + area.height - pet_size.height - 24,
        )
    else:
        relative_x = settings.relative_x if math.isfinite(settings.relative_x) else 0.5
        relative_y = settings.relative_y if math.isfinite(settings.relative_y) else 0.5
        position = Point(
            area.x + area.width * relative_x - pet_size.width / 2,
            area.y + area.height * relative_y - pet_size.height / 2,
        )
    return selected_name, clamp_position(position, pet_size, area)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ShiyiDesktopPet")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--quit-existing", action="store_true")
    modes.add_argument("--startup", action="store_true")
    return parser.parse_args(argv)


def run_self_test(
    catalog_factory: Callable[[], AnimationCatalog] = AnimationCatalog.load_default,
) -> dict[str, object]:
    """Decode and validate packaged resources plus the Qt WebP reader plugin."""
    catalog = catalog_factory()
    standard_frames = sum(len(catalog.frames(action)) for action in ACTION_SPECS)
    look_only_frames = 16
    formats = {bytes(item).lower() for item in QImageReader.supportedImageFormats()}
    return {
        "ok": standard_frames + look_only_frames == 74 and b"webp" in formats,
        "qt": qVersion(),
        "atlas": {"width": 1536, "height": 2288, "frames": 74},
        "webp_plugin": b"webp" in formats,
    }


class DesktopPetApplication:
    """Own Qt UI, behavior timers, input hook, persistence, and cleanup."""

    def __init__(
        self,
        qapp: QApplication,
        *,
        settings_store: SettingsStore,
        startup_manager: StartupManager,
        catalog_factory: Callable[[], AnimationCatalog] = AnimationCatalog.load_default,
        hook_factory: Callable[..., object] = LowLevelKeyboardHook,
        tray_factory: Callable[..., object] = TrayController,
        random: Random | None = None,
        logger: logging.Logger | None = None,
        window_factory: Callable[[AnimationCatalog], PetWindow] = PetWindow,
        about_dialog: Callable[[object, str, str], object] = QMessageBox.about,
    ) -> None:
        self.qapp = qapp
        self.logger = logger or _LOGGER
        self.catalog = catalog_factory()
        self.settings_store = settings_store
        self.startup_manager = startup_manager
        self._settings = settings_store.load()
        self._session_hover_digits_enabled = self._settings.hover_digits_enabled
        self._hook_available = True
        self._hook_notification_shown = False
        self._rng = random or Random()
        self._about_dialog = about_dialog
        self.behavior = BehaviorEngine(wander_enabled=self._settings.wander_enabled)
        self.timeline = AnimationTimeline()
        self.wander_planner = WanderPlanner(self._rng)
        self.gaze_stabilizer = GazeStabilizer()
        self.window = window_factory(self.catalog)
        self.window.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint, self._settings.always_on_top
        )
        self._hover_snapshot = _EMPTY_HOVER_SNAPSHOT
        self._alpha_cache: dict[tuple[int, int], tuple[bytes, int]] = {}
        self._displayed_frame: tuple[int, int, int] | None = None
        self._started = False
        self._shut_down = False
        self._wander_target: Point | None = None
        self._wander_direction = 0
        self._wander_area: Rect | None = None
        self._fixed_look_degrees: float | None = None
        self._last_frame_index: int | None = None
        self._last_tick_ms = 0

        self._clock = QElapsedTimer()
        self._clock.start()
        self.timeline.start(ActionId.IDLE, self._now_ms())

        self.menu_controller = MenuController(
            lambda: self.settings,
            self.startup_manager.is_enabled,
            self.dispatch_menu,
            self.logger,
        )
        self.body_menu = self.menu_controller.create_menu(self.window)
        self.tray = tray_factory(self.window, self.menu_controller)
        self.hook = hook_factory(
            self._hook_hit_test,
            enabled=self._session_hover_digits_enabled,
        )

        self.animation_timer = QTimer(self.window)
        self.animation_timer.setInterval(16)
        self.animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.animation_timer.timeout.connect(self._animation_tick)
        self.gaze_timer = QTimer(self.window)
        self.gaze_timer.setInterval(50)
        self.gaze_timer.timeout.connect(self._gaze_tick)
        self.wander_timer = QTimer(self.window)
        self.wander_timer.setSingleShot(True)
        self.wander_timer.timeout.connect(self.begin_wander)

        self.window.action_requested.connect(self.trigger_action)
        self.window.menu_requested.connect(self.body_menu.popup)
        self.window.drag_started.connect(self._begin_drag)
        self.window.drag_moved.connect(self._drag_to)
        self.window.drag_finished.connect(self._finish_drag)
        self.hook.digit_pressed.connect(self._digit_pressed)
        self.hook.hook_failed.connect(self._hook_failed)
        self.qapp.screenAdded.connect(self._screen_added)
        self.qapp.screenRemoved.connect(self._screen_removed)
        for screen in self.qapp.screens():
            self._connect_screen(screen)

        initial = self.catalog.frames(ActionId.IDLE)[0]
        self._show_frame(initial)
        self._restore_position()
        self._refresh_hover_snapshot()

    @property
    def settings(self) -> AppSettings:
        effective_hover = (
            self._settings.hover_digits_enabled
            and self._session_hover_digits_enabled
            and self._hook_available
        )
        if effective_hover == self._settings.hover_digits_enabled:
            return self._settings
        return replace(self._settings, hover_digits_enabled=effective_hover)

    @property
    def hover_snapshot(self) -> HoverSnapshot:
        return self._hover_snapshot

    @property
    def wander_target(self) -> Point | None:
        return self._wander_target

    @property
    def current_action(self) -> ActionId:
        if self.behavior.current_action is not None:
            return self.behavior.current_action
        if self._wander_target is not None and self._wander_direction != 0:
            return ActionId.RUN_RIGHT if self._wander_direction > 0 else ActionId.RUN_LEFT
        return ActionId.IDLE

    def start(self, *, startup: bool = False) -> None:
        if self._started or self._shut_down:
            return
        self._started = True
        self.tray.show()
        self.window.show()
        if not startup:
            self.window.raise_()
        self._refresh_hover_snapshot()
        self.animation_timer.start()
        self.gaze_timer.start()
        self._schedule_wander()
        try:
            self.hook.start()
        except Exception as error:
            self.logger.exception("Keyboard hook startup failed")
            self._disable_hook_for_session(error)

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self.behavior.begin_shutdown()
        self.animation_timer.stop()
        self.gaze_timer.stop()
        self.wander_timer.stop()
        try:
            self.hook.stop()
        except Exception:
            self.logger.exception("Could not stop keyboard hook")
        try:
            self.tray.hide()
        except Exception:
            self.logger.exception("Could not hide tray icon")
        try:
            self._save_window_position()
            self.settings_store.save(self._settings)
        except Exception:
            self.logger.exception("Could not save application settings")
        self.window.hide()
        self._refresh_hover_snapshot()

    def handle_ipc_command(self, command: str) -> None:
        if command == "activate":
            self.activate()
        elif command == "quit":
            self.request_quit()

    def activate(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self._refresh_hover_snapshot()

    def request_quit(self) -> None:
        self.behavior.begin_shutdown()
        self.qapp.quit()

    def trigger_action(self, action: ActionId) -> None:
        if action is ActionId.RANDOM:
            action = self._rng.choice(_RANDOM_ACTIONS)
        if action not in ACTION_SPECS:
            raise ValueError(f"unsupported action: {action}")
        self._fixed_look_degrees = None
        self._wander_target = None
        self._wander_direction = 0
        self.wander_timer.stop()
        self.behavior.trigger_manual(action)
        self.timeline.start(action, self._now_ms())
        self._last_frame_index = None
        if action is ActionId.IDLE:
            self._resume_base_mode()

    def begin_wander(self) -> None:
        if self.behavior.mode is not BehaviorMode.WANDER or self._shut_down:
            return
        area = self._current_screen_area()
        self._fixed_look_degrees = None
        current = Point(float(self.window.x()), float(self.window.y()))
        target = self.wander_planner.choose_target(current, self._pet_size(), area)
        if target.direction == 0:
            self._wander_target = None
            self._wander_direction = 0
            self._wander_area = area
            self.timeline.start(ActionId.IDLE, self._now_ms())
            self._show_frame(self.catalog.frames(ActionId.IDLE)[0])
            self._schedule_wander()
            return
        self._wander_target = target.position
        self._wander_direction = target.direction
        self._wander_area = area
        action = ActionId.RUN_RIGHT if target.direction > 0 else ActionId.RUN_LEFT
        self.timeline.start(action, self._now_ms())
        self._last_frame_index = None

    def dispatch_menu(self, command: MenuCommand) -> None:
        kind = command.kind
        if kind == "action":
            self.trigger_action(ActionId(command.value))
            return
        if kind == "look":
            degrees = float(command.value)
            self._wander_target = None
            self._wander_direction = 0
            self.wander_timer.stop()
            self._fixed_look_degrees = degrees
            self.behavior.request_gaze(degrees)
            self._show_frame(self.catalog.look_frame(degrees))
            return
        if kind == "toggle":
            self._dispatch_toggle(command.target, bool(command.value))
            return
        if kind == "scale":
            self._settings = replace(self._settings, scale_percent=int(command.value))
            self._displayed_frame = None
            self._render_current_frame()
            self._recover_window_visibility()
            return
        if kind == "animation_speed":
            self._settings = replace(self._settings, animation_speed=str(command.value))
            return
        if kind == "movement_speed":
            self._settings = replace(self._settings, movement_speed=str(command.value))
            return
        if kind == "center":
            self.center_on_cursor_screen()
            return
        if kind == "about":
            self._about_dialog(self.window, "关于十一", "十一桌面宠物 1.0")
            return
        if kind == "quit":
            self.request_quit()
            return
        raise ValueError(f"unsupported menu command: {kind}")

    def center_on_cursor_screen(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or self.qapp.primaryScreen()
        if screen is None:
            return
        area = self._rect_from_qrect(screen.availableGeometry())
        size = self._pet_size()
        position = clamp_position(
            Point(
                area.x + (area.width - size.width) / 2,
                area.y + (area.height - size.height) / 2,
            ),
            size,
            area,
        )
        self._move_window(position)

    def _dispatch_toggle(self, target: str | None, enabled: bool) -> None:
        if target == "startup_enabled":
            self.startup_manager.set_enabled(enabled)
            return
        if target not in {
            "wander_enabled",
            "gaze_enabled",
            "hover_digits_enabled",
            "always_on_top",
        }:
            raise ValueError(f"unsupported setting toggle: {target}")
        self._settings = replace(self._settings, **{target: enabled})
        if target == "wander_enabled":
            self.behavior.set_wander_enabled(enabled)
            self._wander_target = None
            self._wander_direction = 0
            if enabled:
                self._schedule_wander()
            else:
                self.wander_timer.stop()
        elif target == "gaze_enabled" and not enabled:
            self.behavior.request_gaze(None)
        elif target == "hover_digits_enabled":
            effective = enabled and self._hook_available
            self._session_hover_digits_enabled = effective
            self.hook.set_enabled(effective)
        elif target == "always_on_top":
            visible = self.window.isVisible()
            self.window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
            if visible:
                self.window.show()
        self._render_current_frame()

    def _digit_pressed(self, digit: int) -> None:
        self.trigger_action(resolve_digit_action(digit, self._rng))

    def _hook_failed(self, message: str) -> None:
        error = getattr(self.hook, "last_error", None) or message
        self.logger.error("Keyboard hook failed: %s", error)
        self._disable_hook_for_session(error)

    def _disable_hook_for_session(self, error: object) -> None:
        del error
        self._hook_available = False
        self._session_hover_digits_enabled = False
        try:
            self.hook.set_enabled(False)
        except Exception:
            self.logger.exception("Could not disable failed keyboard hook")
        if not self._hook_notification_shown:
            self._hook_notification_shown = True
            try:
                self.tray.show_message(
                    "十一桌面宠物",
                    "数字快捷键暂时不可用，其他功能仍可正常使用。",
                )
            except Exception:
                self.logger.exception("Could not show keyboard-hook failure notification")

    def _hook_hit_test(self) -> bool:
        """Run on the hook thread; deliberately touches no Qt or QWidget state."""
        return self._hover_snapshot.hit_test()

    def _refresh_hover_snapshot(self, cursor: QPoint | None = None) -> None:
        frame = self.window.current_frame
        if frame is None:
            self._hover_snapshot = _EMPTY_HOVER_SNAPSHOT
            return
        cursor = cursor or QCursor.pos()
        alpha, stride = self._alpha_bytes(frame)
        self._hover_snapshot = HoverSnapshot(
            alpha=alpha,
            width=frame.image.width(),
            height=frame.image.height(),
            bytes_per_line=stride,
            scale=self._settings.scale_percent / 100.0,
            window_x=float(self.window.x()),
            window_y=float(self.window.y()),
            visible=self.window.isVisible(),
            cursor_x=float(cursor.x()),
            cursor_y=float(cursor.y()),
        )

    def _alpha_bytes(self, frame: FrameAsset) -> tuple[bytes, int]:
        key = (frame.row, frame.column)
        cached = self._alpha_cache.get(key)
        if cached is not None:
            return cached
        image = frame.image.convertToFormat(QImage.Format.Format_Alpha8)
        result = bytes(image.constBits()), image.bytesPerLine()
        self._alpha_cache[key] = result
        return result

    def _animation_tick(self) -> None:
        now_ms = self._now_ms()
        delta_seconds = min(0.1, max(0.0, (now_ms - self._last_tick_ms) / 1000.0))
        self._last_tick_ms = now_ms
        mode = self.behavior.mode
        if mode is BehaviorMode.DRAGGING or mode is BehaviorMode.SHUTTING_DOWN:
            self._refresh_hover_snapshot()
            return
        if self._fixed_look_degrees is not None:
            self._show_frame(self.catalog.look_frame(self._fixed_look_degrees))
            return
        if mode is BehaviorMode.MANUAL_ACTION:
            self._advance_manual(now_ms)
            return
        if mode is BehaviorMode.WANDER and self._wander_target is not None:
            self._advance_wander(now_ms, delta_seconds)
            return
        self._render_base(now_ms)

    def _advance_manual(self, now_ms: int) -> None:
        action = self.behavior.current_action
        if action is None:
            self._resume_base_mode()
            return
        adjusted_now = self._adjusted_animation_time(now_ms)
        step = self.timeline.advance(adjusted_now)
        frames = self.catalog.frames(action)
        self._show_frame(frames[step.frame_index])
        if step.frame_index != self._last_frame_index:
            self._last_frame_index = step.frame_index
            movement = ACTION_SPECS[action].movement
            if movement:
                self._manual_move(movement)
        if step.finished:
            self.behavior.manual_finished()
            self._resume_base_mode()

    def _adjusted_animation_time(self, now_ms: int) -> int:
        multiplier = _ANIMATION_SPEED.get(self._settings.animation_speed, 1.0)
        elapsed = max(0, now_ms - self.timeline.started_ms)
        return self.timeline.started_ms + round(elapsed / multiplier)

    def _manual_move(self, direction: int) -> None:
        area = self._current_screen_area()
        distance = 12.0 * self._settings.scale_percent / 100.0
        desired = Point(self.window.x() + direction * distance, float(self.window.y()))
        self._move_window(clamp_position(desired, self._pet_size(), area))

    def _advance_wander(self, now_ms: int, delta_seconds: float) -> None:
        target = self._wander_target
        area = self._wander_area
        if target is None or area is None or self._wander_direction == 0:
            self._wander_target = None
            self._wander_direction = 0
            self._resume_base_mode()
            return
        action = ActionId.RUN_RIGHT if self._wander_direction > 0 else ActionId.RUN_LEFT
        spec = ACTION_SPECS[action]
        adjusted_now = self._adjusted_animation_time(now_ms)
        frame_index = (
            (adjusted_now - self.timeline.started_ms) // spec.frame_ms
        ) % spec.frame_count
        self._show_frame(self.catalog.frames(action)[frame_index])

        speed = _MOVEMENT_SPEED.get(self._settings.movement_speed, 120.0)
        speed *= self._settings.scale_percent / 100.0
        current = Point(float(self.window.x()), float(self.window.y()))
        next_position = self.wander_planner.step_toward(
            current, target, speed * delta_seconds
        )
        next_position = clamp_position(next_position, self._pet_size(), area)
        self._move_window(next_position)
        if next_position == target or next_position == current:
            self._wander_target = None
            self._wander_direction = 0
            self.timeline.start(ActionId.IDLE, now_ms)
            if self._rng.random() < 0.35:
                self.trigger_action(self._rng.choice(_RANDOM_ACTIONS))
            else:
                self._schedule_wander()

    def _gaze_tick(self) -> None:
        cursor = QCursor.pos()
        self._refresh_hover_snapshot(cursor)
        if self._fixed_look_degrees is not None:
            return
        if not self._settings.gaze_enabled or self.behavior.mode not in {
            BehaviorMode.IDLE,
            BehaviorMode.GAZE,
        }:
            return
        center_x = self.window.x() + self.window.width() / 2
        center_y = self.window.y() + self.window.height() / 2
        direction = quantize_gaze(
            cursor.x() - center_x,
            cursor.y() - center_y,
            dead_zone=24 * self._settings.scale_percent / 100.0,
        )
        stable = self.gaze_stabilizer.update(direction, self._now_ms())
        self.behavior.request_gaze(stable)

    def _render_base(self, now_ms: int) -> None:
        if self._fixed_look_degrees is not None:
            self._show_frame(self.catalog.look_frame(self._fixed_look_degrees))
            return
        if self.behavior.mode is BehaviorMode.GAZE and self.behavior.gaze_degrees is not None:
            self._show_frame(self.catalog.look_frame(self.behavior.gaze_degrees))
            return
        step = self.timeline.advance(self._adjusted_animation_time(now_ms))
        if self.timeline.action is not ActionId.IDLE:
            self.timeline.start(ActionId.IDLE, now_ms)
            step = self.timeline.advance(now_ms)
        self._show_frame(self.catalog.frames(ActionId.IDLE)[step.frame_index])

    def _render_current_frame(self) -> None:
        self._displayed_frame = None
        if self.behavior.mode is BehaviorMode.MANUAL_ACTION and self.behavior.current_action:
            step = self.timeline.advance(self._now_ms())
            self._show_frame(self.catalog.frames(self.behavior.current_action)[step.frame_index])
        else:
            self._render_base(self._now_ms())

    def _resume_base_mode(self) -> None:
        now = self._now_ms()
        self.timeline.start(ActionId.IDLE, now)
        self._last_frame_index = None
        self._render_base(now)
        if self.behavior.mode is BehaviorMode.WANDER:
            self._schedule_wander()

    def _show_frame(self, frame: FrameAsset) -> None:
        identity = (frame.row, frame.column, self._settings.scale_percent)
        if self._displayed_frame != identity:
            self.window.set_frame(frame, self._settings.scale_percent)
            self._displayed_frame = identity
        self._refresh_hover_snapshot()

    def _schedule_wander(self) -> None:
        if (
            self._settings.wander_enabled
            and self.behavior.mode is BehaviorMode.WANDER
            and self._wander_target is None
            and not self._shut_down
        ):
            self.wander_timer.start(self._rng.randint(2_000, 6_000))

    def _begin_drag(self) -> None:
        self._wander_target = None
        self._wander_direction = 0
        self.wander_timer.stop()
        self.behavior.begin_drag()

    def _drag_to(self, target: QPoint) -> None:
        self.window.move(target)
        self._refresh_hover_snapshot()

    def _finish_drag(self, target: QPoint) -> None:
        self.window.move(target)
        area = self._current_screen_area()
        clamped = clamp_position(
            Point(float(self.window.x()), float(self.window.y())),
            self._pet_size(),
            area,
        )
        self._move_window(clamped)
        self.behavior.end_drag()
        self._schedule_wander()

    def _restore_position(self) -> None:
        screens, primary_name = self._screen_rectangles()
        _, position = restore_window_position(
            self._settings, screens, primary_name, self._pet_size()
        )
        self._move_window(position)

    def _save_window_position(self) -> None:
        screen = QGuiApplication.screenAt(
            QPoint(
                self.window.x() + self.window.width() // 2,
                self.window.y() + self.window.height() // 2,
            )
        ) or self.qapp.primaryScreen()
        if screen is None:
            return
        area = self._rect_from_qrect(screen.availableGeometry())
        relative_x = (
            (self.window.x() + self.window.width() / 2 - area.x) / area.width
            if area.width > 0
            else 0.5
        )
        relative_y = (
            (self.window.y() + self.window.height() / 2 - area.y) / area.height
            if area.height > 0
            else 0.5
        )
        screen_name = self._name_for_screen(screen)
        self._settings = replace(
            self._settings,
            screen_name=screen_name,
            relative_x=min(1.0, max(0.0, relative_x)),
            relative_y=min(1.0, max(0.0, relative_y)),
        )

    def _screen_rectangles(self) -> tuple[dict[str, Rect], str]:
        screens = {
            self._name_for_screen(screen): self._rect_from_qrect(
                screen.availableGeometry()
            )
            for screen in self.qapp.screens()
        }
        primary = self.qapp.primaryScreen()
        if not screens or primary is None:
            raise RuntimeError("no screen is available")
        return screens, self._name_for_screen(primary)

    def _name_for_screen(self, target: object) -> str:
        for index, screen in enumerate(self.qapp.screens()):
            if screen is target:
                return screen.name() or f"screen-{index}"
        name = getattr(target, "name", lambda: "")()
        return name or "screen-0"

    @staticmethod
    def _rect_from_qrect(rect: object) -> Rect:
        return Rect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()))

    def _current_screen_area(self) -> Rect:
        center = QPoint(
            self.window.x() + self.window.width() // 2,
            self.window.y() + self.window.height() // 2,
        )
        screen = QGuiApplication.screenAt(center) or self.qapp.primaryScreen()
        if screen is None:
            raise RuntimeError("no screen is available")
        return self._rect_from_qrect(screen.availableGeometry())

    def _screen_added(self, screen: object) -> None:
        self._connect_screen(screen)
        self._recover_window_visibility()

    def _screen_removed(self, screen: object) -> None:
        del screen
        QTimer.singleShot(0, self._recover_window_visibility)

    def _connect_screen(self, screen: object) -> None:
        screen.availableGeometryChanged.connect(self._recover_window_visibility)

    def _recover_window_visibility(self, *args: object) -> None:
        del args
        try:
            area = self._current_screen_area()
        except RuntimeError:
            return
        position = clamp_position(
            Point(float(self.window.x()), float(self.window.y())),
            self._pet_size(),
            area,
        )
        self._move_window(position)

    def _move_window(self, position: Point) -> None:
        self.window.move(round(position.x), round(position.y))
        self._refresh_hover_snapshot()

    def _pet_size(self) -> Size:
        scale = self._settings.scale_percent / 100.0
        return Size(CELL_WIDTH * scale, CELL_HEIGHT * scale)

    def _now_ms(self) -> int:
        return int(self._clock.elapsed())


def _default_data_root(environment_name: str) -> Path:
    value = os.environ.get(environment_name)
    if value:
        return Path(value)
    return Path.home() / "AppData" / ("Roaming" if environment_name == "APPDATA" else "Local")


def _default_settings_store() -> SettingsStore:
    return SettingsStore(_default_data_root("APPDATA") / "ShiyiDesktopPet" / "settings.ini")


def _default_startup_manager() -> StartupManager:
    return StartupManager(WinRegRunKey(), Path(sys.executable))


def _write_stdout(text: str) -> None:
    """Write JSON in console and PyInstaller windowed/inherited-pipe modes."""
    stream = sys.stdout
    if stream is not None:
        stream.write(text)
        stream.flush()
        return
    data = text.encode("utf-8")
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_std_handle = kernel32.GetStdHandle
        get_std_handle.argtypes = (ctypes.c_ulong,)
        get_std_handle.restype = ctypes.c_void_p
        write_file = kernel32.WriteFile
        write_file.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_void_p,
        )
        write_file.restype = ctypes.c_int
        handle = get_std_handle(ctypes.c_ulong(-11).value)
        if handle not in (None, ctypes.c_void_p(-1).value):
            written = ctypes.c_ulong()
            buffer = ctypes.create_string_buffer(data)
            if write_file(handle, buffer, len(data), ctypes.byref(written), None):
                return
    os.write(1, data)


def main(
    argv: list[str] | None = None,
    *,
    qapp: QApplication | None = None,
    guard_factory: Callable[[], SingleInstanceGuard] = SingleInstanceGuard,
    catalog_factory: Callable[[], AnimationCatalog] = AnimationCatalog.load_default,
    settings_store_factory: Callable[[], SettingsStore] = _default_settings_store,
    startup_manager_factory: Callable[[], StartupManager] = _default_startup_manager,
    hook_factory: Callable[..., object] = LowLevelKeyboardHook,
    tray_factory: Callable[..., object] = TrayController,
    critical_error: Callable[[str, str], object] | None = None,
    stdout_writer: Callable[[str], object] = _write_stdout,
    run_event_loop: bool = True,
) -> int:
    args = parse_args(argv)
    if args.self_test:
        try:
            report = run_self_test(catalog_factory)
            stdout_writer(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n")
            return 0 if report["ok"] else 1
        except Exception as error:
            stdout_writer(
                json.dumps(
                    {"ok": False, "error": f"{type(error).__name__}: {error}"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            return 1

    application = qapp or QApplication.instance() or QApplication([sys.argv[0]])
    application.setQuitOnLastWindowClosed(False)
    guard = guard_factory()
    command = "quit" if args.quit_existing else "activate"
    if not guard.acquire(command=command):
        guard.close()
        return 0
    if args.quit_existing:
        guard.close()
        return 0

    logger = configure_logging(_default_data_root("LOCALAPPDATA") / "ShiyiDesktopPet" / "logs")
    dialog = critical_error or (
        lambda title, message: QMessageBox.critical(None, title, message)
    )
    controller: DesktopPetApplication | None = None
    try:
        controller = DesktopPetApplication(
            application,
            settings_store=settings_store_factory(),
            startup_manager=startup_manager_factory(),
            catalog_factory=catalog_factory,
            hook_factory=hook_factory,
            tray_factory=tray_factory,
            logger=logger,
        )
    except Exception as error:
        logger.exception("Desktop-pet atlas or runtime construction failed")
        try:
            dialog("十一桌面宠物无法启动", f"资源加载失败：{error}")
        except Exception:
            logger.exception("Could not show startup failure dialog")
        finally:
            guard.close()
        return 1

    cleaned_up = False

    def cleanup() -> None:
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True
        controller.shutdown()
        guard.close()

    try:
        guard.command_received.connect(controller.handle_ipc_command)
        install_exception_hook(
            logger,
            hook_supplier=lambda: controller.hook,
            tray_supplier=lambda: controller.tray,
        )
        application.aboutToQuit.connect(cleanup)
        controller.start(startup=args.startup)
        if not run_event_loop:
            return 0
        return int(application.exec())
    finally:
        cleanup()
