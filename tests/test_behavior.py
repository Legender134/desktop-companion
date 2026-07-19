from shiyi_desktop_pet.behavior import BehaviorEngine, BehaviorMode
from shiyi_desktop_pet.models import ActionId


def test_priority_and_manual_return_to_remembered_wander():
    engine = BehaviorEngine()
    engine.set_wander_enabled(True)
    assert engine.mode is BehaviorMode.WANDER
    engine.trigger_manual(ActionId.WAVE)
    assert engine.mode is BehaviorMode.MANUAL_ACTION
    engine.begin_drag()
    assert engine.mode is BehaviorMode.DRAGGING
    engine.end_drag()
    assert engine.mode is BehaviorMode.MANUAL_ACTION
    engine.manual_finished()
    assert engine.mode is BehaviorMode.WANDER


def test_manual_idle_disables_current_action_but_not_saved_wander_setting():
    engine = BehaviorEngine(wander_enabled=True)
    engine.trigger_manual(ActionId.IDLE)
    assert engine.mode is BehaviorMode.IDLE
    assert engine.wander_enabled


def test_manual_trigger_during_drag_is_deferred_until_drag_ends():
    engine = BehaviorEngine()
    engine.trigger_manual(ActionId.WAVE)
    engine.begin_drag()

    engine.trigger_manual(ActionId.JUMP)

    assert engine.mode is BehaviorMode.DRAGGING
    assert engine.current_action is ActionId.JUMP
    engine.end_drag()
    assert engine.mode is BehaviorMode.MANUAL_ACTION


def test_manual_completion_during_drag_waits_for_drag_end_then_returns_to_base():
    engine = BehaviorEngine(gaze_degrees=0.0)
    engine.trigger_manual(ActionId.WAVE)
    engine.begin_drag()

    engine.manual_finished()

    assert engine.mode is BehaviorMode.DRAGGING
    assert engine.current_action is None
    engine.end_drag()
    assert engine.mode is BehaviorMode.GAZE


def test_wander_setting_changed_during_drag_is_used_after_drag_ends():
    engine = BehaviorEngine()
    engine.set_wander_enabled(True)
    engine.begin_drag()

    engine.set_wander_enabled(False)

    assert engine.mode is BehaviorMode.DRAGGING
    engine.end_drag()
    assert engine.mode is BehaviorMode.IDLE


def test_constructor_derives_the_configured_base_mode():
    assert BehaviorEngine(wander_enabled=True).mode is BehaviorMode.WANDER
    assert BehaviorEngine(gaze_degrees=0.0).mode is BehaviorMode.GAZE
    assert BehaviorEngine().mode is BehaviorMode.IDLE


def test_live_gaze_takes_priority_over_wander_and_releases_back_to_it():
    engine = BehaviorEngine(wander_enabled=True)
    engine.request_gaze(45.0)
    assert engine.mode is BehaviorMode.GAZE

    engine.request_gaze(None)
    assert engine.mode is BehaviorMode.WANDER


def test_shutdown_cannot_be_resurrected_by_normal_intents():
    engine = BehaviorEngine()
    engine.begin_shutdown()

    engine.trigger_manual(ActionId.WAVE)
    engine.manual_finished()
    engine.begin_drag()
    engine.end_drag()
    engine.set_wander_enabled(True)
    engine.request_gaze(0.0)

    assert engine.mode is BehaviorMode.SHUTTING_DOWN


def test_repeated_and_unpaired_drag_calls_are_safe():
    engine = BehaviorEngine(wander_enabled=True)

    engine.end_drag()
    assert engine.mode is BehaviorMode.WANDER
    engine.begin_drag()
    engine.begin_drag()
    assert engine.mode is BehaviorMode.DRAGGING
    engine.end_drag()
    assert engine.mode is BehaviorMode.WANDER
    engine.end_drag()
    assert engine.mode is BehaviorMode.WANDER
