from PySide6.QtCore import QPoint, Qt

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

    with qtbot.waitSignal(window.drag_started):
        qtbot.mousePress(window, Qt.LeftButton, pos=QPoint(96, 150))
    with qtbot.waitSignal(window.drag_moved) as moved:
        qtbot.mouseMove(window, pos=QPoint(110, 160))
    assert moved.args == [window.mapToGlobal(QPoint(14, 10))]
    with qtbot.waitSignal(window.drag_finished):
        qtbot.mouseRelease(window, Qt.LeftButton, pos=QPoint(110, 160))


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
