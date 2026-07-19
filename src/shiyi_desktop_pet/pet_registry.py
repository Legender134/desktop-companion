"""Discover safe data-only desktop-pet packs in legacy v2 or dynamic v3 form."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from .constants import ACTION_MANIFEST_SLOTS, DEFAULT_PET_ACTIONS, IN_PLACE_ACTIONS
from .models import ActionRole, AnimationSpec, PetActionDefinition


_PET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ACTION_KEY = re.compile(r"^[a-z][a-zA-Z0-9_-]{0,63}$")
_AUTOPLAY_GROUP = re.compile(r"^[a-z][a-zA-Z0-9_-]{0,31}$")
_MANIFEST_NAME = "pet.json"
_SPRITESHEET_NAME = "spritesheet.webp"
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_SPRITESHEET_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class PetDefinition:
    pet_id: str
    display_name: str
    description: str
    manifest_path: Path
    spritesheet_path: Path
    is_bundled: bool
    icon_frame: tuple[int, int]
    actions: tuple[PetActionDefinition, ...]
    sprite_version: int = 2


@dataclass(frozen=True)
class PetLoadIssue:
    pet_directory: Path
    message: str


@dataclass(frozen=True)
class PetRegistrySnapshot:
    pets: tuple[PetDefinition, ...]
    issues: tuple[PetLoadIssue, ...]

    @property
    def choices(self) -> tuple[tuple[str, str], ...]:
        return tuple((pet.pet_id, pet.display_name) for pet in self.pets)

    def by_id(self, pet_id: str) -> PetDefinition | None:
        normalized = str(pet_id).lower()
        return next((pet for pet in self.pets if pet.pet_id == normalized), None)


def is_valid_pet_id(value: object) -> bool:
    return isinstance(value, str) and _PET_ID.fullmatch(value.lower()) is not None


class PetRegistry:
    """Combine immutable bundled pets with validated per-user pet packs."""

    def __init__(
        self,
        bundled_root: Path,
        user_root: Path | None,
        *,
        validator: Callable[[PetDefinition], object] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.bundled_root = Path(bundled_root)
        self.user_root = Path(user_root) if user_root is not None else None
        self._validator = validator
        self._logger = logger or logging.getLogger(__name__)
        self._snapshot = PetRegistrySnapshot((), ())

    @property
    def snapshot(self) -> PetRegistrySnapshot:
        return self._snapshot

    def refresh(self) -> PetRegistrySnapshot:
        pets: list[PetDefinition] = []
        issues: list[PetLoadIssue] = []
        seen: set[str] = set()
        sources = [(self.bundled_root, True)]
        if self.user_root is not None:
            try:
                self.user_root.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                issues.append(PetLoadIssue(self.user_root, str(error)))
                self._logger.warning(
                    "Cannot prepare user pet directory %s (%s: %s)",
                    self.user_root,
                    type(error).__name__,
                    error,
                )
            else:
                sources.append((self.user_root, False))

        for root, is_bundled in sources:
            if not root.is_dir():
                issues.append(PetLoadIssue(root, "pet root is missing"))
                continue
            try:
                directories = sorted(root.iterdir(), key=lambda path: path.name.lower())
            except OSError as error:
                issues.append(PetLoadIssue(root, str(error)))
                continue
            for directory in directories:
                if not directory.is_dir():
                    continue
                try:
                    definition = self._load_definition(directory, is_bundled=is_bundled)
                    if definition.pet_id in seen:
                        raise ValueError(f"duplicate pet id: {definition.pet_id}")
                    if self._validator is not None:
                        self._validator(definition)
                except (
                    OSError,
                    UnicodeError,
                    json.JSONDecodeError,
                    TypeError,
                    ValueError,
                ) as error:
                    issue = PetLoadIssue(directory, str(error))
                    issues.append(issue)
                    self._logger.warning(
                        "Ignoring invalid pet pack %s (%s: %s)",
                        directory,
                        type(error).__name__,
                        error,
                    )
                    continue
                seen.add(definition.pet_id)
                pets.append(definition)

        self._snapshot = PetRegistrySnapshot(tuple(pets), tuple(issues))
        return self._snapshot

    @staticmethod
    def _load_definition(directory: Path, *, is_bundled: bool) -> PetDefinition:
        if directory.is_symlink() or (
            hasattr(directory, "is_junction") and directory.is_junction()
        ):
            raise ValueError("pet directory cannot be a link or junction")

        manifest_path = directory / _MANIFEST_NAME
        if not manifest_path.is_file():
            raise ValueError("pet.json is missing")
        if manifest_path.is_symlink():
            raise ValueError("pet.json cannot be a link")
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise ValueError("pet.json is too large")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("pet.json must contain an object")

        pet_id = manifest.get("id")
        if not is_valid_pet_id(pet_id) or pet_id != pet_id.lower():
            raise ValueError("invalid pet id")
        if directory.name != pet_id:
            raise ValueError("pet id must match its directory name")

        display_name = manifest.get("displayName")
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("displayName is required")
        display_name = display_name.strip()
        if len(display_name) > 64:
            raise ValueError("displayName is too long")

        description = manifest.get("description", "")
        if not isinstance(description, str) or len(description) > 500:
            raise ValueError("description must be text with at most 500 characters")

        sprite_version = manifest.get("spriteVersionNumber")
        if sprite_version not in {2, 3}:
            raise ValueError("unsupported sprite version; expected 2 or 3")
        if manifest.get("spritesheetPath") != _SPRITESHEET_NAME:
            raise ValueError("spritesheetPath must be spritesheet.webp")

        icon_frame = manifest.get("iconFrame", {"row": 0, "column": 0})
        if not isinstance(icon_frame, dict) or set(icon_frame) != {"row", "column"}:
            raise ValueError("iconFrame must contain row and column")
        icon_row = icon_frame["row"]
        icon_column = icon_frame["column"]
        row_limit = 10 if sprite_version == 2 else 127
        column_limit = 7 if sprite_version == 2 else 63
        if (
            not isinstance(icon_row, int)
            or isinstance(icon_row, bool)
            or not 0 <= icon_row <= row_limit
            or not isinstance(icon_column, int)
            or isinstance(icon_column, bool)
            or not 0 <= icon_column <= column_limit
        ):
            raise ValueError("iconFrame is outside the supported atlas grid")

        actions = (
            PetRegistry._parse_actions(manifest.get("actions"))
            if sprite_version == 2
            else PetRegistry._parse_v3_actions(manifest.get("actions"))
        )

        spritesheet_path = directory / _SPRITESHEET_NAME
        if not spritesheet_path.is_file():
            raise ValueError("spritesheet.webp is missing")
        if spritesheet_path.is_symlink():
            raise ValueError("spritesheet.webp cannot be a link")
        sprite_size = spritesheet_path.stat().st_size
        if sprite_size <= 0 or sprite_size > _MAX_SPRITESHEET_BYTES:
            raise ValueError("spritesheet.webp has an invalid file size")

        return PetDefinition(
            pet_id=pet_id,
            display_name=display_name,
            description=description,
            manifest_path=manifest_path,
            spritesheet_path=spritesheet_path,
            is_bundled=is_bundled,
            icon_frame=(icon_row, icon_column),
            actions=actions,
            sprite_version=sprite_version,
        )

    @staticmethod
    def _parse_actions(value: object) -> tuple[PetActionDefinition, ...]:
        if value is None:
            return DEFAULT_PET_ACTIONS
        expected_keys = {key for key, *_ in ACTION_MANIFEST_SLOTS}
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise ValueError("actions must contain every documented v2 action key")

        definitions: list[PetActionDefinition] = []
        for key, action_id, _default_label, _default_weight in ACTION_MANIFEST_SLOTS:
            entry = value[key]
            if not isinstance(entry, dict) or set(entry) != {"label", "autoplayWeight"}:
                raise ValueError(
                    f"actions.{key} must contain label and autoplayWeight"
                )
            label = entry["label"]
            if not isinstance(label, str):
                raise ValueError(f"actions.{key}.label must be text")
            label = label.strip()
            if (
                not label
                or len(label) > 32
                or any(not character.isprintable() for character in label)
            ):
                raise ValueError(
                    f"actions.{key}.label must be 1 through 32 printable characters"
                )
            weight = entry["autoplayWeight"]
            if (
                not isinstance(weight, int)
                or isinstance(weight, bool)
                or not 0 <= weight <= 10
            ):
                raise ValueError(
                    f"actions.{key}.autoplayWeight must be an integer from 0 through 10"
                )
            if action_id not in IN_PLACE_ACTIONS and weight != 0:
                raise ValueError(
                    f"actions.{key}.autoplayWeight must be 0 for a moving or idle action"
                )
            legacy = next(
                definition
                for definition in DEFAULT_PET_ACTIONS
                if definition.action_id is action_id
            )
            definitions.append(
                PetActionDefinition(
                    key,
                    action_id,
                    label,
                    weight,
                    spec=legacy.spec,
                    role=legacy.role,
                    direction=legacy.direction,
                )
            )

        if not any(definition.autoplay_weight for definition in definitions):
            raise ValueError("actions must enable at least one in-place autoplay action")
        return tuple(definitions)

    @staticmethod
    def _parse_v3_actions(value: object) -> tuple[PetActionDefinition, ...]:
        if not isinstance(value, dict) or not 3 <= len(value) <= 64:
            raise ValueError("v3 actions must contain 3 through 64 named actions")
        if any(not isinstance(key, str) or _ACTION_KEY.fullmatch(key) is None for key in value):
            raise ValueError("v3 action ids must be safe 1 through 64 character names")

        parsed: dict[str, PetActionDefinition] = {}
        mirrored: list[tuple[str, dict[str, object]]] = []
        for key, raw_entry in value.items():
            if not isinstance(raw_entry, dict):
                raise ValueError(f"actions.{key} must contain an object")
            entry = dict(raw_entry)
            common = PetRegistry._parse_v3_common(key, entry)
            if "mirrorOf" in entry:
                mirrored.append((key, entry))
                continue
            parsed[key] = PetRegistry._parse_v3_direct(key, entry, common)

        for key, entry in mirrored:
            common = PetRegistry._parse_v3_common(key, entry)
            source_key = entry.get("mirrorOf")
            if not isinstance(source_key, str) or source_key not in parsed:
                raise ValueError(f"actions.{key}.mirrorOf must name a direct action")
            source = parsed[source_key]
            (
                role,
                direction,
                label,
                weight,
                show,
                cooldown,
                autoplay_group,
                min_distance,
                travel_distance_ratio,
                max_vertical_ratio,
            ) = common
            allowed = {
                "label",
                "role",
                "direction",
                "mirrorOf",
                "showInMenu",
                "autoplayWeight",
                "cooldownMs",
                "autoplayGroup",
                "minDistance",
                "travelDistanceRatio",
                "maxVerticalRatio",
            }
            if set(entry) - allowed:
                raise ValueError(f"actions.{key} contains fields not allowed with mirrorOf")
            if source.role is not role or direction != -source.direction:
                raise ValueError(f"actions.{key} must mirror the opposite direction of the same role")
            parsed[key] = PetActionDefinition(
                key,
                key,
                label,
                weight,
                spec=source.spec,
                role=role,
                direction=direction,
                show_in_menu=show,
                cooldown_ms=cooldown,
                autoplay_group=autoplay_group,
                min_distance=min_distance or source.min_distance,
                travel_start_frame=source.travel_start_frame,
                travel_end_frame=source.travel_end_frame,
                travel_distance_ratio=(
                    travel_distance_ratio
                    if travel_distance_ratio is not None
                    else source.travel_distance_ratio
                ),
                max_vertical_ratio=(
                    max_vertical_ratio
                    if max_vertical_ratio is not None
                    else source.max_vertical_ratio
                ),
                mirror_of=source.action_id,
            )

        definitions = tuple(parsed[key] for key in value)
        idle = [item for item in definitions if item.role is ActionRole.IDLE]
        interactions = [
            item for item in definitions if item.role is ActionRole.INTERACTION
        ]
        if len(idle) != 1:
            raise ValueError("v3 actions must contain exactly one idle action")
        if not interactions:
            raise ValueError("v3 actions must contain at least one interaction action")
        for direction, name in ((-1, "left"), (1, "right")):
            if not any(
                item.role is ActionRole.MOVE and item.direction == direction
                for item in definitions
            ):
                raise ValueError(f"v3 actions must contain a normal {name} move")
        if sum(item.role is ActionRole.GAZE for item in definitions) > 1:
            raise ValueError("v3 actions may contain at most one gaze action")
        return definitions

    @staticmethod
    def _parse_v3_common(
        key: str, entry: dict[str, object]
    ) -> tuple[
        ActionRole,
        int,
        str,
        int,
        bool,
        int,
        str,
        int,
        float | None,
        float | None,
    ]:
        label = entry.get("label")
        if not isinstance(label, str):
            raise ValueError(f"actions.{key}.label must be text")
        label = label.strip()
        if not label or len(label) > 32 or any(not char.isprintable() for char in label):
            raise ValueError(f"actions.{key}.label must be 1 through 32 printable characters")
        try:
            role = ActionRole(entry.get("role"))
        except (TypeError, ValueError) as error:
            raise ValueError(f"actions.{key}.role is unsupported") from error

        direction_value = entry.get("direction")
        if role in {ActionRole.MOVE, ActionRole.BURST_MOVE}:
            if direction_value not in {"left", "right"}:
                raise ValueError(f"actions.{key}.direction must be left or right")
            direction = -1 if direction_value == "left" else 1
        else:
            if direction_value is not None:
                raise ValueError(f"actions.{key}.direction is only valid for movement")
            direction = 0

        weight = entry.get("autoplayWeight", 10 if role is ActionRole.MOVE else 0)
        if not PetRegistry._is_int_between(weight, 0, 100):
            raise ValueError(f"actions.{key}.autoplayWeight must be an integer from 0 through 100")
        if role in {ActionRole.IDLE, ActionRole.GAZE} and weight != 0:
            raise ValueError(f"actions.{key}.autoplayWeight must be 0 for its role")
        show = entry.get("showInMenu", role is not ActionRole.GAZE)
        if not isinstance(show, bool):
            raise ValueError(f"actions.{key}.showInMenu must be boolean")
        cooldown = entry.get("cooldownMs", 0)
        if not PetRegistry._is_int_between(cooldown, 0, 600_000):
            raise ValueError(f"actions.{key}.cooldownMs must be 0 through 600000")
        autoplay_group = entry.get("autoplayGroup", "")
        if not isinstance(autoplay_group, str) or (
            autoplay_group and _AUTOPLAY_GROUP.fullmatch(autoplay_group) is None
        ):
            raise ValueError(
                f"actions.{key}.autoplayGroup must be empty or a safe 1 through 32 character name"
            )
        if role is not ActionRole.INTERACTION and autoplay_group:
            raise ValueError(
                f"actions.{key}.autoplayGroup is only valid for interaction actions"
            )
        min_distance = entry.get("minDistance", 0)
        if not PetRegistry._is_int_between(min_distance, 0, 10_000):
            raise ValueError(f"actions.{key}.minDistance must be 0 through 10000")
        if role is not ActionRole.BURST_MOVE and min_distance != 0:
            raise ValueError(f"actions.{key}.minDistance is only valid for burstMove")
        travel_distance_ratio = entry.get("travelDistanceRatio")
        if travel_distance_ratio is not None and not PetRegistry._is_number_between(
            travel_distance_ratio, 0.05, 1.0
        ):
            raise ValueError(
                f"actions.{key}.travelDistanceRatio must be a number from 0.05 through 1"
            )
        max_vertical_ratio = entry.get("maxVerticalRatio")
        if max_vertical_ratio is not None and not PetRegistry._is_number_between(
            max_vertical_ratio, 0.0, 1.0
        ):
            raise ValueError(
                f"actions.{key}.maxVerticalRatio must be a number from 0 through 1"
            )
        if role is not ActionRole.BURST_MOVE and (
            travel_distance_ratio is not None or max_vertical_ratio is not None
        ):
            raise ValueError(
                f"actions.{key} travel ratios are only valid for burstMove"
            )
        return (
            role,
            direction,
            label,
            weight,
            show,
            cooldown,
            autoplay_group,
            min_distance,
            float(travel_distance_ratio) if travel_distance_ratio is not None else None,
            float(max_vertical_ratio) if max_vertical_ratio is not None else None,
        )

    @staticmethod
    def _parse_v3_direct(
        key: str,
        entry: dict[str, object],
        common: tuple[
            ActionRole,
            int,
            str,
            int,
            bool,
            int,
            str,
            int,
            float | None,
            float | None,
        ],
    ) -> PetActionDefinition:
        (
            role,
            direction,
            label,
            weight,
            show,
            cooldown,
            autoplay_group,
            min_distance,
            travel_distance_ratio,
            max_vertical_ratio,
        ) = common
        allowed = {
            "label",
            "role",
            "direction",
            "row",
            "startColumn",
            "frameCount",
            "frameMs",
            "frameDurations",
            "loop",
            "repeatCount",
            "holdMs",
            "showInMenu",
            "autoplayWeight",
            "cooldownMs",
            "autoplayGroup",
            "minDistance",
            "travelStartFrame",
            "travelEndFrame",
            "travelDistanceRatio",
            "maxVerticalRatio",
        }
        unknown = set(entry) - allowed
        if unknown:
            raise ValueError(f"actions.{key} contains unknown fields: {', '.join(sorted(unknown))}")
        row = entry.get("row")
        column = entry.get("startColumn", 0)
        frame_count = entry.get("frameCount")
        if not PetRegistry._is_int_between(row, 0, 127):
            raise ValueError(f"actions.{key}.row must be 0 through 127")
        if not PetRegistry._is_int_between(column, 0, 63):
            raise ValueError(f"actions.{key}.startColumn must be 0 through 63")
        if not PetRegistry._is_int_between(frame_count, 1, 64):
            raise ValueError(f"actions.{key}.frameCount must be 1 through 64")

        frame_ms = entry.get("frameMs")
        durations_value = entry.get("frameDurations")
        if (frame_ms is None) == (durations_value is None):
            raise ValueError(f"actions.{key} must contain exactly one of frameMs or frameDurations")
        durations: tuple[int, ...] | None = None
        if frame_ms is not None:
            if not PetRegistry._is_int_between(frame_ms, 33, 2_000):
                raise ValueError(f"actions.{key}.frameMs must be 33 through 2000")
        else:
            if (
                not isinstance(durations_value, list)
                or len(durations_value) != frame_count
                or any(
                    not PetRegistry._is_int_between(duration, 33, 2_000)
                    for duration in durations_value
                )
            ):
                raise ValueError(
                    f"actions.{key}.frameDurations must match frameCount with values 33 through 2000"
                )
            durations = tuple(durations_value)
            frame_ms = durations[0]

        loop = entry.get("loop", role is ActionRole.IDLE)
        if not isinstance(loop, bool):
            raise ValueError(f"actions.{key}.loop must be boolean")
        repeat_count = entry.get("repeatCount", 1)
        if not PetRegistry._is_int_between(repeat_count, 1, 20):
            raise ValueError(f"actions.{key}.repeatCount must be 1 through 20")
        if loop and "repeatCount" in entry:
            raise ValueError(f"actions.{key}.repeatCount cannot be used with loop")
        hold_ms = entry.get("holdMs", 0)
        if not PetRegistry._is_int_between(hold_ms, 0, 10_000):
            raise ValueError(f"actions.{key}.holdMs must be 0 through 10000")
        if role is ActionRole.IDLE and not loop:
            raise ValueError(f"actions.{key} idle action must loop")
        if role in {ActionRole.INTERACTION, ActionRole.BURST_MOVE} and loop:
            raise ValueError(f"actions.{key} finite action cannot loop forever")
        if role is ActionRole.BURST_MOVE and repeat_count != 1:
            raise ValueError(f"actions.{key} burstMove repeatCount must be 1")
        if role is ActionRole.GAZE and frame_count != 16:
            raise ValueError(f"actions.{key} gaze action must contain 16 frames")

        travel_start: int | None = None
        travel_end: int | None = None
        if role is ActionRole.BURST_MOVE:
            if frame_count < 3:
                raise ValueError(f"actions.{key} burstMove must contain at least 3 frames")
            travel_start = entry.get("travelStartFrame", max(1, frame_count // 3))
            if not PetRegistry._is_int_between(travel_start, 0, frame_count - 2):
                raise ValueError(
                    f"actions.{key} travel frames must satisfy 0 <= start < end < frameCount"
                )
            travel_end = entry.get(
                "travelEndFrame",
                min(frame_count - 1, max(travel_start + 1, frame_count * 2 // 3)),
            )
            if not PetRegistry._is_int_between(
                travel_end, travel_start + 1, frame_count - 1
            ):
                raise ValueError(
                    f"actions.{key} travel frames must satisfy 0 <= start < end < frameCount"
                )
        elif "travelStartFrame" in entry or "travelEndFrame" in entry:
            raise ValueError(f"actions.{key} travel frames are only valid for burstMove")

        spec = AnimationSpec(
            row,
            frame_count,
            frame_ms,
            None if loop else repeat_count,
            hold_ms=hold_ms,
            movement=direction if role is ActionRole.MOVE else 0,
            start_column=column,
            frame_durations=durations,
        )
        return PetActionDefinition(
            key,
            key,
            label,
            weight,
            spec=spec,
            role=role,
            direction=direction,
            show_in_menu=show,
            cooldown_ms=cooldown,
            autoplay_group=autoplay_group,
            min_distance=min_distance,
            travel_start_frame=travel_start,
            travel_end_frame=travel_end,
            travel_distance_ratio=travel_distance_ratio,
            max_vertical_ratio=max_vertical_ratio,
        )

    @staticmethod
    def _is_int_between(value: object, lower: int, upper: int) -> bool:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and lower <= value <= upper
        )

    @staticmethod
    def _is_number_between(value: object, lower: float, upper: float) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and lower <= float(value) <= upper
        )
