"""Discover safe, data-only desktop-pet packs using the fixed v2 atlas contract."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable


_PET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
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

        if manifest.get("spriteVersionNumber") != 2:
            raise ValueError("unsupported sprite version; expected 2")
        if manifest.get("spritesheetPath") != _SPRITESHEET_NAME:
            raise ValueError("spritesheetPath must be spritesheet.webp")

        icon_frame = manifest.get("iconFrame", {"row": 0, "column": 0})
        if not isinstance(icon_frame, dict) or set(icon_frame) != {"row", "column"}:
            raise ValueError("iconFrame must contain row and column")
        icon_row = icon_frame["row"]
        icon_column = icon_frame["column"]
        if (
            not isinstance(icon_row, int)
            or isinstance(icon_row, bool)
            or not 0 <= icon_row < 11
            or not isinstance(icon_column, int)
            or isinstance(icon_column, bool)
            or not 0 <= icon_column < 8
        ):
            raise ValueError(
                "iconFrame row must be 0 through 10 and column must be 0 through 7"
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
        )
