from random import Random

from shiyi_desktop_pet.geometry import Point, Rect, Size, clamp_position
from shiyi_desktop_pet.wander import WanderPlanner


def test_position_is_clamped_inside_available_geometry():
    area = Rect(100, 50, 1000, 700)
    assert clamp_position(Point(20, 900), Size(192, 208), area) == Point(100, 542)


def test_planner_target_stays_visible_and_direction_matches():
    planner = WanderPlanner(Random(7))
    target = planner.choose_target(Point(500, 300), Size(192, 208), Rect(0, 0, 1200, 800))
    assert 0 <= target.position.x <= 1008
    assert 0 <= target.position.y <= 592
    assert target.direction in (-1, 1)
    assert (target.position.x - 500) * target.direction > 0


def test_step_toward_never_overshoots_target():
    planner = WanderPlanner(Random(7))
    assert planner.step_toward(Point(100, 50), Point(107, 50), 10) == Point(107, 50)
