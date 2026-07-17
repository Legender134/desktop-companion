"""Transparent, alpha-shaped widget used to render and interact with the pet."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QBitmap, QMouseEvent, QPaintEvent, QPainter
from PySide6.QtWidgets import QWidget

from .animation_catalog import AnimationCatalog
from .models import ActionId, FrameAsset


class PetWindow(QWidget):
    """Render frames and publish user intent without making behavior decisions."""

    action_requested = Signal(object)
    menu_requested = Signal(QPoint)
    drag_started = Signal()
    drag_moved = Signal(QPoint)
    drag_finished = Signal(QPoint)

    def __init__(self, catalog: AnimationCatalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._current_frame: FrameAsset | None = None
        self._scale_percent = 100
        self._drag_offset: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    @property
    def current_frame(self) -> FrameAsset | None:
        return self._current_frame

    @property
    def scale_percent(self) -> int:
        return self._scale_percent

    def set_frame(self, frame: FrameAsset, scale_percent: int) -> None:
        """Display *frame* and make its scaled alpha shape the input region."""
        if scale_percent <= 0:
            raise ValueError("scale_percent must be positive")

        self._current_frame = frame
        self._scale_percent = scale_percent
        width = round(frame.image.width() * scale_percent / 100)
        height = round(frame.image.height() * scale_percent / 100)
        self.resize(width, height)

        scaled_mask = QBitmap.fromImage(frame.image.createAlphaMask()).scaled(
            self.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setMask(QBitmap.fromPixmap(scaled_mask))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        if self._current_frame is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self._current_frame.image)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.action_requested.emit(ActionId.JUMP)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.position().toPoint()
            self.drag_started.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self.action_requested.emit(ActionId.RANDOM)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            target = event.globalPosition().toPoint() - self._drag_offset
            self.drag_moved.emit(target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            target = event.globalPosition().toPoint() - self._drag_offset
            self._drag_offset = None
            self.drag_finished.emit(target)
            event.accept()
            return
        super().mouseReleaseEvent(event)
