from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from PySide6.QtCore import QObject, Qt, Signal, Slot

from .constants import KEY_TO_ACTION


WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
PM_NOREMOVE = 0x0000

_KEYDOWN_MESSAGES = frozenset((WM_KEYDOWN, WM_SYSKEYDOWN))
_KEYUP_MESSAGES = frozenset((WM_KEYUP, WM_SYSKEYUP))


@dataclass(frozen=True, slots=True)
class HookDecision:
    consume: bool
    digit: int | None = None


_PASS_THROUGH = HookDecision(consume=False)
_CONSUME_WITHOUT_EMIT = HookDecision(consume=True)


def _digit_for_virtual_key(vk_code: int) -> int | None:
    if 0x30 <= vk_code <= 0x39:
        return vk_code - 0x30
    if 0x60 <= vk_code <= 0x69:
        return vk_code - 0x60
    return None


class KeyboardDecisionEngine:
    """Track the consume decision made by every recognized physical press."""

    def __init__(self) -> None:
        self._down_keys: dict[int, bool] = {}

    def handle(
        self,
        vk_code: int,
        is_down: bool,
        enabled: bool,
        hovered: bool,
    ) -> HookDecision:
        digit = _digit_for_virtual_key(vk_code)
        if digit is None or digit not in KEY_TO_ACTION:
            return _PASS_THROUGH

        if is_down:
            if vk_code in self._down_keys:
                if self._down_keys[vk_code]:
                    return _CONSUME_WITHOUT_EMIT
                return _PASS_THROUGH

            consume = bool(enabled and hovered)
            self._down_keys[vk_code] = consume
            if consume:
                return HookDecision(consume=True, digit=digit)
            return _PASS_THROUGH

        consume = self._down_keys.pop(vk_code, False)
        if consume:
            return _CONSUME_WITHOUT_EMIT
        return _PASS_THROUGH

    def is_down(self, vk_code: int) -> bool:
        return vk_code in self._down_keys

    def mark_press_passed_through(self, vk_code: int) -> None:
        if vk_code in self._down_keys:
            self._down_keys[vk_code] = False


@dataclass(frozen=True, slots=True)
class _HookInputSnapshot:
    enabled: bool
    hover_hit_test: Callable[[], bool]


class HookLifecycleState(Enum):
    STOPPED = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    FAILED = auto()


class KeyboardHookError(RuntimeError):
    """A sanitized hook failure that never contains keyboard event data."""


class _WorkerFailure(Exception):
    def __init__(self, public_message: str, cause: BaseException | None = None):
        super().__init__(public_message)
        self.public_message = public_message
        self.cause = cause


class _KeyboardBackend(Protocol):
    def prepare(self) -> int: ...

    def make_callback(self, target: Callable[[int, int, int], int]) -> object: ...

    def install(self, callback: object) -> object: ...

    def get_message(self) -> int: ...

    def post_quit(self, thread_id: int) -> bool: ...

    def unhook(self, handle: object) -> bool: ...

    def call_next(self, handle: object | None, code: int, message: int, data: int) -> int: ...

    def decode_vk(self, data: int) -> int: ...

    def error(self, operation: str) -> BaseException: ...


if sys.platform == "win32":
    from ctypes import wintypes

    LRESULT = ctypes.c_ssize_t
    LPARAM = ctypes.c_ssize_t
    WPARAM = ctypes.c_size_t
    ULONG_PTR = ctypes.c_size_t

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = (
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        )

    _LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
        LRESULT,
        ctypes.c_int,
        WPARAM,
        LPARAM,
    )


class _WindowsKeyboardBackend:
    """Small typed Win32 surface, constructed only inside the hook worker."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("low-level keyboard hooks are available only on Windows")

        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._message = wintypes.MSG()

        self._set_windows_hook = self._user32.SetWindowsHookExW
        self._set_windows_hook.argtypes = (
            ctypes.c_int,
            _LowLevelKeyboardProc,
            ctypes.c_void_p,
            ctypes.c_ulong,
        )
        self._set_windows_hook.restype = ctypes.c_void_p

        self._unhook_windows_hook = self._user32.UnhookWindowsHookEx
        self._unhook_windows_hook.argtypes = (ctypes.c_void_p,)
        self._unhook_windows_hook.restype = ctypes.c_int

        self._call_next_hook = self._user32.CallNextHookEx
        self._call_next_hook.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            WPARAM,
            LPARAM,
        )
        self._call_next_hook.restype = LRESULT

        self._get_message = self._user32.GetMessageW
        self._get_message.argtypes = (
            ctypes.POINTER(wintypes.MSG),
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
        )
        self._get_message.restype = ctypes.c_int

        self._peek_message = self._user32.PeekMessageW
        self._peek_message.argtypes = (
            ctypes.POINTER(wintypes.MSG),
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
        )
        self._peek_message.restype = ctypes.c_int

        self._post_thread_message = self._user32.PostThreadMessageW
        self._post_thread_message.argtypes = (
            ctypes.c_ulong,
            ctypes.c_uint,
            WPARAM,
            LPARAM,
        )
        self._post_thread_message.restype = ctypes.c_int

        self._get_current_thread_id = self._kernel32.GetCurrentThreadId
        self._get_current_thread_id.restype = ctypes.c_ulong
        self._get_module_handle = self._kernel32.GetModuleHandleW
        self._get_module_handle.argtypes = (wintypes.LPCWSTR,)
        self._get_module_handle.restype = ctypes.c_void_p

    def prepare(self) -> int:
        thread_id = int(self._get_current_thread_id())
        self._peek_message(
            ctypes.byref(self._message),
            None,
            0,
            0,
            PM_NOREMOVE,
        )
        return thread_id

    def make_callback(self, target: Callable[[int, int, int], int]) -> object:
        return _LowLevelKeyboardProc(target)

    def install(self, callback: object) -> object:
        return self._set_windows_hook(
            WH_KEYBOARD_LL,
            callback,
            self._get_module_handle(None),
            0,
        )

    def get_message(self) -> int:
        return int(self._get_message(ctypes.byref(self._message), None, 0, 0))

    def post_quit(self, thread_id: int) -> bool:
        return bool(self._post_thread_message(thread_id, WM_QUIT, 0, 0))

    def unhook(self, handle: object) -> bool:
        return bool(self._unhook_windows_hook(handle))

    def call_next(
        self,
        handle: object | None,
        code: int,
        message: int,
        data: int,
    ) -> int:
        return int(self._call_next_hook(handle, code, message, data))

    def decode_vk(self, data: int) -> int:
        return int(
            ctypes.cast(
                data,
                ctypes.POINTER(_KBDLLHOOKSTRUCT),
            ).contents.vkCode
        )

    def error(self, operation: str) -> BaseException:
        return ctypes.WinError(ctypes.get_last_error())


class LowLevelKeyboardHook(QObject):
    """Coordinate a Windows keyboard hook through an auditable state machine."""

    digit_pressed = Signal(int)
    hook_failed = Signal(str)
    _digit_detected = Signal(int)
    _failure_detected = Signal(str)

    def __init__(
        self,
        hover_hit_test: Callable[[], bool],
        *,
        enabled: bool = True,
        parent: QObject | None = None,
        backend_factory: Callable[[], _KeyboardBackend] | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
    ) -> None:
        super().__init__(parent)
        if not callable(hover_hit_test):
            raise TypeError("hover_hit_test must be callable")

        self._input_snapshot = _HookInputSnapshot(bool(enabled), hover_hit_test)
        self._backend_factory = backend_factory or _WindowsKeyboardBackend
        self._thread_factory = thread_factory or threading.Thread
        self._condition = threading.Condition(threading.RLock())
        self._state = HookLifecycleState.STOPPED
        self._generation = 0
        self._generation_results: dict[int, KeyboardHookError | None] = {}
        self._last_error: KeyboardHookError | None = None
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._backend: _KeyboardBackend | None = None
        self._callback: object | None = None
        self._hook_handle: object | None = None
        self._engine = KeyboardDecisionEngine()
        self._stop_requested = False
        self._control_error: KeyboardHookError | None = None

        self._digit_detected.connect(
            self._deliver_digit,
            Qt.ConnectionType.QueuedConnection,
        )
        self._failure_detected.connect(
            self._deliver_failure,
            Qt.ConnectionType.QueuedConnection,
        )

    @property
    def state(self) -> HookLifecycleState:
        with self._condition:
            return self._state

    @property
    def last_error(self) -> KeyboardHookError | None:
        with self._condition:
            return self._last_error

    @property
    def is_running(self) -> bool:
        with self._condition:
            thread = self._thread
            return self._state is HookLifecycleState.RUNNING and bool(
                thread is not None and thread.is_alive()
            )

    def set_enabled(self, enabled: bool) -> None:
        snapshot = self._input_snapshot
        self._input_snapshot = _HookInputSnapshot(
            bool(enabled),
            snapshot.hover_hit_test,
        )

    def set_hover_hit_test(self, hover_hit_test: Callable[[], bool]) -> None:
        if not callable(hover_hit_test):
            raise TypeError("hover_hit_test must be callable")
        snapshot = self._input_snapshot
        self._input_snapshot = _HookInputSnapshot(
            snapshot.enabled,
            hover_hit_test,
        )

    def start(self, timeout: float = 2.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if sys.platform != "win32" and self._backend_factory is _WindowsKeyboardBackend:
            raise OSError("low-level keyboard hooks are available only on Windows")

        deadline = time.monotonic() + timeout
        with self._condition:
            while self._state is HookLifecycleState.STOPPING:
                self._wait_locked(deadline, "keyboard hook stop did not finish")

            if self._state is HookLifecycleState.RUNNING:
                return
            if self._state is HookLifecycleState.FAILED:
                raise self._last_error or KeyboardHookError("keyboard hook failed")

            if self._state is HookLifecycleState.STOPPED:
                self._generation += 1
                installation_generation = self._generation
                self._engine = KeyboardDecisionEngine()
                self._stop_requested = False
                self._control_error = None
                self._last_error = None
                self._backend = None
                self._thread_id = None
                self._callback = None
                self._hook_handle = None
                self._state = HookLifecycleState.STARTING
                try:
                    thread = self._thread_factory(
                        target=lambda: self._run_hook_worker(
                            installation_generation
                        ),
                        name="ShiyiKeyboardHook",
                        daemon=False,
                    )
                except BaseException:
                    error = KeyboardHookError(
                        "keyboard hook thread construction failed"
                    )
                    self._thread = None
                    self._last_error = error
                    self._generation_results[installation_generation] = error
                    self._state = HookLifecycleState.FAILED
                    self._condition.notify_all()
                    self._publish_failure(str(error))
                    raise error

                self._thread = thread
                try:
                    thread.start()
                except BaseException:
                    error = KeyboardHookError("keyboard hook thread start failed")
                    self._thread = None
                    self._last_error = error
                    self._generation_results[installation_generation] = error
                    self._state = HookLifecycleState.FAILED
                    self._condition.notify_all()
                    self._publish_failure(str(error))
                    raise error
            else:
                installation_generation = self._generation

            installation_thread = self._thread
            try:
                while (
                    self._generation == installation_generation
                    and self._thread is installation_thread
                    and self._state
                    in (HookLifecycleState.STARTING, HookLifecycleState.STOPPING)
                ):
                    self._wait_locked(deadline, "keyboard hook start timed out")
            except TimeoutError:
                if (
                    self._generation == installation_generation
                    and self._thread is installation_thread
                    and self._state is HookLifecycleState.STARTING
                ):
                    self._stop_requested = True
                    self._state = HookLifecycleState.STOPPING
                    self._condition.notify_all()
                raise

            if (
                self._generation == installation_generation
                and self._thread is installation_thread
                and self._state is HookLifecycleState.RUNNING
            ):
                return
            generation_result = self._generation_results.get(
                installation_generation
            )
            if generation_result is not None:
                raise generation_result
            if (
                self._generation == installation_generation
                and self._state is HookLifecycleState.FAILED
            ):
                raise self._last_error or KeyboardHookError(
                    "keyboard hook start failed"
                )
            raise KeyboardHookError("keyboard hook start was cancelled")

    def stop(self, timeout: float = 2.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        deadline = time.monotonic() + timeout

        with self._condition:
            waited_for_existing_stop = False
            while self._state is HookLifecycleState.STOPPING:
                waited_for_existing_stop = True
                self._wait_locked(deadline, "keyboard hook shutdown timed out")

            if self._state is HookLifecycleState.STOPPED:
                return
            if self._state is HookLifecycleState.FAILED:
                if waited_for_existing_stop:
                    raise self._last_error or KeyboardHookError(
                        "keyboard hook shutdown failed"
                    )
                retry = self._take_failed_cleanup_locked()
                if retry is None:
                    self._reset_stopped_locked()
                    return
                self._state = HookLifecycleState.STOPPING
                self._condition.notify_all()
            else:
                retry = None

            if retry is None and self._state in (
                HookLifecycleState.STARTING,
                HookLifecycleState.RUNNING,
            ):
                self._stop_requested = True
                self._state = HookLifecycleState.STOPPING
                self._condition.notify_all()

            if retry is None:
                while (
                    self._state is HookLifecycleState.STOPPING
                    and self._backend is None
                    and self._thread is not None
                    and self._thread.is_alive()
                ):
                    self._wait_locked(deadline, "keyboard hook shutdown timed out")
                backend = self._backend
                thread_id = self._thread_id
                thread = self._thread
                stop_generation = self._generation

        if retry is not None:
            backend, handle = retry
            self._retry_failed_unhook(backend, handle)
            return

        if (
            backend is not None
            and thread_id is not None
            and thread is not None
            and thread.is_alive()
        ):
            try:
                posted = bool(backend.post_quit(thread_id))
            except BaseException:
                posted = False
            if not posted:
                post_error = KeyboardHookError(
                    "keyboard hook shutdown request failed"
                )
                with self._condition:
                    if (
                        self._generation == stop_generation
                        and self._thread is thread
                        and thread.is_alive()
                        and self._state is HookLifecycleState.STOPPING
                    ):
                        self._stop_requested = False
                        self._control_error = None
                        self._last_error = post_error
                        self._state = HookLifecycleState.RUNNING
                        self._condition.notify_all()
                        self._publish_failure(str(post_error))
                        raise post_error

        if thread is not None:
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(remaining)
            if thread.is_alive():
                raise TimeoutError("keyboard hook shutdown timed out")

        with self._condition:
            result_known = stop_generation in self._generation_results
            generation_result = self._generation_results.get(stop_generation)
            if result_known:
                if generation_result is not None:
                    raise generation_result
                return
            if self._generation != stop_generation:
                raise KeyboardHookError(
                    "keyboard hook shutdown result unavailable"
                )
            if self._state is HookLifecycleState.FAILED:
                raise self._last_error or KeyboardHookError(
                    "keyboard hook shutdown failed"
                )
            if self._state is not HookLifecycleState.STOPPED:
                raise KeyboardHookError("keyboard hook shutdown did not complete")

    def _wait_locked(self, deadline: float, message: str) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(message)
        self._condition.wait(remaining)

    def _take_failed_cleanup_locked(
        self,
    ) -> tuple[_KeyboardBackend, object] | None:
        if self._backend is None or self._hook_handle is None:
            return None
        return self._backend, self._hook_handle

    def _retry_failed_unhook(
        self,
        backend: _KeyboardBackend,
        handle: object,
    ) -> None:
        try:
            removed = bool(backend.unhook(handle))
        except BaseException:
            removed = False
        if not removed:
            error = KeyboardHookError("keyboard hook unhook failed")
            with self._condition:
                self._last_error = error
                self._state = HookLifecycleState.FAILED
                self._condition.notify_all()
            self._publish_failure(str(error))
            raise error

        with self._condition:
            if self._hook_handle is handle:
                self._hook_handle = None
                self._callback = None
                self._backend = None
                self._thread_id = None
            self._generation_results[self._generation] = None
            self._reset_stopped_locked()

    def _reset_stopped_locked(self) -> None:
        self._engine = KeyboardDecisionEngine()
        self._stop_requested = False
        self._control_error = None
        self._state = HookLifecycleState.STOPPED
        self._condition.notify_all()

    def _run_hook_worker(self, generation: int) -> None:
        backend: _KeyboardBackend | None = None
        callback: object | None = None
        hook_handle: object | None = None
        public_error: KeyboardHookError | None = None
        phase = "start"
        unhook_confirmed = True

        try:
            backend = self._backend_factory()
            thread_id = backend.prepare()
            with self._condition:
                if generation != self._generation:
                    return
                self._backend = backend
                self._thread_id = thread_id
                self._condition.notify_all()
                if self._stop_requested:
                    return

            callback = backend.make_callback(self._native_callback_no_throw)
            with self._condition:
                if generation != self._generation:
                    return
                self._callback = callback

            hook_handle = backend.install(callback)
            if not hook_handle:
                raise _WorkerFailure(
                    "keyboard hook start failed",
                    backend.error("SetWindowsHookExW"),
                )

            with self._condition:
                if generation != self._generation:
                    return
                self._hook_handle = hook_handle
                if self._stop_requested:
                    self._state = HookLifecycleState.STOPPING
                else:
                    self._state = HookLifecycleState.RUNNING
                self._condition.notify_all()
                should_stop = self._stop_requested

            if should_stop:
                return

            phase = "message loop"
            while True:
                result = backend.get_message()
                if result == 0:
                    with self._condition:
                        expected_stop = self._stop_requested
                    if expected_stop:
                        break
                    raise _WorkerFailure(
                        "keyboard hook message loop stopped unexpectedly"
                    )
                if result == -1:
                    raise _WorkerFailure(
                        "keyboard hook message loop failed",
                        backend.error("GetMessageW"),
                    )
        except _WorkerFailure as error:
            public_error = KeyboardHookError(error.public_message)
        except BaseException:
            if phase == "start":
                public_error = KeyboardHookError("keyboard hook start failed")
            else:
                public_error = KeyboardHookError("keyboard hook message loop failed")
        finally:
            if hook_handle is not None and backend is not None:
                try:
                    unhook_confirmed = bool(backend.unhook(hook_handle))
                except BaseException:
                    unhook_confirmed = False
                if not unhook_confirmed:
                    public_error = KeyboardHookError("keyboard hook unhook failed")

            with self._condition:
                if (
                    generation == self._generation
                    and public_error is None
                    and self._control_error is not None
                ):
                    public_error = self._control_error

                self._generation_results[generation] = public_error
                if generation == self._generation:
                    self._engine = KeyboardDecisionEngine()
                    self._stop_requested = False
                    self._control_error = None
                    self._thread_id = None

                    if unhook_confirmed:
                        self._hook_handle = None
                        self._callback = None
                        self._backend = None
                    else:
                        self._hook_handle = hook_handle
                        self._callback = callback
                        self._backend = backend

                    if public_error is not None:
                        self._last_error = public_error
                        self._state = HookLifecycleState.FAILED
                    else:
                        self._state = HookLifecycleState.STOPPED
                self._condition.notify_all()

            if public_error is not None:
                self._publish_failure(str(public_error))

    def _native_callback_no_throw(
        self,
        n_code: int,
        w_param: int,
        l_param: int,
    ) -> int:
        try:
            return int(self._process_hook_event(n_code, w_param, l_param))
        except BaseException:
            self._record_callback_failure("keyboard hook callback failed")
            return self._call_next_no_throw(n_code, w_param, l_param)

    def _process_hook_event(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code < 0:
            return self._call_next_no_throw(n_code, w_param, l_param)

        message = int(w_param)
        if message not in _KEYDOWN_MESSAGES and message not in _KEYUP_MESSAGES:
            return self._call_next_no_throw(n_code, w_param, l_param)

        backend = self._backend
        if backend is None:
            raise RuntimeError("keyboard hook backend unavailable")
        vk_code = backend.decode_vk(l_param)
        digit = _digit_for_virtual_key(vk_code)
        if digit is None or digit not in KEY_TO_ACTION:
            return self._call_next_no_throw(n_code, w_param, l_param)

        is_down = message in _KEYDOWN_MESSAGES
        snapshot = self._input_snapshot
        hovered = False
        if is_down and not self._engine.is_down(vk_code) and snapshot.enabled:
            try:
                hovered = bool(snapshot.hover_hit_test())
            except BaseException:
                self._engine.handle(vk_code, True, False, False)
                self._record_callback_failure("keyboard hook hit test failed")
                return self._call_next_no_throw(n_code, w_param, l_param)

        decision = self._engine.handle(
            vk_code,
            is_down=is_down,
            enabled=snapshot.enabled,
            hovered=hovered,
        )
        if decision.digit is not None:
            try:
                self._queue_digit(decision.digit)
            except BaseException:
                try:
                    self._engine.mark_press_passed_through(vk_code)
                except BaseException:
                    pass
                self._record_callback_failure("keyboard hook queued delivery failed")
                return self._call_next_no_throw(n_code, w_param, l_param)
        if decision.consume:
            return 1
        return self._call_next_no_throw(n_code, w_param, l_param)

    def _queue_digit(self, digit: int) -> None:
        self._digit_detected.emit(digit)

    def _call_next_no_throw(self, n_code: int, w_param: int, l_param: int) -> int:
        try:
            backend = self._backend
            if backend is None:
                return 0
            return int(
                backend.call_next(
                    self._hook_handle,
                    n_code,
                    w_param,
                    l_param,
                )
            )
        except BaseException:
            self._record_callback_failure("keyboard hook chaining failed")
            return 0

    def _record_callback_failure(self, message: str) -> None:
        try:
            error = KeyboardHookError(message)
            with self._condition:
                self._last_error = error
            self._publish_failure(message)
        except BaseException:
            pass

    def _publish_failure(self, message: str) -> None:
        try:
            self._failure_detected.emit(message)
        except BaseException:
            pass

    @Slot(int)
    def _deliver_digit(self, digit: int) -> None:
        self.digit_pressed.emit(digit)

    @Slot(str)
    def _deliver_failure(self, message: str) -> None:
        self.hook_failed.emit(message)
