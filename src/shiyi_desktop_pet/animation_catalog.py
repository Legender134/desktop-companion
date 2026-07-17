from PySide6.QtGui import QImage

from .constants import (
    ACTION_SPECS,
    CELL_HEIGHT,
    CELL_WIDTH,
    DEFAULT_PET_ACTIONS,
    IN_PLACE_ACTIONS,
    LOOK_DEGREES,
)
from .models import ActionId, FrameAsset, PetActionDefinition
from .pet_registry import PetDefinition, PetRegistry
from .resource_locator import resource_root


def _has_visible_pixel(image: QImage) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )


class AnimationCatalog:
    def __init__(
        self,
        atlas: QImage,
        *,
        pet_id: str = "custom",
        display_name: str = "",
        icon_frame: tuple[int, int] = (0, 0),
        actions: tuple[PetActionDefinition, ...] = DEFAULT_PET_ACTIONS,
    ):
        if atlas.isNull():
            raise ValueError("spritesheet could not be decoded")
        if (atlas.width(), atlas.height()) != (1536, 2288):
            raise ValueError("spritesheet must be 1536x2288")
        if not atlas.hasAlphaChannel():
            raise ValueError("spritesheet must have alpha")
        self.pet_id = pet_id
        self.display_name = display_name
        self._atlas = atlas.convertToFormat(QImage.Format.Format_RGBA8888)
        if (
            not isinstance(icon_frame, tuple)
            or len(icon_frame) != 2
            or any(not isinstance(value, int) or isinstance(value, bool) for value in icon_frame)
            or not 0 <= icon_frame[0] < 11
            or not 0 <= icon_frame[1] < 8
        ):
            raise ValueError("iconFrame is outside the v2 atlas")
        self.icon_frame = icon_frame
        action_map = {definition.action_id: definition for definition in actions}
        if set(action_map) != set(ACTION_SPECS) or len(action_map) != len(actions):
            raise ValueError("actions must define every v2 atlas action exactly once")
        self._action_definitions = tuple(action_map[action] for action in ACTION_SPECS)
        self._action_map = action_map
        self.look_degrees = LOOK_DEGREES
        used_counts = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)
        for row, used in enumerate(used_counts):
            for column in range(8):
                visible = _has_visible_pixel(self._cell(row, column))
                if visible is not (column < used):
                    raise ValueError(f"unexpected occupancy at row {row} column {column}")
        self._icon_image = self._cell(*self.icon_frame)
        if not _has_visible_pixel(self._icon_image):
            raise ValueError("iconFrame must select a visible atlas cell")
        self._actions = {
            action: tuple(
                FrameAsset(self._cell(spec.row, column), spec.row, column)
                for column in range(spec.frame_count)
            )
            for action, spec in ACTION_SPECS.items()
        }

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
        )

    def _cell(self, row: int, column: int) -> QImage:
        return self._atlas.copy(column * CELL_WIDTH, row * CELL_HEIGHT, CELL_WIDTH, CELL_HEIGHT)

    def frames(self, action: ActionId) -> tuple[FrameAsset, ...]:
        return self._actions[action]

    def icon_image(self) -> QImage:
        return self._icon_image.copy()

    def action_menu_items(self) -> tuple[tuple[str, ActionId], ...]:
        return tuple(
            (definition.label, definition.action_id)
            for definition in self._action_definitions
        )

    def autoplay_actions(self) -> tuple[tuple[ActionId, int], ...]:
        return tuple(
            (definition.action_id, definition.autoplay_weight)
            for definition in self._action_definitions
            if definition.action_id in IN_PLACE_ACTIONS
            and definition.autoplay_weight > 0
        )

    def showcase_actions(self) -> tuple[ActionId, ...]:
        return tuple(
            definition.action_id
            for definition in self._action_definitions
            if definition.action_id in IN_PLACE_ACTIONS
        )

    def look_frame(self, degrees: float) -> FrameAsset:
        index = round(degrees / 22.5)
        if not 0.0 <= degrees < 360.0 or abs(degrees - index * 22.5) > 1e-6:
            raise ValueError("direction must be a 22.5-degree step from 0 through 337.5")
        row, column = 9 + index // 8, index % 8
        return FrameAsset(self._cell(row, column), row, column)

    def hit_test(self, frame: FrameAsset, x: float, y: float, scale: float) -> bool:
        if scale <= 0 or x < 0 or y < 0:
            return False
        source_x, source_y = int(x / scale), int(y / scale)
        if not 0 <= source_x < CELL_WIDTH or not 0 <= source_y < CELL_HEIGHT:
            return False
        return frame.image.pixelColor(source_x, source_y).alpha() > 0
