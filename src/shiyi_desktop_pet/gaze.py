"""Cursor-direction mapping and smooth gaze tracking."""

import math


def quantize_gaze(dx: float, dy: float, dead_zone: float) -> float | None:
    """Map a screen-space vector to one of sixteen clockwise directions.

    Zero degrees points up, matching the coordinate system used by the sprite
    sheet.  Vectors inside the Euclidean dead zone do not request a direction.
    """
    if math.hypot(dx, dy) < dead_zone:
        return None
    degrees = math.degrees(math.atan2(dx, -dy)) % 360
    return round(degrees / 22.5) % 16 * 22.5


def cursor_angle(dx: float, dy: float, dead_zone: float) -> float | None:
    """Return the exact clockwise screen-space angle, with zero pointing up."""
    if math.hypot(dx, dy) < dead_zone:
        return None
    return math.degrees(math.atan2(dx, -dy)) % 360


class GazeSmoother:
    """Follow cursor angles over the shortest arc without abrupt direction jumps."""

    def __init__(
        self,
        response_ms: int = 110,
        max_speed_degrees_per_second: float = 360.0,
    ) -> None:
        if response_ms <= 0:
            raise ValueError("response_ms must be positive")
        if max_speed_degrees_per_second <= 0:
            raise ValueError("max gaze speed must be positive")
        self.response_ms = response_ms
        self.max_speed_degrees_per_second = max_speed_degrees_per_second
        self._direction: float | None = None
        self._updated_ms: int | None = None

    @property
    def direction(self) -> float | None:
        return self._direction

    def reset(self) -> None:
        self._direction = None
        self._updated_ms = None

    def update(self, target: float | None, now_ms: int) -> float | None:
        """Move toward ``target`` using a time-based circular low-pass filter."""
        if target is None:
            self._updated_ms = now_ms
            return self._direction
        target %= 360
        if self._direction is None or self._updated_ms is None:
            self._direction = target
            self._updated_ms = now_ms
            return self._direction

        elapsed_ms = max(0, now_ms - self._updated_ms)
        self._updated_ms = now_ms
        if elapsed_ms == 0:
            return self._direction

        delta = (target - self._direction + 180) % 360 - 180
        progress = 1.0 - math.exp(-elapsed_ms / self.response_ms)
        movement = delta * progress
        maximum = self.max_speed_degrees_per_second * elapsed_ms / 1000.0
        movement = min(maximum, max(-maximum, movement))
        self._direction = (self._direction + movement) % 360
        if abs(delta) < 0.1:
            self._direction = target
        return self._direction
