"""Cursor-direction quantization and timing-based gaze stabilization."""

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


class GazeStabilizer:
    """Publish a changed direction only after it remains stable long enough."""

    def __init__(self, stable_ms: int = 80) -> None:
        self.stable_ms = stable_ms
        self._direction: float | None = None
        self._candidate: float | None = None
        self._candidate_since_ms: int | None = None

    def update(self, direction: float | None, now_ms: int) -> float | None:
        """Return the current stabilized direction at ``now_ms``.

        A new candidate starts its own timer.  The previous stable direction
        remains active while the candidate is still settling.
        """
        if direction == self._direction:
            self._candidate = direction
            self._candidate_since_ms = now_ms
            return self._direction

        if direction != self._candidate:
            self._candidate = direction
            self._candidate_since_ms = now_ms

        if (
            self._candidate_since_ms is not None
            and now_ms - self._candidate_since_ms >= self.stable_ms
        ):
            self._direction = self._candidate

        return self._direction
