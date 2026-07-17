from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent

from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.models import ActionId
from shiyi_desktop_pet.pet_window import PetWindow


def test_window_uses_frame_mask_and_emits_mouse_intents(qtbot):
    catalog = AnimationCatalog.load_default()
    window = PetWindow(catalog)
    qtbot.addWidget(window)
    window.set_frame(catalog.frames(ActionId.IDLE)[0], scale_percent=100)

    assert (window.width(), window.height()) == (192, 208)
    assert not window.mask().isEmpty()

    with qtbot.waitSignal(window.action_requested) as signal:
        qtbot.mouseDClick(window, Qt.LeftButton, pos=QPoint(96, 150))
    assert signal.args == [ActionId.JUMP]

    with qtbot.waitSignal(window.action_requested) as signal:
        qtbot.mouseClick(window, Qt.MiddleButton, pos=QPoint(96, 150))
    assert signal.args == [ActionId.RANDOM]

    with qtbot.waitSignal(window.menu_requested):
        qtbot.mouseClick(window, Qt.RightButton, pos=QPoint(96, 150))

    drag_events = []
    window.drag_started.connect(lambda: drag_events.append(("started", None)))
    window.drag_moved.connect(lambda target: drag_events.append(("moved", target)))
    window.drag_finished.connect(lambda target: drag_events.append(("finished", target)))
    qtbot.mousePress(window, Qt.LeftButton, pos=QPoint(96, 150))
    assert drag_events == []
    qtbot.mouseMove(window, pos=QPoint(110, 160))
    qtbot.mouseRelease(window, Qt.LeftButton, pos=QPoint(110, 160))
    target = window.mapToGlobal(QPoint(14, 10))
    assert drag_events == [("started", None), ("moved", target), ("finished", target)]


def test_mask_and_size_follow_frame_scale(qtbot):
    catalog = AnimationCatalog.load_default()
    window = PetWindow(catalog)
    qtbot.addWidget(window)

    first = catalog.frames(ActionId.IDLE)[0]
    second = catalog.frames(ActionId.WAVE)[1]
    window.set_frame(first, scale_percent=75)
    first_mask = window.mask()
    assert (window.width(), window.height()) == (144, 156)
    assert first_mask.boundingRect().right() < window.width()
    assert first_mask.boundingRect().bottom() < window.height()

    window.set_frame(second, scale_percent=150)
    assert (window.width(), window.height()) == (288, 312)
    assert not window.mask().isEmpty()
    assert window.current_frame is second
    assert window.scale_percent == 150


def test_mask_excludes_a_transparent_pixel_and_includes_an_opaque_pixel(qtbot):
    catalog = AnimationCatalog.load_default()
    frame = catalog.frames(ActionId.IDLE)[0]
    window = PetWindow(catalog)
    qtbot.addWidget(window)
    window.set_frame(frame, scale_percent=100)

    transparent = None
    opaque = None
    for y in range(frame.image.height()):
        for x in range(frame.image.width()):
            point = QPoint(x, y)
            if frame.image.pixelColor(x, y).alpha() == 0 and transparent is None:
                transparent = point
            if frame.image.pixelColor(x, y).alpha() == 255 and opaque is None:
                opaque = point
            if transparent is not None and opaque is not None:
                break
        if transparent is not None and opaque is not None:
            break

    assert transparent is not None and not window.mask().contains(transparent)
    assert opaque is not None and window.mask().contains(opaque)


def test_drag_target_uses_global_mouse_position_minus_press_offset(qtbot):
    catalog = AnimationCatalog.load_default()
    window = PetWindow(catalog)
    qtbot.addWidget(window)
    window.set_frame(catalog.frames(ActionId.IDLE)[0], scale_percent=100)
    window.move(320, 240)
    window.show()

    press_position = QPoint(80, 120)
    move_position = QPoint(105, 145)
    qtbot.mousePress(window, Qt.LeftButton, pos=press_position)
    with qtbot.waitSignal(window.drag_moved) as moved:
        qtbot.mouseMove(window, pos=move_position)

    expected = window.mapToGlobal(move_position) - press_position
    assert moved.args == [expected]
    qtbot.mouseRelease(window, Qt.LeftButton, pos=move_position)


def _mouse_event(
    event_type: QEvent.Type,
    local: QPointF,
    global_position: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        local,
        global_position,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_realistic_double_click_emits_only_jump_and_no_drag_transaction(qtbot):
    catalog = AnimationCatalog.load_default()
    window = PetWindow(catalog)
    qtbot.addWidget(window)
    window.set_frame(catalog.frames(ActionId.IDLE)[0], scale_percent=100)
    events = []
    window.drag_started.connect(lambda: events.append("drag_started"))
    window.drag_moved.connect(lambda target: events.append(("drag_moved", target)))
    window.drag_finished.connect(lambda target: events.append(("drag_finished", target)))
    window.action_requested.connect(lambda action: events.append(("action", action)))
    local = QPointF(96.0, 150.0)
    global_position = QPointF(416.0, 390.0)

    window.mousePressEvent(
        _mouse_event(
            QEvent.Type.MouseButtonPress,
            local,
            global_position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    window.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.MouseButtonRelease,
            local,
            global_position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    window.mouseDoubleClickEvent(
        _mouse_event(
            QEvent.Type.MouseButtonDblClick,
            local,
            global_position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    window.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.MouseButtonRelease,
            local,
            global_position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert events == [("action", ActionId.JUMP)]


def test_sub_threshold_jitter_double_click_emits_only_jump(qtbot):
    catalog = AnimationCatalog.load_default()
    window = PetWindow(catalog)
    qtbot.addWidget(window)
    window.set_frame(catalog.frames(ActionId.IDLE)[0], scale_percent=100)
    events = []
    window.drag_started.connect(lambda: events.append("drag_started"))
    window.drag_moved.connect(lambda target: events.append(("drag_moved", target)))
    window.drag_finished.connect(lambda target: events.append(("drag_finished", target)))
    window.action_requested.connect(lambda action: events.append(("action", action)))
    threshold = QGuiApplication.styleHints().startDragDistance()
    assert threshold > 0
    jitter = max(0.5, threshold - 1.0)
    press_local = QPointF(96.0, 150.0)
    press_global = QPointF(416.0, 390.0)
    jitter_local = press_local + QPointF(jitter, 0.0)
    jitter_global = press_global + QPointF(jitter, 0.0)

    window.mousePressEvent(
        _mouse_event(
            QEvent.Type.MouseButtonPress,
            press_local,
            press_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    window.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            jitter_local,
            jitter_global,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    window.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.MouseButtonRelease,
            jitter_local,
            jitter_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )
    window.mouseDoubleClickEvent(
        _mouse_event(
            QEvent.Type.MouseButtonDblClick,
            jitter_local,
            jitter_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    window.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.MouseButtonRelease,
            jitter_local,
            jitter_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert jitter < threshold
    assert events == [("action", ActionId.JUMP)]


def test_movement_reaching_platform_threshold_starts_one_drag(qtbot):
    catalog = AnimationCatalog.load_default()
    window = PetWindow(catalog)
    qtbot.addWidget(window)
    window.set_frame(catalog.frames(ActionId.IDLE)[0], scale_percent=100)
    events = []
    window.drag_started.connect(lambda: events.append(("started", None)))
    window.drag_moved.connect(lambda target: events.append(("moved", target)))
    window.drag_finished.connect(lambda target: events.append(("finished", target)))
    threshold = QGuiApplication.styleHints().startDragDistance()
    assert threshold > 0
    press_local = QPointF(40.25, 60.25)
    press_global = QPointF(340.25, 260.25)
    move_local = press_local + QPointF(float(threshold), 0.0)
    move_global = press_global + QPointF(float(threshold), 0.0)
    target = (move_global - press_local).toPoint()

    window.mousePressEvent(
        _mouse_event(
            QEvent.Type.MouseButtonPress,
            press_local,
            press_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    window.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            move_local,
            move_global,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )
    window.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.MouseButtonRelease,
            move_local,
            move_global,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
    )

    assert events == [("started", None), ("moved", target), ("finished", target)]


def test_fractional_drag_subtracts_before_rounding(qtbot):
    catalog = AnimationCatalog.load_default()
    window = PetWindow(catalog)
    qtbot.addWidget(window)
    window.set_frame(catalog.frames(ActionId.IDLE)[0], scale_percent=100)
    events = []
    window.drag_started.connect(lambda: events.append(("started", None)))
    window.drag_moved.connect(lambda target: events.append(("moved", target)))

    window.mousePressEvent(
        _mouse_event(
            QEvent.Type.MouseButtonPress,
            QPointF(10.6, 20.6),
            QPointF(100.6, 200.6),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
    )
    window.mouseMoveEvent(
        _mouse_event(
            QEvent.Type.MouseMove,
            QPointF(40.4, 60.4),
            QPointF(130.4, 240.4),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    )

    assert events == [("started", None), ("moved", QPoint(120, 220))]
