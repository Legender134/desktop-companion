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
