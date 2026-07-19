import math

import pytest

from shiyi_desktop_pet.gaze import GazeSmoother, cursor_angle, quantize_gaze


def test_screen_vectors_map_clockwise_from_up():
    assert quantize_gaze(0, -100, 18) == 0.0
    assert quantize_gaze(100, 0, 18) == 90.0
    assert quantize_gaze(0, 100, 18) == 180.0
    assert quantize_gaze(-100, 0, 18) == 270.0
    assert quantize_gaze(100, -100, 18) == 45.0
    assert quantize_gaze(2, 2, 18) is None


def test_exact_cursor_angle_preserves_intermediate_directions():
    assert cursor_angle(0, -100, 18) == 0.0
    assert cursor_angle(100, 0, 18) == 90.0
    assert cursor_angle(0, 100, 18) == 180.0
    assert cursor_angle(-100, 0, 18) == 270.0
    assert cursor_angle(2, 2, 18) is None


def test_quantization_wraps_and_uses_22_5_degree_boundaries():
    near_up_left = quantize_gaze(-1, -100, 0)
    boundary = math.radians(11.25)
    assert near_up_left == 0.0
    assert quantize_gaze(math.sin(boundary), -math.cos(boundary), 0) == 0.0
    assert quantize_gaze(math.sin(math.radians(11.3)), -math.cos(math.radians(11.3)), 0) == 22.5


def test_smoother_follows_shortest_arc_and_holds_inside_dead_zone():
    gaze = GazeSmoother(response_ms=100)
    assert gaze.update(350.0, 0) == 350.0
    clockwise = gaze.update(10.0, 100)
    assert clockwise is not None
    assert clockwise > 350.0 or clockwise < 10.0
    assert gaze.update(None, 150) == clockwise
    gaze.reset()
    assert gaze.direction is None


def test_smoother_limits_large_jumps_so_keyframes_are_visited_in_order():
    gaze = GazeSmoother(response_ms=100, max_speed_degrees_per_second=360)
    assert gaze.update(0.0, 0) == 0.0
    assert gaze.update(180.0, 50) == 342.0
    assert gaze.update(180.0, 100) == 324.0


def test_smoother_rejects_invalid_response_time():
    with pytest.raises(ValueError, match="positive"):
        GazeSmoother(response_ms=0)
    with pytest.raises(ValueError, match="speed"):
        GazeSmoother(max_speed_degrees_per_second=0)
