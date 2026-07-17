from shiyi_desktop_pet.animation_player import AnimationTimeline
from shiyi_desktop_pet.models import ActionId


def test_wave_runs_exactly_two_loops_then_finishes():
    timeline = AnimationTimeline()
    timeline.start(ActionId.WAVE, now_ms=0)
    assert timeline.advance(0).frame_index == 0
    assert timeline.advance(1050).frame_index == 3
    assert not timeline.advance(1050).finished
    assert timeline.advance(1200).finished


def test_belly_flop_holds_last_frame_for_one_second():
    timeline = AnimationTimeline()
    timeline.start(ActionId.BELLY_FLOP, now_ms=0)
    assert timeline.advance(1199).frame_index == 7
    assert not timeline.advance(2199).finished
    assert timeline.advance(2200).finished
