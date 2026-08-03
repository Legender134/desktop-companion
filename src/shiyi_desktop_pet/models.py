from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QPoint, QRect
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
class PetAtlasDefinition:
    key: str
    path: Path
    cell_width: int
    cell_height: int


@dataclass(frozen=True)
class PetActionLayerDefinition:
    atlas_id: str
    row: int
    start_column: int
    anchor_x: int
    anchor_y: int
    offset_x: int = 0
    offset_y: int = 0
    scale_percent: int = 100
    opacity_percent: int = 100
    hit_test: bool = False
    optional_in_simplified: bool = False
    frame_map: tuple[int | None, ...] | None = None


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
    layers: tuple[PetActionLayerDefinition, ...] = ()


@dataclass(frozen=True)
class PetFormDefinition:
    key: str
    label: str
    idle_action: ActionKey
    move_right_action: ActionKey
    move_left_action: ActionKey
    gaze_action: ActionKey | None
    representative_action: ActionKey
    interaction_actions: tuple[ActionKey, ...]


@dataclass(frozen=True)
class PetAutoplayDefinition:
    bucket: str
    weight: int
    min_delay_ms: int
    max_delay_ms: int
    cooldown_groups: tuple[str, ...]


@dataclass(frozen=True)
class PetTransformationDefinition:
    key: str
    label: str
    from_form: str
    to_form: str
    enter_action: ActionKey
    resident_actions: tuple["PetStateActionChoice", ...]
    exit_action: ActionKey
    min_duration_ms: int
    max_duration_ms: int
    show_in_menu: bool
    autoplay: PetAutoplayDefinition | None = None


@dataclass(frozen=True)
class PetCooldownGroupDefinition:
    key: str
    cooldown_ms: int


@dataclass(frozen=True)
class PetSequenceStep:
    action_id: ActionKey
    repeat_count: int
    hold_ms: int
    form_after: str | None
    safe_stop_after: bool


@dataclass(frozen=True)
class PetSequenceDefinition:
    key: str
    label: str
    show_in_menu: bool
    steps: tuple[PetSequenceStep, ...]
    autoplay: PetAutoplayDefinition | None = None


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


@dataclass(frozen=True)
class RenderedFrame:
    image: QImage
    body_image: QImage
    body_rect: QRect
    anchor: QPoint
    identity: tuple[object, ...]
