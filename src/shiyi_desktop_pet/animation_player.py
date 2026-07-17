from dataclasses import dataclass

from .constants import ACTION_SPECS
from .models import ActionId


@dataclass(frozen=True)
class PlaybackStep:
    frame_index: int
    finished: bool


class AnimationTimeline:
    def __init__(self) -> None:
        self.action = ActionId.IDLE
        self.started_ms = 0

    def start(self, action: ActionId, now_ms: int) -> None:
        self.action = action
        self.started_ms = now_ms

    def advance(self, now_ms: int) -> PlaybackStep:
        spec = ACTION_SPECS[self.action]
        elapsed = max(0, now_ms - self.started_ms)
        cycle_ms = spec.frame_count * spec.frame_ms
        if spec.loops is None:
            return PlaybackStep((elapsed // spec.frame_ms) % spec.frame_count, False)
        animation_ms = cycle_ms * spec.loops
        if elapsed < animation_ms:
            return PlaybackStep((elapsed // spec.frame_ms) % spec.frame_count, False)
        if elapsed < animation_ms + spec.hold_ms:
            return PlaybackStep(spec.frame_count - 1, False)
        return PlaybackStep(spec.frame_count - 1, True)
