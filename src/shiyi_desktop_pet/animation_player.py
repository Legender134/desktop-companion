from dataclasses import dataclass

from .constants import ACTION_SPECS
from .models import ActionId, ActionKey, AnimationSpec


@dataclass(frozen=True)
class PlaybackStep:
    frame_index: int
    finished: bool


class AnimationTimeline:
    def __init__(self) -> None:
        self.action: ActionKey = ActionId.IDLE
        self.started_ms = 0

    def start(self, action: ActionKey, now_ms: int) -> None:
        self.action = action
        self.started_ms = now_ms

    def advance(
        self, now_ms: int, spec: AnimationSpec | None = None
    ) -> PlaybackStep:
        if spec is None:
            spec = ACTION_SPECS[self.action]
        elapsed = max(0, now_ms - self.started_ms)
        cycle_ms = spec.cycle_ms
        if spec.loops is None:
            return PlaybackStep(spec.frame_index_at(elapsed), False)
        animation_ms = cycle_ms * spec.loops
        if elapsed < animation_ms:
            return PlaybackStep(spec.frame_index_at(elapsed), False)
        if elapsed < animation_ms + spec.hold_ms:
            return PlaybackStep(spec.frame_count - 1, False)
        return PlaybackStep(spec.frame_count - 1, True)
