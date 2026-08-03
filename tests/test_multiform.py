import random

import pytest

from shiyi_desktop_pet.models import (
    PetFormDefinition,
    PetSequenceDefinition,
    PetSequenceStep,
    PetStateActionChoice,
    PetTransformationDefinition,
)
from shiyi_desktop_pet.multiform import (
    MultiformController,
    RuntimeCommand,
    RuntimeCommandKind,
)


DEFAULT_FORM = "foxEaredHuman"


def _controller(
    *,
    sequence_safe_flags: tuple[bool, ...] = (False, True, False),
    include_sequence_only_form: bool = False,
) -> MultiformController:
    forms = (
        PetFormDefinition(
            DEFAULT_FORM,
            "Default",
            "idle",
            "moveRight",
            "moveLeft",
            "gaze",
            "greet",
            ("greet",),
        ),
        PetFormDefinition(
            "whiteFox",
            "White fox",
            "whiteFoxIdle",
            "whiteFoxRight",
            "whiteFoxLeft",
            None,
            "whiteFoxGreet",
            ("whiteFoxGreet",),
        ),
        PetFormDefinition(
            "fullHuman",
            "Full human",
            "fullHumanIdle",
            "fullHumanRight",
            "fullHumanLeft",
            None,
            "fullHumanGreet",
            ("fullHumanGreet",),
        ),
        PetFormDefinition(
            "corpseHost",
            "Corpse host",
            "corpseIdle",
            "corpseRight",
            "corpseLeft",
            None,
            "corpseGreet",
            ("corpseGreet",),
        ),
    )
    if include_sequence_only_form:
        forms += (
            PetFormDefinition(
                "sequenceOnly",
                "Sequence only",
                "sequenceIdle",
                "sequenceRight",
                "sequenceLeft",
                None,
                "sequenceGreet",
                ("sequenceGreet",),
            ),
        )
    transformations = (
        PetTransformationDefinition(
            "whiteFoxChange",
            "Become white fox",
            DEFAULT_FORM,
            "whiteFox",
            "whiteFoxEnter",
            (
                PetStateActionChoice("whiteFoxRest", 1),
                PetStateActionChoice("whiteFoxSniff", 3),
            ),
            "whiteFoxExit",
            1_000,
            2_000,
            True,
        ),
        PetTransformationDefinition(
            "fullHumanChange",
            "Become full human",
            DEFAULT_FORM,
            "fullHuman",
            "fullHumanEnter",
            (PetStateActionChoice("fullHumanIdle", 1),),
            "fullHumanExit",
            1_000,
            2_000,
            True,
        ),
        PetTransformationDefinition(
            "corpseChange",
            "Become corpse host",
            DEFAULT_FORM,
            "corpseHost",
            "corpseEnter",
            (PetStateActionChoice("corpseIdle", 1),),
            "corpseExit",
            1_000,
            2_000,
            True,
        ),
    )
    spell_steps = tuple(
        PetSequenceStep(
            action_id=action,
            repeat_count=repeat_count,
            hold_ms=hold_ms,
            form_after=form_after,
            safe_stop_after=safe,
        )
        for action, repeat_count, hold_ms, form_after, safe in zip(
            ("a", "b", "c"),
            (2, 3, 1),
            (25, 50, 0),
            ("fullHuman", None, DEFAULT_FORM),
            sequence_safe_flags,
            strict=True,
        )
    )
    sequences = (
        PetSequenceDefinition("spell", "Spell", True, spell_steps),
        PetSequenceDefinition(
            "completeShowcase",
            "Complete showcase",
            True,
            (
                PetSequenceStep("showcaseA", 1, 0, "whiteFox", False),
                PetSequenceStep("showcaseB", 1, 0, DEFAULT_FORM, True),
            ),
        ),
        PetSequenceDefinition(
            "leaveAsFox",
            "Leave as fox",
            True,
            (PetSequenceStep("becomeFox", 1, 0, "whiteFox", True),),
        ),
    )
    return MultiformController(
        default_form=DEFAULT_FORM,
        forms=forms,
        transformations=transformations,
        sequences=sequences,
        rng=random.Random(7),
    )


def test_transformation_enters_changes_form_resides_until_deadline_and_exits():
    controller = _controller()

    assert controller.request_transformation(
        "whiteFoxChange", manual=True, now_ms=100
    ) == RuntimeCommand(RuntimeCommandKind.PLAY, action="whiteFoxEnter")
    assert controller.current_form == DEFAULT_FORM
    assert controller.busy is True

    assert controller.action_finished(200) == RuntimeCommand(
        RuntimeCommandKind.SET_FORM,
        action="whiteFoxSniff",
        form="whiteFox",
    )
    assert controller.current_form == "whiteFox"

    assert controller.action_finished(1_430) == RuntimeCommand(
        RuntimeCommandKind.PLAY,
        action="whiteFoxSniff",
    )
    assert controller.action_finished(1_431) == RuntimeCommand(
        RuntimeCommandKind.PLAY,
        action="whiteFoxExit",
    )
    assert controller.action_finished(1_500) == RuntimeCommand(
        RuntimeCommandKind.SET_FORM,
        form=DEFAULT_FORM,
    )
    assert controller.current_form == DEFAULT_FORM
    assert controller.busy is False


def test_idle_request_for_current_form_plays_its_representative_action():
    controller = _controller()
    controller.request_sequence("leaveAsFox", manual=True, now_ms=0)
    assert controller.action_finished(100).form == "whiteFox"
    assert controller.busy is False

    assert controller.request_transformation(
        "whiteFoxChange", manual=True, now_ms=200
    ) == RuntimeCommand(RuntimeCommandKind.PLAY, action="whiteFoxGreet")
    assert controller.current_form == "whiteFox"
    assert controller.busy is False


def test_busy_manual_request_overwrites_one_pending_target_across_request_kinds():
    controller = _controller()
    controller.request_transformation("whiteFoxChange", manual=True, now_ms=0)
    controller.action_finished(1)

    assert (
        controller.request_transformation(
            "fullHumanChange", manual=True, now_ms=2
        )
        is None
    )
    assert controller.request_sequence("spell", manual=True, now_ms=3) is None

    assert controller.action_finished(2_000).action == "whiteFoxExit"
    command = controller.action_finished(2_100)
    assert command == RuntimeCommand(
        RuntimeCommandKind.SET_FORM,
        action="a",
        form=DEFAULT_FORM,
        repeat_count=2,
        hold_ms=25,
    )
    assert controller.current_form == DEFAULT_FORM
    assert controller.busy is True


def test_busy_automatic_request_is_ignored_and_never_chains():
    controller = _controller()
    controller.request_transformation("whiteFoxChange", manual=True, now_ms=0)

    assert (
        controller.request_transformation(
            "corpseChange", manual=False, now_ms=1
        )
        is None
    )
    controller.action_finished(100)
    controller.action_finished(2_000)
    command = controller.action_finished(2_100)

    assert command == RuntimeCommand(RuntimeCommandKind.SET_FORM, form=DEFAULT_FORM)
    assert controller.current_form == DEFAULT_FORM
    assert controller.busy is False


def test_later_busy_manual_request_is_retained_after_automatic_request_is_ignored():
    controller = _controller()
    controller.request_transformation("whiteFoxChange", manual=True, now_ms=0)
    controller.request_transformation("corpseChange", manual=False, now_ms=1)
    controller.request_transformation("fullHumanChange", manual=True, now_ms=2)
    controller.action_finished(100)
    controller.action_finished(2_000)

    command = controller.action_finished(2_100)

    assert command == RuntimeCommand(
        RuntimeCommandKind.SET_FORM,
        action="fullHumanEnter",
        form=DEFAULT_FORM,
    )
    assert controller.busy is True


def test_manual_switch_from_an_idle_non_default_form_exits_before_new_enter():
    controller = _controller()
    controller.request_sequence("leaveAsFox", manual=True, now_ms=0)
    controller.action_finished(100)

    command = controller.request_transformation(
        "fullHumanChange", manual=True, now_ms=200
    )

    assert command == RuntimeCommand(RuntimeCommandKind.PLAY, action="whiteFoxExit")
    assert controller.current_form == "whiteFox"
    assert controller.busy is True
    assert controller.action_finished(300) == RuntimeCommand(
        RuntimeCommandKind.SET_FORM,
        action="fullHumanEnter",
        form=DEFAULT_FORM,
    )


def test_sequence_propagates_repeat_hold_and_form_changes_at_step_boundaries():
    controller = _controller()

    assert controller.request_sequence("spell", manual=True, now_ms=0) == RuntimeCommand(
        RuntimeCommandKind.PLAY,
        action="a",
        repeat_count=2,
        hold_ms=25,
    )
    assert controller.action_finished(100) == RuntimeCommand(
        RuntimeCommandKind.SET_FORM,
        action="b",
        form="fullHuman",
        repeat_count=3,
        hold_ms=50,
    )
    assert controller.action_finished(200) == RuntimeCommand(
        RuntimeCommandKind.PLAY,
        action="c",
    )
    assert controller.action_finished(300) == RuntimeCommand(
        RuntimeCommandKind.SET_FORM,
        form=DEFAULT_FORM,
    )
    assert controller.busy is False


def test_sequence_stops_only_after_declared_boundary_and_cleans_to_default():
    controller = _controller(sequence_safe_flags=(False, True, False))
    assert controller.request_sequence("spell", manual=True, now_ms=0).action == "a"
    assert controller.request_stop() is None
    assert controller.action_finished(100).action == "b"
    command = controller.action_finished(200)
    assert command.kind is RuntimeCommandKind.CLEANUP
    assert controller.current_form == DEFAULT_FORM
    assert controller.busy is False


@pytest.mark.parametrize("phase", ("enter", "resident", "exit"))
def test_normal_transformation_stop_restores_through_exit_clip(phase: str):
    controller = _controller()
    controller.request_transformation("whiteFoxChange", manual=True, now_ms=0)

    if phase == "enter":
        assert controller.request_stop() is None
        command = controller.action_finished(100)
        assert command == RuntimeCommand(
            RuntimeCommandKind.SET_FORM,
            action="whiteFoxExit",
            form="whiteFox",
        )
    else:
        controller.action_finished(100)
        if phase == "resident":
            assert controller.request_stop() is None
            command = controller.action_finished(200)
            assert command == RuntimeCommand(
                RuntimeCommandKind.PLAY,
                action="whiteFoxExit",
            )
        else:
            controller.action_finished(2_000)
            assert controller.request_stop() is None

    command = controller.action_finished(2_100)
    assert command == RuntimeCommand(RuntimeCommandKind.SET_FORM, form=DEFAULT_FORM)
    assert controller.current_form == DEFAULT_FORM
    assert controller.busy is False


def _at_hard_cancel_phase(phase: str) -> MultiformController:
    controller = _controller()
    if phase in {"enter", "resident", "exit"}:
        controller.request_transformation("whiteFoxChange", manual=True, now_ms=0)
        if phase in {"resident", "exit"}:
            controller.action_finished(100)
        if phase == "exit":
            controller.action_finished(2_000)
    elif phase == "spell_step":
        controller.request_sequence("spell", manual=True, now_ms=0)
    else:
        controller.request_sequence("completeShowcase", manual=True, now_ms=0)
        controller.action_finished(100)
    return controller


@pytest.mark.parametrize(
    "phase", ("enter", "resident", "exit", "spell_step", "complete_showcase")
)
def test_hard_cancel_cleans_every_phase_and_is_idempotent(phase: str):
    controller = _at_hard_cancel_phase(phase)
    expected = (
        RuntimeCommand(RuntimeCommandKind.CLEANUP, form=DEFAULT_FORM),
    )

    assert controller.hard_cancel() == expected
    assert controller.current_form == DEFAULT_FORM
    assert controller.busy is False
    assert controller.hard_cancel() == expected
    assert controller.current_form == DEFAULT_FORM
    assert controller.busy is False


def test_unknown_requests_fail_without_mutating_controller():
    controller = _controller()

    with pytest.raises(KeyError):
        controller.request_transformation("missing", manual=True, now_ms=0)
    with pytest.raises(KeyError):
        controller.request_sequence("missing", manual=True, now_ms=0)

    assert controller.current_form == DEFAULT_FORM
    assert controller.busy is False


def test_controller_rejects_non_default_form_without_a_declared_exit():
    with pytest.raises(
        ValueError,
        match="non-default forms must have a transformation exit: sequenceOnly",
    ):
        _controller(include_sequence_only_form=True)
