"""Discover safe data-only desktop-pet packs in v2, v3, or layered v4 form."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from .constants import ACTION_MANIFEST_SLOTS, DEFAULT_PET_ACTIONS, IN_PLACE_ACTIONS
from .models import (
    ActionRole,
    AnimationSpec,
    PetActionDefinition,
    PetActionLayerDefinition,
    PetAtlasDefinition,
    PetAutoplayDefinition,
    PetCooldownGroupDefinition,
    PetFormDefinition,
    PetSequenceDefinition,
    PetSequenceStep,
    PetStateActionChoice,
    PetStateDefinition,
    PetTransformationDefinition,
)


_PET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ACTION_KEY = re.compile(r"^[a-z][a-zA-Z0-9_-]{0,63}$")
_AUTOPLAY_GROUP = re.compile(r"^[a-z][a-zA-Z0-9_-]{0,31}$")
_STATE_KEY = re.compile(r"^[a-z][a-zA-Z0-9_-]{0,63}$")
_V4_KEY = re.compile(r"^[a-z][A-Za-z0-9]{0,63}$")
_V4_ATLAS_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.webp$")
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
    states: tuple[PetStateDefinition, ...] = ()
    sprite_version: int = 2
    atlases: tuple[PetAtlasDefinition, ...] = ()
    forms: tuple[PetFormDefinition, ...] = ()
    default_form: str = ""
    transformations: tuple[PetTransformationDefinition, ...] = ()
    cooldown_groups: tuple[PetCooldownGroupDefinition, ...] = ()
    sequences: tuple[PetSequenceDefinition, ...] = ()


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
        requested = str(pet_id)
        exact = next((pet for pet in self.pets if pet.pet_id == requested), None)
        if exact is not None:
            return exact
        normalized = requested.lower()
        return next(
            (
                pet
                for pet in self.pets
                if pet.sprite_version in {2, 3} and pet.pet_id == normalized
            ),
            None,
        )


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

        sprite_version = manifest.get("spriteVersionNumber")
        if (
            not isinstance(sprite_version, int)
            or isinstance(sprite_version, bool)
            or sprite_version not in {2, 3, 4}
        ):
            raise ValueError("unsupported sprite version; expected 2, 3, or 4")

        pet_id = manifest.get("id")
        if sprite_version == 4:
            if not isinstance(pet_id, str) or _V4_KEY.fullmatch(pet_id) is None:
                raise ValueError("invalid v4 pet id")
        elif not is_valid_pet_id(pet_id) or pet_id != pet_id.lower():
            raise ValueError("invalid pet id")
        if directory.name != pet_id:
            raise ValueError("pet id must match its directory name")

        display_name = manifest.get("displayName")
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("displayName is required")
        display_name = display_name.strip()
        display_name_limit = 80 if sprite_version == 4 else 64
        if len(display_name) > display_name_limit or (
            sprite_version == 4
            and any(
                ord(character) < 32 or 127 <= ord(character) <= 159
                for character in display_name
            )
        ):
            raise ValueError("displayName is too long")

        description = manifest.get("description", "")
        if not isinstance(description, str) or len(description) > 500:
            raise ValueError("description must be text with at most 500 characters")
        if sprite_version == 4 and any(
            ord(character) < 32 or ord(character) == 127
            for character in description
        ):
            raise ValueError("description contains control characters")

        if sprite_version == 4:
            allowed_v4_fields = {
                "id",
                "displayName",
                "description",
                "spriteVersionNumber",
                "defaultForm",
                "iconFrame",
                "atlases",
                "cooldownGroups",
                "actions",
                "forms",
                "transformations",
                "sequences",
            }
            unknown = set(manifest) - allowed_v4_fields
            if unknown:
                raise ValueError(
                    f"v4 manifest contains unknown fields: {', '.join(sorted(unknown))}"
                )
            if "spritesheetPath" in manifest:
                raise ValueError("spritesheetPath is not supported by sprite version 4")
        elif manifest.get("spritesheetPath") != _SPRITESHEET_NAME:
            raise ValueError("spritesheetPath must be spritesheet.webp")

        if sprite_version == 4:
            raw_atlases = manifest.get("atlases")
            first_atlas = next(iter(raw_atlases), "") if isinstance(raw_atlases, dict) else ""
            default_icon_frame = {"atlas": first_atlas, "row": 0, "column": 0}
        else:
            default_icon_frame = {"row": 0, "column": 0}
        icon_frame = manifest.get("iconFrame", default_icon_frame)
        expected_icon_fields = (
            {"atlas", "row", "column"}
            if sprite_version == 4
            else {"row", "column"}
        )
        if not isinstance(icon_frame, dict) or set(icon_frame) != expected_icon_fields:
            raise ValueError(
                "iconFrame must contain atlas, row, and column"
                if sprite_version == 4
                else "iconFrame must contain row and column"
            )
        icon_row = icon_frame["row"]
        icon_column = icon_frame["column"]
        if sprite_version == 4:
            if not PetRegistry._is_int_between(icon_row, 0, 2**31 - 1) or not PetRegistry._is_int_between(
                icon_column, 0, 2**31 - 1
            ):
                raise ValueError("iconFrame is outside the supported atlas grid")
        else:
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

        if sprite_version == 2:
            actions = PetRegistry._parse_actions(manifest.get("actions"))
            if "states" in manifest:
                raise ValueError("states are only supported by sprite version 3")
            states: tuple[PetStateDefinition, ...] = ()
            atlases: tuple[PetAtlasDefinition, ...] = ()
            forms: tuple[PetFormDefinition, ...] = ()
            default_form = ""
            transformations: tuple[PetTransformationDefinition, ...] = ()
            cooldown_groups: tuple[PetCooldownGroupDefinition, ...] = ()
            sequences: tuple[PetSequenceDefinition, ...] = ()
        elif sprite_version == 3:
            actions = PetRegistry._parse_v3_actions(manifest.get("actions"))
            states = PetRegistry._parse_v3_states(
                manifest.get("states"), actions
            )
            atlases = ()
            forms = ()
            default_form = ""
            transformations = ()
            cooldown_groups = ()
            sequences = ()
        else:
            if "states" in manifest:
                raise ValueError("states are only supported by sprite version 3")
            atlases = PetRegistry._parse_v4_atlases(manifest.get("atlases"), directory)
            actions = PetRegistry._parse_v4_actions(manifest.get("actions"))
            forms = PetRegistry._parse_v4_forms(manifest.get("forms"))
            default_form = manifest.get("defaultForm")
            transformations = PetRegistry._parse_v4_transformations(
                manifest.get("transformations")
            )
            cooldown_groups = PetRegistry._parse_v4_cooldown_groups(
                manifest.get("cooldownGroups")
            )
            sequences = PetRegistry._parse_v4_sequences(manifest.get("sequences"))
            PetRegistry._validate_v4_references(
                atlases,
                actions,
                forms,
                default_form,
                transformations,
                cooldown_groups,
                sequences,
                icon_frame["atlas"],
            )
            states = ()

        if sprite_version == 4:
            spritesheet_path = atlases[0].path
        else:
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
            states=states,
            sprite_version=sprite_version,
            atlases=atlases,
            forms=forms,
            default_form=default_form,
            transformations=transformations,
            cooldown_groups=cooldown_groups,
            sequences=sequences,
        )

    @staticmethod
    def _parse_v4_atlases(
        value: object, directory: Path
    ) -> tuple[PetAtlasDefinition, ...]:
        if not isinstance(value, dict) or not 1 <= len(value) <= 8:
            raise ValueError("v4 atlases must contain 1 through 8 named atlases")
        PetRegistry._validate_v4_keys(value, "atlas")

        definitions: list[PetAtlasDefinition] = []
        paths: set[str] = set()
        encoded_bytes = 0
        for key, raw_entry in value.items():
            if not isinstance(raw_entry, dict) or set(raw_entry) != {
                "path",
                "cellWidth",
                "cellHeight",
            }:
                raise ValueError(
                    f"atlases.{key} must contain path, cellWidth, and cellHeight"
                )
            path_value = raw_entry["path"]
            if (
                not isinstance(path_value, str)
                or _V4_ATLAS_PATH.fullmatch(path_value) is None
                or Path(path_value).name != path_value
            ):
                raise ValueError(f"atlases.{key}.path must be a bare WebP filename")
            if path_value in paths:
                raise ValueError("v4 atlases must use distinct files")
            cell_width = raw_entry["cellWidth"]
            cell_height = raw_entry["cellHeight"]
            if not PetRegistry._is_int_between(cell_width, 1, 2**31 - 1):
                raise ValueError(f"atlases.{key}.cellWidth must be a positive integer")
            if not PetRegistry._is_int_between(cell_height, 1, 2**31 - 1):
                raise ValueError(f"atlases.{key}.cellHeight must be a positive integer")

            path = directory / path_value
            if not path.is_file():
                raise ValueError(f"atlases.{key} atlas file is missing")
            if path.is_symlink():
                raise ValueError(f"atlases.{key} atlas file cannot be a link")
            size = path.stat().st_size
            if size <= 0:
                raise ValueError(f"atlases.{key} atlas file is empty")
            encoded_bytes += size
            if encoded_bytes > _MAX_SPRITESHEET_BYTES:
                raise ValueError("v4 encoded atlas files may total at most 32 MiB")
            paths.add(path_value)
            definitions.append(
                PetAtlasDefinition(key, path, cell_width, cell_height)
            )
        return tuple(definitions)

    @staticmethod
    def _parse_v4_actions(value: object) -> tuple[PetActionDefinition, ...]:
        if not isinstance(value, dict) or not 1 <= len(value) <= 128:
            raise ValueError("v4 actions must contain 1 through 128 named actions")
        PetRegistry._validate_v4_keys(value, "action")
        definitions: list[PetActionDefinition] = []
        allowed = {
            "label",
            "role",
            "direction",
            "showInMenu",
            "includeInShowcase",
            "autoplayWeight",
            "cooldownMs",
            "autoplayGroup",
            "minDistance",
            "travelDistanceRatio",
            "maxVerticalRatio",
            "mirrorOf",
            "frameCount",
            "frameMs",
            "frameDurations",
            "loop",
            "repeatCount",
            "holdMs",
            "travelStartFrame",
            "travelEndFrame",
            "layers",
        }
        for key, raw_entry in value.items():
            if not isinstance(raw_entry, dict):
                raise ValueError(f"actions.{key} must contain an object")
            unknown = set(raw_entry) - allowed
            if unknown:
                raise ValueError(
                    f"actions.{key} contains unknown fields: {', '.join(sorted(unknown))}"
                )
            if not {"label", "role", "frameCount", "layers"} <= set(raw_entry):
                raise ValueError(f"actions.{key} is missing required v4 fields")

            label = PetRegistry._parse_v4_label(raw_entry["label"], f"actions.{key}.label")
            try:
                role = ActionRole(raw_entry["role"])
            except (TypeError, ValueError) as error:
                raise ValueError(f"actions.{key}.role is unsupported") from error
            direction_value = raw_entry.get("direction")
            if role in {ActionRole.MOVE, ActionRole.BURST_MOVE}:
                if direction_value not in {"left", "right"}:
                    raise ValueError(f"actions.{key}.direction must be left or right")
                direction = -1 if direction_value == "left" else 1
            else:
                if direction_value is not None:
                    raise ValueError(
                        f"actions.{key}.direction is only valid for movement"
                    )
                direction = 0

            frame_count = raw_entry["frameCount"]
            if not PetRegistry._is_int_between(frame_count, 1, 512):
                raise ValueError(f"actions.{key}.frameCount must be 1 through 512")
            frame_ms = raw_entry.get("frameMs")
            durations_value = raw_entry.get("frameDurations")
            if (frame_ms is None) == (durations_value is None):
                raise ValueError(
                    f"actions.{key} must contain exactly one of frameMs or frameDurations"
                )
            durations: tuple[int, ...] | None = None
            if frame_ms is not None:
                if not PetRegistry._is_int_between(frame_ms, 33, 2_000):
                    raise ValueError(f"actions.{key}.frameMs must be 33 through 2000")
            else:
                if (
                    not isinstance(durations_value, list)
                    or len(durations_value) != frame_count
                    or any(
                        not PetRegistry._is_int_between(item, 33, 2_000)
                        for item in durations_value
                    )
                ):
                    raise ValueError(
                        f"actions.{key}.frameDurations must match frameCount with values 33 through 2000"
                    )
                durations = tuple(durations_value)
                frame_ms = durations[0]

            loop = raw_entry.get("loop", role is ActionRole.IDLE)
            if not isinstance(loop, bool):
                raise ValueError(f"actions.{key}.loop must be boolean")
            repeat_count = raw_entry.get("repeatCount", 1)
            if not PetRegistry._is_int_between(repeat_count, 1, 20):
                raise ValueError(f"actions.{key}.repeatCount must be 1 through 20")
            if loop and "repeatCount" in raw_entry:
                raise ValueError(f"actions.{key}.repeatCount cannot be used with loop")
            hold_ms = raw_entry.get("holdMs", 0)
            if not PetRegistry._is_int_between(hold_ms, 0, 10_000):
                raise ValueError(f"actions.{key}.holdMs must be 0 through 10000")
            if role is ActionRole.IDLE and not loop:
                raise ValueError(f"actions.{key} idle action must loop")
            if role in {ActionRole.INTERACTION, ActionRole.BURST_MOVE} and loop:
                raise ValueError(f"actions.{key} finite action cannot loop forever")
            if role is ActionRole.BURST_MOVE and repeat_count != 1:
                raise ValueError(f"actions.{key} burstMove repeatCount must be 1")
            if role is ActionRole.GAZE and frame_count not in {16, 32, 64}:
                raise ValueError(
                    f"actions.{key} gaze action must contain 16, 32, or 64 frames"
                )

            weight = raw_entry.get("autoplayWeight", 10 if role is ActionRole.MOVE else 0)
            if not PetRegistry._is_int_between(weight, 0, 100):
                raise ValueError(f"actions.{key}.autoplayWeight must be 0 through 100")
            if role in {ActionRole.IDLE, ActionRole.GAZE} and weight:
                raise ValueError(f"actions.{key}.autoplayWeight must be 0 for its role")
            show = raw_entry.get("showInMenu", role is not ActionRole.GAZE)
            include = raw_entry.get("includeInShowcase", True)
            if not isinstance(show, bool):
                raise ValueError(f"actions.{key}.showInMenu must be boolean")
            if not isinstance(include, bool):
                raise ValueError(f"actions.{key}.includeInShowcase must be boolean")
            cooldown = raw_entry.get("cooldownMs", 0)
            if not PetRegistry._is_int_between(cooldown, 0, 1_200_000):
                raise ValueError(f"actions.{key}.cooldownMs must be 0 through 1200000")
            autoplay_group = raw_entry.get("autoplayGroup", "")
            if not isinstance(autoplay_group, str) or (
                autoplay_group and _V4_KEY.fullmatch(autoplay_group) is None
            ):
                raise ValueError(f"actions.{key}.autoplayGroup must be empty or a safe id")
            if role is not ActionRole.INTERACTION and autoplay_group:
                raise ValueError(
                    f"actions.{key}.autoplayGroup is only valid for interaction actions"
                )
            min_distance = raw_entry.get("minDistance", 0)
            if not PetRegistry._is_int_between(min_distance, 0, 10_000):
                raise ValueError(f"actions.{key}.minDistance must be 0 through 10000")
            if role is not ActionRole.BURST_MOVE and min_distance:
                raise ValueError(f"actions.{key}.minDistance is only valid for burstMove")
            travel_ratio = raw_entry.get("travelDistanceRatio")
            vertical_ratio = raw_entry.get("maxVerticalRatio")
            if travel_ratio is not None and not PetRegistry._is_number_between(
                travel_ratio, 0.05, 1.0
            ):
                raise ValueError(
                    f"actions.{key}.travelDistanceRatio must be 0.05 through 1"
                )
            if vertical_ratio is not None and not PetRegistry._is_number_between(
                vertical_ratio, 0.0, 1.0
            ):
                raise ValueError(f"actions.{key}.maxVerticalRatio must be 0 through 1")
            if role is not ActionRole.BURST_MOVE and (
                travel_ratio is not None or vertical_ratio is not None
            ):
                raise ValueError(f"actions.{key} travel ratios require burstMove")

            travel_start: int | None = None
            travel_end: int | None = None
            if role is ActionRole.BURST_MOVE:
                if frame_count < 3:
                    raise ValueError(f"actions.{key} burstMove must contain at least 3 frames")
                travel_start = raw_entry.get("travelStartFrame", max(1, frame_count // 3))
                travel_end = raw_entry.get(
                    "travelEndFrame",
                    min(frame_count - 1, max(travel_start + 1, frame_count * 2 // 3))
                    if isinstance(travel_start, int) and not isinstance(travel_start, bool)
                    else None,
                )
                if not PetRegistry._is_int_between(travel_start, 0, frame_count - 2) or not PetRegistry._is_int_between(
                    travel_end, travel_start + 1 if isinstance(travel_start, int) else 1, frame_count - 1
                ):
                    raise ValueError(
                        f"actions.{key} travel frames must satisfy 0 <= start < end < frameCount"
                    )
            elif "travelStartFrame" in raw_entry or "travelEndFrame" in raw_entry:
                raise ValueError(f"actions.{key} travel frames require burstMove")

            layers_value = raw_entry["layers"]
            if not isinstance(layers_value, list) or not 1 <= len(layers_value) <= 8:
                raise ValueError(f"actions.{key}.layers must contain 1 through 8 layers")
            layers: list[PetActionLayerDefinition] = []
            for index, layer_value in enumerate(layers_value):
                layers.append(
                    PetRegistry._parse_v4_layer(key, index, layer_value, frame_count)
                )
            if sum(layer.hit_test for layer in layers) != 1:
                raise ValueError(f"actions.{key} must contain exactly one hitTest layer")

            mirror_of = raw_entry.get("mirrorOf")
            if mirror_of is not None and (
                not isinstance(mirror_of, str) or _V4_KEY.fullmatch(mirror_of) is None
            ):
                raise ValueError(f"actions.{key}.mirrorOf must be a safe action id")
            definitions.append(
                PetActionDefinition(
                    key,
                    key,
                    label,
                    weight,
                    spec=AnimationSpec(
                        0,
                        frame_count,
                        frame_ms,
                        None if loop else repeat_count,
                        hold_ms=hold_ms,
                        movement=direction if role is ActionRole.MOVE else 0,
                        frame_durations=durations,
                    ),
                    role=role,
                    direction=direction,
                    show_in_menu=show,
                    include_in_showcase=include,
                    cooldown_ms=cooldown,
                    autoplay_group=autoplay_group,
                    min_distance=min_distance,
                    travel_start_frame=travel_start,
                    travel_end_frame=travel_end,
                    travel_distance_ratio=float(travel_ratio) if travel_ratio is not None else None,
                    max_vertical_ratio=float(vertical_ratio) if vertical_ratio is not None else None,
                    mirror_of=mirror_of,
                    layers=tuple(layers),
                )
            )
        return tuple(definitions)

    @staticmethod
    def _parse_v4_layer(
        action_key: str, index: int, value: object, frame_count: int
    ) -> PetActionLayerDefinition:
        required = {"atlas", "row", "startColumn", "anchorX", "anchorY"}
        allowed = required | {
            "offsetX",
            "offsetY",
            "scalePercent",
            "opacityPercent",
            "hitTest",
            "optionalInSimplified",
            "frameMap",
        }
        prefix = f"actions.{action_key}.layers[{index}]"
        if not isinstance(value, dict) or not required <= set(value) or set(value) - allowed:
            raise ValueError(f"{prefix} does not match the documented layer fields")
        atlas_id = value["atlas"]
        if not isinstance(atlas_id, str) or _V4_KEY.fullmatch(atlas_id) is None:
            raise ValueError(f"{prefix}.atlas must be a safe atlas id")
        for name in ("row", "startColumn", "anchorX", "anchorY"):
            if not PetRegistry._is_int_between(value[name], 0, 2**31 - 1):
                raise ValueError(f"{prefix}.{name} must be a non-negative integer")
        offset_x = value.get("offsetX", 0)
        offset_y = value.get("offsetY", 0)
        if not PetRegistry._is_int_between(offset_x, -100_000, 100_000) or not PetRegistry._is_int_between(
            offset_y, -100_000, 100_000
        ):
            raise ValueError(f"{prefix} offsets must be -100000 through 100000")
        scale = value.get("scalePercent", 100)
        opacity = value.get("opacityPercent", 100)
        if not PetRegistry._is_int_between(scale, 1, 1_000):
            raise ValueError(f"{prefix}.scalePercent must be 1 through 1000")
        if not PetRegistry._is_int_between(opacity, 0, 100):
            raise ValueError(f"{prefix}.opacityPercent must be 0 through 100")
        hit_test = value.get("hitTest", False)
        optional = value.get("optionalInSimplified", False)
        if not isinstance(hit_test, bool) or not isinstance(optional, bool):
            raise ValueError(f"{prefix} layer flags must be boolean")
        frame_map_value = value.get("frameMap")
        frame_map: tuple[int | None, ...] | None = None
        if frame_map_value is not None:
            if not isinstance(frame_map_value, list) or len(frame_map_value) != frame_count:
                raise ValueError(f"{prefix}.frameMap length must match frameCount")
            if any(
                item is not None
                and not PetRegistry._is_int_between(item, 0, frame_count - 1)
                for item in frame_map_value
            ):
                raise ValueError(f"{prefix}.frameMap references an unavailable atlas cell")
            frame_map = tuple(frame_map_value)
        return PetActionLayerDefinition(
            atlas_id,
            value["row"],
            value["startColumn"],
            value["anchorX"],
            value["anchorY"],
            offset_x=offset_x,
            offset_y=offset_y,
            scale_percent=scale,
            opacity_percent=opacity,
            hit_test=hit_test,
            optional_in_simplified=optional,
            frame_map=frame_map,
        )

    @staticmethod
    def _parse_v4_forms(value: object) -> tuple[PetFormDefinition, ...]:
        if not isinstance(value, dict) or not 1 <= len(value) <= 16:
            raise ValueError("v4 forms must contain 1 through 16 named forms")
        PetRegistry._validate_v4_keys(value, "form")
        definitions: list[PetFormDefinition] = []
        required = {
            "label",
            "idleAction",
            "moveRightAction",
            "moveLeftAction",
            "representativeAction",
            "interactionActions",
        }
        allowed = required | {"gazeAction"}
        for key, raw_entry in value.items():
            if (
                not isinstance(raw_entry, dict)
                or not required <= set(raw_entry)
                or set(raw_entry) - allowed
            ):
                raise ValueError(f"forms.{key} does not match the documented form fields")
            label = PetRegistry._parse_v4_label(raw_entry["label"], f"forms.{key}.label")
            reference_names = (
                "idleAction",
                "moveRightAction",
                "moveLeftAction",
                "representativeAction",
            )
            if any(
                not isinstance(raw_entry[name], str)
                or _V4_KEY.fullmatch(raw_entry[name]) is None
                for name in reference_names
            ):
                raise ValueError(f"forms.{key} action references must be safe ids")
            gaze = raw_entry.get("gazeAction")
            if gaze is not None and (
                not isinstance(gaze, str) or _V4_KEY.fullmatch(gaze) is None
            ):
                raise ValueError(f"forms.{key}.gazeAction must be a safe action id")
            interactions = raw_entry["interactionActions"]
            if (
                not isinstance(interactions, list)
                or not 1 <= len(interactions) <= 128
                or any(
                    not isinstance(item, str) or _V4_KEY.fullmatch(item) is None
                    for item in interactions
                )
                or len(set(interactions)) != len(interactions)
            ):
                raise ValueError(
                    f"forms.{key}.interactionActions must contain distinct safe action ids"
                )
            definitions.append(
                PetFormDefinition(
                    key,
                    label,
                    raw_entry["idleAction"],
                    raw_entry["moveRightAction"],
                    raw_entry["moveLeftAction"],
                    gaze,
                    raw_entry["representativeAction"],
                    tuple(interactions),
                )
            )
        return tuple(definitions)

    @staticmethod
    def _parse_v4_transformations(
        value: object,
    ) -> tuple[PetTransformationDefinition, ...]:
        if value is None:
            return ()
        if not isinstance(value, dict) or len(value) > 32:
            raise ValueError("v4 transformations may contain at most 32 entries")
        PetRegistry._validate_v4_keys(value, "transformation")
        definitions: list[PetTransformationDefinition] = []
        required = {
            "label",
            "fromForm",
            "toForm",
            "enterAction",
            "residentActions",
            "exitAction",
            "minDurationMs",
            "maxDurationMs",
            "showInMenu",
        }
        allowed = required | {"autoplay"}
        for key, raw_entry in value.items():
            if (
                not isinstance(raw_entry, dict)
                or not required <= set(raw_entry)
                or set(raw_entry) - allowed
            ):
                raise ValueError(
                    f"transformations.{key} does not match the documented fields"
                )
            label = PetRegistry._parse_v4_label(
                raw_entry["label"], f"transformations.{key}.label"
            )
            references = ("fromForm", "toForm", "enterAction", "exitAction")
            if any(
                not isinstance(raw_entry[name], str)
                or _V4_KEY.fullmatch(raw_entry[name]) is None
                for name in references
            ):
                raise ValueError(f"transformations.{key} references must be safe ids")
            residents = PetRegistry._parse_v4_resident_actions(
                raw_entry["residentActions"], f"transformations.{key}.residentActions"
            )
            minimum = raw_entry["minDurationMs"]
            maximum = raw_entry["maxDurationMs"]
            if not PetRegistry._is_int_between(minimum, 0, 1_200_000) or not PetRegistry._is_int_between(
                maximum, 0, 1_200_000
            ):
                raise ValueError(
                    f"transformations.{key} durations must be 0 through 1200000"
                )
            if minimum > maximum:
                raise ValueError(
                    f"transformations.{key}.minDurationMs cannot exceed maxDurationMs"
                )
            show = raw_entry["showInMenu"]
            if not isinstance(show, bool):
                raise ValueError(f"transformations.{key}.showInMenu must be boolean")
            autoplay = PetRegistry._parse_v4_autoplay(
                raw_entry.get("autoplay"), f"transformations.{key}.autoplay"
            )
            definitions.append(
                PetTransformationDefinition(
                    key,
                    label,
                    raw_entry["fromForm"],
                    raw_entry["toForm"],
                    raw_entry["enterAction"],
                    residents,
                    raw_entry["exitAction"],
                    minimum,
                    maximum,
                    show,
                    autoplay,
                )
            )
        return tuple(definitions)

    @staticmethod
    def _parse_v4_cooldown_groups(
        value: object,
    ) -> tuple[PetCooldownGroupDefinition, ...]:
        if value is None:
            return ()
        if not isinstance(value, dict) or len(value) > 32:
            raise ValueError("v4 cooldownGroups may contain at most 32 entries")
        PetRegistry._validate_v4_keys(value, "cooldown group")
        definitions: list[PetCooldownGroupDefinition] = []
        for key, raw_entry in value.items():
            if not isinstance(raw_entry, dict) or set(raw_entry) != {"cooldownMs"}:
                raise ValueError(f"cooldownGroups.{key} must contain cooldownMs")
            cooldown = raw_entry["cooldownMs"]
            if not PetRegistry._is_int_between(cooldown, 0, 1_200_000):
                raise ValueError(
                    f"cooldownGroups.{key}.cooldownMs must be 0 through 1200000"
                )
            definitions.append(PetCooldownGroupDefinition(key, cooldown))
        return tuple(definitions)

    @staticmethod
    def _parse_v4_sequences(value: object) -> tuple[PetSequenceDefinition, ...]:
        if value is None:
            return ()
        if not isinstance(value, dict) or len(value) > 16:
            raise ValueError("v4 sequences may contain at most 16 entries")
        PetRegistry._validate_v4_keys(value, "sequence")
        definitions: list[PetSequenceDefinition] = []
        for key, raw_entry in value.items():
            required = {"label", "showInMenu", "steps"}
            if (
                not isinstance(raw_entry, dict)
                or not required <= set(raw_entry)
                or set(raw_entry) - (required | {"autoplay"})
            ):
                raise ValueError(f"sequences.{key} does not match the documented fields")
            label = PetRegistry._parse_v4_label(
                raw_entry["label"], f"sequences.{key}.label"
            )
            show = raw_entry["showInMenu"]
            if not isinstance(show, bool):
                raise ValueError(f"sequences.{key}.showInMenu must be boolean")
            steps_value = raw_entry["steps"]
            if not isinstance(steps_value, list) or not 1 <= len(steps_value) <= 128:
                raise ValueError(f"sequences.{key}.steps must contain 1 through 128 steps")
            steps: list[PetSequenceStep] = []
            for index, step_value in enumerate(steps_value):
                required_step = {"action", "repeatCount", "holdMs", "safeStopAfter"}
                if (
                    not isinstance(step_value, dict)
                    or not required_step <= set(step_value)
                    or set(step_value) - (required_step | {"formAfter"})
                ):
                    raise ValueError(
                        f"sequences.{key}.steps[{index}] does not match the documented fields"
                    )
                action_id = step_value["action"]
                form_after = step_value.get("formAfter")
                if not isinstance(action_id, str) or _V4_KEY.fullmatch(action_id) is None:
                    raise ValueError(f"sequences.{key}.steps[{index}].action must be a safe id")
                if form_after is not None and (
                    not isinstance(form_after, str)
                    or _V4_KEY.fullmatch(form_after) is None
                ):
                    raise ValueError(
                        f"sequences.{key}.steps[{index}].formAfter must be a safe id"
                    )
                repeat_count = step_value["repeatCount"]
                hold_ms = step_value["holdMs"]
                safe_stop = step_value["safeStopAfter"]
                if not PetRegistry._is_int_between(repeat_count, 1, 20):
                    raise ValueError(
                        f"sequences.{key}.steps[{index}].repeatCount must be 1 through 20"
                    )
                if not PetRegistry._is_int_between(hold_ms, 0, 10_000):
                    raise ValueError(
                        f"sequences.{key}.steps[{index}].holdMs must be 0 through 10000"
                    )
                if not isinstance(safe_stop, bool):
                    raise ValueError(
                        f"sequences.{key}.steps[{index}].safeStopAfter must be boolean"
                    )
                steps.append(
                    PetSequenceStep(
                        action_id, repeat_count, hold_ms, form_after, safe_stop
                    )
                )
            autoplay = PetRegistry._parse_v4_autoplay(
                raw_entry.get("autoplay"), f"sequences.{key}.autoplay"
            )
            definitions.append(
                PetSequenceDefinition(key, label, show, tuple(steps), autoplay)
            )
        return tuple(definitions)

    @staticmethod
    def _parse_v4_resident_actions(
        value: object, prefix: str
    ) -> tuple[PetStateActionChoice, ...]:
        if not isinstance(value, list) or not 1 <= len(value) <= 128:
            raise ValueError(f"{prefix} must contain 1 through 128 choices")
        choices: list[PetStateActionChoice] = []
        seen: set[str] = set()
        for index, raw_choice in enumerate(value):
            if not isinstance(raw_choice, dict) or set(raw_choice) != {"action", "weight"}:
                raise ValueError(f"{prefix}[{index}] must contain action and weight")
            action_id = raw_choice["action"]
            weight = raw_choice["weight"]
            if not isinstance(action_id, str) or _V4_KEY.fullmatch(action_id) is None:
                raise ValueError(f"{prefix}[{index}].action must be a safe id")
            if action_id in seen:
                raise ValueError(f"{prefix} cannot repeat an action")
            if not PetRegistry._is_int_between(weight, 1, 100):
                raise ValueError(f"{prefix}[{index}].weight must be 1 through 100")
            seen.add(action_id)
            choices.append(PetStateActionChoice(action_id, weight))
        return tuple(choices)

    @staticmethod
    def _parse_v4_autoplay(
        value: object, prefix: str
    ) -> PetAutoplayDefinition | None:
        if value is None:
            return None
        required = {"bucket", "weight", "minDelayMs", "maxDelayMs", "cooldownGroups"}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError(f"{prefix} must contain the documented autoplay fields")
        bucket = value["bucket"]
        if not isinstance(bucket, str) or _V4_KEY.fullmatch(bucket) is None:
            raise ValueError(f"{prefix}.bucket must be a safe id")
        weight = value["weight"]
        minimum = value["minDelayMs"]
        maximum = value["maxDelayMs"]
        if not PetRegistry._is_int_between(weight, 1, 100):
            raise ValueError(f"{prefix}.weight must be 1 through 100")
        if not PetRegistry._is_int_between(minimum, 0, 1_200_000) or not PetRegistry._is_int_between(
            maximum, 0, 1_200_000
        ):
            raise ValueError(f"{prefix} delays must be 0 through 1200000")
        if minimum > maximum:
            raise ValueError(f"{prefix}.minDelayMs cannot exceed maxDelayMs")
        groups = value["cooldownGroups"]
        if (
            not isinstance(groups, list)
            or len(groups) > 32
            or any(
                not isinstance(group, str) or _V4_KEY.fullmatch(group) is None
                for group in groups
            )
            or len(set(groups)) != len(groups)
        ):
            raise ValueError(f"{prefix}.cooldownGroups must contain distinct safe ids")
        return PetAutoplayDefinition(bucket, weight, minimum, maximum, tuple(groups))

    @staticmethod
    def _validate_v4_references(
        atlases: tuple[PetAtlasDefinition, ...],
        actions: tuple[PetActionDefinition, ...],
        forms: tuple[PetFormDefinition, ...],
        default_form: object,
        transformations: tuple[PetTransformationDefinition, ...],
        cooldown_groups: tuple[PetCooldownGroupDefinition, ...],
        sequences: tuple[PetSequenceDefinition, ...],
        icon_atlas: object,
    ) -> None:
        atlas_map = {item.key: item for item in atlases}
        action_map = {str(item.action_id): item for item in actions}
        form_map = {item.key: item for item in forms}
        group_keys = {item.key for item in cooldown_groups}
        sequence_keys = {item.key for item in sequences}

        if not isinstance(default_form, str) or default_form not in form_map:
            raise ValueError("v4 manifest contains an unknown defaultForm")
        if icon_atlas not in atlas_map:
            raise ValueError("iconFrame references an unknown atlas")
        for action in actions:
            for layer in action.layers:
                if layer.atlas_id not in atlas_map:
                    raise ValueError(
                        f"actions.{action.key}.layers references an unknown atlas"
                    )
            if action.mirror_of is not None:
                source = action_map.get(str(action.mirror_of))
                if source is None:
                    raise ValueError(f"actions.{action.key}.mirrorOf references an unknown action")
                if source.mirror_of is not None:
                    raise ValueError(f"actions.{action.key}.mirrorOf must name a direct action")
                if source.role is not action.role or source.direction != -action.direction:
                    raise ValueError(
                        f"actions.{action.key} must mirror the opposite direction of the same role"
                    )

        for form in forms:
            references = (
                form.idle_action,
                form.move_right_action,
                form.move_left_action,
                form.representative_action,
                *form.interaction_actions,
            )
            if form.gaze_action is not None:
                references += (form.gaze_action,)
            if any(str(reference) not in action_map for reference in references):
                raise ValueError(f"forms.{form.key} references an unknown action")
            idle = action_map[str(form.idle_action)]
            right = action_map[str(form.move_right_action)]
            left = action_map[str(form.move_left_action)]
            capabilities_valid = (
                idle.role is ActionRole.IDLE
                and right.role is ActionRole.MOVE
                and right.direction == 1
                and left.role is ActionRole.MOVE
                and left.direction == -1
            )
            if not capabilities_valid:
                if form.key == default_form:
                    raise ValueError(
                        "default form must define idle and both move directions"
                    )
                raise ValueError(
                    f"forms.{form.key} must define idle and both move directions"
                )
            if any(
                action_map[str(action_id)].role is not ActionRole.INTERACTION
                for action_id in form.interaction_actions
            ):
                raise ValueError(f"forms.{form.key}.interactionActions must be interactions")
            if form.gaze_action is not None:
                if form.key != default_form:
                    raise ValueError("only the default form may define gazeAction")
                if action_map[str(form.gaze_action)].role is not ActionRole.GAZE:
                    raise ValueError(f"forms.{form.key}.gazeAction must name a gaze action")

        for transformation in transformations:
            if transformation.from_form not in form_map or transformation.to_form not in form_map:
                raise ValueError(f"transformations.{transformation.key} references an unknown form")
            if transformation.from_form != default_form:
                raise ValueError("transformations must originate from defaultForm")
            action_ids = (
                transformation.enter_action,
                *(choice.action_id for choice in transformation.resident_actions),
                transformation.exit_action,
            )
            if any(str(action_id) not in action_map for action_id in action_ids):
                raise ValueError(
                    f"transformations.{transformation.key} references an unknown action"
                )

        for sequence in sequences:
            for step in sequence.steps:
                action_id = str(step.action_id)
                if action_id not in action_map:
                    if action_id in sequence_keys:
                        raise ValueError("sequence steps may reference actions only")
                    raise ValueError(f"sequences.{sequence.key} references an unknown action")
                if step.form_after is not None and step.form_after not in form_map:
                    raise ValueError(f"sequences.{sequence.key} references an unknown form")

        bucket_specs: dict[str, tuple[int, int, tuple[str, ...]]] = {}
        autoplays = [
            item.autoplay
            for item in (*transformations, *sequences)
            if item.autoplay is not None
        ]
        for autoplay in autoplays:
            unknown_groups = set(autoplay.cooldown_groups) - group_keys
            if unknown_groups:
                raise ValueError(
                    f"autoplay bucket {autoplay.bucket} references an unknown cooldown group"
                )
            signature = (
                autoplay.min_delay_ms,
                autoplay.max_delay_ms,
                autoplay.cooldown_groups,
            )
            existing = bucket_specs.setdefault(autoplay.bucket, signature)
            if existing != signature:
                raise ValueError("autoplay bucket definitions must match")

    @staticmethod
    def _validate_v4_keys(value: dict[object, object], name: str) -> None:
        if any(
            not isinstance(key, str) or _V4_KEY.fullmatch(key) is None
            for key in value
        ):
            raise ValueError(f"v4 {name} ids must be safe 1 through 64 character names")

    @staticmethod
    def _parse_v4_label(value: object, prefix: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{prefix} must be text")
        label = value.strip()
        if (
            not label
            or len(label) > 80
            or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in label)
        ):
            raise ValueError(f"{prefix} must be 1 through 80 printable characters")
        return label

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
                include_in_showcase,
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
                "includeInShowcase",
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
                include_in_showcase=include_in_showcase,
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
    def _parse_v3_states(
        value: object,
        actions: tuple[PetActionDefinition, ...],
    ) -> tuple[PetStateDefinition, ...]:
        """Parse optional persistent states without granting them executable code."""

        if value is None:
            return ()
        if not isinstance(value, dict) or not 1 <= len(value) <= 16:
            raise ValueError("states must contain 1 through 16 named states")
        if any(
            not isinstance(key, str) or _STATE_KEY.fullmatch(key) is None
            for key in value
        ):
            raise ValueError("state ids must be safe 1 through 64 character names")

        action_map = {definition.action_id: definition for definition in actions}
        used_actions: set[object] = set()
        parsed: list[PetStateDefinition] = []
        required = {
            "label",
            "enterAction",
            "residentActions",
            "exitAction",
            "minDurationMs",
            "rampDurationMs",
            "maxDurationMs",
            "exitChanceAfterMin",
            "exitChanceAfterRamp",
        }
        for key, raw_entry in value.items():
            if not isinstance(raw_entry, dict) or set(raw_entry) != required:
                raise ValueError(
                    f"states.{key} must contain exactly the documented state fields"
                )
            label = raw_entry["label"]
            if (
                not isinstance(label, str)
                or not label.strip()
                or len(label.strip()) > 32
                or any(not char.isprintable() for char in label.strip())
            ):
                raise ValueError(
                    f"states.{key}.label must be 1 through 32 printable characters"
                )

            enter_action = raw_entry["enterAction"]
            exit_action = raw_entry["exitAction"]
            resident_value = raw_entry["residentActions"]
            if (
                not isinstance(resident_value, list)
                or not 2 <= len(resident_value) <= 16
            ):
                raise ValueError(
                    f"states.{key}.residentActions must contain 2 through 16 choices"
                )
            choices: list[PetStateActionChoice] = []
            resident_ids: set[object] = set()
            for index, choice_value in enumerate(resident_value):
                if (
                    not isinstance(choice_value, dict)
                    or set(choice_value) != {"action", "weight"}
                ):
                    raise ValueError(
                        f"states.{key}.residentActions[{index}] must contain action and weight"
                    )
                action_id = choice_value["action"]
                weight = choice_value["weight"]
                if action_id not in action_map:
                    raise ValueError(
                        f"states.{key}.residentActions[{index}].action is unknown"
                    )
                if action_id in resident_ids:
                    raise ValueError(
                        f"states.{key}.residentActions cannot repeat an action"
                    )
                if not PetRegistry._is_int_between(weight, 1, 100):
                    raise ValueError(
                        f"states.{key}.residentActions[{index}].weight must be 1 through 100"
                    )
                resident_ids.add(action_id)
                choices.append(PetStateActionChoice(action_id, weight))

            referenced = (enter_action, *resident_ids, exit_action)
            if any(action_id not in action_map for action_id in referenced):
                raise ValueError(f"states.{key} references an unknown action")
            if len(set(referenced)) != len(referenced):
                raise ValueError(
                    f"states.{key} enter, resident, and exit actions must be distinct"
                )
            if any(action_id in used_actions for action_id in referenced):
                raise ValueError("an action cannot belong to more than one state")

            enter_definition = action_map[enter_action]
            if enter_definition.role is not ActionRole.INTERACTION:
                raise ValueError(f"states.{key}.enterAction must be an interaction")
            internal_definitions = [
                action_map[action_id] for action_id in (*resident_ids, exit_action)
            ]
            if any(
                item.role is not ActionRole.INTERACTION
                for item in internal_definitions
            ):
                raise ValueError(
                    f"states.{key} resident and exit actions must be interactions"
                )
            if any(
                item.show_in_menu or item.autoplay_weight
                for item in internal_definitions
            ):
                raise ValueError(
                    f"states.{key} resident and exit actions must be hidden with autoplayWeight 0"
                )
            if (
                not enter_definition.show_in_menu
                and not enter_definition.autoplay_weight
            ):
                raise ValueError(
                    f"states.{key}.enterAction must be visible or eligible for autoplay"
                )

            minimum = raw_entry["minDurationMs"]
            ramp = raw_entry["rampDurationMs"]
            maximum = raw_entry["maxDurationMs"]
            chance_min = raw_entry["exitChanceAfterMin"]
            chance_ramp = raw_entry["exitChanceAfterRamp"]
            if not PetRegistry._is_int_between(minimum, 5_000, 300_000):
                raise ValueError(
                    f"states.{key}.minDurationMs must be 5000 through 300000"
                )
            if not PetRegistry._is_int_between(ramp, 0, 300_000):
                raise ValueError(
                    f"states.{key}.rampDurationMs must be 0 through 300000"
                )
            if (
                not PetRegistry._is_int_between(maximum, 10_000, 600_000)
                or maximum < minimum + ramp
            ):
                raise ValueError(
                    f"states.{key}.maxDurationMs must be at least minDurationMs plus rampDurationMs"
                )
            if (
                not PetRegistry._is_int_between(chance_min, 0, 100)
                or not PetRegistry._is_int_between(chance_ramp, chance_min, 100)
            ):
                raise ValueError(
                    f"states.{key} exit chances must increase from 0 through 100"
                )

            used_actions.update(referenced)
            parsed.append(
                PetStateDefinition(
                    key=key,
                    label=label.strip(),
                    enter_action=enter_action,
                    resident_actions=tuple(choices),
                    exit_action=exit_action,
                    min_duration_ms=minimum,
                    ramp_duration_ms=ramp,
                    max_duration_ms=maximum,
                    exit_chance_after_min=chance_min,
                    exit_chance_after_ramp=chance_ramp,
                )
            )
        return tuple(parsed)

    @staticmethod
    def _parse_v3_common(
        key: str, entry: dict[str, object]
    ) -> tuple[
        ActionRole,
        int,
        str,
        int,
        bool,
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
        include_in_showcase = entry.get("includeInShowcase", True)
        if not isinstance(include_in_showcase, bool):
            raise ValueError(f"actions.{key}.includeInShowcase must be boolean")
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
            include_in_showcase,
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
            include_in_showcase,
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
            "includeInShowcase",
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
        if not PetRegistry._is_int_between(frame_count, 1, 512):
            raise ValueError(f"actions.{key}.frameCount must be 1 through 512")

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
        if role is ActionRole.GAZE and frame_count not in {16, 32, 64}:
            raise ValueError(
                f"actions.{key} gaze action must contain 16, 32, or 64 frames"
            )

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
            include_in_showcase=include_in_showcase,
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
            and lower <= value <= upper
        )
