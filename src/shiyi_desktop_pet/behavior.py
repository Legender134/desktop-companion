from dataclasses import dataclass, field
from enum import StrEnum

from .models import ActionId, ActionKey


class BehaviorMode(StrEnum):
    IDLE = "idle"
    GAZE = "gaze"
    WANDER = "wander"
    MANUAL_ACTION = "manual_action"
    DRAGGING = "dragging"
    SHUTTING_DOWN = "shutting_down"


@dataclass
class BehaviorEngine:
    wander_enabled: bool = False
    gaze_degrees: float | None = None
    mode: BehaviorMode = field(default=BehaviorMode.IDLE, init=False)
    current_action: ActionKey | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.mode = self._base_mode()

    def trigger_manual(self, action: ActionKey) -> None:
        if self.mode is BehaviorMode.SHUTTING_DOWN:
            return
        if action is ActionId.IDLE:
            self.current_action = None
            if self.mode is not BehaviorMode.DRAGGING:
                self.mode = BehaviorMode.IDLE
            return
        self.current_action = action
        if self.mode is not BehaviorMode.DRAGGING:
            self.mode = BehaviorMode.MANUAL_ACTION

    def manual_finished(self) -> None:
        if self.mode is BehaviorMode.SHUTTING_DOWN:
            return
        self.current_action = None
        if self.mode is not BehaviorMode.DRAGGING:
            self.mode = self._base_mode()

    def begin_drag(self) -> None:
        if self.mode in {BehaviorMode.DRAGGING, BehaviorMode.SHUTTING_DOWN}:
            return
        self.mode = BehaviorMode.DRAGGING

    def end_drag(self) -> None:
        if self.mode is not BehaviorMode.DRAGGING:
            return
        if self.current_action is not None:
            self.mode = BehaviorMode.MANUAL_ACTION
            return
        self.mode = self._base_mode()

    def set_wander_enabled(self, enabled: bool) -> None:
        self.wander_enabled = enabled
        if self.mode not in {
            BehaviorMode.MANUAL_ACTION,
            BehaviorMode.DRAGGING,
            BehaviorMode.SHUTTING_DOWN,
        }:
            self.mode = self._base_mode()

    def request_gaze(self, degrees: float | None) -> None:
        self.gaze_degrees = degrees
        if self.mode in {BehaviorMode.IDLE, BehaviorMode.GAZE}:
            self.mode = self._base_mode()

    def begin_shutdown(self) -> None:
        self.mode = BehaviorMode.SHUTTING_DOWN

    def _base_mode(self) -> BehaviorMode:
        if self.wander_enabled:
            return BehaviorMode.WANDER
        if self.gaze_degrees is not None:
            return BehaviorMode.GAZE
        return BehaviorMode.IDLE
