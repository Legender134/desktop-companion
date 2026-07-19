from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .constants import (
    ACTION_SPECS,
    CELL_HEIGHT,
    CELL_WIDTH,
    DEFAULT_PET_ACTIONS,
    LOOK_DEGREES,
)
from .models import (
    ActionId,
    ActionKey,
    ActionRole,
    AnimationSpec,
    FrameAsset,
    PetActionDefinition,
)
from .pet_registry import PetDefinition, PetRegistry
from .resource_locator import resource_root


def _has_visible_pixel(image: QImage) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )


class AnimationCatalog:
    """Validated atlas and semantic action catalog for v2 and dynamic v3 pets."""

    def __init__(
        self,
        atlas: QImage,
        *,
        pet_id: str = "custom",
        display_name: str = "",
        icon_frame: tuple[int, int] = (0, 0),
        actions: tuple[PetActionDefinition, ...] = DEFAULT_PET_ACTIONS,
        sprite_version: int = 2,
    ):
        if atlas.isNull():
            raise ValueError("spritesheet could not be decoded")
        if not atlas.hasAlphaChannel():
            raise ValueError("spritesheet must have alpha")
        if sprite_version == 2:
            if (atlas.width(), atlas.height()) != (1536, 2288):
                raise ValueError("spritesheet must be 1536x2288")
        elif sprite_version == 3:
            if (
                atlas.width() % CELL_WIDTH
                or atlas.height() % CELL_HEIGHT
                or atlas.width() <= 0
                or atlas.height() <= 0
            ):
                raise ValueError("v3 spritesheet dimensions must be cell-size multiples")
            cell_total = (atlas.width() // CELL_WIDTH) * (
                atlas.height() // CELL_HEIGHT
            )
            if cell_total > 2_048 or atlas.width() * atlas.height() > 50_000_000:
                raise ValueError("v3 spritesheet grid is too large")
        else:
            raise ValueError("unsupported sprite version")

        self.pet_id = pet_id
        self.display_name = display_name
        self.sprite_version = sprite_version
        self._atlas = atlas.convertToFormat(QImage.Format.Format_RGBA8888)
        self.columns = self._atlas.width() // CELL_WIDTH
        self.rows = self._atlas.height() // CELL_HEIGHT
        if (
            not isinstance(icon_frame, tuple)
            or len(icon_frame) != 2
            or any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in icon_frame
            )
            or not 0 <= icon_frame[0] < self.rows
            or not 0 <= icon_frame[1] < self.columns
        ):
            raise ValueError("iconFrame is outside the atlas")
        self.icon_frame = icon_frame

        action_map = {definition.action_id: definition for definition in actions}
        if len(action_map) != len(actions):
            raise ValueError("action ids must be unique")
        if sprite_version == 2 and set(action_map) != set(ACTION_SPECS):
            raise ValueError("actions must define every v2 atlas action exactly once")
        if sprite_version == 3:
            if not any(item.role is ActionRole.IDLE for item in actions):
                raise ValueError("v3 actions must define idle")
            if any(item.spec is None for item in actions):
                raise ValueError("v3 actions must define animation timing")

        self._action_definitions = tuple(actions)
        self._action_map = action_map
        self._specs: dict[ActionKey, AnimationSpec] = {}
        self._actions: dict[ActionKey, tuple[FrameAsset, ...]] = {}

        if sprite_version == 2:
            used_counts = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)
            for row, used in enumerate(used_counts):
                for column in range(8):
                    visible = _has_visible_pixel(self._cell(row, column))
                    if visible is not (column < used):
                        raise ValueError(
                            f"unexpected occupancy at row {row} column {column}"
                        )

        for definition in actions:
            spec = definition.spec
            if spec is None:
                spec = ACTION_SPECS[definition.action_id]
            self._specs[definition.action_id] = spec
            coordinates = self._frame_coordinates(spec)
            frames: list[FrameAsset] = []
            for row, column in coordinates:
                image = self._cell(row, column)
                variant = ""
                if definition.mirror_of is not None:
                    image = image.flipped(Qt.Orientation.Horizontal)
                    variant = f"mirror:{definition.action_id}"
                if not _has_visible_pixel(image):
                    raise ValueError(
                        f"action {definition.key} uses empty cell at row {row} column {column}"
                    )
                frames.append(FrameAsset(image, row, column, variant))
            self._actions[definition.action_id] = tuple(frames)

        self._idle_action = next(
            definition.action_id
            for definition in actions
            if definition.role is ActionRole.IDLE
        )
        gaze = next(
            (item for item in actions if item.role is ActionRole.GAZE), None
        )
        if sprite_version == 2:
            self.look_degrees = LOOK_DEGREES
            self._look_frames = tuple(
                FrameAsset(self._cell(9 + index // 8, index % 8), 9 + index // 8, index % 8)
                for index in range(16)
            )
        elif gaze is not None:
            self.look_degrees = LOOK_DEGREES
            self._look_frames = self._actions[gaze.action_id]
        else:
            self.look_degrees = ()
            self._look_frames = ()

        self._icon_image = self._cell(*self.icon_frame)
        if not _has_visible_pixel(self._icon_image):
            raise ValueError("iconFrame must select a visible atlas cell")

    @classmethod
    def load_default(cls) -> "AnimationCatalog":
        return cls.load_pet("shiyi")

    @classmethod
    def load_pet(cls, pet_id: str) -> "AnimationCatalog":
        snapshot = PetRegistry(resource_root() / "pets", None).refresh()
        definition = snapshot.by_id(pet_id)
        if definition is None:
            raise ValueError(f"unknown pet: {pet_id}")
        return cls.load_definition(definition)

    @classmethod
    def load_definition(cls, definition: PetDefinition) -> "AnimationCatalog":
        return cls(
            QImage(str(definition.spritesheet_path)),
            pet_id=definition.pet_id,
            display_name=definition.display_name,
            icon_frame=definition.icon_frame,
            actions=definition.actions,
            sprite_version=definition.sprite_version,
        )

    @property
    def idle_action(self) -> ActionKey:
        return self._idle_action

    @property
    def supports_gaze(self) -> bool:
        return bool(self._look_frames)

    @property
    def action_ids(self) -> tuple[ActionKey, ...]:
        return tuple(self._actions)

    @property
    def atlas_size(self) -> tuple[int, int]:
        return self._atlas.width(), self._atlas.height()

    def _cell(self, row: int, column: int) -> QImage:
        return self._atlas.copy(
            column * CELL_WIDTH, row * CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT
        )

    def _frame_coordinates(self, spec: AnimationSpec) -> tuple[tuple[int, int], ...]:
        start = spec.row * self.columns + spec.start_column
        coordinates = tuple(
            divmod(start + offset, self.columns)
            for offset in range(spec.frame_count)
        )
        if not coordinates or coordinates[-1][0] >= self.rows:
            raise ValueError("action frames extend outside the spritesheet")
        return coordinates

    def frames(self, action: ActionKey) -> tuple[FrameAsset, ...]:
        return self._actions[action]

    def spec(self, action: ActionKey) -> AnimationSpec:
        return self._specs[action]

    def definition(self, action: ActionKey) -> PetActionDefinition:
        return self._action_map[action]

    def icon_image(self) -> QImage:
        return self._icon_image.copy()

    def action_menu_items(self) -> tuple[tuple[str, ActionKey], ...]:
        return tuple(
            (definition.label, definition.action_id)
            for definition in self._action_definitions
            if definition.show_in_menu and definition.role is not ActionRole.GAZE
        )

    def autoplay_actions(self) -> tuple[tuple[ActionKey, int], ...]:
        return tuple(
            (definition.action_id, definition.autoplay_weight)
            for definition in self._action_definitions
            if definition.role is ActionRole.INTERACTION
            and definition.autoplay_weight > 0
        )

    def interaction_actions(self) -> tuple[ActionKey, ...]:
        return tuple(
            definition.action_id
            for definition in self._action_definitions
            if definition.role is ActionRole.INTERACTION
        )

    def showcase_actions(self) -> tuple[ActionKey, ...]:
        return self.interaction_actions()

    def movement_actions(
        self, direction: int, *, include_burst: bool = True
    ) -> tuple[PetActionDefinition, ...]:
        roles = (
            {ActionRole.MOVE, ActionRole.BURST_MOVE}
            if include_burst
            else {ActionRole.MOVE}
        )
        return tuple(
            definition
            for definition in self._action_definitions
            if definition.role in roles and definition.direction == direction
        )

    def resolve_action(self, requested: ActionKey) -> ActionKey:
        if requested in self._actions:
            return self._action_map[requested].action_id
        if requested is ActionId.IDLE:
            return self.idle_action
        if requested in {ActionId.RUN_LEFT, ActionId.RUN_RIGHT}:
            direction = -1 if requested is ActionId.RUN_LEFT else 1
            candidates = self.movement_actions(direction, include_burst=False)
            if candidates:
                return candidates[0].action_id
        preferred_keys = {
            ActionId.WAVE: "greet",
            ActionId.JUMP: "jump",
            ActionId.BELLY_FLOP: "special",
            ActionId.EXPECT: "wait",
            ActionId.PATROL: "observe",
            ActionId.CURIOUS: "curious",
        }
        preferred = preferred_keys.get(requested)
        if preferred in self._actions:
            return self._action_map[preferred].action_id
        if not isinstance(requested, ActionId):
            raise ValueError(f"unsupported action: {requested}")
        interactions = self.interaction_actions()
        if interactions:
            return interactions[0]
        raise ValueError(f"unsupported action: {requested}")

    def look_frame(self, degrees: float) -> FrameAsset:
        index = round(degrees / 22.5)
        if (
            not self.supports_gaze
            or not 0.0 <= degrees < 360.0
            or abs(degrees - index * 22.5) > 1e-6
        ):
            raise ValueError("direction must be a supported 22.5-degree step")
        return self._look_frames[index]

    def hit_test(self, frame: FrameAsset, x: float, y: float, scale: float) -> bool:
        if scale <= 0 or x < 0 or y < 0:
            return False
        source_x, source_y = int(x / scale), int(y / scale)
        if not 0 <= source_x < CELL_WIDTH or not 0 <= source_y < CELL_HEIGHT:
            return False
        return frame.image.pixelColor(source_x, source_y).alpha() > 0
