import sys
import threading
import time
from collections import deque

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

import shiyi_desktop_pet.keyboard_hook as keyboard_hook
from shiyi_desktop_pet.keyboard_hook import (
    HookLifecycleState,
    KeyboardDecisionEngine,
    KeyboardHookError,
    LowLevelKeyboardHook,
)


def test_top_row_and_numpad_are_consumed_only_during_visible_hover():
    engine = KeyboardDecisionEngine()
    down = engine.handle(0x35, is_down=True, enabled=True, hovered=True)
    assert down.consume and down.digit == 5
    up = engine.handle(0x35, is_down=False, enabled=True, hovered=False)
    assert up.consume and up.digit is None
    assert not engine.handle(0x35, True, True, False).consume
    assert engine.handle(0x63, True, True, True).digit == 3


def test_repeat_keydown_emits_once_until_keyup():
    engine = KeyboardDecisionEngine()
    first = engine.handle(0x34, True, True, True)
    repeat = engine.handle(0x34, True, True, True)
    assert first.consume and first.digit == 4
    assert repeat.consume and repeat.digit is None
    engine.handle(0x34, False, True, True)
    assert engine.handle(0x34, True, True, True).digit == 4


def test_non_digits_disabled_and_non_hovered_digits_pass_through():
    engine = KeyboardDecisionEngine()
    for vk_code in (0x2F, 0x3A, 0x5A, 0x5F, 0x6A):
        assert not engine.handle(vk_code, True, True, True).consume
    assert not engine.handle(0x31, True, False, True).consume
    assert not engine.handle(0x31, True, True, False).consume
    assert not engine.handle(0x31, False, True, True).consume


@pytest.mark.parametrize(
    ("initial_enabled", "initial_hovered"),
    ((False, True), (True, False)),
)
def test_passed_initial_down_stays_passed_for_held_repeats(
    initial_enabled,
    initial_hovered,
):
    engine = KeyboardDecisionEngine()
    initial = engine.handle(0x37, True, initial_enabled, initial_hovered)
    repeat = engine.handle(0x37, True, True, True)
    released = engine.handle(0x37, False, True, True)

    assert not initial.consume and initial.digit is None
    assert not repeat.consume and repeat.digit is None
    assert not released.consume and released.digit is None


class FakeKeyboardBackend:
    def __init__(
        self,
        *,
        prepare_gate=None,
        prepare_error=None,
        install_error=None,
        message_result=0,
        message_gate=None,
        post_result=True,
        post_results=None,
        post_gate=None,
        unhook_results=(True,),
        invoke_vk=None,
        native_callback=False,
    ):
        self.prepare_gate = prepare_gate
        self.prepare_error = prepare_error
        self.install_error = install_error
        self.message_result = message_result
        self.message_gate = message_gate
        self.post_result = post_result
        self.post_results = (
            deque(post_results) if post_results is not None else None
        )
        self.post_gate = post_gate
        self.unhook_results = deque(unhook_results)
        self.invoke_vk = invoke_vk
        self.native_callback = native_callback
        self.prepared = threading.Event()
        self.installed = threading.Event()
        self.invoked = threading.Event()
        self.quit_requested = threading.Event()
        self.post_entered = threading.Event()
        self.callback = None
        self.callback_thread_id = None
        self.call_next_result = 73
        self.call_next_error = None
        self.decode_error = None
        self.unhook_calls = 0
        self.post_calls = 0

    def prepare(self):
        self.prepared.set()
        if self.prepare_gate is not None:
            assert self.prepare_gate.wait(2)
        if self.prepare_error is not None:
            raise self.prepare_error
        return 4242

    def make_callback(self, target):
        if self.native_callback:
            self.callback = keyboard_hook._LowLevelKeyboardProc(target)
        else:
            self.callback = target
        return self.callback

    def install(self, callback):
        if self.install_error is not None:
            raise self.install_error
        self.installed.set()
        return object()

    def get_message(self):
        if self.invoke_vk is not None and not self.invoked.is_set():
            self.callback_thread_id = threading.get_ident()
            self.callback(0, keyboard_hook.WM_KEYDOWN, self.invoke_vk)
            self.invoked.set()
        if self.message_gate is not None:
            assert self.message_gate.wait(2)
        else:
            self.quit_requested.wait()
        return self.message_result

    def post_quit(self, thread_id):
        self.post_calls += 1
        self.post_entered.set()
        if self.post_gate is not None:
            assert self.post_gate.wait(2)
        result = (
            self.post_results.popleft()
            if self.post_results is not None
            else self.post_result
        )
        if isinstance(result, BaseException):
            raise result
        if result:
            self.quit_requested.set()
        return result

    def unhook(self, handle):
        self.unhook_calls += 1
        if not self.unhook_results:
            return True
        return self.unhook_results.popleft()

    def call_next(self, handle, code, message, data):
        if self.call_next_error is not None:
            raise self.call_next_error
        return self.call_next_result

    def decode_vk(self, data):
        if self.decode_error is not None:
            raise self.decode_error
        return int(data)

    def error(self, operation):
        return OSError(f"{operation} failed")


def wait_for_state(hook, expected, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if hook.state is expected:
            return
        time.sleep(0.005)
    pytest.fail(f"hook did not reach {expected.name}; current={hook.state.name}")


def test_stop_start_resets_missing_keyup_state():
    backends = deque((FakeKeyboardBackend(), FakeKeyboardBackend()))
    emitted = []
    hook = LowLevelKeyboardHook(
        lambda: True,
        backend_factory=lambda: backends.popleft(),
    )
    hook._queue_digit = emitted.append

    hook.start()
    first_backend = hook._backend
    assert first_backend.callback(0, keyboard_hook.WM_KEYDOWN, 0x33) == 1
    hook.stop()

    hook.start()
    second_backend = hook._backend
    assert second_backend.callback(0, keyboard_hook.WM_KEYDOWN, 0x33) == 1
    hook.stop()

    assert emitted == [3, 3]
    assert hook.state is HookLifecycleState.STOPPED


def test_setup_failure_is_public_and_does_not_strand_a_thread():
    backend = FakeKeyboardBackend(prepare_error=OSError("setup unavailable"))
    hook = LowLevelKeyboardHook(lambda: False, backend_factory=lambda: backend)

    with pytest.raises(KeyboardHookError, match="start"):
        hook.start()

    assert hook.state is HookLifecycleState.FAILED
    assert isinstance(hook.last_error, KeyboardHookError)
    assert "setup unavailable" not in str(hook.last_error)
    assert not hook.is_running
    hook.stop()
    assert hook.state is HookLifecycleState.STOPPED


def test_concurrent_start_callers_share_one_failed_installation():
    gate = threading.Event()
    backend = FakeKeyboardBackend(
        prepare_gate=gate,
        install_error=OSError("install failed"),
    )
    factory_calls = 0
    errors = []

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        return backend

    hook = LowLevelKeyboardHook(lambda: False, backend_factory=factory)

    def start_hook():
        try:
            hook.start()
        except BaseException as error:
            errors.append(error)

    callers = [threading.Thread(target=start_hook) for _ in range(2)]
    for caller in callers:
        caller.start()
    assert backend.prepared.wait(2)
    gate.set()
    for caller in callers:
        caller.join(2)

    assert factory_calls == 1
    assert len(errors) == 2
    assert all(isinstance(error, KeyboardHookError) for error in errors)
    assert hook.state is HookLifecycleState.FAILED
    assert not any(caller.is_alive() for caller in callers)
    hook.stop()


def test_concurrent_start_callers_wait_for_one_successful_installation():
    gate = threading.Event()
    backend = FakeKeyboardBackend(prepare_gate=gate)
    factory_calls = 0
    completed = []

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        return backend

    hook = LowLevelKeyboardHook(lambda: False, backend_factory=factory)
    callers = [
        threading.Thread(target=lambda: (hook.start(), completed.append(True)))
        for _ in range(2)
    ]
    for caller in callers:
        caller.start()
    assert backend.prepared.wait(2)
    time.sleep(0.02)
    assert completed == []
    gate.set()
    for caller in callers:
        caller.join(2)

    assert factory_calls == 1
    assert completed == [True, True]
    assert hook.state is HookLifecycleState.RUNNING
    hook.stop()


def test_stop_coordinates_with_starting_before_queue_readiness():
    gate = threading.Event()
    backend = FakeKeyboardBackend(prepare_gate=gate)
    hook = LowLevelKeyboardHook(lambda: False, backend_factory=lambda: backend)
    start_errors = []
    stop_errors = []
    starter = threading.Thread(
        target=lambda: _capture_error(hook.start, start_errors),
        name="test-hook-starter",
    )
    stopper = threading.Thread(
        target=lambda: _capture_error(hook.stop, stop_errors),
        name="test-hook-stopper",
    )

    starter.start()
    assert backend.prepared.wait(2)
    stopper.start()
    gate.set()
    starter.join(2)
    stopper.join(2)

    assert len(start_errors) == 1
    assert isinstance(start_errors[0], KeyboardHookError)
    assert stop_errors == []
    assert hook.state is HookLifecycleState.STOPPED
    assert not starter.is_alive() and not stopper.is_alive()


def test_concurrent_stop_callers_share_one_shutdown_request():
    post_gate = threading.Event()
    backend = FakeKeyboardBackend(post_gate=post_gate)
    hook = LowLevelKeyboardHook(lambda: False, backend_factory=lambda: backend)
    errors = []
    hook.start()
    first = threading.Thread(target=lambda: _capture_error(hook.stop, errors))
    second = threading.Thread(target=lambda: _capture_error(hook.stop, errors))

    first.start()
    assert backend.post_entered.wait(2)
    second.start()
    time.sleep(0.02)
    post_gate.set()
    first.join(2)
    second.join(2)

    assert errors == []
    assert backend.post_calls == 1
    assert hook.state is HookLifecycleState.STOPPED
    assert not first.is_alive() and not second.is_alive()


@pytest.mark.parametrize(
    "failed_post",
    (False, OSError("post failed before enqueue")),
)
def test_failed_post_without_queue_release_can_be_retried(failed_post):
    backend = FakeKeyboardBackend(post_results=(failed_post, True))
    hook = LowLevelKeyboardHook(lambda: False, backend_factory=lambda: backend)
    hook.start()
    worker_thread = hook._thread

    started_at = time.monotonic()
    try:
        with pytest.raises(KeyboardHookError, match="shutdown request"):
            hook.stop(timeout=0.2)
        assert time.monotonic() - started_at < 0.2
        assert backend.post_calls == 1
        assert not backend.quit_requested.is_set()
        assert hook.state is HookLifecycleState.RUNNING
        assert hook.is_running
        assert isinstance(hook.last_error, KeyboardHookError)

        hook.stop(timeout=1.0)
        assert backend.post_calls == 2
        assert backend.quit_requested.is_set()
        assert backend.unhook_calls == 1
        assert hook.state is HookLifecycleState.STOPPED
    finally:
        backend.quit_requested.set()
        worker_thread.join(1.0)
        for _ in range(2):
            try:
                hook.stop(timeout=1.0)
            except (KeyboardHookError, TimeoutError):
                pass
        assert not any(
            thread.name == "ShiyiKeyboardHook" and thread.is_alive()
            for thread in threading.enumerate()
        )


def test_old_stop_validates_its_generation_while_new_start_runs():
    old_backend = FakeKeyboardBackend()
    new_backend = FakeKeyboardBackend()
    backends = deque((old_backend, new_backend))
    old_joined = threading.Event()
    release_old_join = threading.Event()
    thread_count = 0

    class GatedJoinThread(threading.Thread):
        def join(self, timeout=None):
            super().join(timeout)
            if not self.is_alive():
                old_joined.set()
                assert release_old_join.wait(2)

    def thread_factory(**kwargs):
        nonlocal thread_count
        thread_count += 1
        if thread_count == 1:
            return GatedJoinThread(**kwargs)
        return threading.Thread(**kwargs)

    hook = LowLevelKeyboardHook(
        lambda: False,
        backend_factory=lambda: backends.popleft(),
        thread_factory=thread_factory,
    )
    stop_errors = []
    start_errors = []
    hook.start()
    stopper = threading.Thread(target=lambda: _capture_error(hook.stop, stop_errors))
    starter = threading.Thread(target=lambda: _capture_error(hook.start, start_errors))

    stopper.start()
    assert old_backend.post_entered.wait(2)
    starter.start()
    assert old_joined.wait(2)
    assert new_backend.installed.wait(2)
    assert hook.state is HookLifecycleState.RUNNING
    release_old_join.set()
    stopper.join(2)
    starter.join(2)

    assert stop_errors == []
    assert start_errors == []
    assert hook.state is HookLifecycleState.RUNNING
    assert hook._backend is new_backend
    hook.stop()
    assert not stopper.is_alive() and not starter.is_alive()


@pytest.mark.parametrize("failure_mode", ("construction", "start"))
def test_thread_creation_failures_are_sanitized_and_reusable(failure_mode):
    backend = FakeKeyboardBackend()
    attempts = 0

    class StartFailingThread(threading.Thread):
        def start(self):
            raise OSError("raw thread start detail")

        def join(self, timeout=None):
            raise AssertionError("an unstarted thread must never be joined")

    def thread_factory(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1 and failure_mode == "construction":
            raise OSError("raw thread construction detail")
        if attempts == 1:
            return StartFailingThread(**kwargs)
        return threading.Thread(**kwargs)

    hook = LowLevelKeyboardHook(
        lambda: False,
        backend_factory=lambda: backend,
        thread_factory=thread_factory,
    )

    with pytest.raises(KeyboardHookError, match="thread"):
        hook.start()
    assert hook.state is HookLifecycleState.FAILED
    assert isinstance(hook.last_error, KeyboardHookError)
    assert "raw thread" not in str(hook.last_error)
    assert attempts == 1

    with pytest.raises(KeyboardHookError, match="thread"):
        hook.start()
    assert attempts == 1
    hook.stop()
    hook.stop()
    assert hook.state is HookLifecycleState.STOPPED

    hook.start()
    assert hook.state is HookLifecycleState.RUNNING
    hook.stop()
    assert attempts == 2
    assert not hook.is_running


def _capture_error(call, errors):
    try:
        call()
    except BaseException as error:
        errors.append(error)


def test_runtime_message_failure_sets_last_error_and_queues_failure(qapp):
    message_gate = threading.Event()
    backend = FakeKeyboardBackend(message_result=-1, message_gate=message_gate)
    hook = LowLevelKeyboardHook(lambda: False, backend_factory=lambda: backend)
    failures = QSignalSpy(hook.hook_failed)

    hook.start()
    message_gate.set()
    wait_for_state(hook, HookLifecycleState.FAILED)
    QCoreApplication.processEvents()

    assert isinstance(hook.last_error, KeyboardHookError)
    assert failures.count() == 1
    assert failures.at(0) == ["keyboard hook message loop failed"]
    with pytest.raises(KeyboardHookError, match="message loop"):
        hook.start()
    hook.stop()


def test_failed_unhook_retains_callback_until_retry_succeeds():
    backend = FakeKeyboardBackend(unhook_results=(False, True))
    hook = LowLevelKeyboardHook(lambda: False, backend_factory=lambda: backend)
    hook.start()
    retained_callback = backend.callback

    with pytest.raises(KeyboardHookError, match="unhook"):
        hook.stop()

    assert hook.state is HookLifecycleState.FAILED
    assert hook._callback is retained_callback
    assert hook._hook_handle is not None
    assert not hook.is_running

    hook.stop()
    assert backend.unhook_calls == 2
    assert hook.state is HookLifecycleState.STOPPED
    assert hook._callback is None and hook._hook_handle is None


@pytest.mark.parametrize(
    "failure_point",
    ("decode", "engine", "hit_test", "emit", "pass_through"),
)
def test_native_callback_contains_all_python_exceptions(failure_point):
    def hit_test():
        if failure_point == "hit_test":
            raise RuntimeError("hit test exploded")
        return True

    backend = FakeKeyboardBackend()
    hook = LowLevelKeyboardHook(hit_test, backend_factory=lambda: backend)
    emitted = []
    hook._queue_digit = emitted.append
    hook.start()
    if failure_point == "decode":
        backend.decode_error = RuntimeError("decode exploded")
    if failure_point == "engine":
        hook._engine.handle = lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("engine exploded")
        )
    if failure_point == "emit":
        hook._queue_digit = lambda digit: (_ for _ in ()).throw(
            RuntimeError("emit exploded")
        )
    if failure_point == "pass_through":
        backend.call_next_error = RuntimeError("chain exploded")

    result = backend.callback(0, keyboard_hook.WM_KEYDOWN, 0x36)
    if failure_point == "pass_through":
        assert result == 1
        result = backend.callback(-1, keyboard_hook.WM_KEYDOWN, 0x36)
        assert result == 0
    else:
        assert result == 73
        if failure_point not in ("decode", "engine"):
            assert backend.callback(0, keyboard_hook.WM_KEYDOWN, 0x36) == 73

    if failure_point == "emit":
        hook._queue_digit = emitted.append
        assert backend.callback(0, keyboard_hook.WM_KEYUP, 0x36) == 73
        assert emitted == []
    assert hook.last_error is not None
    hook.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="requires WINFUNCTYPE")
def test_worker_thread_native_callback_delivery_is_queued(qapp):
    backend = FakeKeyboardBackend(invoke_vk=0x32, native_callback=True)
    hit_thread_ids = []
    hook = LowLevelKeyboardHook(
        lambda: hit_thread_ids.append(threading.get_ident()) or True,
        backend_factory=lambda: backend,
    )
    emitted_digits = QSignalSpy(hook.digit_pressed)

    hook.start()
    assert backend.invoked.wait(2)
    assert backend.callback_thread_id != threading.get_ident()
    assert hit_thread_ids == [backend.callback_thread_id]
    assert emitted_digits.count() == 0
    QCoreApplication.processEvents()
    assert emitted_digits.count() == 1
    assert emitted_digits.at(0) == [2]
    hook.stop()


def test_consumed_keys_are_tracked_by_virtual_key():
    engine = KeyboardDecisionEngine()
    assert engine.handle(0x31, True, True, True).digit == 1
    assert engine.handle(0x61, True, True, True).digit == 1
    assert engine.handle(0x31, False, False, False).consume
    assert engine.handle(0x61, True, True, True).consume
    assert engine.handle(0x61, True, True, True).digit is None
    assert engine.handle(0x61, False, False, False).consume


@pytest.mark.skipif(sys.platform != "win32", reason="requires the Windows hook API")
def test_hook_thread_starts_and_stops_without_synthesizing_keys():
    hook = LowLevelKeyboardHook(lambda: False)
    try:
        hook.start()
        assert hook.is_running
    finally:
        hook.stop(timeout=2.0)
    assert not hook.is_running
    assert not any(
        thread.name == "ShiyiKeyboardHook" and thread.is_alive()
        for thread in threading.enumerate()
    )
