from shiyi_desktop_pet.animation_catalog import AnimationCatalog
from shiyi_desktop_pet.animation_player import AnimationTimeline
from shiyi_desktop_pet.models import ActionId, AnimationSpec


def test_wave_runs_exactly_three_loops_then_finishes():
    timeline = AnimationTimeline()
    timeline.start(ActionId.WAVE, now_ms=0)
    assert timeline.advance(0).frame_index == 0
    assert timeline.advance(1050).frame_index == 3
    assert not timeline.advance(1050).finished
    assert not timeline.advance(1799).finished
    assert timeline.advance(1800).finished


def test_belly_flop_holds_last_frame_for_one_second():
    timeline = AnimationTimeline()
    timeline.start(ActionId.BELLY_FLOP, now_ms=0)
    assert timeline.advance(1199).frame_index == 7
    assert not timeline.advance(2199).finished
    assert timeline.advance(2200).finished


def test_finite_animation_finishes_at_its_new_exact_boundary_without_a_hold():
    timeline = AnimationTimeline()
    timeline.start(ActionId.WAVE, now_ms=0)

    assert not timeline.advance(1799).finished
    assert timeline.advance(1800).finished


def test_jump_holds_its_landing_frame_for_four_hundred_milliseconds():
    timeline = AnimationTimeline()
    timeline.start(ActionId.JUMP, now_ms=0)

    assert not timeline.advance(999).finished
    assert timeline.advance(1000).finished


def test_idle_wraps_indefinitely_and_clamps_pre_start_timestamps():
    timeline = AnimationTimeline()
    timeline.start(ActionId.IDLE, now_ms=100)

    assert timeline.advance(0).frame_index == 0
    assert not timeline.advance(0).finished
    assert timeline.advance(100 + 7 * 180).frame_index == 0
    assert timeline.advance(100 + 9 * 180).frame_index == 2


def test_dynamic_per_frame_durations_and_repeat_count_are_honored():
    timeline = AnimationTimeline()
    spec = AnimationSpec(
        row=0,
        frame_count=3,
        frame_ms=100,
        loops=2,
        frame_durations=(50, 100, 200),
    )
    timeline.start("custom", 0)

    assert timeline.advance(49, spec).frame_index == 0
    assert timeline.advance(50, spec).frame_index == 1
    assert timeline.advance(149, spec).frame_index == 1
    assert timeline.advance(150, spec).frame_index == 2
    assert timeline.advance(349, spec).frame_index == 2
    assert timeline.advance(350, spec).frame_index == 0
    assert timeline.advance(699, spec).frame_index == 2
    assert timeline.advance(700, spec).finished


def test_complete_showcase_finishes_at_its_exact_82433_ms_boundary():
    catalog = AnimationCatalog.load_pet("nangongwan")
    spec = catalog.spec("completeShowcase")
    timeline = AnimationTimeline()
    timeline.start("completeShowcase", now_ms=1_000)

    assert not timeline.advance(83_432, spec).finished
    assert timeline.advance(83_433, spec).finished
