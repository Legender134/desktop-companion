from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtGui import QImage


class ActionId(StrEnum):
    IDLE = "idle"
    RUN_RIGHT = "running-right"
    RUN_LEFT = "running-left"
    WAVE = "waving"
    JUMP = "jumping"
    BELLY_FLOP = "failed"
    EXPECT = "waiting"
    PATROL = "running"
    CURIOUS = "review"
    RANDOM = "random"


@dataclass(frozen=True)
class PetActionDefinition:
    """Pet-specific presentation for one stable v2 atlas action slot."""

    key: str
    action_id: ActionId
    label: str
    autoplay_weight: int


@dataclass(frozen=True)
class AnimationSpec:
    row: int
    frame_count: int
    frame_ms: int
    loops: int | None
    hold_ms: int = 0
    movement: int = 0


@dataclass(frozen=True)
class FrameAsset:
    image: QImage
    row: int
    column: int
