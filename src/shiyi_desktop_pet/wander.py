"""Deterministic, boundary-safe target selection for autonomous wandering."""

from dataclasses import dataclass
import math
from random import Random

from .geometry import Point, Rect, Size, clamp_position


@dataclass(frozen=True)
class WanderTarget:
    position: Point
    direction: int


class WanderPlanner:
    """Plan wandering using only the caller-supplied pseudo-random generator."""

    def __init__(self, random: Random) -> None:
        self._random = random

    def choose_target(self, current: Point, pet: Size, area: Rect) -> WanderTarget:
        """Choose a visible target on this monitor and its horizontal heading."""
        current = clamp_position(current, pet, area)
        min_x = area.x
        max_x = max(area.x, area.x + area.width - pet.width)
        min_y = area.y
        max_y = max(area.y, area.y + area.height - pet.height)

        left_room = current.x - min_x
        right_room = max_x - current.x
        useful_directions = [
            direction
            for direction, room in ((-1, left_room), (1, right_room))
            if room >= 80
        ]
        movable_directions = [
            direction
            for direction, room in ((-1, left_room), (1, right_room))
            if room > 0
        ]
        directions = useful_directions or movable_directions
        if not directions:
            return WanderTarget(position=current, direction=0)

        direction = self._random.choice(directions)

        room = right_room if direction == 1 else left_room
        minimum_motion = 80 if room >= 80 else 0
        motion = self._random.uniform(minimum_motion, room) if room > 0 else 0
        target_x = current.x + direction * motion
        target_y = self._random.uniform(min_y, max_y) if max_y > min_y else min_y
        position = clamp_position(Point(target_x, target_y), pet, area)
        return WanderTarget(position=position, direction=direction)

    def step_toward(self, current: Point, target: Point, pixels: float) -> Point:
        """Move toward a target by at most ``pixels``, preserving its endpoint."""
        if pixels <= 0:
            return current
        dx = target.x - current.x
        dy = target.y - current.y
        distance = math.hypot(dx, dy)
        if distance == 0 or distance <= pixels:
            return target
        scale = pixels / distance
        return Point(current.x + dx * scale, current.y + dy * scale)
