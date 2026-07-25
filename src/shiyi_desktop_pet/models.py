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


class ActionRole(StrEnum):
    """Runtime behavior supplied by a data-only action definition."""

    IDLE = "idle"
    MOVE = "move"
    INTERACTION = "interaction"
    BURST_MOVE = "burstMove"
    GAZE = "gaze"


ActionKey = ActionId | str


@dataclass(frozen=True)
class PetActionDefinition:
    """Pet-specific presentation and behavior for one atlas animation."""

    key: str
    action_id: ActionKey
    label: str
    autoplay_weight: int
    spec: "AnimationSpec | None" = None
    role: ActionRole = ActionRole.INTERACTION
    direction: int = 0
    show_in_menu: bool = True
    include_in_showcase: bool = True
    cooldown_ms: int = 0
    autoplay_group: str = ""
    min_distance: int = 0
    travel_start_frame: int | None = None
    travel_end_frame: int | None = None
    travel_distance_ratio: float | None = None
    max_vertical_ratio: float | None = None
    mirror_of: ActionKey | None = None


@dataclass(frozen=True)
class PetStateActionChoice:
    """One finite animation that may play while a pet state is active."""

    action_id: ActionKey
    weight: int


@dataclass(frozen=True)
class PetStateDefinition:
    """A persistent pet state with finite enter, resident, and exit clips."""

    key: str
    label: str
    enter_action: ActionKey
    resident_actions: tuple[PetStateActionChoice, ...]
    exit_action: ActionKey
    min_duration_ms: int
    ramp_duration_ms: int
    max_duration_ms: int
    exit_chance_after_min: int
    exit_chance_after_ramp: int


@dataclass(frozen=True)
class AnimationSpec:
    row: int
    frame_count: int
    frame_ms: int
    loops: int | None
    hold_ms: int = 0
    movement: int = 0
    start_column: int = 0
    frame_durations: tuple[int, ...] | None = None

    @property
    def durations(self) -> tuple[int, ...]:
        return self.frame_durations or (self.frame_ms,) * self.frame_count

    @property
    def cycle_ms(self) -> int:
        return sum(self.durations)

    def frame_start_ms(self, frame_index: int) -> int:
        if not 0 <= frame_index <= self.frame_count:
            raise ValueError("frame index is outside the animation")
        return sum(self.durations[:frame_index])

    def frame_index_at(self, elapsed_ms: int) -> int:
        offset = max(0, elapsed_ms) % self.cycle_ms
        boundary = 0
        for index, duration in enumerate(self.durations):
            boundary += duration
            if offset < boundary:
                return index
        return self.frame_count - 1


@dataclass(frozen=True)
class FrameAsset:
    image: QImage
    row: int
    column: int
    variant: str = ""
