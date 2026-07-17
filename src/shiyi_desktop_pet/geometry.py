"""Platform-independent geometry primitives for pet positioning."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Size:
    width: float
    height: float


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float


def clamp_position(position: Point, pet: Size, area: Rect) -> Point:
    """Return a pet's top-left position constrained to an available area."""
    max_x = max(area.x, area.x + area.width - pet.width)
    max_y = max(area.y, area.y + area.height - pet.height)
    return Point(
        min(max(position.x, area.x), max_x),
        min(max(position.y, area.y), max_y),
    )
