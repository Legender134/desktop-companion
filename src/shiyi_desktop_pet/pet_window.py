"""Transparent, alpha-shaped widget used to render and interact with the pet."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSizeF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QBitmap,
    QGuiApplication,
    QImage,
    QMouseEvent,
    QPaintEvent,
    QPainter,
)
from PySide6.QtWidgets import QWidget

from .animation_catalog import AnimationCatalog
from .models import ActionId, RenderedFrame


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
        self._current_frame: RenderedFrame | None = None
        self._scaled_image = QImage()
        self._scaled_body_rect = QRectF()
        self._scale_percent = 100
        self._pending_press_offset: QPointF | None = None
        self._pending_press_position: QPointF | None = None
        self._drag_active = False
        self._single_click_timer = QTimer(self)
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.timeout.connect(
            lambda: self.action_requested.emit(ActionId.RANDOM)
        )

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    @property
    def current_frame(self) -> RenderedFrame | None:
        return self._current_frame

    @property
    def scale_percent(self) -> int:
        return self._scale_percent

    def set_frame(
        self,
        frame: RenderedFrame,
        scale_percent: int,
        *,
        preserve_anchor: bool = True,
    ) -> None:
        """Display *frame* while keeping its public anchor stationary."""
        if scale_percent <= 0:
            raise ValueError("scale_percent must be positive")

        anchor_global = None
        if preserve_anchor and self._current_frame is not None:
            anchor_global = self.mapToGlobal(self._scaled_anchor())

        self._current_frame = frame
        self._scale_percent = scale_percent
        scale = scale_percent / 100.0
        width = round(frame.image.width() * scale_percent / 100)
        height = round(frame.image.height() * scale_percent / 100)
        self._scaled_image = frame.image.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._scaled_body_rect = QRectF(
            frame.body_rect.x() * scale,
            frame.body_rect.y() * scale,
            frame.body_rect.width() * scale,
            frame.body_rect.height() * scale,
        )
        self.resize(width, height)

        self.setMask(QBitmap.fromImage(self._scaled_image.createAlphaMask()))
        if anchor_global is not None:
            scaled_anchor = self._scaled_anchor()
            self.move(
                anchor_global.x() - scaled_anchor.x(),
                anchor_global.y() - scaled_anchor.y(),
            )
        self.update()

    def pet_position(self) -> QPointF:
        """Return the body's global top-left position."""
        return self.body_global_rect().topLeft()

    def move_pet(self, position: QPointF) -> None:
        """Move the window so the body, rather than the union frame, reaches *position*."""
        target = QPointF(position) - self._scaled_body_rect.topLeft()
        self.move(round(target.x()), round(target.y()))

    def pet_size(self) -> QSizeF:
        """Return the scaled body size."""
        return self._scaled_body_rect.size()

    def body_global_rect(self) -> QRectF:
        """Return the scaled body bounds in global coordinates."""
        origin = self.mapToGlobal(QPoint(0, 0))
        return self._scaled_body_rect.translated(float(origin.x()), float(origin.y()))

    def body_hit_test(self, local_position: QPointF) -> bool:
        """Return whether *local_position* touches an opaque body pixel."""
        frame = self._current_frame
        if frame is None or not self._scaled_body_rect.contains(local_position):
            return False
        scale = self._scale_percent / 100.0
        source_x = int((local_position.x() - self._scaled_body_rect.x()) / scale)
        source_y = int((local_position.y() - self._scaled_body_rect.y()) / scale)
        if not (
            0 <= source_x < frame.body_image.width()
            and 0 <= source_y < frame.body_image.height()
        ):
            return False
        return frame.body_image.pixelColor(source_x, source_y).alpha() > 0

    def set_catalog(self, catalog: AnimationCatalog) -> None:
        """Replace the active catalog without recreating the window."""
        self._catalog = catalog

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        if self._current_frame is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QPoint(0, 0), self._scaled_image)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.body_hit_test(event.position())
        ):
            self._single_click_timer.stop()
            self._clear_drag_state()
            self.action_requested.emit(ActionId.JUMP)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.body_hit_test(event.position())
        ):
            self._pending_press_position = QPointF(event.position())
            self._pending_press_offset = (
                event.position() - self._scaled_body_rect.topLeft()
            )
            self._drag_active = False
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.MiddleButton
            and self.body_hit_test(event.position())
        ):
            self._single_click_timer.stop()
            self.action_requested.emit(ActionId.RANDOM)
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.RightButton
            and self.body_hit_test(event.position())
        ):
            self._single_click_timer.stop()
            self.menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        offset = self._pending_press_offset
        press_position = self._pending_press_position
        if offset is not None and press_position is not None:
            if not self._drag_active:
                movement = event.position() - press_position
                threshold = QGuiApplication.styleHints().startDragDistance()
                if movement.manhattanLength() < threshold:
                    event.accept()
                    return
                self._drag_active = True
                self._single_click_timer.stop()
                self.drag_started.emit()
            target = (event.globalPosition() - offset).toPoint()
            self.drag_moved.emit(target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        offset = self._pending_press_offset
        if event.button() == Qt.MouseButton.LeftButton and offset is not None:
            was_dragging = self._drag_active
            target = (event.globalPosition() - offset).toPoint() if was_dragging else None
            self._clear_drag_state()
            if target is not None:
                self.drag_finished.emit(target)
            else:
                self._single_click_timer.start(
                    QGuiApplication.styleHints().mouseDoubleClickInterval()
                )
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _clear_drag_state(self) -> None:
        self._pending_press_offset = None
        self._pending_press_position = None
        self._drag_active = False

    def _scaled_anchor(self) -> QPoint:
        assert self._current_frame is not None
        scale = self._scale_percent / 100.0
        return QPoint(
            round(self._current_frame.anchor.x() * scale),
            round(self._current_frame.anchor.y() * scale),
        )
