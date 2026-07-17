"""Optional system-tray integration for the desktop pet."""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QWidget

from .menu_controller import MenuController
from .product import PRODUCT_NAME
from .resource_locator import resource_path


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

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason != QSystemTrayIcon.ActivationReason.DoubleClick:
            return
        self._pet_window.show()
        self._pet_window.raise_()
        self._pet_window.activateWindow()
