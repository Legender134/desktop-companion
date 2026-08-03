"""Pure state transitions for v4 forms, transformations, and sequences."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
import random

from .models import (
    ActionKey,
    PetFormDefinition,
    PetSequenceDefinition,
    PetSequenceStep,
    PetTransformationDefinition,
)


class RuntimeCommandKind(StrEnum):
    PLAY = "play"
    SET_FORM = "setForm"
    CLEANUP = "cleanup"
    FINISH = "finish"


@dataclass(frozen=True)
class RuntimeCommand:
    kind: RuntimeCommandKind
    action: ActionKey | None = None
    form: str | None = None
    repeat_count: int = 1
    hold_ms: int = 0


class _Operation(StrEnum):
    IDLE = "idle"
    ENTER = "enter"
    RESIDENT = "resident"
    EXIT = "exit"
    SEQUENCE = "sequence"


class _RequestKind(StrEnum):
    TRANSFORMATION = "transformation"
    SEQUENCE = "sequence"


@dataclass(frozen=True)
class _PendingRequest:
    kind: _RequestKind
    key: str
    manual: bool


class MultiformController:
    """Advance immutable v4 definitions one completed action at a time."""

    def __init__(
        self,
        *,
        default_form: str,
        forms: tuple[PetFormDefinition, ...],
        transformations: tuple[PetTransformationDefinition, ...],
        sequences: tuple[PetSequenceDefinition, ...],
        rng: random.Random,
    ) -> None:
        self._default_form = default_form
        self._current_form = default_form
        self._form_map = {form.key: form for form in forms}
        self._transformation_map = {
            transformation.key: transformation
            for transformation in transformations
        }
        self._transformation_by_form = {
            transformation.to_form: transformation
            for transformation in transformations
        }
        missing_exits = (
            set(self._form_map)
            - {self._default_form}
            - set(self._transformation_by_form)
        )
        if missing_exits:
            raise ValueError(
                "non-default forms must have a transformation exit: "
                + ", ".join(sorted(missing_exits))
            )
        self._sequence_map = {sequence.key: sequence for sequence in sequences}
        self._rng = rng

        self._operation = _Operation.IDLE
        self._transformation: PetTransformationDefinition | None = None
        self._resident_deadline_ms: int | None = None
        self._sequence_steps: deque[PetSequenceStep] = deque()
        self._pending: _PendingRequest | None = None
        self._stop_requested = False

    @property
    def current_form(self) -> str:
        return self._current_form

    @property
    def busy(self) -> bool:
        return self._operation is not _Operation.IDLE

    def request_transformation(
        self, key: str, *, manual: bool, now_ms: int
    ) -> RuntimeCommand | None:
        transformation = self._transformation_map[key]
        if self.busy:
            if manual:
                self._pending = _PendingRequest(
                    _RequestKind.TRANSFORMATION, key, manual
                )
            return None

        if transformation.to_form == self._current_form:
            return RuntimeCommand(
                RuntimeCommandKind.PLAY,
                action=self._form_map[self._current_form].representative_action,
            )
        if self._current_form != self._default_form:
            if not manual:
                return None
            current = self._transformation_by_form[self._current_form]
            self._pending = _PendingRequest(
                _RequestKind.TRANSFORMATION, key, manual
            )
            self._transformation = current
            self._operation = _Operation.EXIT
            self._stop_requested = False
            return RuntimeCommand(
                RuntimeCommandKind.PLAY,
                action=current.exit_action,
            )
        return self._start_transformation(transformation, now_ms)

    def request_sequence(
        self, key: str, *, manual: bool, now_ms: int
    ) -> RuntimeCommand | None:
        sequence = self._sequence_map[key]
        if self.busy:
            if manual:
                self._pending = _PendingRequest(_RequestKind.SEQUENCE, key, manual)
            return None
        if not manual and self._current_form != self._default_form:
            return None
        return self._start_sequence(sequence)

    def action_finished(self, now_ms: int) -> RuntimeCommand:
        if self._operation is _Operation.ENTER:
            return self._enter_finished(now_ms)
        if self._operation is _Operation.RESIDENT:
            return self._resident_finished(now_ms)
        if self._operation is _Operation.EXIT:
            return self._exit_finished(now_ms)
        if self._operation is _Operation.SEQUENCE:
            return self._sequence_step_finished(now_ms)
        return RuntimeCommand(RuntimeCommandKind.FINISH)

    def request_stop(self) -> RuntimeCommand | None:
        if self.busy:
            self._stop_requested = True
        return None

    def hard_cancel(self) -> tuple[RuntimeCommand, ...]:
        self._reset(default_form=True)
        return (
            RuntimeCommand(
                RuntimeCommandKind.CLEANUP,
                form=self._default_form,
            ),
        )

    def _start_transformation(
        self, transformation: PetTransformationDefinition, now_ms: int
    ) -> RuntimeCommand:
        self._transformation = transformation
        self._resident_deadline_ms = now_ms + self._rng.randint(
            transformation.min_duration_ms,
            transformation.max_duration_ms,
        )
        self._operation = _Operation.ENTER
        self._stop_requested = False
        return RuntimeCommand(
            RuntimeCommandKind.PLAY,
            action=transformation.enter_action,
        )

    def _enter_finished(self, now_ms: int) -> RuntimeCommand:
        transformation = self._require_transformation()
        self._current_form = transformation.to_form
        if self._stop_requested:
            self._operation = _Operation.EXIT
            self._stop_requested = False
            return RuntimeCommand(
                RuntimeCommandKind.SET_FORM,
                action=transformation.exit_action,
                form=transformation.to_form,
            )

        self._operation = _Operation.RESIDENT
        return RuntimeCommand(
            RuntimeCommandKind.SET_FORM,
            action=self._choose_resident(transformation),
            form=transformation.to_form,
        )

    def _resident_finished(self, now_ms: int) -> RuntimeCommand:
        transformation = self._require_transformation()
        if self._stop_requested or now_ms >= self._require_resident_deadline():
            self._operation = _Operation.EXIT
            self._stop_requested = False
            return RuntimeCommand(
                RuntimeCommandKind.PLAY,
                action=transformation.exit_action,
            )
        return RuntimeCommand(
            RuntimeCommandKind.PLAY,
            action=self._choose_resident(transformation),
        )

    def _exit_finished(self, now_ms: int) -> RuntimeCommand:
        previous_form = self._current_form
        self._current_form = self._default_form
        self._operation = _Operation.IDLE
        self._transformation = None
        self._resident_deadline_ms = None
        self._stop_requested = False
        pending_command = self._consume_pending(now_ms)
        if pending_command is not None:
            return self._apply_form_change(pending_command, previous_form)
        return RuntimeCommand(
            RuntimeCommandKind.SET_FORM,
            form=self._default_form,
        )

    def _start_sequence(self, sequence: PetSequenceDefinition) -> RuntimeCommand:
        self._sequence_steps = deque(sequence.steps)
        self._operation = _Operation.SEQUENCE
        self._stop_requested = False
        return self._step_command(self._sequence_steps[0])

    def _sequence_step_finished(self, now_ms: int) -> RuntimeCommand:
        previous_form = self._current_form
        completed = self._sequence_steps.popleft()
        if completed.form_after is not None:
            self._current_form = completed.form_after

        if self._stop_requested and completed.safe_stop_after:
            self._reset(default_form=True)
            return RuntimeCommand(
                RuntimeCommandKind.CLEANUP,
                form=self._default_form,
            )

        if self._sequence_steps:
            command = self._step_command(self._sequence_steps[0])
            return self._apply_form_change(command, previous_form)

        self._operation = _Operation.IDLE
        self._stop_requested = False
        pending_command = self._consume_pending(now_ms)
        if pending_command is not None:
            return self._apply_form_change(pending_command, previous_form)
        if self._current_form != previous_form:
            return RuntimeCommand(
                RuntimeCommandKind.SET_FORM,
                form=self._current_form,
            )
        return RuntimeCommand(RuntimeCommandKind.FINISH)

    def _consume_pending(self, now_ms: int) -> RuntimeCommand | None:
        pending = self._pending
        self._pending = None
        if pending is None:
            return None
        if pending.kind is _RequestKind.TRANSFORMATION:
            return self.request_transformation(
                pending.key,
                manual=pending.manual,
                now_ms=now_ms,
            )
        return self.request_sequence(
            pending.key,
            manual=pending.manual,
            now_ms=now_ms,
        )

    def _step_command(self, step: PetSequenceStep) -> RuntimeCommand:
        return RuntimeCommand(
            RuntimeCommandKind.PLAY,
            action=step.action_id,
            repeat_count=step.repeat_count,
            hold_ms=step.hold_ms,
        )

    def _apply_form_change(
        self, command: RuntimeCommand, previous_form: str
    ) -> RuntimeCommand:
        if command.kind is RuntimeCommandKind.SET_FORM:
            return command
        if self._current_form == previous_form:
            return command
        return RuntimeCommand(
            RuntimeCommandKind.SET_FORM,
            action=command.action,
            form=self._current_form,
            repeat_count=command.repeat_count,
            hold_ms=command.hold_ms,
        )

    def _choose_resident(
        self, transformation: PetTransformationDefinition
    ) -> ActionKey:
        choices = transformation.resident_actions
        return self._rng.choices(
            [choice.action_id for choice in choices],
            weights=[choice.weight for choice in choices],
            k=1,
        )[0]

    def _require_transformation(self) -> PetTransformationDefinition:
        if self._transformation is None:
            raise RuntimeError("transformation phase has no definition")
        return self._transformation

    def _require_resident_deadline(self) -> int:
        if self._resident_deadline_ms is None:
            raise RuntimeError("resident phase has no deadline")
        return self._resident_deadline_ms

    def _reset(self, *, default_form: bool) -> None:
        if default_form:
            self._current_form = self._default_form
        self._operation = _Operation.IDLE
        self._transformation = None
        self._resident_deadline_ms = None
        self._sequence_steps.clear()
        self._pending = None
        self._stop_requested = False
