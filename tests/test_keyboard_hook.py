import ctypes
import sys

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy

import shiyi_desktop_pet.keyboard_hook as keyboard_hook
from shiyi_desktop_pet.keyboard_hook import (
    KeyboardDecisionEngine,
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


def test_consumed_keys_are_tracked_by_virtual_key():
    engine = KeyboardDecisionEngine()
    assert engine.handle(0x31, True, True, True).digit == 1
    assert engine.handle(0x61, True, True, True).digit == 1
    assert engine.handle(0x31, False, False, False).consume
    assert engine.handle(0x61, True, True, True).consume
    assert engine.handle(0x61, True, True, True).digit is None
    assert engine.handle(0x61, False, False, False).consume


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows callback types")
def test_callback_passes_unhandled_events_and_queues_one_digit(qapp):
    hit_test_calls = 0

    def hit_test():
        nonlocal hit_test_calls
        hit_test_calls += 1
        if hit_test_calls > 1:
            raise AssertionError("a consumed repeat must use decision-engine state")
        return True

    passed_events = []
    hook = LowLevelKeyboardHook(hit_test)
    emitted_digits = QSignalSpy(hook.digit_pressed)
    hook._call_next_hook = lambda handle, code, message, data: (
        passed_events.append((code, message, data)) or 73
    )
    event = keyboard_hook._KBDLLHOOKSTRUCT(vkCode=0x32)
    event_pointer = ctypes.addressof(event)

    assert hook._hook_callback(-1, keyboard_hook.WM_KEYDOWN, event_pointer) == 73
    assert hook._hook_callback(0, 0x0200, event_pointer) == 73
    assert hook._hook_callback(0, keyboard_hook.WM_KEYDOWN, event_pointer) == 1
    assert hook._hook_callback(0, keyboard_hook.WM_KEYDOWN, event_pointer) == 1
    assert hook._hook_callback(0, keyboard_hook.WM_KEYUP, event_pointer) == 1
    assert emitted_digits.count() == 0
    QCoreApplication.processEvents()
    assert hit_test_calls == 1
    assert len(passed_events) == 2
    assert emitted_digits.count() == 1
    assert emitted_digits.at(0) == [2]


@pytest.mark.skipif(sys.platform != "win32", reason="requires the Windows hook API")
def test_hook_thread_starts_and_stops_without_synthesizing_keys():
    hook = LowLevelKeyboardHook(lambda: False)
    try:
        hook.start()
        assert hook.is_running
    finally:
        hook.stop(timeout=2.0)
    assert not hook.is_running
