"""Bucketed autonomous scheduling for data-only v4 pet events."""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Literal

from .models import (
    PetAutoplayDefinition,
    PetCooldownGroupDefinition,
    PetSequenceDefinition,
    PetTransformationDefinition,
)


AutoplayCandidateKind = Literal["transformation", "sequence"]
AutoplayDefinition = PetTransformationDefinition | PetSequenceDefinition


@dataclass(frozen=True)
class AutoplayCandidate:
    """A stable runtime-facing wrapper for either kind of v4 autoplay event."""

    kind: AutoplayCandidateKind
    key: str
    definition: AutoplayDefinition
    autoplay: PetAutoplayDefinition


class AutoplayBucketScheduler:
    """Schedule one weighted v4 event per bucket deadline."""

    DEFER_DELAY_MS = 1_000

    def __init__(
        self,
        transformations: tuple[PetTransformationDefinition, ...],
        sequences: tuple[PetSequenceDefinition, ...],
        cooldown_groups: tuple[PetCooldownGroupDefinition, ...],
        *,
        default_form: str,
        rng: random.Random,
    ) -> None:
        self.default_form = default_form
        self._rng = rng
        self._cooldown_durations = {
            definition.key: definition.cooldown_ms
            for definition in cooldown_groups
        }
        self.cooldown_deadlines: dict[str, int] = {
            key: 0 for key in self._cooldown_durations
        }

        candidates: list[AutoplayCandidate] = []
        for definition in transformations:
            if definition.autoplay is not None:
                candidates.append(
                    AutoplayCandidate(
                        "transformation",
                        definition.key,
                        definition,
                        definition.autoplay,
                    )
                )
        for definition in sequences:
            if definition.autoplay is not None:
                candidates.append(
                    AutoplayCandidate(
                        "sequence",
                        definition.key,
                        definition,
                        definition.autoplay,
                    )
                )
        self.candidates = tuple(candidates)

        self._buckets: dict[str, tuple[AutoplayCandidate, ...]] = {}
        bucket_lists: dict[str, list[AutoplayCandidate]] = {}
        self._bucket_specs: dict[str, PetAutoplayDefinition] = {}
        for candidate in self.candidates:
            autoplay = candidate.autoplay
            if autoplay.weight <= 0:
                raise ValueError("autoplay candidate weight must be positive")
            bucket_lists.setdefault(autoplay.bucket, []).append(candidate)
            existing = self._bucket_specs.setdefault(autoplay.bucket, autoplay)
            existing_signature = (
                existing.min_delay_ms,
                existing.max_delay_ms,
                existing.cooldown_groups,
            )
            signature = (
                autoplay.min_delay_ms,
                autoplay.max_delay_ms,
                autoplay.cooldown_groups,
            )
            if existing_signature != signature:
                raise ValueError("autoplay bucket definitions must match")
            unknown_groups = (
                set(autoplay.cooldown_groups) - self._cooldown_durations.keys()
            )
            if unknown_groups:
                raise ValueError(
                    f"autoplay bucket {autoplay.bucket} references an unknown "
                    "cooldown group"
                )
        self._buckets = {
            bucket: tuple(items) for bucket, items in bucket_lists.items()
        }
        self.deadlines: dict[str, int] = {}

    def reset(self, now_ms: int) -> None:
        """Reset bucket deadlines and discard cooldown bookkeeping."""

        self.deadlines = {}
        for bucket in self._buckets:
            self._schedule_bucket(bucket, now_ms)
        self.cooldown_deadlines = {
            key: 0 for key in self._cooldown_durations
        }

    def next_deadline_ms(self) -> int | None:
        """Return the earliest bucket deadline, or ``None`` without candidates."""

        return min(self.deadlines.values(), default=None)

    def choose_due(
        self,
        now_ms: int,
        current_form: str,
        rng: random.Random,
        *,
        is_wandering: bool = False,
        always_gaze: bool = False,
        sequence_active: bool = False,
        autonomous_enabled: bool = True,
    ) -> AutoplayCandidate | None:
        """Choose one eligible candidate without consuming paused bucket state."""

        if (
            current_form != self.default_form
            or is_wandering
            or always_gaze
            or sequence_active
            or not autonomous_enabled
        ):
            return None

        due_buckets = sorted(
            (
                bucket
                for bucket, deadline in self.deadlines.items()
                if deadline <= now_ms
            ),
            key=lambda bucket: self.deadlines[bucket],
        )
        for bucket in due_buckets:
            eligible = tuple(
                candidate
                for candidate in self._buckets[bucket]
                if self._is_eligible(candidate, now_ms, current_form)
            )
            if not eligible:
                continue
            return self._weighted_choice(eligible, rng)
        return None

    def record_started(
        self,
        candidate: AutoplayCandidate,
        now_ms: int,
        *,
        automatic: bool = False,
    ) -> None:
        """Record an accepted start, consuming a bucket only when automatic."""

        if candidate not in self.candidates:
            raise ValueError("autoplay candidate does not belong to this scheduler")

        for group in candidate.autoplay.cooldown_groups:
            duration = self._cooldown_durations[group]
            self.cooldown_deadlines[group] = max(
                self.cooldown_deadlines.get(group, 0),
                now_ms + duration,
            )
        if automatic:
            self._schedule_bucket(candidate.autoplay.bucket, now_ms)

    def defer(self, now_ms: int) -> None:
        """Move already-due buckets to the next short polling opportunity."""

        retry_at = now_ms + self.DEFER_DELAY_MS
        for bucket, deadline in tuple(self.deadlines.items()):
            if deadline <= now_ms:
                self.deadlines[bucket] = retry_at

    def _schedule_bucket(self, bucket: str, now_ms: int) -> None:
        autoplay = self._bucket_specs[bucket]
        delay = self._rng.randint(
            autoplay.min_delay_ms,
            autoplay.max_delay_ms,
        )
        self.deadlines[bucket] = now_ms + delay

    def _is_eligible(
        self,
        candidate: AutoplayCandidate,
        now_ms: int,
        current_form: str,
    ) -> bool:
        definition = candidate.definition
        if (
            candidate.kind == "transformation"
            and isinstance(definition, PetTransformationDefinition)
            and definition.from_form != current_form
        ):
            return False
        return all(
            now_ms >= self.cooldown_deadlines.get(group, 0)
            for group in candidate.autoplay.cooldown_groups
        )

    @staticmethod
    def _weighted_choice(
        candidates: tuple[AutoplayCandidate, ...],
        rng: random.Random,
    ) -> AutoplayCandidate:
        total = sum(candidate.autoplay.weight for candidate in candidates)
        selected = rng.randrange(total)
        for candidate in candidates:
            selected -= candidate.autoplay.weight
            if selected < 0:
                return candidate
        raise AssertionError("positive autoplay weights must yield a candidate")
