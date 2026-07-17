"""Optional system-tray integration for the desktop pet."""

from __future__ import annotations

import math

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QSystemTrayIcon, QWidget

from .menu_controller import MenuController
from .product import PRODUCT_NAME
from .resource_locator import resource_path


def _icon_from_companion_image(image: QImage) -> QIcon:
    if image.isNull() or not image.hasAlphaChannel():
        return QIcon()
    left, top = image.width(), image.height()
    right = bottom = 0
    found_visible = False
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() == 0:
                continue
            found_visible = True
            left = min(left, x)
            top = min(top, y)
            right = max(right, x + 1)
            bottom = max(bottom, y + 1)
    if not found_visible:
        return QIcon()
    trimmed = image.copy(left, top, right - left, bottom - top)
    square_size = math.ceil(max(trimmed.width(), trimmed.height()) / 0.84)
    canvas = QImage(square_size, square_size, QImage.Format.Format_RGBA8888)
    canvas.fill(0)
    painter = QPainter(canvas)
    try:
        painter.drawImage(
            (square_size - trimmed.width()) // 2,
            (square_size - trimmed.height()) // 2,
            trimmed,
        )
    finally:
        painter.end()
    return QIcon(QPixmap.fromImage(canvas))


class TrayController(QObject):
    """Own a tray icon when supported and degrade to safe no-ops otherwise."""

    def __init__(
        self,
        pet_window: QWidget,
        menu_controller: MenuController,
        icon: QIcon | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pet_window = pet_window
        self.menu = menu_controller.create_menu()
        self.available = bool(QSystemTrayIcon.isSystemTrayAvailable())
        self.tray_icon: QSystemTrayIcon | None = None

        if not self.available:
            return

        tray_icon = icon
        if tray_icon is None or tray_icon.isNull():
            tray_icon = QIcon(str(resource_path("app.ico")))
        self.tray_icon = QSystemTrayIcon(tray_icon, self)
        self.tray_icon.setToolTip(PRODUCT_NAME)
        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self._activated)

    def show(self) -> bool:
        if self.tray_icon is None:
            return False
        self.tray_icon.show()
        return True

    def hide(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.hide()

    def show_message(self, title: str, message: str, milliseconds: int = 10_000) -> bool:
        if self.tray_icon is None:
            return False
        self.tray_icon.showMessage(title, message, msecs=milliseconds)
        return True

    def set_companion_icon(self, image: QImage, display_name: str) -> bool:
        if self.tray_icon is None:
            return False
        icon = _icon_from_companion_image(image)
        if icon.isNull():
            return False
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip(f"{PRODUCT_NAME} · {display_name}")
        return True

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason != QSystemTrayIcon.ActivationReason.DoubleClick:
            return
        self._pet_window.show()
        self._pet_window.raise_()
        self._pet_window.activateWindow()
