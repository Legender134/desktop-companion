from random import Random

from shiyi_desktop_pet.geometry import Point, Rect, Size, clamp_position
from shiyi_desktop_pet.wander import WanderPlanner, WanderTarget


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


def test_planner_reports_no_direction_when_pet_is_wider_than_area():
    planner = WanderPlanner(Random(7))
    target = planner.choose_target(Point(40, 80), Size(200, 100), Rect(10, 20, 120, 300))
    assert target == WanderTarget(Point(10, 80), 0)


def test_planner_reports_no_direction_at_clamped_zero_horizontal_room():
    planner = WanderPlanner(Random(7))
    target = planner.choose_target(Point(-10, 80), Size(120, 100), Rect(10, 20, 120, 300))
    assert target == WanderTarget(Point(10, 80), 0)


def test_no_motion_path_does_not_consume_random_values():
    class NoRandom:
        def choice(self, values):
            raise AssertionError("no random value should be consumed")

        def uniform(self, start, end):
            raise AssertionError("no random value should be consumed")

    target = WanderPlanner(NoRandom()).choose_target(
        Point(10, 80), Size(120, 100), Rect(10, 20, 120, 300)
    )
    assert target == WanderTarget(Point(10, 80), 0)


def test_clamp_supports_negative_origins_and_oversized_pets():
    area = Rect(-500, -200, 400, 300)
    assert clamp_position(Point(-600, 500), Size(100, 80), area) == Point(-500, 20)
    assert clamp_position(Point(-300, -100), Size(500, 400), area) == Point(-500, -200)


def test_planner_uses_exactly_80_pixels_when_that_is_the_available_room():
    target = WanderPlanner(Random(7)).choose_target(
        Point(0, 0), Size(10, 10), Rect(0, 0, 90, 100)
    )
    assert target.direction == 1
    assert target.position.x == 80


def test_planner_uses_smaller_available_horizontal_motion_when_needed():
    target = WanderPlanner(Random(7)).choose_target(
        Point(0, 0), Size(10, 10), Rect(0, 0, 80, 100)
    )
    assert target.direction == 1
    assert 0 < target.position.x <= 70


def test_seeded_planners_produce_identical_target_sequences():
    first = WanderPlanner(Random(17))
    second = WanderPlanner(Random(17))
    args = (Point(500, 300), Size(192, 208), Rect(-100, -50, 1200, 800))
    assert [first.choose_target(*args) for _ in range(3)] == [
        second.choose_target(*args) for _ in range(3)
    ]


def test_step_toward_preserves_current_position_for_non_positive_steps():
    planner = WanderPlanner(Random(7))
    current = Point(100, 50)
    target = Point(107, 54)
    assert planner.step_toward(current, target, 0) == current
    assert planner.step_toward(current, target, -1) == current


def test_step_toward_supports_fractional_vector_steps():
    planner = WanderPlanner(Random(7))
    assert planner.step_toward(Point(0, 0), Point(3, 4), 2.5) == Point(1.5, 2.0)
