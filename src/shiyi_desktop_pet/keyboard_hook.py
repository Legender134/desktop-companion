from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass

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
_CONSUME_KEYUP_OR_REPEAT = HookDecision(consume=True)


def _digit_for_virtual_key(vk_code: int) -> int | None:
    if 0x30 <= vk_code <= 0x39:
        return vk_code - 0x30
    if 0x60 <= vk_code <= 0x69:
        return vk_code - 0x60
    return None


class KeyboardDecisionEngine:
    """Pure state machine deciding which digit events belong to the pet."""

    def __init__(self) -> None:
        self._consumed_keys: set[int] = set()

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
            if vk_code in self._consumed_keys:
                return _CONSUME_KEYUP_OR_REPEAT
            if not enabled or not hovered:
                return _PASS_THROUGH
            self._consumed_keys.add(vk_code)
            return HookDecision(consume=True, digit=digit)

        if vk_code not in self._consumed_keys:
            return _PASS_THROUGH
        self._consumed_keys.remove(vk_code)
        return _CONSUME_KEYUP_OR_REPEAT


@dataclass(frozen=True, slots=True)
class _HookInputSnapshot:
    """Atomically replaced UI-owned inputs read by the hook callback."""

    enabled: bool
    hover_hit_test: Callable[[], bool]


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


class LowLevelKeyboardHook(QObject):
    """Own a Windows low-level keyboard hook and its message-loop thread."""

    digit_pressed = Signal(int)
    _digit_detected = Signal(int)

    def __init__(
        self,
        hover_hit_test: Callable[[], bool],
        *,
        enabled: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not callable(hover_hit_test):
            raise TypeError("hover_hit_test must be callable")

        self._input_snapshot = _HookInputSnapshot(bool(enabled), hover_hit_test)
        self._engine = KeyboardDecisionEngine()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hook_handle: int | None = None
        self._callback = None
        self._startup_error: BaseException | None = None
        self._ready = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._digit_detected.connect(
            self._deliver_digit,
            Qt.ConnectionType.QueuedConnection,
        )

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

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
        if sys.platform != "win32":
            raise OSError("low-level keyboard hooks are available only on Windows")
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready.clear()
            self._startup_error = None
            self._thread = threading.Thread(
                target=self._run_hook_loop,
                name="ShiyiKeyboardHook",
                daemon=False,
            )
            thread = self._thread
            thread.start()

        if not self._ready.wait(timeout):
            self.stop(timeout=timeout)
            raise TimeoutError("keyboard hook thread did not start in time")
        if self._startup_error is not None:
            thread.join(timeout)
            error = self._startup_error
            with self._lifecycle_lock:
                if self._thread is thread:
                    self._thread = None
            raise RuntimeError("could not install keyboard hook") from error

    def stop(self, timeout: float = 2.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        with self._lifecycle_lock:
            thread = self._thread
            thread_id = self._thread_id
        if thread is None:
            return

        if thread.is_alive() and thread_id is not None:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            post_thread_message = user32.PostThreadMessageW
            post_thread_message.argtypes = (
                ctypes.c_ulong,
                ctypes.c_uint,
                ctypes.c_size_t,
                ctypes.c_ssize_t,
            )
            post_thread_message.restype = ctypes.c_int
            post_thread_message(thread_id, WM_QUIT, 0, 0)

        thread.join(timeout)
        if thread.is_alive():
            raise TimeoutError("keyboard hook thread did not stop in time")
        with self._lifecycle_lock:
            if self._thread is thread:
                self._thread = None

    @Slot(int)
    def _deliver_digit(self, digit: int) -> None:
        self.digit_pressed.emit(digit)

    def _run_hook_loop(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        set_windows_hook = user32.SetWindowsHookExW
        set_windows_hook.argtypes = (
            ctypes.c_int,
            _LowLevelKeyboardProc,
            ctypes.c_void_p,
            ctypes.c_ulong,
        )
        set_windows_hook.restype = ctypes.c_void_p

        unhook_windows_hook = user32.UnhookWindowsHookEx
        unhook_windows_hook.argtypes = (ctypes.c_void_p,)
        unhook_windows_hook.restype = ctypes.c_int

        call_next_hook = user32.CallNextHookEx
        call_next_hook.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            WPARAM,
            LPARAM,
        )
        call_next_hook.restype = LRESULT
        self._call_next_hook = call_next_hook

        get_message = user32.GetMessageW
        get_message.argtypes = (
            ctypes.POINTER(wintypes.MSG),
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
        )
        get_message.restype = ctypes.c_int

        peek_message = user32.PeekMessageW
        peek_message.argtypes = (
            ctypes.POINTER(wintypes.MSG),
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
        )
        peek_message.restype = ctypes.c_int

        get_current_thread_id = kernel32.GetCurrentThreadId
        get_current_thread_id.restype = ctypes.c_ulong
        get_module_handle = kernel32.GetModuleHandleW
        get_module_handle.argtypes = (wintypes.LPCWSTR,)
        get_module_handle.restype = ctypes.c_void_p

        hook_handle = None
        try:
            message = wintypes.MSG()
            self._thread_id = int(get_current_thread_id())
            peek_message(ctypes.byref(message), None, 0, 0, PM_NOREMOVE)

            callback = _LowLevelKeyboardProc(self._hook_callback)
            self._callback = callback
            hook_handle = set_windows_hook(
                WH_KEYBOARD_LL,
                callback,
                get_module_handle(None),
                0,
            )
            if not hook_handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self._hook_handle = hook_handle
            self._ready.set()

            while True:
                result = get_message(ctypes.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as error:
            self._startup_error = error
        finally:
            if hook_handle:
                unhook_windows_hook(hook_handle)
            self._hook_handle = None
            self._callback = None
            self._thread_id = None
            self._ready.set()

    def _hook_callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code < 0:
            return self._pass_to_next(n_code, w_param, l_param)

        message = int(w_param)
        if message not in _KEYDOWN_MESSAGES and message not in _KEYUP_MESSAGES:
            return self._pass_to_next(n_code, w_param, l_param)

        try:
            vk_code = int(
                ctypes.cast(
                    l_param,
                    ctypes.POINTER(_KBDLLHOOKSTRUCT),
                ).contents.vkCode
            )
            is_down = message in _KEYDOWN_MESSAGES
            snapshot = self._input_snapshot
            decision = self._engine.handle(
                vk_code,
                is_down=is_down,
                enabled=snapshot.enabled,
                hovered=False,
            )
            if (
                is_down
                and not decision.consume
                and snapshot.enabled
                and _digit_for_virtual_key(vk_code) is not None
                and snapshot.hover_hit_test()
            ):
                decision = self._engine.handle(
                    vk_code,
                    is_down=True,
                    enabled=True,
                    hovered=True,
                )
        except BaseException:
            return self._pass_to_next(n_code, w_param, l_param)

        if decision.digit is not None:
            self._digit_detected.emit(decision.digit)
        if decision.consume:
            return 1
        return self._pass_to_next(n_code, w_param, l_param)

    def _pass_to_next(self, n_code: int, w_param: int, l_param: int) -> int:
        return int(self._call_next_hook(self._hook_handle, n_code, w_param, l_param))
