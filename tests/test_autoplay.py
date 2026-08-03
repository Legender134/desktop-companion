from __future__ import annotations

import random

import pytest

from shiyi_desktop_pet.autoplay import AutoplayBucketScheduler, AutoplayCandidate
from shiyi_desktop_pet.models import (
    PetAutoplayDefinition,
    PetCooldownGroupDefinition,
    PetSequenceDefinition,
    PetTransformationDefinition,
)


DEFAULT_FORM = "foxEaredHuman"


def _autoplay(
    bucket: str,
    weight: int,
    minimum: int,
    maximum: int,
    *groups: str,
) -> PetAutoplayDefinition:
    return PetAutoplayDefinition(bucket, weight, minimum, maximum, groups)


def _transformation(
    key: str,
    autoplay: PetAutoplayDefinition,
) -> PetTransformationDefinition:
    return PetTransformationDefinition(
        key,
        key,
        DEFAULT_FORM,
        f"{key}Form",
        "enter",
        (),
        "exit",
        1_000,
        2_000,
        True,
        autoplay,
    )


def _sequence(
    key: str,
    autoplay: PetAutoplayDefinition,
) -> PetSequenceDefinition:
    return PetSequenceDefinition(key, key, True, (), autoplay)


def _silvermoon_candidates(
    *,
    common_window: tuple[int, int] = (180_000, 360_000),
    rare_window: tuple[int, int] = (480_000, 900_000),
    spell_window: tuple[int, int] = (720_000, 1_200_000),
) -> tuple[
    tuple[PetTransformationDefinition, ...],
    tuple[PetSequenceDefinition, ...],
]:
    common = lambda weight: _autoplay(  # noqa: E731 - compact fixture factory
        "commonTransform", weight, *common_window, "globalTransform"
    )
    rare = lambda weight, *groups: _autoplay(  # noqa: E731
        "rareEvent", weight, *rare_window, *groups
    )
    spell = _autoplay(
        "majorSpell",
        4,
        *spell_window,
        "majorMagic",
        "magicReserve",
    )
    return (
        (
            _transformation("fox", common(8)),
            _transformation("rabbit", common(3)),
            _transformation("wolf", rare(2, "globalTransform")),
        ),
        (
            _sequence("corpse", rare(6, "globalTransform")),
            _sequence("han", rare(3, "globalTransform")),
            _sequence("moonSpell", spell),
        ),
    )


def _silvermoon_like_scheduler(
    rng: random.Random,
    *,
    common_window: tuple[int, int] = (180_000, 360_000),
    rare_window: tuple[int, int] = (480_000, 900_000),
    spell_window: tuple[int, int] = (720_000, 1_200_000),
    transform_cooldown_ms: int = 120_000,
    magic_cooldown_ms: int = 300_000,
    magic_reserve_cooldown_ms: int = 180_000,
) -> AutoplayBucketScheduler:
    transformations, sequences = _silvermoon_candidates(
        common_window=common_window,
        rare_window=rare_window,
        spell_window=spell_window,
    )
    return AutoplayBucketScheduler(
        transformations,
        sequences,
        (
            PetCooldownGroupDefinition(
                "globalTransform", transform_cooldown_ms
            ),
            PetCooldownGroupDefinition("majorMagic", magic_cooldown_ms),
            PetCooldownGroupDefinition(
                "magicReserve", magic_reserve_cooldown_ms
            ),
        ),
        default_form=DEFAULT_FORM,
        rng=rng,
    )


def test_common_rare_and_spell_buckets_use_approved_windows():
    scheduler = _silvermoon_like_scheduler(random.Random(3))

    scheduler.reset(1_000)

    deadlines = scheduler.deadlines
    assert 181_000 <= deadlines["commonTransform"] <= 361_000
    assert 481_000 <= deadlines["rareEvent"] <= 901_000
    assert 721_000 <= deadlines["majorSpell"] <= 1_201_000
    assert scheduler.next_deadline_ms() == min(deadlines.values())


def test_candidates_have_stable_kind_key_definition_and_autoplay_fields():
    scheduler = _silvermoon_like_scheduler(random.Random(0))

    candidates = {candidate.key: candidate for candidate in scheduler.candidates}

    assert isinstance(candidates["fox"], AutoplayCandidate)
    assert candidates["fox"].kind == "transformation"
    assert candidates["fox"].definition.key == "fox"
    assert candidates["corpse"].kind == "sequence"
    assert candidates["corpse"].autoplay.bucket == "rareEvent"


def test_common_bucket_only_chooses_its_two_transformations():
    transformations, _ = _silvermoon_candidates(
        common_window=(0, 0), rare_window=(10_000, 10_000)
    )
    scheduler = AutoplayBucketScheduler(
        transformations[:2],
        (),
        (PetCooldownGroupDefinition("globalTransform", 0),),
        default_form=DEFAULT_FORM,
        rng=random.Random(1),
    )
    scheduler.reset(0)
    seen: set[str] = set()

    for seed in range(100):
        choice = scheduler.choose_due(0, DEFAULT_FORM, random.Random(seed))
        assert choice is not None
        assert choice.kind == "transformation"
        seen.add(choice.key)

    assert seen == {"fox", "rabbit"}


def test_rare_bucket_uses_weights_across_transformations_and_sequences():
    transformations, sequences = _silvermoon_candidates(
        common_window=(10_000, 10_000),
        rare_window=(0, 0),
        spell_window=(10_000, 10_000),
    )
    scheduler = AutoplayBucketScheduler(
        transformations,
        sequences,
        (
            PetCooldownGroupDefinition("globalTransform", 0),
            PetCooldownGroupDefinition("majorMagic", 0),
            PetCooldownGroupDefinition("magicReserve", 0),
        ),
        default_form=DEFAULT_FORM,
        rng=random.Random(1),
    )
    scheduler.reset(0)
    counts = {"corpse": 0, "han": 0, "wolf": 0}

    for _ in range(2_000):
        choice = scheduler.choose_due(0, DEFAULT_FORM, random.Random(_))
        assert choice is not None
        assert choice.key in counts
        counts[choice.key] += 1

    assert counts["corpse"] > counts["han"] > counts["wolf"] > 0


def test_due_offer_is_not_consumed_until_automatic_start_is_accepted():
    scheduler = _silvermoon_like_scheduler(
        random.Random(0),
        common_window=(100, 100),
        rare_window=(10_000, 10_000),
        spell_window=(20_000, 20_000),
    )
    scheduler.reset(0)
    due_deadline = scheduler.deadlines["commonTransform"]

    offered = scheduler.choose_due(100, DEFAULT_FORM, random.Random(0))

    assert offered is not None
    assert offered.autoplay.bucket == "commonTransform"
    assert scheduler.deadlines["commonTransform"] == due_deadline

    rejected_offer = scheduler.choose_due(101, DEFAULT_FORM, random.Random(1))
    assert rejected_offer is not None
    assert scheduler.deadlines["commonTransform"] == due_deadline

    scheduler.record_started(offered, 101, automatic=True)

    assert scheduler.deadlines["commonTransform"] == 201


def test_recording_one_transform_group_candidate_blocks_every_group_member():
    scheduler = _silvermoon_like_scheduler(
        random.Random(0),
        common_window=(0, 0),
        rare_window=(0, 0),
        spell_window=(1_000_000, 1_000_000),
    )
    scheduler.reset(0)
    fox = next(candidate for candidate in scheduler.candidates if candidate.key == "fox")

    scheduler.record_started(fox, 10_000)

    assert scheduler.cooldown_deadlines["globalTransform"] == 130_000
    assert scheduler.choose_due(129_999, DEFAULT_FORM, random.Random(0)) is None
    choice = scheduler.choose_due(130_000, DEFAULT_FORM, random.Random(0))
    assert choice is not None
    assert "globalTransform" in choice.autoplay.cooldown_groups


@pytest.mark.parametrize(
    ("major_cooldown", "reserve_cooldown", "last_deadline"),
    [(10, 5, 110), (5, 10, 110)],
    ids=["first-group-blocks", "second-group-blocks"],
)
def test_every_named_shared_cooldown_blocks_a_two_group_candidate(
    major_cooldown: int,
    reserve_cooldown: int,
    last_deadline: int,
):
    scheduler = _silvermoon_like_scheduler(
        random.Random(0),
        common_window=(10_000, 10_000),
        rare_window=(20_000, 20_000),
        spell_window=(0, 0),
        magic_cooldown_ms=major_cooldown,
        magic_reserve_cooldown_ms=reserve_cooldown,
    )
    scheduler.reset(0)
    spell = next(
        candidate for candidate in scheduler.candidates if candidate.key == "moonSpell"
    )

    scheduler.record_started(spell, 100)

    assert scheduler.cooldown_deadlines == {
        "globalTransform": 0,
        "majorMagic": 100 + major_cooldown,
        "magicReserve": 100 + reserve_cooldown,
    }
    assert (
        scheduler.choose_due(
            last_deadline - 1,
            DEFAULT_FORM,
            random.Random(0),
        )
        is None
    )
    assert scheduler.choose_due(last_deadline, DEFAULT_FORM, random.Random(0)) == spell


def test_an_earlier_started_record_cannot_shorten_shared_cooldowns():
    scheduler = _silvermoon_like_scheduler(
        random.Random(0),
        magic_cooldown_ms=300,
        magic_reserve_cooldown_ms=200,
    )
    spell = next(
        candidate for candidate in scheduler.candidates if candidate.key == "moonSpell"
    )
    expected = {
        "globalTransform": 0,
        "majorMagic": 1_300,
        "magicReserve": 1_200,
    }

    scheduler.record_started(spell, 1_000)
    scheduler.record_started(spell, 500)

    assert scheduler.cooldown_deadlines == expected


def test_record_started_rejects_a_foreign_candidate_without_mutating_state():
    scheduler = _silvermoon_like_scheduler(random.Random(0))
    scheduler.reset(0)
    foreign_definition = _transformation(
        "foreign",
        _autoplay(
            "commonTransform",
            1,
            180_000,
            360_000,
            "globalTransform",
        ),
    )
    foreign = AutoplayCandidate(
        "transformation",
        foreign_definition.key,
        foreign_definition,
        foreign_definition.autoplay,
    )
    expected_deadlines = dict(scheduler.deadlines)
    expected_cooldowns = dict(scheduler.cooldown_deadlines)

    with pytest.raises(ValueError, match="does not belong"):
        scheduler.record_started(foreign, 1_000, automatic=True)

    assert scheduler.deadlines == expected_deadlines
    assert scheduler.cooldown_deadlines == expected_cooldowns


def test_value_equal_candidate_from_another_scheduler_is_still_foreign():
    scheduler = _silvermoon_like_scheduler(random.Random(0))
    other_scheduler = _silvermoon_like_scheduler(random.Random(1))
    scheduler.reset(0)
    owned = next(
        candidate for candidate in scheduler.candidates if candidate.key == "fox"
    )
    foreign = next(
        candidate
        for candidate in other_scheduler.candidates
        if candidate.key == "fox"
    )
    assert foreign == owned
    assert foreign is not owned
    expected_deadlines = dict(scheduler.deadlines)
    expected_cooldowns = dict(scheduler.cooldown_deadlines)

    with pytest.raises(ValueError, match="does not belong"):
        scheduler.record_started(foreign, 1_000, automatic=True)

    assert scheduler.deadlines == expected_deadlines
    assert scheduler.cooldown_deadlines == expected_cooldowns


@pytest.mark.parametrize(
    ("current_form", "pause_flags"),
    [
        ("whiteFox", {}),
        (DEFAULT_FORM, {"is_wandering": True}),
        (DEFAULT_FORM, {"always_gaze": True}),
        (DEFAULT_FORM, {"sequence_active": True}),
        (DEFAULT_FORM, {"autonomous_enabled": False}),
    ],
    ids=[
        "non-default-form",
        "wander",
        "always-gaze",
        "active-sequence",
        "autonomous-disabled",
    ],
)
def test_pauses_keep_an_expired_bucket_due(
    current_form: str,
    pause_flags: dict[str, bool],
):
    scheduler = _silvermoon_like_scheduler(
        random.Random(0),
        common_window=(0, 0),
        rare_window=(10_000, 10_000),
        spell_window=(20_000, 20_000),
    )
    scheduler.reset(100)
    expired_deadline = scheduler.deadlines["commonTransform"]

    assert (
        scheduler.choose_due(
            5_000,
            current_form,
            random.Random(0),
            **pause_flags,
        )
        is None
    )
    assert scheduler.deadlines["commonTransform"] == expired_deadline

    choice = scheduler.choose_due(5_000, DEFAULT_FORM, random.Random(0))
    assert choice is not None
    assert choice.autoplay.bucket == "commonTransform"


def test_defer_shortly_moves_due_poll_without_drawing_a_new_bucket_window():
    scheduler = _silvermoon_like_scheduler(
        random.Random(0),
        common_window=(180_000, 360_000),
        rare_window=(480_000, 900_000),
        spell_window=(720_000, 1_200_000),
    )
    scheduler.reset(-1_000_000)
    assert scheduler.deadlines["commonTransform"] <= 0

    scheduler.defer(10_000)

    assert scheduler.deadlines["commonTransform"] == 11_000
    assert scheduler.choose_due(10_999, DEFAULT_FORM, random.Random(0)) is None
    choice = scheduler.choose_due(11_000, DEFAULT_FORM, random.Random(0))
    assert choice is not None
    assert choice.autoplay.bucket == "commonTransform"


def test_manual_start_is_bookkept_even_when_scheduler_would_not_deliver_it():
    scheduler = _silvermoon_like_scheduler(random.Random(0))
    scheduler.reset(0)
    fox = next(candidate for candidate in scheduler.candidates if candidate.key == "fox")

    assert scheduler.choose_due(0, "whiteFox", random.Random(0)) is None
    initial_deadline = scheduler.deadlines["commonTransform"]
    scheduler.record_started(fox, 7_000)

    assert scheduler.cooldown_deadlines["globalTransform"] == 127_000
    assert scheduler.deadlines["commonTransform"] == initial_deadline


@pytest.mark.parametrize("weight", [0, -1, 1.0, True])
def test_scheduler_rejects_non_positive_integer_autoplay_weights(
    weight: int | float,
):
    invalid = _sequence("invalid", _autoplay("invalidBucket", weight, 0, 0))

    with pytest.raises(ValueError, match="weight must be a positive integer"):
        AutoplayBucketScheduler(
            (),
            (invalid,),
            (),
            default_form=DEFAULT_FORM,
            rng=random.Random(0),
        )


def test_one_hundred_thousand_picks_preserve_windows_eligibility_and_cooldowns():
    scheduler = _silvermoon_like_scheduler(
        random.Random(41),
        common_window=(1, 6),
        rare_window=(2, 8),
        spell_window=(3, 9),
        transform_cooldown_ms=4,
        magic_cooldown_ms=5,
        magic_reserve_cooldown_ms=7,
    )
    scheduler.reset(0)
    selection_rng = random.Random(91)
    windows = {
        "commonTransform": (1, 6),
        "rareEvent": (2, 8),
        "majorSpell": (3, 9),
    }
    all_keys = {candidate.key for candidate in scheduler.candidates}
    seen: set[str] = set()
    cooldown_durations = {
        "globalTransform": 4,
        "majorMagic": 5,
        "magicReserve": 7,
    }
    expected_cooldown_deadlines = {group: 0 for group in cooldown_durations}
    now = 0

    for _ in range(100_000):
        now = max(now, scheduler.next_deadline_ms())
        choice = scheduler.choose_due(now, DEFAULT_FORM, selection_rng)
        if choice is None:
            scheduler.defer(now)
            continue

        assert choice.key in all_keys
        assert choice.definition is not None
        assert all(
            now >= expected_cooldown_deadlines[group]
            for group in choice.autoplay.cooldown_groups
        )
        assert scheduler.deadlines[choice.autoplay.bucket] <= now
        scheduler.record_started(choice, now, automatic=True)
        for group in choice.autoplay.cooldown_groups:
            expected_cooldown_deadlines[group] = max(
                expected_cooldown_deadlines[group],
                now + cooldown_durations[group],
            )
        assert scheduler.cooldown_deadlines == expected_cooldown_deadlines
        minimum, maximum = windows[choice.autoplay.bucket]
        deadline = scheduler.deadlines[choice.autoplay.bucket]
        assert now + minimum <= deadline <= now + maximum
        seen.add(choice.key)

    assert seen == all_keys
