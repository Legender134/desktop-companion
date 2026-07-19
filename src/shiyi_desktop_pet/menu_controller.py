"""One declarative command hierarchy shared by pet and tray menus."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Callable

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QWidget

from .constants import DEFAULT_PET_ACTIONS
from .models import ActionId, ActionKey
from .settings import AppSettings


_LOGGER = logging.getLogger(__name__)
ErrorReporter = Callable[[str, str], None] | logging.Logger


@dataclass(frozen=True)
class MenuCommand:
    """A controller intent emitted by a menu item."""

    kind: str
    value: object | None = None
    target: str | None = None


@dataclass(frozen=True)
class MenuItem:
    label: str
    command: MenuCommand | None = None
    children: tuple["MenuItem", ...] = ()
    checked_from: str | None = None
    checked_value: object | None = None
    radio_group: str | None = None


@dataclass(frozen=True)
class _ActionBinding:
    action: QAction
    item: MenuItem


_DEFAULT_ACTION_ITEMS = tuple(
    (definition.label, definition.action_id) for definition in DEFAULT_PET_ACTIONS
)


def _direction_label(degrees: float) -> str:
    number = f"{degrees:05.1f}" if not degrees.is_integer() else f"{int(degrees):03d}"
    return f"观察 {number}°"


def _toggle(label: str, setting_name: str) -> MenuItem:
    return MenuItem(
        label,
        MenuCommand("toggle", target=setting_name),
        checked_from=setting_name,
    )


def _choice(
    label: str, kind: str, value: object, setting_name: str, radio_group: str
) -> MenuItem:
    return MenuItem(
        label,
        MenuCommand(kind, value),
        checked_from=setting_name,
        checked_value=value,
        radio_group=radio_group,
    )


def _menu_items(
    pet_choices: tuple[tuple[str, str], ...],
    action_items: tuple[tuple[str, ActionKey], ...],
    look_degrees: tuple[float, ...] = tuple(index * 22.5 for index in range(16)),
) -> tuple[MenuItem, ...]:
    look_item = (
        (
            MenuItem(
                "观察方向",
                children=tuple(
                    MenuItem(
                        _direction_label(degrees),
                        MenuCommand("look", degrees),
                    )
                    for degrees in look_degrees
                ),
            ),
        )
        if look_degrees
        else ()
    )
    gaze_toggle = (_toggle("看向鼠标", "gaze_enabled"),) if look_degrees else ()
    return (
        MenuItem(
            "动作",
            children=(
                *(
                    MenuItem(label, MenuCommand("action", action))
                    for label, action in action_items
                ),
                MenuItem("随机动作", MenuCommand("action", ActionId.RANDOM)),
                MenuItem("动作展示", MenuCommand("showcase")),
                *look_item,
            ),
        ),
        _toggle("自动闲逛", "wander_enabled"),
        MenuItem(
            "闲逛强度",
            children=tuple(
                _choice(
                    label,
                    "wander_intensity",
                    intensity,
                    "wander_intensity",
                    "wander_intensity",
                )
                for label, intensity in (
                    ("安静", "quiet"),
                    ("标准", "standard"),
                    ("活跃", "active"),
                )
            ),
        ),
        *gaze_toggle,
        _toggle("自主小动作", "autonomous_actions_enabled"),
        _toggle("悬停数字快捷键", "hover_digits_enabled"),
        _toggle("始终置顶", "always_on_top"),
        MenuItem(
            "开机启动",
            MenuCommand("toggle", target="startup_enabled"),
            checked_from="startup_enabled",
        ),
        MenuItem(
            "切换宠物",
            children=tuple(
                _choice(display_name, "pet", pet_id, "pet_id", "pet")
                for pet_id, display_name in pet_choices
            ),
        ),
        MenuItem("重新扫描宠物", MenuCommand("refresh_pets")),
        MenuItem("打开宠物目录", MenuCommand("open_pets_directory")),
        MenuItem(
            "大小",
            children=tuple(
                _choice(f"{scale}%", "scale", scale, "scale_percent", "scale")
                for scale in (75, 100, 125, 150)
            ),
        ),
        MenuItem(
            "动画速度",
            children=tuple(
                _choice(
                    label,
                    "animation_speed",
                    speed,
                    "animation_speed",
                    "animation_speed",
                )
                for label, speed in (
                    ("慢速", "slow"),
                    ("正常", "normal"),
                    ("快速", "fast"),
                )
            ),
        ),
        MenuItem(
            "移动速度",
            children=tuple(
                _choice(
                    label,
                    "movement_speed",
                    speed,
                    "movement_speed",
                    "movement_speed",
                )
                for label, speed in (
                    ("慢速", "slow"),
                    ("正常", "normal"),
                    ("快速", "fast"),
                )
            ),
        ),
        MenuItem("回到屏幕中央", MenuCommand("center")),
        MenuItem("关于桌面灵伴", MenuCommand("about")),
        MenuItem("退出", MenuCommand("quit")),
    )


class MenuController:
    """Materialize the shared command model as refreshable Qt menus."""

    def __init__(
        self,
        settings_supplier: Callable[[], AppSettings],
        startup_supplier: Callable[[], bool],
        dispatch: Callable[[MenuCommand], None],
        error_reporter: ErrorReporter | None = None,
        pet_choices_supplier: Callable[[], tuple[tuple[str, str], ...]] | None = None,
        action_items_supplier: Callable[[], tuple[tuple[str, ActionKey], ...]] | None = None,
        look_degrees_supplier: Callable[[], tuple[float, ...]] | None = None,
    ) -> None:
        self._settings_supplier = settings_supplier
        self._startup_supplier = startup_supplier
        self._dispatch = dispatch
        self._error_reporter = error_reporter if error_reporter is not None else _LOGGER
        self._pet_choices_supplier = pet_choices_supplier or (lambda: ())
        self._action_items_supplier = action_items_supplier or (
            lambda: _DEFAULT_ACTION_ITEMS
        )
        self._look_degrees_supplier = look_degrees_supplier or (
            lambda: tuple(index * 22.5 for index in range(16))
        )
        self._menus: list[QMenu] = []

    @property
    def items(self) -> tuple[MenuItem, ...]:
        return _menu_items(
            self._pet_choices(), self._action_items(), self._look_degrees()
        )

    def flattened_labels(self) -> tuple[str, ...]:
        def flatten(items: tuple[MenuItem, ...]):
            for item in items:
                yield item.label
                yield from flatten(item.children)

        return tuple(flatten(self.items))

    def create_menu(self, parent: QWidget | None = None) -> QMenu:
        menu = QMenu(parent)
        self._rebuild(menu)
        menu.aboutToShow.connect(lambda current=menu: self.refresh(current))
        self._menus.append(menu)
        return menu

    def _rebuild(self, menu: QMenu) -> None:
        menu.clear()
        bindings: list[_ActionBinding] = []
        groups: dict[str, QActionGroup] = {}
        retained: list[object] = []
        self._populate(menu, self.items, bindings, groups, retained)
        menu._shiyi_bindings = bindings
        menu._shiyi_retained = retained

    def refresh(self, menu: QMenu) -> None:
        self._rebuild(menu)
        try:
            settings = self._settings_supplier()
            if not isinstance(settings, AppSettings):
                raise TypeError("settings supplier returned an invalid value")
        except Exception as error:
            settings = AppSettings()
            self._report_supplier_error("settings supplier", error)

        try:
            startup_enabled = bool(self._startup_supplier())
        except Exception as error:
            startup_enabled = False
            self._report_supplier_error("startup supplier", error)

        bindings = menu._shiyi_bindings
        for binding in bindings:
            source = binding.item.checked_from
            if source is None:
                continue
            actual = (
                startup_enabled
                if source == "startup_enabled"
                else getattr(settings, source)
            )
            expected = binding.item.checked_value
            binding.action.setChecked(bool(actual) if expected is None else actual == expected)

    def refresh_all(self) -> None:
        for menu in tuple(self._menus):
            self.refresh(menu)

    def _pet_choices(self) -> tuple[tuple[str, str], ...]:
        try:
            choices = tuple(self._pet_choices_supplier())
            if any(
                not isinstance(pet_id, str)
                or not isinstance(display_name, str)
                or not pet_id
                or not display_name
                for pet_id, display_name in choices
            ):
                raise TypeError("pet choices supplier returned invalid values")
            return choices
        except Exception as error:
            self._report_supplier_error("pet choices supplier", error)
            return ()

    def _action_items(self) -> tuple[tuple[str, ActionKey], ...]:
        try:
            items = tuple(self._action_items_supplier())
            if (
                not items
                or len({action for _, action in items}) != len(items)
                or any(
                    not isinstance(label, str)
                    or not label
                    or not isinstance(action, str)
                    or not action
                    for label, action in items
                )
            ):
                raise TypeError("action items supplier returned invalid values")
            return items
        except Exception as error:
            self._report_supplier_error("action items supplier", error)
            return _DEFAULT_ACTION_ITEMS

    def _look_degrees(self) -> tuple[float, ...]:
        try:
            values = tuple(self._look_degrees_supplier())
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not 0.0 <= float(value) < 360.0
                for value in values
            ):
                raise TypeError("look degrees supplier returned invalid values")
            return tuple(float(value) for value in values)
        except Exception as error:
            self._report_supplier_error("look degrees supplier", error)
            return ()

    def _report_supplier_error(self, context: str, error: Exception) -> None:
        error_type = type(error).__name__
        try:
            warning = getattr(self._error_reporter, "warning", None)
            if callable(warning):
                warning("%s failed (%s)", context, error_type)
            else:
                self._error_reporter(context, error_type)
        except Exception:
            _LOGGER.warning("menu error reporter failed for %s (%s)", context, error_type)

    def _populate(
        self,
        menu: QMenu,
        items: tuple[MenuItem, ...],
        bindings: list[_ActionBinding],
        groups: dict[str, QActionGroup],
        retained: list[object],
    ) -> None:
        for item in items:
            if item.children:
                submenu = QMenu(item.label, menu)
                menu.addMenu(submenu)
                retained.append(submenu)
                self._populate(submenu, item.children, bindings, groups, retained)
                continue

            action = menu.addAction(item.label)
            retained.append(action)
            if item.checked_from is not None:
                action.setCheckable(True)
            if item.radio_group is not None:
                group = groups.get(item.radio_group)
                if group is None:
                    group = QActionGroup(menu)
                    group.setExclusive(True)
                    groups[item.radio_group] = group
                    retained.append(group)
                group.addAction(action)
            if item.command is not None:
                action.triggered.connect(
                    lambda checked=False, current=item: self._trigger(current, checked)
                )
            bindings.append(_ActionBinding(action, item))

    def _trigger(self, item: MenuItem, checked: bool) -> None:
        command = item.command
        if command is None:
            return
        if command.kind == "toggle":
            command = replace(command, value=bool(checked))
        self._dispatch(command)
