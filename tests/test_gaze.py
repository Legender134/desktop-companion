import math

from shiyi_desktop_pet.gaze import GazeStabilizer, quantize_gaze


def test_screen_vectors_map_clockwise_from_up():
    assert quantize_gaze(0, -100, 18) == 0.0
    assert quantize_gaze(100, 0, 18) == 90.0
    assert quantize_gaze(0, 100, 18) == 180.0
    assert quantize_gaze(-100, 0, 18) == 270.0
    assert quantize_gaze(100, -100, 18) == 45.0
    assert quantize_gaze(2, 2, 18) is None


def test_stabilizer_requires_80_ms_before_direction_switch():
    gaze = GazeStabilizer(stable_ms=80)
    assert gaze.update(90.0, 0) is None
    assert gaze.update(90.0, 79) is None
    assert gaze.update(90.0, 80) == 90.0


def test_quantization_wraps_and_uses_22_5_degree_boundaries():
    near_up_left = quantize_gaze(-1, -100, 0)
    boundary = math.radians(11.25)
    assert near_up_left == 0.0
    assert quantize_gaze(math.sin(boundary), -math.cos(boundary), 0) == 0.0
    assert quantize_gaze(math.sin(math.radians(11.3)), -math.cos(math.radians(11.3)), 0) == 22.5


def test_stabilizer_resets_changed_candidates_and_return_to_current_direction():
    gaze = GazeStabilizer(stable_ms=80)
    assert gaze.update(90.0, 0) is None
    assert gaze.update(90.0, 80) == 90.0
    assert gaze.update(180.0, 100) == 90.0
    assert gaze.update(None, 150) == 90.0
    assert gaze.update(180.0, 200) == 90.0
    assert gaze.update(180.0, 279) == 90.0
    assert gaze.update(180.0, 280) == 180.0
    assert gaze.update(90.0, 300) == 180.0
    assert gaze.update(180.0, 340) == 180.0
    assert gaze.update(90.0, 400) == 180.0
    assert gaze.update(90.0, 480) == 90.0
