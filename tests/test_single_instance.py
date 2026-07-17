from uuid import uuid4

from PySide6.QtCore import QTimer

from shiyi_desktop_pet.single_instance import SingleInstanceGuard


def test_second_guard_sends_activate_to_first(qtbot):
    instance_name = f"ShiyiDesktopPet.Test.{uuid4().hex}"
    first = SingleInstanceGuard(instance_name)
    assert first.acquire()

    with qtbot.waitSignal(first.command_received) as signal:
        second = SingleInstanceGuard(instance_name)
        assert not second.acquire(command="activate")

    assert signal.args == ["activate"]
    second.close()
    first.close()


def test_second_guard_sends_quit_and_owner_close_is_idempotent(qtbot):
    instance_name = f"ShiyiDesktopPet.Test.{uuid4().hex}"
    first = SingleInstanceGuard(instance_name)
    assert first.acquire()

    with qtbot.waitSignal(first.command_received) as signal:
        second = SingleInstanceGuard(instance_name)
        assert not second.acquire(command="quit")

    assert signal.args == ["quit"]
    second.close()
    first.close()
    first.close()


def test_guard_rejects_unknown_command():
    instance_name = f"ShiyiDesktopPet.Test.{uuid4().hex}"
    guard = SingleInstanceGuard(instance_name)
    try:
        with __import__("pytest").raises(ValueError):
            guard.acquire(command="digits")
    finally:
        guard.close()


def test_guard_validation_owner_properties_and_missing_peer():
    with __import__("pytest").raises(ValueError):
        SingleInstanceGuard("")
    with __import__("pytest").raises(ValueError):
        SingleInstanceGuard("test", timeout_ms=0)

    instance_name = f"ShiyiDesktopPet.Test.{uuid4().hex}"
    owner = SingleInstanceGuard(instance_name)
    try:
        assert not owner.is_owner
        assert owner.acquire()
        assert owner.is_owner
        assert owner.acquire()
    finally:
        owner.close()

    class ExistingMutex:
        already_exists = True

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    missing = ExistingMutex()
    peer = SingleInstanceGuard(
        f"ShiyiDesktopPet.Test.{uuid4().hex}",
        timeout_ms=10,
        mutex_factory=lambda name: missing,
    )
    assert not peer.acquire()
    assert peer.last_delivery_succeeded is False
    assert missing.closed


def test_existing_mutex_retries_until_delayed_server_listens(qtbot):
    instance_name = f"ShiyiDesktopPet.Test.{uuid4().hex}"

    class Mutex:
        def __init__(self, already_exists):
            self.already_exists = already_exists
            self.closed = False

        def close(self):
            self.closed = True

    owner_mutex = Mutex(False)
    sender_mutex = Mutex(True)
    owner = SingleInstanceGuard(
        instance_name,
        mutex_factory=lambda name: owner_mutex,
    )
    sender = SingleInstanceGuard(
        instance_name,
        timeout_ms=1_000,
        mutex_factory=lambda name: sender_mutex,
    )

    QTimer.singleShot(50, owner.acquire)
    try:
        with qtbot.waitSignal(owner.command_received, timeout=2_000) as signal:
            assert not sender.acquire(command="activate")
        assert signal.args == ["activate"]
        assert sender.last_delivery_succeeded is True
        assert sender_mutex.closed
    finally:
        sender.close()
        owner.close()
