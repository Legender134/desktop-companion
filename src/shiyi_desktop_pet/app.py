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

from PySide6.QtCore import QElapsedTimer, QPoint, QTimer, Qt, QUrl, qVersion
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication, QImage, QImageReader
from PySide6.QtWidgets import QApplication, QMessageBox

from .animation_catalog import AnimationCatalog
from .animation_player import AnimationTimeline
from .behavior import BehaviorEngine, BehaviorMode
from .constants import (
    CELL_HEIGHT,
    CELL_WIDTH,
    KEY_TO_ACTION,
)
from .gaze import GazeSmoother, cursor_angle
from .geometry import Point, Rect, Size, clamp_position
from .keyboard_hook import LowLevelKeyboardHook
from .logging_setup import configure_logging, install_exception_hook
from .menu_controller import MenuCommand, MenuController
from .models import (
    ActionId,
    ActionKey,
    ActionRole,
    AnimationSpec,
    FrameAsset,
    PetActionDefinition,
    PetStateDefinition,
)
from .pet_registry import PetDefinition, PetRegistry
from .pet_window import PetWindow
from .product import (
    APP_IDENTIFIER,
    DEFAULT_PET_ID,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    SETTINGS_DIRECTORY,
)
from .resource_locator import resource_root
from .settings import AppSettings, SettingsStore
from .single_instance import SingleInstanceGuard
from .startup import StartupManager, WinRegRunKey
from .tray_controller import TrayController
from .wander import WanderPlanner


_LOGGER = logging.getLogger(__name__)


def _configured_action_duration_ms(spec: AnimationSpec) -> int:
    """Return the configured duration of one finite action playback."""

    if spec.loops is None:
        raise ValueError("finite action duration requires a repeat count")
    return spec.cycle_ms * spec.loops + spec.hold_ms


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
_CURSOR_STILL_MS = 8_000
_AUTONOMOUS_MIN_DELAY_MS = 15_000
_AUTONOMOUS_MAX_DELAY_MS = 35_000
_WANDER_PROFILES: dict[str, tuple[int, int, float | None]] = {
    "quiet": (8_000, 18_000, 0.25),
    "standard": (2_000, 6_000, None),
    "active": (1_000, 3_000, None),
}


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
    parser = argparse.ArgumentParser(prog=APP_IDENTIFIER)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--self-test", action="store_true")
    modes.add_argument("--quit-existing", action="store_true")
    modes.add_argument("--startup", action="store_true")
    modes.add_argument("--qa-window", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def run_self_test(
    catalog_factory: Callable[[], AnimationCatalog] | None = None,
) -> dict[str, object]:
    """Decode and validate packaged resources plus the Qt WebP reader plugin."""
    if catalog_factory is not None:
        catalogs = [catalog_factory()]
    else:
        snapshot = PetRegistry(
            resource_root() / "pets",
            None,
        ).refresh()
        if snapshot.issues:
            raise ValueError(snapshot.issues[0].message)
        catalogs = [AnimationCatalog.load_definition(pet) for pet in snapshot.pets]
    frame_counts = [
        sum(len(catalog.frames(action)) for action in catalog.action_ids)
        + (len(catalog.look_degrees) if catalog.sprite_version == 2 else 0)
        for catalog in catalogs
    ]
    formats = {bytes(item).lower() for item in QImageReader.supportedImageFormats()}
    primary_index = next(
        (
            index
            for index, catalog in enumerate(catalogs)
            if catalog.pet_id == DEFAULT_PET_ID
        ),
        0,
    )
    primary_catalog = catalogs[primary_index]
    primary_width, primary_height = primary_catalog.atlas_size
    return {
        "ok": all(count >= 4 for count in frame_counts) and b"webp" in formats,
        "qt": qVersion(),
        "atlas": {
            "width": primary_width,
            "height": primary_height,
            "frames": frame_counts[primary_index],
        },
        "webp_plugin": b"webp" in formats,
        "pets": [catalog.pet_id for catalog in catalogs],
    }


class DesktopPetApplication:
    """Own Qt UI, behavior timers, input hook, persistence, and cleanup."""

    def __init__(
        self,
        qapp: QApplication,
        *,
        settings_store: SettingsStore,
        startup_manager: StartupManager,
        catalog_factory: Callable[[], AnimationCatalog] | None = None,
        catalog_loader: Callable[[PetDefinition], AnimationCatalog] = (
            AnimationCatalog.load_definition
        ),
        hook_factory: Callable[..., object] = LowLevelKeyboardHook,
        tray_factory: Callable[..., object] = TrayController,
        random: Random | None = None,
        logger: logging.Logger | None = None,
        window_factory: Callable[[AnimationCatalog], PetWindow] = PetWindow,
        about_dialog: Callable[[object, str, str], object] = QMessageBox.about,
        qa_window: bool = False,
        pet_registry: PetRegistry | None = None,
        open_pet_directory: Callable[[Path], object] | None = None,
    ) -> None:
        self.qapp = qapp
        self.logger = logger or _LOGGER
        self.settings_store = settings_store
        self.startup_manager = startup_manager
        self._settings = settings_store.load()
        self._catalog_loader = catalog_loader
        self.pet_registry = pet_registry or PetRegistry(
            resource_root() / "pets",
            _default_data_root("APPDATA") / SETTINGS_DIRECTORY / "pets",
            validator=self._catalog_loader,
            logger=self.logger,
        )
        self._pet_snapshot = self.pet_registry.refresh()
        selected_pet = self._pet_snapshot.by_id(self._settings.pet_id)
        if selected_pet is None:
            selected_pet = self._pet_snapshot.by_id(DEFAULT_PET_ID)
            if selected_pet is None and self._pet_snapshot.pets:
                selected_pet = self._pet_snapshot.pets[0]
            if selected_pet is None:
                raise ValueError("no valid desktop-pet packs are available")
            self._settings = replace(self._settings, pet_id=selected_pet.pet_id)
            self.settings_store.save(self._settings)
        self._open_pet_directory = open_pet_directory or (
            lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        )
        self.catalog = (
            catalog_factory()
            if catalog_factory is not None
            else self._catalog_loader(selected_pet)
        )
        self._session_hover_digits_enabled = self._settings.hover_digits_enabled
        self._hook_available = True
        self._hook_notification_shown = False
        self._rng = random or Random()
        self._about_dialog = about_dialog
        self.behavior = BehaviorEngine(wander_enabled=self._settings.wander_enabled)
        self.timeline = AnimationTimeline()
        self.wander_planner = WanderPlanner(self._rng)
        self.gaze_smoother = GazeSmoother()
        self.window = window_factory(self.catalog)
        if qa_window:
            window_flags = self.window.windowFlags()
            window_flags &= ~Qt.WindowType.WindowType_Mask
            self.window.setWindowFlags(window_flags | Qt.WindowType.Window)
            self.window.setWindowTitle(f"{APP_IDENTIFIER} QA")
        self.window.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint, self._settings.always_on_top
        )
        self._hover_snapshot = _EMPTY_HOVER_SNAPSHOT
        self._alpha_cache: dict[tuple[int, int, str], tuple[bytes, int]] = {}
        self._displayed_frame: tuple[int, int, str, int] | None = None
        self._started = False
        self._shut_down = False
        self._wander_target: Point | None = None
        self._wander_direction = 0
        self._wander_area: Rect | None = None
        self._wander_action: ActionKey | None = None
        self._wander_start: Point | None = None
        self._manual_burst_start: Point | None = None
        self._manual_burst_target: Point | None = None
        self._fixed_look_degrees: float | None = None
        self._last_frame_index: int | None = None
        self._last_tick_ms = 0
        self._last_random_action: ActionKey | None = None
        self._last_random_group: str | None = None
        self._last_action_played_ms: dict[ActionKey, int] = {}
        self._showcase_active = False
        self._showcase_queue: list[ActionKey] = []
        self._active_state: PetStateDefinition | None = None
        self._state_phase: str | None = None
        self._state_active_started_ms: int | None = None
        self._state_last_action: ActionKey | None = None
        self._state_exit_requested = False

        self._clock = QElapsedTimer()
        self._clock.start()
        self._last_cursor_position = QCursor.pos()
        self._last_cursor_move_ms = self._now_ms()
        self._live_gaze_active = False
        self._autonomous_not_before_ms = 0
        self.timeline.start(self.catalog.idle_action, self._now_ms())

        self.menu_controller = MenuController(
            lambda: self.settings,
            self.startup_manager.is_enabled,
            self.dispatch_menu,
            self.logger,
            pet_choices_supplier=lambda: self.pet_choices,
            action_items_supplier=self._action_menu_items,
            look_degrees_supplier=lambda: tuple(self.catalog.manual_look_degrees),
            action_details_supplier=self._action_menu_details,
            gaze_frame_count_supplier=lambda: len(self.catalog.look_degrees),
            shortcut_labels_supplier=lambda: self.catalog.digit_shortcut_labels(),
        )
        self.body_menu = self.menu_controller.create_menu(self.window)
        self.tray = tray_factory(self.window, self.menu_controller)
        self.tray.set_companion_icon(
            self.catalog.icon_image(), self.catalog.display_name
        )
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
        self.autonomous_timer = QTimer(self.window)
        self.autonomous_timer.setSingleShot(True)
        self.autonomous_timer.timeout.connect(self._autonomous_timeout)

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

        initial = self.catalog.frames(self.catalog.idle_action)[0]
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
    def pet_choices(self) -> tuple[tuple[str, str], ...]:
        return self._pet_snapshot.choices

    @property
    def wander_target(self) -> Point | None:
        return self._wander_target

    @property
    def current_action(self) -> ActionKey:
        if self.behavior.current_action is not None:
            return self.behavior.current_action
        if self._wander_target is not None and self._wander_action is not None:
            return self._wander_action
        return self.catalog.idle_action

    def start(self, *, startup: bool = False) -> None:
        if self._started or self._shut_down:
            return
        self._started = True
        self.tray.show()
        if self._pet_snapshot.issues:
            self.tray.show_message(
                PRODUCT_NAME,
                f"已忽略 {len(self._pet_snapshot.issues)} 个无效宠物包。",
            )
        if startup:
            attribute = Qt.WidgetAttribute.WA_ShowWithoutActivating
            previous = self.window.testAttribute(attribute)
            self.window.setAttribute(attribute, True)
            try:
                self.window.show()
            finally:
                self.window.setAttribute(attribute, previous)
        else:
            self.window.show()
            self.window.raise_()
        self._refresh_hover_snapshot()
        self.animation_timer.start()
        self.gaze_timer.start()
        self._schedule_wander()
        self._schedule_autonomous()
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
        self.autonomous_timer.stop()
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

    def trigger_action(self, action: ActionKey) -> None:
        if action is ActionId.RANDOM:
            action = self._choose_random_action()
        else:
            action = self.catalog.resolve_action(action)
        self._cancel_showcase()
        self._play_action(action, defer_autonomous=True)

    def _play_action(self, action: ActionKey, *, defer_autonomous: bool) -> None:
        if action not in self.catalog.action_ids:
            raise ValueError(f"unsupported action: {action}")
        state = self.catalog.state_for_enter_action(action)
        if self._active_state is not None:
            if state is not None and state.key == self._active_state.key:
                self._request_state_exit()
                return
            self._cancel_active_state()
        if state is not None:
            self._start_state(state, defer_autonomous=defer_autonomous)
            return
        definition = self.catalog.definition(action)
        if (
            definition.role is ActionRole.BURST_MOVE
            and definition.travel_distance_ratio is not None
        ):
            action = self._resolve_manual_burst_action(definition)
            definition = self.catalog.definition(action)
        self.autonomous_timer.stop()
        if defer_autonomous:
            self._defer_autonomous()
        self._fixed_look_degrees = None
        self._interrupt_wander(reschedule=False)
        self.behavior.trigger_manual(action)
        self.timeline.start(action, self._now_ms())
        self._last_action_played_ms[action] = self._now_ms()
        self._last_frame_index = None
        self._manual_burst_start = None
        self._manual_burst_target = None
        if definition.role is ActionRole.BURST_MOVE:
            self._prepare_manual_burst(definition)
        if definition.role is ActionRole.IDLE:
            self.behavior.manual_finished()
            self._resume_base_mode()

    @property
    def active_state(self) -> PetStateDefinition | None:
        return self._active_state

    def _action_menu_items(self) -> tuple[tuple[str, ActionKey], ...]:
        items = list(self.catalog.action_menu_items())
        state = self._active_state
        if state is None:
            return tuple(items)
        replacement = (
            f"正在结束{state.label}"
            if self._state_exit_requested
            else f"结束{state.label}"
        )
        return tuple(
            (replacement if action == state.enter_action else label, action)
            for label, action in items
        )

    def _action_menu_details(self) -> dict[ActionKey, str]:
        details = self.catalog.action_menu_details()
        state = self._active_state
        if state is None:
            return details
        if self._state_exit_requested:
            details[state.enter_action] = (
                f"“{state.label}”已收到结束请求。为避免人物从半个动作突然跳到起身姿势，"
                "程序会先播放完当前坐姿小动作，再接专用起身动画并恢复待机、注视或闲逛。"
            )
        else:
            details[state.enter_action] = (
                f"结束当前“{state.label}”状态。程序会让正在播放的坐姿小动作自然收尾，"
                "随后播放专用起身动画；通常只需等待当前小动作剩余的几秒，不会等到自动"
                f"上限 {state.max_duration_ms / 1000:g} 秒。"
            )
        return details

    def _start_state(
        self, state: PetStateDefinition, *, defer_autonomous: bool
    ) -> None:
        self.autonomous_timer.stop()
        if defer_autonomous:
            self._defer_autonomous()
        self._fixed_look_degrees = None
        self._interrupt_wander(reschedule=False)
        self._active_state = state
        self._state_phase = "enter"
        self._state_active_started_ms = None
        self._state_last_action = None
        self._state_exit_requested = False
        self._play_state_action(state.enter_action)
        self._last_action_played_ms[state.enter_action] = self._now_ms()

    def _play_state_action(self, action: ActionKey) -> None:
        self.behavior.trigger_manual(action)
        self.timeline.start(action, self._now_ms())
        self._last_frame_index = None
        self._manual_burst_start = None
        self._manual_burst_target = None

    def _request_state_exit(self) -> None:
        if self._active_state is None or self._state_phase == "exit":
            return
        self._state_exit_requested = True

    def _cancel_active_state(self) -> bool:
        if self._active_state is None:
            return False
        self._active_state = None
        self._state_phase = None
        self._state_active_started_ms = None
        self._state_last_action = None
        self._state_exit_requested = False
        if self.behavior.current_action is not None:
            self.behavior.manual_finished()
        self._manual_burst_start = None
        self._manual_burst_target = None
        return True

    def _choose_state_action(self, state: PetStateDefinition) -> ActionKey:
        weighted = list(state.resident_actions)
        if len(weighted) > 1 and self._state_last_action is not None:
            without_repeat = [
                choice
                for choice in weighted
                if choice.action_id != self._state_last_action
            ]
            if without_repeat:
                weighted = without_repeat
        target = self._rng.randint(1, sum(choice.weight for choice in weighted))
        for choice in weighted:
            target -= choice.weight
            if target <= 0:
                self._state_last_action = choice.action_id
                return choice.action_id
        raise RuntimeError("could not choose a resident state action")

    def _state_should_exit(self, state: PetStateDefinition, now_ms: int) -> bool:
        started = self._state_active_started_ms
        if started is None:
            return False
        elapsed = max(0, now_ms - started)
        if elapsed < state.min_duration_ms:
            return False
        if elapsed >= state.max_duration_ms:
            return True
        ramp_end = state.min_duration_ms + state.ramp_duration_ms
        if state.ramp_duration_ms == 0 or elapsed >= ramp_end:
            chance = state.exit_chance_after_ramp
        else:
            progress = (elapsed - state.min_duration_ms) / state.ramp_duration_ms
            chance = round(
                state.exit_chance_after_min
                + (state.exit_chance_after_ramp - state.exit_chance_after_min)
                * progress
            )
        return chance > 0 and self._rng.randint(1, 100) <= chance

    def _play_next_state_resident_or_exit(
        self, state: PetStateDefinition, now_ms: int
    ) -> None:
        candidate = self._choose_state_action(state)
        started = self._state_active_started_ms
        elapsed = max(0, now_ms - started) if started is not None else 0
        candidate_duration = math.ceil(
            _configured_action_duration_ms(self.catalog.spec(candidate))
            * self._animation_speed_multiplier()
        )
        if elapsed + candidate_duration > state.max_duration_ms:
            self._state_phase = "exit"
            self._play_state_action(state.exit_action)
            return
        self._state_phase = "resident"
        self._play_state_action(candidate)

    def _advance_active_state(self, now_ms: int) -> None:
        state = self._active_state
        action = self.behavior.current_action
        if state is None or action is None:
            self._cancel_active_state()
            self._resume_base_mode()
            return
        spec = self.catalog.spec(action)
        step = self.timeline.advance(self._adjusted_animation_time(now_ms), spec)
        self._show_frame(self.catalog.frames(action)[step.frame_index])
        if not step.finished:
            return
        if self._state_phase == "enter":
            self._state_active_started_ms = now_ms
            if self._state_exit_requested:
                self._state_phase = "exit"
                self._play_state_action(state.exit_action)
            else:
                self._play_next_state_resident_or_exit(state, now_ms)
            return
        if self._state_phase == "resident":
            if self._state_exit_requested or self._state_should_exit(state, now_ms):
                self._state_phase = "exit"
                self._play_state_action(state.exit_action)
            else:
                self._play_next_state_resident_or_exit(state, now_ms)
            return
        if self._state_phase == "exit":
            self._cancel_active_state()
            self._resume_base_mode()
            return
        raise RuntimeError("active pet state has an invalid phase")

    def _choose_wander_action(self, direction: int, distance: float) -> ActionKey:
        now_ms = self._now_ms()
        weighted: list[tuple[ActionKey, int]] = []
        normal_fallbacks: list[PetActionDefinition] = []
        for definition in self.catalog.movement_actions(direction):
            if definition.role is ActionRole.BURST_MOVE:
                if definition.autoplay_weight <= 0 or distance < definition.min_distance:
                    continue
                last_played = self._last_action_played_ms.get(definition.action_id)
                if (
                    last_played is not None
                    and now_ms - last_played < definition.cooldown_ms
                ):
                    continue
                weight = definition.autoplay_weight
            else:
                normal_fallbacks.append(definition)
                last_played = self._last_action_played_ms.get(definition.action_id)
                if definition.autoplay_weight <= 0 or (
                    last_played is not None
                    and now_ms - last_played < definition.cooldown_ms
                ):
                    continue
                weight = definition.autoplay_weight
            weighted.append((definition.action_id, weight))
        if not any(
            self.catalog.definition(action).role is ActionRole.MOVE
            for action, _ in weighted
        ) and normal_fallbacks:
            weighted.insert(0, (normal_fallbacks[0].action_id, 1))
        if not weighted:
            raise RuntimeError("pet has no usable movement action")
        target = self._rng.randint(1, sum(weight for _, weight in weighted))
        for action, weight in weighted:
            target -= weight
            if target <= 0:
                return action
        raise RuntimeError("could not choose a movement action")

    def _choose_ratio_wander_plan(
        self, current: Point, target: Point, direction: int, area: Rect
    ) -> tuple[ActionKey, Point, int] | None:
        pet = self._pet_size()
        min_x = area.x
        max_x = max(area.x, area.x + area.width - pet.width)
        usable_width = max(0.0, max_x - min_x)
        if usable_width <= 0:
            return None

        now_ms = self._now_ms()
        burst: PetActionDefinition | None = None
        for candidate_direction in (direction, -direction):
            room = (
                max_x - current.x
                if candidate_direction > 0
                else current.x - min_x
            )
            for definition in self.catalog.movement_actions(candidate_direction):
                ratio = definition.travel_distance_ratio
                if (
                    definition.role is not ActionRole.BURST_MOVE
                    or ratio is None
                    or definition.autoplay_weight <= 0
                    or usable_width * ratio < definition.min_distance
                    or room + 0.001 < usable_width * ratio
                ):
                    continue
                last_played = self._last_action_played_ms.get(definition.action_id)
                if (
                    last_played is not None
                    and now_ms - last_played < definition.cooldown_ms
                ):
                    continue
                burst = definition
                break
            if burst is not None:
                break
        if burst is None:
            return None

        normal_definitions = list(
            self.catalog.movement_actions(direction, include_burst=False)
        )
        if not normal_definitions:
            return None
        normal = normal_definitions[0]
        normal_weight = max(1, normal.autoplay_weight)
        total_weight = normal_weight + burst.autoplay_weight
        if self._rng.randint(1, total_weight) <= normal_weight:
            return normal.action_id, target, direction

        ratio = burst.travel_distance_ratio
        assert ratio is not None
        distance = usable_width * ratio
        target_x = current.x + burst.direction * distance
        target_y = target.y
        if burst.max_vertical_ratio is not None:
            min_y = area.y
            max_y = max(area.y, area.y + area.height - pet.height)
            usable_height = max(0.0, max_y - min_y)
            max_delta_y = usable_height * burst.max_vertical_ratio
            delta_y = min(max_delta_y, max(-max_delta_y, target.y - current.y))
            target_y = current.y + delta_y
        planned = clamp_position(Point(target_x, target_y), pet, area)
        return burst.action_id, planned, burst.direction

    def start_showcase(self) -> None:
        self._cancel_showcase()
        self._cancel_active_state()
        self._showcase_active = True
        self._showcase_queue = list(self.catalog.showcase_actions())
        self._defer_autonomous()
        self._play_next_showcase_action()

    def _play_next_showcase_action(self) -> None:
        if self._showcase_queue:
            action = self._showcase_queue.pop(0)
            self._play_action(action, defer_autonomous=False)
            return
        self._showcase_active = False
        self.behavior.manual_finished()
        self._resume_base_mode()

    def _cancel_showcase(self) -> None:
        self._showcase_active = False
        self._showcase_queue.clear()

    def begin_wander(self) -> None:
        if self.behavior.mode is not BehaviorMode.WANDER or self._shut_down:
            return
        area = self._current_screen_area()
        self._fixed_look_degrees = None
        current = Point(float(self.window.x()), float(self.window.y()))
        pet_size = self._pet_size()
        _minimum_delay, _maximum_delay, distance_ratio = _WANDER_PROFILES.get(
            self._settings.wander_intensity,
            _WANDER_PROFILES["standard"],
        )
        max_distance = (
            None
            if distance_ratio is None
            else max(0.0, area.width - pet_size.width) * distance_ratio
        )
        target = self.wander_planner.choose_target(
            current,
            pet_size,
            area,
            max_distance=max_distance,
        )
        if target.direction == 0:
            self._wander_target = None
            self._wander_direction = 0
            self._wander_area = None
            self._wander_action = None
            self._wander_start = None
            self.timeline.start(self.catalog.idle_action, self._now_ms())
            self._show_frame(self.catalog.frames(self.catalog.idle_action)[0])
            self._schedule_wander()
            return
        distance = math.hypot(
            target.position.x - current.x, target.position.y - current.y
        )
        plan = self._choose_ratio_wander_plan(
            current, target.position, target.direction, area
        )
        if plan is None:
            action = self._choose_wander_action(target.direction, distance)
            planned_target = target.position
            planned_direction = target.direction
        else:
            action, planned_target, planned_direction = plan
        self._wander_target = planned_target
        self._wander_direction = planned_direction
        self._wander_area = area
        self._wander_start = current
        self._wander_action = action
        self.timeline.start(action, self._now_ms())
        self._last_action_played_ms[action] = self._now_ms()
        self._last_frame_index = None

    def dispatch_menu(self, command: MenuCommand) -> None:
        self._interrupt_wander(reschedule=False)
        try:
            self._dispatch_menu_command(command)
        finally:
            self._schedule_wander()
            self._schedule_autonomous()

    def _dispatch_menu_command(self, command: MenuCommand) -> None:
        kind = command.kind
        if kind == "action":
            self.trigger_action(command.value)
            return
        if kind == "look":
            if not self.catalog.supports_gaze:
                return
            self._cancel_active_state()
            degrees = float(command.value)
            self._wander_target = None
            self._wander_direction = 0
            self._wander_area = None
            self.wander_timer.stop()
            self._fixed_look_degrees = degrees
            self.behavior.request_gaze(degrees)
            self._show_frame(self.catalog.look_frame(degrees))
            return
        if kind == "showcase":
            self.start_showcase()
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
        if kind == "pet":
            self._switch_pet(str(command.value))
            return
        if kind == "refresh_pets":
            self._refresh_pets(notify=True)
            return
        if kind == "open_pets_directory":
            self._open_user_pet_directory()
            return
        if kind == "animation_speed":
            self._settings = replace(self._settings, animation_speed=str(command.value))
            return
        if kind == "movement_speed":
            self._settings = replace(self._settings, movement_speed=str(command.value))
            return
        if kind == "wander_intensity":
            value = str(command.value)
            if value not in _WANDER_PROFILES:
                raise ValueError(f"unsupported wander intensity: {value}")
            self._settings = replace(self._settings, wander_intensity=value)
            return
        if kind == "gaze_mode":
            value = str(command.value)
            if value not in {"active", "always"}:
                raise ValueError(f"unsupported gaze mode: {value}")
            self._settings = replace(self._settings, gaze_mode=value)
            self._last_cursor_position = QCursor.pos()
            self._last_cursor_move_ms = self._now_ms()
            self._live_gaze_active = False
            self.gaze_smoother.reset()
            return
        if kind == "center":
            self.center_on_cursor_screen()
            return
        if kind == "about":
            names = "、".join(display_name for _, display_name in self.pet_choices)
            self._about_dialog(
                self.window,
                f"关于{PRODUCT_NAME}",
                f"{PRODUCT_NAME} {PRODUCT_VERSION}\n"
                f"可用宠物：{len(self.pet_choices)}（{names}）",
            )
            return
        if kind == "quit":
            self.request_quit()
            return
        raise ValueError(f"unsupported menu command: {kind}")

    def _switch_pet(self, pet_id: str, *, force: bool = False) -> None:
        definition = self._pet_snapshot.by_id(pet_id)
        if definition is None:
            raise ValueError(f"unknown pet: {pet_id}")
        if not force and pet_id == self._settings.pet_id and self.catalog.pet_id == pet_id:
            return
        catalog = self._catalog_loader(definition)
        self._cancel_active_state()
        self.catalog = catalog
        self._fixed_look_degrees = None
        self._live_gaze_active = False
        self.gaze_smoother.reset()
        self.behavior.request_gaze(None)
        self._cancel_showcase()
        if self.behavior.current_action is not None:
            self.behavior.manual_finished()
        self._interrupt_wander(reschedule=False)
        self.window.set_catalog(catalog)
        self.tray.set_companion_icon(catalog.icon_image(), catalog.display_name)
        self._settings = replace(self._settings, pet_id=pet_id)
        self._alpha_cache.clear()
        self._displayed_frame = None
        self._last_random_action = None
        self._last_random_group = None
        self._last_action_played_ms.clear()
        self.timeline.start(self.catalog.idle_action, self._now_ms())
        self._render_current_frame()
        self._recover_window_visibility()
        self.settings_store.save(self._settings)

    def _refresh_pets(self, *, notify: bool) -> None:
        snapshot = self.pet_registry.refresh()
        if not snapshot.pets:
            if notify:
                self.tray.show_message(PRODUCT_NAME, "没有发现可用宠物，继续使用当前宠物。")
            return
        self._pet_snapshot = snapshot
        selected = snapshot.by_id(self._settings.pet_id)
        if selected is None:
            fallback = snapshot.by_id(DEFAULT_PET_ID) or snapshot.pets[0]
            self._switch_pet(fallback.pet_id)
        else:
            self._switch_pet(selected.pet_id, force=True)
        if notify:
            message = f"已发现 {len(snapshot.pets)} 只可用宠物。"
            if snapshot.issues:
                message += f" 已忽略 {len(snapshot.issues)} 个无效宠物包。"
            self.tray.show_message(PRODUCT_NAME, message)

    def _open_user_pet_directory(self) -> None:
        root = self.pet_registry.user_root
        if root is None:
            self.tray.show_message(PRODUCT_NAME, "当前版本没有可写的用户宠物目录。")
            return
        root.mkdir(parents=True, exist_ok=True)
        if self._open_pet_directory(root) is False:
            self.tray.show_message(PRODUCT_NAME, "无法打开宠物目录。")

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
            "autonomous_actions_enabled",
            "hover_digits_enabled",
            "always_on_top",
            "menu_details_enabled",
        }:
            raise ValueError(f"unsupported setting toggle: {target}")
        self._settings = replace(self._settings, **{target: enabled})
        if target == "wander_enabled":
            self.behavior.set_wander_enabled(enabled)
            self._wander_target = None
            self._wander_direction = 0
            self._wander_area = None
            self._wander_action = None
            self._wander_start = None
            if enabled:
                self._schedule_wander()
            else:
                self.wander_timer.stop()
        elif target == "gaze_enabled":
            self._last_cursor_position = QCursor.pos()
            self._last_cursor_move_ms = self._now_ms()
            self._live_gaze_active = False
            self.gaze_smoother.reset()
            if not enabled:
                self.behavior.request_gaze(None)
        elif target == "autonomous_actions_enabled" and not enabled:
            self.autonomous_timer.stop()
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
        self._schedule_autonomous()

    def _digit_pressed(self, digit: int) -> None:
        if digit not in KEY_TO_ACTION:
            raise ValueError(f"unsupported digit: {digit}")
        self.trigger_action(KEY_TO_ACTION[digit])

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
                    PRODUCT_NAME,
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
        key = (frame.row, frame.column, frame.variant)
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
        if self._fixed_look_degrees is not None and self.catalog.supports_gaze:
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
        if self._active_state is not None:
            self._advance_active_state(now_ms)
            return
        action = self.behavior.current_action
        if action is None:
            self._resume_base_mode()
            return
        spec = self.catalog.spec(action)
        definition = self.catalog.definition(action)
        playback_spec = (
            replace(spec, loops=1)
            if definition.role is ActionRole.MOVE and spec.loops is None
            else spec
        )
        adjusted_now = self._adjusted_animation_time(now_ms)
        step = self.timeline.advance(adjusted_now, playback_spec)
        frames = self.catalog.frames(action)
        self._show_frame(frames[step.frame_index])
        if definition.role is ActionRole.BURST_MOVE:
            self._advance_manual_burst(adjusted_now, definition)
        elif step.frame_index != self._last_frame_index:
            self._last_frame_index = step.frame_index
            if definition.role is ActionRole.MOVE and definition.direction:
                self._manual_move(definition.direction)
        if step.finished:
            if self._manual_burst_target is not None:
                self._move_window(self._manual_burst_target)
            self._manual_burst_start = None
            self._manual_burst_target = None
            if self._showcase_active:
                self._play_next_showcase_action()
                return
            self.behavior.manual_finished()
            self._resume_base_mode()

    def _animation_speed_multiplier(self) -> float:
        return _ANIMATION_SPEED.get(self._settings.animation_speed, 1.0)

    def _adjusted_animation_time(self, now_ms: int) -> int:
        elapsed = max(0, now_ms - self.timeline.started_ms)
        return self.timeline.started_ms + round(
            elapsed / self._animation_speed_multiplier()
        )

    def _manual_move(self, direction: int) -> None:
        area = self._current_screen_area()
        distance = 12.0 * self._settings.scale_percent / 100.0
        desired = Point(self.window.x() + direction * distance, float(self.window.y()))
        self._move_window(clamp_position(desired, self._pet_size(), area))

    def _resolve_manual_burst_action(
        self, definition: PetActionDefinition
    ) -> ActionKey:
        ratio = definition.travel_distance_ratio
        if ratio is None:
            return definition.action_id
        area = self._current_screen_area()
        pet = self._pet_size()
        start = clamp_position(
            Point(float(self.window.x()), float(self.window.y())), pet, area
        )
        min_x = area.x
        max_x = max(area.x, area.x + area.width - pet.width)
        usable_width = max(0.0, max_x - min_x)
        preferred_distance = usable_width * ratio
        requested_room = (
            max_x - start.x if definition.direction > 0 else start.x - min_x
        )
        minimum_visible_distance = min(
            preferred_distance,
            max(pet.width * 2.0, preferred_distance * 0.25),
        )
        if requested_room + 0.001 >= minimum_visible_distance:
            return definition.action_id

        for candidate in self.catalog.movement_actions(-definition.direction):
            if (
                candidate.role is ActionRole.BURST_MOVE
                and candidate.travel_distance_ratio is not None
            ):
                return candidate.action_id
        return definition.action_id

    def _prepare_manual_burst(self, definition: PetActionDefinition) -> None:
        area = self._current_screen_area()
        pet = self._pet_size()
        start = clamp_position(
            Point(float(self.window.x()), float(self.window.y())), pet, area
        )
        if definition.travel_distance_ratio is not None:
            min_x = area.x
            max_x = max(area.x, area.x + area.width - pet.width)
            usable_width = max(0.0, max_x - min_x)
            requested = usable_width * definition.travel_distance_ratio
            room = max_x - start.x if definition.direction > 0 else start.x - min_x
            distance = min(requested, max(0.0, room))
        else:
            distance = max(320.0, float(definition.min_distance))
            distance *= self._settings.scale_percent / 100.0
        desired = Point(start.x + definition.direction * distance, start.y)
        self._manual_burst_start = start
        self._manual_burst_target = clamp_position(desired, self._pet_size(), area)

    def _advance_manual_burst(
        self, adjusted_now: int, definition: PetActionDefinition
    ) -> None:
        start = self._manual_burst_start
        target = self._manual_burst_target
        if start is None or target is None:
            return
        progress = self._burst_progress(adjusted_now, definition)
        self._move_window(self._interpolate_position(start, target, progress))

    def _advance_wander(self, now_ms: int, delta_seconds: float) -> None:
        target = self._wander_target
        area = self._wander_area
        action = self._wander_action
        if (
            target is None
            or area is None
            or action is None
            or self._wander_direction == 0
        ):
            self._interrupt_wander(reschedule=True)
            return
        definition = self.catalog.definition(action)
        spec = self.catalog.spec(action)
        adjusted_now = self._adjusted_animation_time(now_ms)
        elapsed = max(0, adjusted_now - self.timeline.started_ms)
        frame_index = spec.frame_index_at(elapsed)
        self._show_frame(self.catalog.frames(action)[frame_index])

        current = Point(float(self.window.x()), float(self.window.y()))
        if definition.role is ActionRole.BURST_MOVE:
            start = self._wander_start or current
            progress = self._burst_progress(adjusted_now, definition)
            next_position = self._interpolate_position(start, target, progress)
        else:
            speed = _MOVEMENT_SPEED.get(self._settings.movement_speed, 120.0)
            speed *= self._settings.scale_percent / 100.0
            next_position = self.wander_planner.step_toward(
                current, target, speed * delta_seconds
            )
        next_position = clamp_position(next_position, self._pet_size(), area)
        self._move_window(next_position)
        burst_finished = (
            definition.role is ActionRole.BURST_MOVE
            and self.timeline.advance(adjusted_now, spec).finished
        )
        stalled_normal_move = (
            definition.role is not ActionRole.BURST_MOVE
            and next_position == current
        )
        reached_normal_target = (
            definition.role is not ActionRole.BURST_MOVE
            and next_position == target
        )
        if reached_normal_target or stalled_normal_move or burst_finished:
            self._finish_wander(now_ms, target)

    def _finish_wander(self, now_ms: int, target: Point) -> None:
        self._move_window(target)
        self._wander_target = None
        self._wander_direction = 0
        self._wander_area = None
        self._wander_action = None
        self._wander_start = None
        self.timeline.start(self.catalog.idle_action, now_ms)
        if self._rng.random() < 0.35:
            self.trigger_action(ActionId.RANDOM)
        else:
            self._schedule_wander()

    def _burst_progress(
        self, adjusted_now: int, definition: PetActionDefinition
    ) -> float:
        spec = self.catalog.spec(definition.action_id)
        start_frame = definition.travel_start_frame or 0
        end_frame = definition.travel_end_frame or spec.frame_count - 1
        start_ms = spec.frame_start_ms(start_frame)
        end_ms = spec.frame_start_ms(end_frame)
        elapsed = max(0, adjusted_now - self.timeline.started_ms)
        if end_ms <= start_ms:
            return 1.0
        linear = min(1.0, max(0.0, (elapsed - start_ms) / (end_ms - start_ms)))
        return linear * linear * (3.0 - 2.0 * linear)

    @staticmethod
    def _interpolate_position(start: Point, target: Point, progress: float) -> Point:
        return Point(
            start.x + (target.x - start.x) * progress,
            start.y + (target.y - start.y) * progress,
        )

    def _gaze_tick(self) -> None:
        now_ms = self._now_ms()
        cursor = QCursor.pos()
        self._refresh_hover_snapshot(cursor)
        cursor_moved = cursor != self._last_cursor_position
        if cursor_moved:
            self._last_cursor_position = QPoint(cursor)
            self._last_cursor_move_ms = now_ms
            if self._gaze_delays_autonomous():
                self._schedule_autonomous()
        if self._fixed_look_degrees is not None:
            return
        if not self.catalog.supports_gaze or not self._settings.gaze_enabled:
            self._live_gaze_active = False
            self.gaze_smoother.reset()
            self.behavior.request_gaze(None)
            return

        gaze_active = (
            self._settings.gaze_mode == "always"
            or now_ms - self._last_cursor_move_ms < _CURSOR_STILL_MS
        )
        if not gaze_active:
            if self._live_gaze_active or self.behavior.gaze_degrees is not None:
                self._live_gaze_active = False
                self.gaze_smoother.reset()
                self.behavior.request_gaze(None)
                self.timeline.start(self.catalog.idle_action, now_ms)
                self._render_current_frame()
                self._schedule_wander()
                self._schedule_autonomous()
            return
        if self.behavior.mode in {
            BehaviorMode.MANUAL_ACTION,
            BehaviorMode.DRAGGING,
            BehaviorMode.SHUTTING_DOWN,
        }:
            return

        activating_gaze = not self._live_gaze_active
        if (cursor_moved or activating_gaze) and (
            self.behavior.mode is BehaviorMode.WANDER
            or self._wander_target is not None
            or self.wander_timer.isActive()
        ):
            self._interrupt_wander(reschedule=False)
        self._live_gaze_active = True
        center_x = self.window.x() + self.window.width() / 2
        center_y = self.window.y() + self.window.height() / 2
        direction = cursor_angle(
            cursor.x() - center_x,
            cursor.y() - center_y,
            dead_zone=24 * self._settings.scale_percent / 100.0,
        )
        smoothed = self.gaze_smoother.update(direction, now_ms)
        self.behavior.request_gaze(0.0 if smoothed is None else smoothed)

    def _render_base(self, now_ms: int) -> None:
        if self._fixed_look_degrees is not None and self.catalog.supports_gaze:
            self._show_frame(self.catalog.look_frame(self._fixed_look_degrees))
            return
        if (
            self.catalog.supports_gaze
            and self.behavior.mode is BehaviorMode.GAZE
            and self.behavior.gaze_degrees is not None
        ):
            self._show_frame(
                self.catalog.nearest_look_frame(self.behavior.gaze_degrees)
            )
            return
        idle = self.catalog.idle_action
        spec = self.catalog.spec(idle)
        step = self.timeline.advance(self._adjusted_animation_time(now_ms), spec)
        if self.timeline.action != idle:
            self.timeline.start(idle, now_ms)
            step = self.timeline.advance(now_ms, spec)
        self._show_frame(self.catalog.frames(idle)[step.frame_index])

    def _render_current_frame(self) -> None:
        self._displayed_frame = None
        if self.behavior.mode is BehaviorMode.MANUAL_ACTION and self.behavior.current_action:
            action = self.behavior.current_action
            step = self.timeline.advance(self._now_ms(), self.catalog.spec(action))
            self._show_frame(self.catalog.frames(action)[step.frame_index])
        else:
            self._render_base(self._now_ms())

    def _resume_base_mode(self) -> None:
        now = self._now_ms()
        self.timeline.start(self.catalog.idle_action, now)
        self._last_frame_index = None
        self._render_base(now)
        if self.behavior.mode is BehaviorMode.WANDER:
            self._schedule_wander()
        self._schedule_autonomous()

    def _show_frame(self, frame: FrameAsset) -> None:
        identity = (
            frame.row,
            frame.column,
            frame.variant,
            self._settings.scale_percent,
        )
        if self._displayed_frame != identity:
            self.window.set_frame(frame, self._settings.scale_percent)
            self._displayed_frame = identity
        self._refresh_hover_snapshot()

    def _schedule_wander(self) -> None:
        if (
            self._settings.wander_enabled
            and self.behavior.mode is BehaviorMode.WANDER
            and self._wander_target is None
            and self._fixed_look_degrees is None
            and not self._shut_down
        ):
            minimum, maximum, _distance_ratio = _WANDER_PROFILES.get(
                self._settings.wander_intensity,
                _WANDER_PROFILES["standard"],
            )
            self.wander_timer.start(self._rng.randint(minimum, maximum))

    def _autonomous_eligible(self) -> bool:
        return (
            self._settings.autonomous_actions_enabled
            and not self._settings.wander_enabled
            and not (
                self._settings.gaze_enabled
                and self._settings.gaze_mode == "always"
                and self.catalog.supports_gaze
            )
            and self.behavior.mode in {BehaviorMode.IDLE, BehaviorMode.GAZE}
            and self.behavior.current_action is None
            and self._fixed_look_degrees is None
            and not self._showcase_active
            and not self._shut_down
        )

    def _gaze_delays_autonomous(self) -> bool:
        return (
            self._settings.gaze_enabled
            and self._settings.gaze_mode == "active"
            and self.catalog.supports_gaze
        )

    def _schedule_autonomous(self) -> None:
        if not self._autonomous_eligible():
            self.autonomous_timer.stop()
            return
        now_ms = self._now_ms()
        if self._gaze_delays_autonomous():
            activity_delay = max(
                0, _CURSOR_STILL_MS - (now_ms - self._last_cursor_move_ms)
            )
        else:
            if self._autonomous_not_before_ms <= now_ms:
                self._autonomous_not_before_ms = now_ms + self._rng.randint(
                    _AUTONOMOUS_MIN_DELAY_MS, _AUTONOMOUS_MAX_DELAY_MS
                )
            activity_delay = 0
        cooldown_delay = max(0, self._autonomous_not_before_ms - now_ms)
        self.autonomous_timer.start(max(1, activity_delay, cooldown_delay))

    def _autonomous_timeout(self) -> None:
        if not self._autonomous_eligible():
            return
        now_ms = self._now_ms()
        if now_ms < self._autonomous_not_before_ms:
            self._schedule_autonomous()
            return
        if (
            self._gaze_delays_autonomous()
            and now_ms - self._last_cursor_move_ms < _CURSOR_STILL_MS
        ):
            self._schedule_autonomous()
            return
        self.trigger_action(ActionId.RANDOM)

    def _defer_autonomous(self) -> None:
        if (
            not self._settings.autonomous_actions_enabled
            or self._settings.wander_enabled
        ):
            return
        self._autonomous_not_before_ms = self._now_ms() + self._rng.randint(
            _AUTONOMOUS_MIN_DELAY_MS, _AUTONOMOUS_MAX_DELAY_MS
        )

    def _choose_random_action(self) -> ActionKey:
        now_ms = self._now_ms()
        configured = list(self.catalog.autoplay_actions())
        weighted = [
            (action, weight)
            for action, weight in configured
            if (
                self._last_action_played_ms.get(action) is None
                or now_ms - self._last_action_played_ms[action]
                >= self.catalog.definition(action).cooldown_ms
            )
        ]
        if len(weighted) > 1 and self._last_random_group is not None:
            outside_previous_group = [
                item
                for item in weighted
                if self.catalog.definition(item[0]).autoplay_group
                != self._last_random_group
            ]
            if outside_previous_group:
                weighted = outside_previous_group
        if len(weighted) > 1 and self._last_random_action is not None:
            without_repeat = [
                item for item in weighted if item[0] != self._last_random_action
            ]
            if without_repeat:
                weighted = without_repeat
        if not weighted:
            if configured:
                return self.catalog.idle_action
            weighted = [(action, 1) for action in self.catalog.interaction_actions()]
        if not weighted:
            return self.catalog.idle_action
        target = self._rng.randint(1, sum(weight for _, weight in weighted))
        for action, weight in weighted:
            target -= weight
            if target <= 0:
                self._last_random_action = action
                self._last_random_group = (
                    self.catalog.definition(action).autoplay_group or None
                )
                return action
        raise RuntimeError("could not choose a random action")

    def _interrupt_wander(self, *, reschedule: bool) -> bool:
        was_active = self._wander_target is not None or self._wander_direction != 0
        self.wander_timer.stop()
        self._wander_target = None
        self._wander_direction = 0
        self._wander_area = None
        self._wander_action = None
        self._wander_start = None
        if was_active and self.behavior.mode is BehaviorMode.WANDER:
            now_ms = self._now_ms()
            self.timeline.start(self.catalog.idle_action, now_ms)
            self._last_frame_index = None
            self._show_frame(self.catalog.frames(self.catalog.idle_action)[0])
        if reschedule:
            self._schedule_wander()
            self._schedule_autonomous()
        return was_active

    def _begin_drag(self) -> None:
        self._interrupt_wander(reschedule=False)
        self.autonomous_timer.stop()
        self._cancel_showcase()
        self._cancel_active_state()
        if self.behavior.current_action is not None:
            self.behavior.manual_finished()
            self.timeline.start(self.catalog.idle_action, self._now_ms())
        self._manual_burst_start = None
        self._manual_burst_target = None
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
        self._defer_autonomous()
        self._schedule_autonomous()

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
        self._interrupt_wander(reschedule=False)
        QTimer.singleShot(0, self._recover_window_visibility)

    def _connect_screen(self, screen: object) -> None:
        screen.availableGeometryChanged.connect(self._recover_window_visibility)

    def _recover_window_visibility(self, *args: object) -> None:
        del args
        self._interrupt_wander(reschedule=False)
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
        self._schedule_wander()

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
    return SettingsStore(_default_data_root("APPDATA") / SETTINGS_DIRECTORY / "settings.ini")


def _default_startup_manager() -> StartupManager:
    return StartupManager(WinRegRunKey(), Path(sys.executable))


def _write_stdout(text: str) -> None:
    """Write JSON in console and PyInstaller windowed/inherited-pipe modes."""
    stream = sys.stdout
    if stream is not None:
        try:
            stream.write(text)
            stream.flush()
        except (OSError, ValueError):
            # A windowed executable started without redirected output can
            # inherit a placeholder stream whose Win32 handle is invalid.
            pass
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
    try:
        os.write(1, data)
    except OSError:
        pass


def main(
    argv: list[str] | None = None,
    *,
    qapp: QApplication | None = None,
    guard_factory: Callable[[], SingleInstanceGuard] = SingleInstanceGuard,
    catalog_factory: Callable[[], AnimationCatalog] | None = None,
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

    logger = configure_logging(_default_data_root("LOCALAPPDATA") / SETTINGS_DIRECTORY / "logs")
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
            qa_window=args.qa_window,
        )
    except Exception as error:
        logger.exception("Desktop-pet atlas or runtime construction failed")
        try:
            dialog(f"{PRODUCT_NAME}无法启动", f"资源加载失败：{error}")
        except Exception:
            logger.exception("Could not show startup failure dialog")
        finally:
            guard.close()
        return 1

    controller_shutdown_attempted = False
    guard_closed = False

    def cleanup() -> None:
        nonlocal controller_shutdown_attempted, guard_closed
        if controller_shutdown_attempted and guard_closed:
            return
        try:
            if not controller_shutdown_attempted:
                controller_shutdown_attempted = True
                controller.shutdown()
        finally:
            if not guard_closed:
                guard.close()
                guard_closed = True

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
