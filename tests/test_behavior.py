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
